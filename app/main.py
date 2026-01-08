"""Main application entry point."""

import logging
import signal
import sys
import time
import queue
import threading
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
import pytz

from app.config import load_config
from app.camera import CameraStream
from app.detector import PersonDetector
from app.tracker import Tracker
from app.vision.gate_counter import GateCounter
from app.vision.gate_counter_segment import GateCounterSegment
from app.storage import Storage
from app.scheduler import WindowScheduler
from app.notifier import Notifier
from app.time_manager import TimeManager
from app.morning_total_manager import MorningTotalManager
from app.alert_manager import AlertManager
from app.phase_manager import PhaseManager
from storage.postgres_writer import PostgresWriter
from scheduler.excel_export_scheduler import ExcelExportScheduler
# from app.web_server import WebServer  # Commented out - file deleted

logger = logging.getLogger(__name__)


class PeopleCounterApp:
    """Main application class."""
    
    def __init__(self, config_path: str = None):
        """Initialize application."""
        self.config = load_config()
        self.running = False
        
        # Setup logging
        self._setup_logging()
        
        # Initialize components
        self.camera = None
        self.detector = None
        self.tracker = None
        self.line_counter = None
        self.gate_counter = None
        self.storage = None
        self.scheduler = None
        self.notifier = None
        self.time_manager = None
        self.morning_total_manager = None
        self.phase_manager = None
        self.alert_manager = None
        self.postgres_writer = None
        self.excel_export_scheduler = None
        self.web_server = None
        
        # Office occupancy tracking
        self.start_time = None
        self.initial_count_in = 0  # Số người vào trong 1 phút đầu
        self.initial_count_out = 0  # Số người ra trong 1 phút đầu
        self.realtime_in = 0  # Số người vào sau 1 phút đầu
        self.realtime_out = 0  # Số người ra sau 1 phút đầu
        self.initial_phase_duration = 60.0  # 1 phút = 60 giây
        
        logger.info("People Counter MVP initialized")
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config.logging.level)
        logging.basicConfig(
            level=log_level,
            format=self.config.logging.format,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler("people_counter.log"),
            ],
        )
    
    def _initialize_components(self):
        """Initialize all components."""
        logger.info("Initializing components...")
        
        # Camera
        self.camera = CameraStream(
            url=self.config.camera.url,
            reconnect_delay=self.config.camera.reconnect_delay,
            max_reconnect_attempts=self.config.camera.max_reconnect_attempts,
            fps_cap=self.config.camera.fps_cap,
        )
        
        # Detector
        self.detector = PersonDetector(
            model_name=self.config.detection.model_name,
            conf_threshold=self.config.detection.conf_threshold,
            iou_threshold=self.config.detection.iou_threshold,
            device=self.config.detection.device,
            imgsz=self.config.detection.imgsz,
        )
        
        # Tracker
        self.tracker = Tracker(
            tracker_type=self.config.tracking.tracker_type,
            track_thresh=self.config.tracking.track_thresh,
            track_buffer=self.config.tracking.track_buffer,
            match_thresh=self.config.tracking.match_thresh,
        )
        
        # Gate counter (new - preferred)
        if self.config.gate.gate_mode == "SEGMENT":
            # Segment-crossing mode
            if (self.config.gate.gate_p1_x is None or self.config.gate.gate_p1_y is None or
                self.config.gate.gate_p2_x is None or self.config.gate.gate_p2_y is None):
                raise ValueError("gate_p1_x, gate_p1_y, gate_p2_x, gate_p2_y required for SEGMENT mode")
            
            self.gate_counter = GateCounterSegment(
                gate_p1=(self.config.gate.gate_p1_x, self.config.gate.gate_p1_y),
                gate_p2=(self.config.gate.gate_p2_x, self.config.gate.gate_p2_y),
                cooldown_sec=self.config.gate.cooldown_sec,
                min_travel_px=self.config.gate.min_travel_px,
                direction_mapping_pos_to_neg=self.config.gate.direction_mapping_pos_to_neg,
                direction_mapping_neg_to_pos=self.config.gate.direction_mapping_neg_to_pos,
                direction_mapping_up=self.config.gate.direction_mapping_up,
                direction_mapping_down=self.config.gate.direction_mapping_down,
                x_range_min=self.config.gate.x_range_min,
                x_range_max=self.config.gate.x_range_max,
            )
        else:
            # Band-based modes (legacy)
            direction_mapping = {}
            if self.config.gate.gate_mode == "HORIZONTAL_BAND":
                direction_mapping = {
                    ("TOP", "BOTTOM"): self.config.gate.direction_mapping_top_bottom,
                    ("BOTTOM", "TOP"): self.config.gate.direction_mapping_bottom_top,
                }
            elif self.config.gate.gate_mode == "VERTICAL_BAND":
                direction_mapping = {
                    ("LEFT", "RIGHT"): self.config.gate.direction_mapping_left_right,
                    ("RIGHT", "LEFT"): self.config.gate.direction_mapping_right_left,
                }
            else:  # LINE_BAND
                direction_mapping = {
                    ("LEFT", "RIGHT"): "IN",
                    ("RIGHT", "LEFT"): "OUT",
                }
            
            if self.config.gate.gate_mode == "HORIZONTAL_BAND":
                self.gate_counter = GateCounter(
                    gate_mode=self.config.gate.gate_mode,
                    gate_y=self.config.gate.gate_y,
                    gate_height=self.config.gate.gate_height,
                    gate_x_min=self.config.gate.gate_x_min,
                    gate_x_max=self.config.gate.gate_x_max,
                    direction_mapping=direction_mapping,
                    cooldown_sec=self.config.gate.cooldown_sec,
                    min_frames_in_gate=self.config.gate.min_frames_in_gate,
                    min_travel_px=self.config.gate.min_travel_px,
                    rearm_dist_px=self.config.gate.rearm_dist_px,
                )
            elif self.config.gate.gate_mode == "VERTICAL_BAND":
                self.gate_counter = GateCounter(
                    gate_mode=self.config.gate.gate_mode,
                    gate_x=self.config.gate.gate_x,
                    gate_width=self.config.gate.gate_width,
                    gate_y_min=self.config.gate.gate_y_min,
                    gate_y_max=self.config.gate.gate_y_max,
                    buffer_zone_width=self.config.gate.buffer_zone_width,
                    use_buffer_zones=self.config.gate.use_buffer_zones,
                    direction_mapping=direction_mapping,
                    cooldown_sec=self.config.gate.cooldown_sec,
                    min_frames_in_gate=self.config.gate.min_frames_in_gate,
                    min_travel_px=self.config.gate.min_travel_px,
                    rearm_dist_px=self.config.gate.rearm_dist_px,
                )
            else:  # LINE_BAND
                if self.config.gate.gate_p1 is None or self.config.gate.gate_p2 is None:
                    raise ValueError("gate_p1 and gate_p2 required for LINE_BAND mode")
                self.gate_counter = GateCounter(
                    gate_mode=self.config.gate.gate_mode,
                    gate_p1=self.config.gate.gate_p1,
                    gate_p2=self.config.gate.gate_p2,
                    gate_thickness=self.config.gate.gate_thickness,
                    direction_mapping=direction_mapping,
                    cooldown_sec=self.config.gate.cooldown_sec,
                    min_frames_in_gate=self.config.gate.min_frames_in_gate,
                    min_travel_px=self.config.gate.min_travel_px,
                    rearm_dist_px=self.config.gate.rearm_dist_px,
                )
        
        # Storage - MANDATORY: app will not start if database init fails
        try:
            self.storage = Storage(
                db_path=self.config.db_path,
                timezone=self.config.window.timezone,
            )
            logger.info("SQLite storage initialized successfully")
        except RuntimeError as e:
            logger.critical(f"CRITICAL: Cannot start application without database: {e}")
            raise
        
        # PostgreSQL (optional, reads from environment variables)
        try:
            self.postgres_writer = PostgresWriter()
            if self.postgres_writer._initialized:
                logger.info("PostgreSQL storage enabled")
            else:
                self.postgres_writer = None
                logger.info("PostgreSQL storage disabled (using SQLite only)")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgreSQL writer: {e}")
            self.postgres_writer = None
        
        # Notifier
        self.notifier = Notifier(
            enabled=self.config.notification.enabled,
            channel=self.config.notification.channel,
            telegram_bot_token=self.config.notification.telegram_bot_token,
            telegram_chat_id=self.config.notification.telegram_chat_id,
            email_smtp_host=self.config.notification.email_smtp_host,
            email_smtp_port=self.config.notification.email_smtp_port,
            email_from=self.config.notification.email_from,
            email_to=self.config.notification.email_to,
            email_password=self.config.notification.email_password,
            webhook_url=self.config.notification.webhook_url,
        )
        
        # Scheduler
        self.scheduler = WindowScheduler(
            storage=self.storage,
            notifier=self.notifier,
            camera_id=self.config.camera.camera_id,
            timezone=self.config.window.timezone,
            window_a_start=self.config.window.window_a_start,
            window_a_end=self.config.window.window_a_end,
            window_b_start=self.config.window.window_b_start,
            window_b_end=self.config.window.window_b_end,
        )
        
        # Time Manager
        self.time_manager = TimeManager(
            timezone=self.config.window.timezone,
            reset_time=self.config.production.reset_time,
            morning_start=self.config.production.morning_start,
            morning_end=self.config.production.morning_end,
            realtime_morning_end=self.config.production.realtime_morning_end,
            lunch_end=self.config.production.lunch_end,
        )
        
        # Morning Total Manager
        self.morning_total_manager = MorningTotalManager(
            storage=self.storage,
            timezone=self.config.window.timezone,
            morning_start=self.config.production.morning_start,
            morning_end=self.config.production.morning_end,
        )
        
        # Phase Manager (tracks missing periods)
        self.phase_manager = PhaseManager(
            storage=self.storage,
            time_manager=self.time_manager,
            camera_id=self.config.camera.camera_id,
            timezone=self.config.window.timezone,
        )
        
        # Alert Manager
        self.alert_manager = AlertManager(
            config=self.config,
            storage=self.storage,
            notifier=self.notifier,
            time_manager=self.time_manager,
            phase_manager=self.phase_manager,
            camera_id=self.config.camera.camera_id,
            timezone=self.config.window.timezone,
        )
        
        # Setup callbacks
        self.time_manager.on_reset = self._on_daily_reset
        self.time_manager.on_morning_start = self._on_morning_start
        self.time_manager.on_morning_end = self._on_morning_end
        self.time_manager.on_day_close = self._on_day_close
        
        # Excel Export Scheduler (use same database path as app)
        self.excel_export_scheduler = ExcelExportScheduler(
            db_path=self.config.db_path,
            exports_dir="exports"
        )
        
        # Web Server for LAN access (port 5001 - FastAPI uses 5000)
        # Commented out - web_server.py was deleted
        # self.web_server = WebServer(
        #     app_instance=self,
        #     host='0.0.0.0',
        #     port=5001
        # )
        self.web_server = None  # Disabled for now
        
        logger.info("All components initialized")
        
        # Background I/O queue for non-blocking database writes and snapshots
        # REDUCED: Smaller queue size to prevent memory buildup (10 items max = ~10MB max if all are snapshots)
        self._io_queue = queue.Queue(maxsize=10)  # Reduced from 100 to prevent memory issues
        self._io_thread = None
        self._io_thread_running = False
        
        # FPS optimization: Cache phase check to avoid calling time_manager.get_current_phase() every frame
        self._cached_phase = None
        self._cached_phase_time = 0
        self._phase_cache_interval = 1.0  # Check phase every 1 second instead of every frame
        self._cached_datetime = None  # Cache datetime.now() to avoid calling every frame
        self._datetime_cache_interval = 0.1  # Update datetime cache every 100ms (10 FPS for display)
    
    def _start_io_worker(self):
        """Start background thread for I/O operations (database writes, snapshots)."""
        self._io_thread_running = True
        self._io_thread = threading.Thread(target=self._io_worker, daemon=True)
        self._io_thread.start()
        logger.info("Background I/O worker thread started")
    
    def _stop_io_worker(self):
        """Stop background I/O worker thread."""
        self._io_thread_running = False
        if self._io_thread:
            self._io_thread.join(timeout=5.0)
            logger.info("Background I/O worker thread stopped")
    
    def _io_worker(self):
        """Background worker thread for I/O operations."""
        while self._io_thread_running:
            try:
                # Get task from queue with timeout
                task = self._io_queue.get(timeout=0.5)
                task_type = task.get('type')
                
                try:
                    if task_type == 'save_daily_state':
                        self.storage.save_daily_state(**task['kwargs'])
                    elif task_type == 'add_event':
                        self.storage.add_event(**task['kwargs'])
                    elif task_type == 'save_snapshot':
                        # Free frame from memory immediately after writing
                        frame_data = task['frame']
                        cv2.imwrite(str(task['path']), frame_data)
                        del frame_data  # Explicitly free frame memory
                    elif task_type == 'postgres_event':
                        if self.postgres_writer:
                            self.postgres_writer.write_event(**task['kwargs'])
                except Exception as e:
                    logger.error(f"Background I/O task failed ({task_type}): {e}", exc_info=True)
                finally:
                    self._io_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in I/O worker: {e}", exc_info=True)
    
    def _draw_overlay(self, frame: np.ndarray, tracks: list = None, frame_count: int = 0) -> np.ndarray:
        """Draw overlay on frame with gate visualization."""
        # OPTIMIZED: Draw directly on frame (modify in-place) - avoids expensive copy operation
        # Note: This modifies the original frame, but we're done processing it, and snapshot will have overlay
        overlay = frame  # No copy - significant FPS improvement
        h, w = overlay.shape[:2]
        
        # Draw gate band
        gate_geom = self.gate_counter.get_gate_geometry()
        
        if gate_geom["type"] == "segment":
            # Draw gate segment (line)
            p1 = tuple(map(int, gate_geom["p1"]))
            p2 = tuple(map(int, gate_geom["p2"]))
            
            # Draw gate segment line (thick, visible)
            cv2.line(overlay, p1, p2, (255, 0, 255), 3)
            cv2.circle(overlay, p1, 8, (255, 0, 255), -1)
            cv2.circle(overlay, p2, 8, (255, 0, 255), -1)
            
            # Draw X range if specified
            if gate_geom.get("x_range_min") is not None and gate_geom.get("x_range_max") is not None:
                x_min = int(gate_geom["x_range_min"])
                x_max = int(gate_geom["x_range_max"])
                # Draw vertical lines at x_range boundaries
                cv2.line(overlay, (x_min, 0), (x_min, h), (255, 255, 0), 1)
                cv2.line(overlay, (x_max, 0), (x_max, h), (255, 255, 0), 1)
            
            # Draw direction arrows
            mid_x = (p1[0] + p2[0]) // 2
            mid_y = (p1[1] + p2[1]) // 2
            
            # Calculate perpendicular direction for arrows
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = np.sqrt(dx*dx + dy*dy)
            if length > 0:
                perp_x = -dy / length
                perp_y = dx / length
                
                # Draw IN arrow (green)
                arrow_len = 30
                arrow_start = (int(mid_x - perp_x * arrow_len), int(mid_y - perp_y * arrow_len))
                arrow_end = (int(mid_x + perp_x * arrow_len), int(mid_y + perp_y * arrow_len))
                cv2.arrowedLine(overlay, arrow_start, arrow_end, (0, 255, 0), 3, tipLength=0.3)
                counts = self.gate_counter.get_counts()
                cv2.putText(overlay, f"IN: {counts['in']}", (arrow_end[0] + 10, arrow_end[1]),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Draw OUT arrow (red)
                arrow_start2 = (int(mid_x + perp_x * arrow_len), int(mid_y + perp_y * arrow_len))
                arrow_end2 = (int(mid_x - perp_x * arrow_len), int(mid_y - perp_y * arrow_len))
                cv2.arrowedLine(overlay, arrow_start2, arrow_end2, (0, 0, 255), 3, tipLength=0.3)
                cv2.putText(overlay, f"OUT: {counts['out']}", (arrow_end2[0] + 10, arrow_end2[1]),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        elif gate_geom["type"] == "horizontal_band":
            # Draw horizontal band (magenta/purple rectangle)
            y_center = int(gate_geom["y"])
            height = int(gate_geom["height"])
            x_min = int(gate_geom["x_min"]) if gate_geom["x_min"] is not None else 0
            x_max = int(gate_geom["x_max"]) if gate_geom["x_max"] is not None else w
            
            top_y = int(y_center - height / 2)
            bottom_y = int(y_center + height / 2)
            
            # Create overlay mask to avoid flickering
            overlay_mask = np.zeros_like(overlay)
            cv2.rectangle(overlay_mask, (x_min, top_y), (x_max, bottom_y), (255, 0, 255), -1)
            cv2.addWeighted(overlay_mask, 0.3, overlay, 0.7, 0, overlay)
            
            # Draw border
            cv2.rectangle(overlay, (x_min, top_y), (x_max, bottom_y), (255, 0, 255), 2)
            
            # Draw direction arrows
            arrow_y = y_center
            arrow_x_center = (x_min + x_max) // 2
            
            arrows = self.gate_counter.get_direction_arrows()
            arrow_offset = 0
            for direction, (entry, exit) in arrows.items():
                if direction == "IN":
                    # Arrow pointing up (BOTTOM->TOP)
                    arrow_start = (arrow_x_center, arrow_y + 20)
                    arrow_end = (arrow_x_center, arrow_y - 20)
                    color = (0, 255, 0)  # Green for IN
                else:  # OUT
                    # Arrow pointing down (TOP->BOTTOM)
                    arrow_start = (arrow_x_center, arrow_y - 20)
                    arrow_end = (arrow_x_center, arrow_y + 20)
                    color = (0, 0, 255)  # Red for OUT
                
                cv2.arrowedLine(overlay, arrow_start, arrow_end, color, 3, tipLength=0.3)
                # Draw count next to arrow
                count = self.gate_counter.get_counts()["in" if direction == "IN" else "out"]
                text_x = arrow_x_center + 30 + arrow_offset
                cv2.putText(overlay, str(count), (text_x, arrow_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                arrow_offset += 50
        
        elif gate_geom["type"] == "vertical_band":
            # Draw vertical band (magenta/purple rectangle)
            x_center = int(gate_geom["x"])
            width = int(gate_geom["width"])
            y_min = int(gate_geom["y_min"]) if gate_geom["y_min"] is not None else 0
            y_max = int(gate_geom["y_max"]) if gate_geom["y_max"] is not None else h
            
            left_x = int(x_center - width / 2)
            right_x = int(x_center + width / 2)
            
            # Create a single overlay mask for all zones to avoid flickering
            overlay_mask = np.zeros_like(overlay)
            
            # Draw buffer zones if enabled
            if "in_zone_left" in gate_geom and gate_geom.get("use_buffer_zones", True):
                in_zone_left = int(gate_geom["in_zone_left"])
                in_zone_right = int(gate_geom["in_zone_right"])
                out_zone_left = int(gate_geom["out_zone_left"])
                out_zone_right = int(gate_geom["out_zone_right"])
                
                # Draw IN zone (left side, green tint) on mask
                cv2.rectangle(overlay_mask, (in_zone_left, y_min), (in_zone_right, y_max), (0, 255, 0), -1)
                cv2.rectangle(overlay, (in_zone_left, y_min), (in_zone_right, y_max), (0, 255, 0), 1)
                cv2.putText(overlay, "IN ZONE", (in_zone_left + 5, y_min + 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                
                # Draw OUT zone (right side, red tint) on mask
                cv2.rectangle(overlay_mask, (out_zone_left, y_min), (out_zone_right, y_max), (0, 0, 255), -1)
                cv2.rectangle(overlay, (out_zone_left, y_min), (out_zone_right, y_max), (0, 0, 255), 1)
                cv2.putText(overlay, "OUT ZONE", (out_zone_left + 5, y_min + 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            
            # Draw gate (magenta/purple rectangle) on mask
            cv2.rectangle(overlay_mask, (left_x, y_min), (right_x, y_max), (255, 0, 255), -1)
            
            # Blend all zones at once to avoid flickering
            cv2.addWeighted(overlay_mask, 0.2, overlay, 0.8, 0, overlay)
            
            # Draw border
            cv2.rectangle(overlay, (left_x, y_min), (right_x, y_max), (255, 0, 255), 2)
            
            # Draw direction arrows
            arrow_x = x_center
            arrow_y_center = (y_min + y_max) // 2
            
            arrows = self.gate_counter.get_direction_arrows()
            arrow_offset = 0
            for direction, (entry, exit) in arrows.items():
                if direction == "IN":
                    # Arrow pointing right (LEFT->RIGHT)
                    arrow_start = (arrow_x - 20, arrow_y_center)
                    arrow_end = (arrow_x + 20, arrow_y_center)
                    color = (0, 255, 0)  # Green for IN
                else:  # OUT
                    # Arrow pointing left (RIGHT->LEFT)
                    arrow_start = (arrow_x + 20, arrow_y_center)
                    arrow_end = (arrow_x - 20, arrow_y_center)
                    color = (0, 0, 255)  # Red for OUT
                
                cv2.arrowedLine(overlay, arrow_start, arrow_end, color, 3, tipLength=0.3)
                # Draw count next to arrow
                count = self.gate_counter.get_counts()["in" if direction == "IN" else "out"]
                text_y = arrow_y_center + 30 + arrow_offset
                cv2.putText(overlay, str(count), (arrow_x + 30, text_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                arrow_offset += 30
        
        else:  # LINE_BAND
            # Draw line band
            p1 = tuple(map(int, gate_geom["p1"]))
            p2 = tuple(map(int, gate_geom["p2"]))
            thickness = int(gate_geom["thickness"])
            
            # Draw thick line (band)
            cv2.line(overlay, p1, p2, (255, 0, 255), thickness)
            cv2.circle(overlay, p1, 8, (255, 0, 255), -1)
            cv2.circle(overlay, p2, 8, (255, 0, 255), -1)
        
        # Draw bounding boxes and track IDs
        if tracks:
            for track_id, x1, y1, x2, y2, conf in tracks:
                # Draw bounding box
                cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
                
                # Draw track ID and confidence
                label = f"ID:{track_id} ({conf:.2f})"
                label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(overlay, (int(x1), int(y1) - label_size[1] - 10),
                             (int(x1) + label_size[0], int(y1)), (255, 0, 0), -1)
                cv2.putText(overlay, label, (int(x1), int(y1) - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # Draw bottom-center point (used for gate counting)
                bottom_center_x = int((x1 + x2) / 2)
                bottom_center_y = int(y2)
                cv2.circle(overlay, (bottom_center_x, bottom_center_y), 5, (0, 0, 255), -1)
        
        # Draw counts and info
        counts = self.gate_counter.get_counts()
        
        # Calculate office occupancy
        if self.time_manager:
            # FPS OPTIMIZATION: Cache phase check - only check every 1 second instead of every frame
            current_time_float = time.time()
            if current_time_float - self._cached_phase_time >= self._phase_cache_interval:
                self._cached_phase = self.time_manager.get_current_phase()
                self._cached_phase_time = current_time_float
            
            # FPS OPTIMIZATION: Cache datetime.now() - only update every 100ms instead of every frame
            if (self._cached_datetime is None or 
                current_time_float - self._cached_datetime[0] >= self._datetime_cache_interval):
                now_dt = datetime.now(self.time_manager.tz)
                self._cached_datetime = (current_time_float, now_dt)
            
            current_phase = self._cached_phase
            now_dt = self._cached_datetime[1]
            current_time = now_dt.time()
            
            # Debug log để kiểm tra phase (throttled)
            if frame_count % 300 == 0:  # Log every 300 frames (~10s)
                logger.debug(f"Current phase: {current_phase.value}, time: {current_time.strftime('%H:%M:%S')}, morning={self.time_manager.morning_start.strftime('%H:%M')}-{self.time_manager.morning_end.strftime('%H:%M')}")
            
            if current_phase.value == "MORNING_COUNT":
                # Morning phase: Chỉ hiển thị total morning, KHÔNG hiển thị realtime
                morning_start_time = self.time_manager.morning_start
                morning_end_time = self.time_manager.morning_end
                
                # Tính thời gian còn lại (giây)
                now_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
                end_seconds = morning_end_time.hour * 3600 + morning_end_time.minute * 60
                remaining_seconds = end_seconds - now_seconds
                
                # Chuyển sang giờ:phút:giây
                remaining_hours = remaining_seconds // 3600
                remaining_minutes = (remaining_seconds % 3600) // 60
                remaining_secs = remaining_seconds % 60
                
                # Total morning = số người vào (IN) trừ đi số người ra (OUT) trong morning phase
                total_morning = self.initial_count_in - self.initial_count_out
                
                info_text = [
                    f"=== MORNING COUNT PHASE ===",
                    f"Time: {morning_start_time.hour:02d}:{morning_start_time.minute:02d} - {morning_end_time.hour:02d}:{morning_end_time.minute:02d}",
                    f"Time remaining: {remaining_hours}h {remaining_minutes}m {remaining_secs}s",
                    f"Total Morning: {total_morning} (IN: {self.initial_count_in} - OUT: {self.initial_count_out})",
                    f"FPS: {self.camera.get_fps():.1f}",
                    f"Active Tracks: {len(tracks) if tracks else 0}",
                    "Press 'q' to quit"
                ]
            else:
                # Realtime monitoring phase: Hiển thị Total và Realtime
                initial_total = self.initial_count_in - self.initial_count_out
                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                info_text = [
                    f"=== REALTIME MONITORING ===",
                    f"Total: {initial_total} (initial: IN {self.initial_count_in} - OUT {self.initial_count_out})",
                    f"Realtime: {realtime_count} (Total + IN - OUT)",
                    f"  + IN: {self.realtime_in} | - OUT: {self.realtime_out}",
                    f"FPS: {self.camera.get_fps():.1f}",
                    f"Active Tracks: {len(tracks) if tracks else 0}",
                    "Press 'q' to quit"
                ]
        else:
            # Fallback if time_manager not set
            info_text = [
                f"IN: {counts['in']} | OUT: {counts['out']}",
                f"FPS: {self.camera.get_fps():.1f}",
                f"Active Tracks: {len(tracks) if tracks else 0}",
                "Press 'q' to quit"
            ]
        
        y_offset = 30
        for i, text in enumerate(info_text):
            # Highlight Total and Realtime lines
            if "Total" in text or "Realtime" in text:
                color = (0, 255, 255)  # Yellow for important info
                thickness = 2
            elif "===" in text:
                color = (255, 255, 0)  # Cyan for headers
                thickness = 2
            else:
                color = (0, 255, 0)  # Green for normal info
                thickness = 2
            
            cv2.putText(overlay, text, (10, y_offset + i * 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, thickness)
        
        return overlay
    
    def _on_daily_reset(self):
        """Handle daily reset callback at 06:00 (per requirements)."""
        logger.info("=== DAILY RESET AT 06:00 - Resetting all data and starting TOTAL_MORNING counting ===")
        
        # Reset morning total manager
        if self.morning_total_manager:
            self.morning_total_manager.reset()
        
        # Reset phase manager
        if self.phase_manager:
            self.phase_manager.reset()
        
        # Reset alert manager
        if self.alert_manager:
            self.alert_manager.reset()
        
        # Reset local counters
        self.initial_count_in = 0
        self.initial_count_out = 0
        self.realtime_in = 0
        self.realtime_out = 0
        
        # Reset daily_state for new day
        tz = pytz.timezone(self.config.window.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        self.storage.save_daily_state(
            date=today,
            total_morning=0,
            is_frozen=False,
            is_missing=False,
            realtime_in=0,
            realtime_out=0,
        )
        
        # Close any open missing periods from yesterday
        try:
            from datetime import timedelta
            yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
            conn = self.storage._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE missing_periods
                SET end_time = ?,
                    duration_minutes = CAST((julianday(?) - julianday(start_time)) * 1440 AS INTEGER)
                WHERE substr(start_time, 1, 10) = ? AND end_time IS NULL
            """, (datetime.now(tz).isoformat(), datetime.now(tz).isoformat(), yesterday))
            conn.commit()
            conn.close()
            logger.info(f"Closed any open missing periods from {yesterday}")
        except Exception as e:
            logger.warning(f"Could not close missing periods: {e}")
        
        logger.info("Daily reset completed. TOTAL_MORNING counting started at 06:00")
    
    def _on_morning_start(self):
        """Handle morning phase start callback."""
        # Morning phase started - reset counters to start counting total morning from 0
        logger.info("=== MORNING PHASE STARTED - Resetting counters to count Total Morning ===")
        self.initial_count_in = 0
        self.initial_count_out = 0
        
        # Clear any existing total_morning for today (if app restarted during morning phase)
        tz = pytz.timezone(self.config.window.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        self.storage.save_daily_state(date=today, total_morning=0, is_frozen=False)
        
        logger.info(f"Counters reset: initial_count_in={self.initial_count_in}, initial_count_out={self.initial_count_out}")
        logger.info("Ready to count Total Morning from now until morning phase ends")
    
    def _on_morning_end(self):
        """Handle morning phase end callback."""
        # Lưu total_morning = initial_count_in - initial_count_out (số người vào trừ đi số người ra)
        tz = pytz.timezone(self.config.window.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        total_morning = self.initial_count_in - self.initial_count_out  # IN - OUT
        
        # Also calculate from database events as backup
        morning_start = self.time_manager.morning_start.strftime('%H:%M')
        morning_end = self.time_manager.morning_end.strftime('%H:%M')
        total_morning_from_db = self.storage.get_total_morning_from_events(today, morning_start, morning_end)
        
        # Use the maximum of in-memory and database values (to handle race conditions)
        if total_morning_from_db != total_morning:
            logger.warning(f"total_morning mismatch: in-memory={total_morning}, from_db={total_morning_from_db}, using max")
            total_morning = max(total_morning, total_morning_from_db)
        
        self.storage.save_daily_state(date=today, total_morning=total_morning, is_frozen=True)
        logger.info(f"Morning phase ended: Saved total_morning={total_morning} (IN: {self.initial_count_in} - OUT: {self.initial_count_out}, from_db: {total_morning_from_db})")
        
        # Freeze morning total manager (nếu có)
        if self.morning_total_manager:
            self.morning_total_manager.freeze()
        
        logger.info("=== TOTAL_MORNING LOCKED at 08:30 - Value will not change anymore ===")
    
    def _on_day_close(self):
        """Handle day close at 23:59 - prepare for next day."""
        logger.info("=== DAY CLOSE AT 23:59 - Finalizing today's data ===")
        tz = pytz.timezone(self.config.window.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        
        # Ensure all data is persisted
        try:
            # Final save of daily state
            state = self.storage.get_daily_state(today)
            if state:
                logger.info(f"Final daily state for {today}: total_morning={state.get('total_morning', 0)}, "
                          f"realtime_in={state.get('realtime_in', 0)}, realtime_out={state.get('realtime_out', 0)}")
            
            # Close any open missing periods
            conn = self.storage._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE missing_periods
                SET end_time = ?,
                    duration_minutes = CAST((julianday(?) - julianday(start_time)) * 1440 AS INTEGER)
                WHERE substr(start_time, 1, 10) = ? AND end_time IS NULL
            """, (datetime.now(tz).isoformat(), datetime.now(tz).isoformat(), today))
            conn.commit()
            conn.close()
            logger.info(f"Closed any open missing periods for {today}")
        except Exception as e:
            logger.warning(f"Error during day close: {e}")
        
        logger.info("Day close completed. System ready for reset at 06:00 tomorrow.")
    
    def run(self):
        """Run main loop."""
        logger.info("Starting People Counter MVP...")
        
        # Initialize components
        self._initialize_components()
        
        # Connect camera
        if not self.camera.connect():
            logger.error("Failed to connect to camera, exiting")
            # Show error window anyway
            error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(error_frame, "Camera connection failed!", (50, 200), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(error_frame, "Check camera connection", (50, 250), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(error_frame, "Press 'q' to exit", (50, 300), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("People Counter", error_frame)
            logger.info("Showing error window - press 'q' to exit")
            while True:
                if cv2.waitKey(100) & 0xFF == ord('q'):
                    break
            return
        
        # Start schedulers
        self.scheduler.start()
        self.time_manager.start()
        self.phase_manager.start()
        self.alert_manager.start()
        self.excel_export_scheduler.start()
        
        # Start web server
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.running = True
        logger.info("Main loop started")
        
        # Create OpenCV window before main loop
        # Use WINDOW_AUTOSIZE for better compatibility on Windows
        cv2.namedWindow("People Counter", cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty("People Counter", cv2.WND_PROP_TOPMOST, 1)  # Make window topmost
        cv2.moveWindow("People Counter", 100, 100)  # Position window
        logger.info("OpenCV window created at position (100, 100)")
        
        # DIAGNOSTIC: Force test insert to verify database writes work
        try:
            logger.info(f"DIAGNOSTIC: Testing database write to {Path(self.config.db_path).resolve()}")
            test_in_id = self.storage.add_event(
                track_id=999998,
                direction='IN',
                camera_id='startup_test'
            )
            test_out_id = self.storage.add_event(
                track_id=999999,
                direction='OUT',
                camera_id='startup_test'
            )
            if test_in_id and test_out_id:
                logger.info(f"DIAGNOSTIC: Test inserts successful - IN id={test_in_id}, OUT id={test_out_id}")
            else:
                logger.error(f"DIAGNOSTIC: Test inserts FAILED - IN id={test_in_id}, OUT id={test_out_id}")
        except Exception as e:
            logger.error(f"DIAGNOSTIC: Test insert error: {e}", exc_info=True)
        
        # Initialize office occupancy tracking
        self.start_time = time.time()
        
        # Sync counters from database if available
        tz = pytz.timezone(self.config.window.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        state = self.storage.get_daily_state(today)
        
        # Check if we're currently in morning phase
        current_phase = self.time_manager.get_current_phase() if self.time_manager else None
        is_in_morning_phase = (current_phase and current_phase.value == "MORNING_COUNT")
        
        # Initialize phase cache for FPS optimization
        if self.time_manager:
            self._cached_phase = current_phase
            self._cached_phase_time = time.time()
            # Initialize datetime cache
            now_dt = datetime.now(self.time_manager.tz)
            self._cached_datetime = (time.time(), now_dt)
        
        if is_in_morning_phase:
            # If in morning phase, reset counters to start counting from 0
            logger.info("=== App started during MORNING PHASE - Resetting counters to count Total Morning ===")
            self.initial_count_in = 0
            self.initial_count_out = 0
            self.realtime_in = state.get('realtime_in', 0) if state else 0
            self.realtime_out = state.get('realtime_out', 0) if state else 0
            # Clear total_morning to start fresh
            self.storage.save_daily_state(date=today, total_morning=0, is_frozen=False)
            logger.info(f"Counters reset for morning phase: initial IN={self.initial_count_in}, OUT={self.initial_count_out}")
        elif state:
            # Load from state (we're past morning phase or before it)
            self.realtime_in = state.get('realtime_in', 0)
            self.realtime_out = state.get('realtime_out', 0)
            
            # Calculate initial_count_in/out from morning phase events
            morning_start = self.time_manager.morning_start.strftime('%H:%M')
            morning_end = self.time_manager.morning_end.strftime('%H:%M')
            conn = self.storage._get_connection()
            cursor = conn.cursor()
            start_hour, start_min = map(int, morning_start.split(':'))
            end_hour, end_min = map(int, morning_end.split(':'))
            # Use events table and handle ISO timestamp format
            cursor.execute("""
                SELECT UPPER(direction) as direction, COUNT(*) as count
                FROM events
                WHERE substr(timestamp, 1, 10) = ?
                  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
                  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
                GROUP BY UPPER(direction)
            """, (today, start_hour * 60 + start_min, end_hour * 60 + end_min))
            results = cursor.fetchall()
            self.initial_count_in = 0
            self.initial_count_out = 0
            for direction, count in results:
                if direction == 'IN':
                    self.initial_count_in = count
                elif direction == 'OUT':
                    self.initial_count_out = count
            conn.close()
            
            total_morning = state.get('total_morning', 0)
            logger.info(f"Synced counters from database: initial IN={self.initial_count_in}, OUT={self.initial_count_out}, realtime IN={self.realtime_in}, OUT={self.realtime_out}, total_morning={total_morning}")
        else:
            # No existing state, start with zero counters
            self.initial_count_in = 0
            self.initial_count_out = 0
            self.realtime_in = 0
            self.realtime_out = 0
            logger.info("No existing state, starting with zero counters")
        
        logger.info("Office occupancy tracking initialized")
        
        # Create snapshot directory if needed
        if self.config.save_snapshots:
            Path(self.config.snapshot_dir).mkdir(parents=True, exist_ok=True)
        
        frame_count = 0
        last_log_time = time.time()
        self_test_inserted = False
        self_test_check_time = time.time()
        
        # Simple logging timer
        
        logger.info("Entering main loop - waiting for camera frames...")
        
        # Show a test frame first to ensure window is visible
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(test_frame, "Initializing camera...", (150, 220), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        try:
            cv2.imshow("People Counter", test_frame)
            cv2.waitKey(100)  # Force window to display
            cv2.setWindowProperty("People Counter", cv2.WND_PROP_TOPMOST, 0)  # Remove topmost after showing
            logger.info("Test frame displayed - window should be visible now")
        except Exception as e:
            logger.error(f"Error showing test frame: {e}", exc_info=True)
        
        try:
            while self.running:
                # Read frame
                success, frame = self.camera.read()
                if not success or frame is None:
                    if frame_count == 0:
                        logger.warning("Camera not returning frames - check camera connection")
                        # Show error frame instead of blank screen
                        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(error_frame, "Waiting for camera frames...", (100, 220), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                        cv2.imshow("People Counter", error_frame)
                        if cv2.waitKey(100) & 0xFF == ord('q'):
                            break
                    continue
                
                # Log first successful frame read
                if frame_count == 0:
                    logger.info(f"First frame received! Frame shape: {frame.shape}")
                
                frame_count += 1
                
                # Detect and track using YOLO's built-in tracker
                try:
                    tracks = self.detector.detect_and_track(frame, persist=True)
                except Exception as e:
                    logger.warning(f"Detect and track failed, falling back to separate detect+track: {e}", exc_info=True)
                    # Fallback to separate detect + track
                    detections = self.detector.detect(frame)
                    tracks = self.tracker.update(detections, frame)
                    
                    # Debug: log if no tracks detected
                    if frame_count % 30 == 0:
                        if len(detections) == 0:
                            logger.debug(f"No detections in frame {frame_count} (fallback mode)")
                        elif len(tracks) == 0:
                            logger.debug(f"{len(detections)} detections but no tracks in frame {frame_count}")
                
                # Update gate counter with bottom-center points
                current_ts = time.time()
                elapsed_time = current_ts - self.start_time
                is_initial_phase = elapsed_time < self.initial_phase_duration
                
                for track_id, x1, y1, x2, y2, conf in tracks:
                    # Use bottom-center of bounding box as tracking point
                    bottom_center = ((x1 + x2) / 2, y2)
                    # Update counter
                    event = self.gate_counter.update(track_id, bottom_center, current_ts)
                    
                    if event:
                        # Track office occupancy based on TimeManager phase
                        # Kiểm tra phase từ time_manager (MORNING_COUNT hoặc REALTIME_MONITORING)
                        if self.time_manager:
                            current_phase = self.time_manager.get_current_phase()
                            is_morning_phase = (current_phase.value == "MORNING_COUNT")
                        else:
                            # Fallback: dùng logic cũ (1 phút đầu)
                            is_morning_phase = is_initial_phase
                        
                        if is_morning_phase:
                            # Morning phase: Đếm vào initial_count_in/out (total morning)
                            if event.direction == "IN":
                                self.initial_count_in += 1
                                total = self.initial_count_in - self.initial_count_out
                                # OPTIMIZED: Throttle logging (only log every 10th event or important ones)
                                if self.initial_count_in % 10 == 1:
                                    logger.info(f"Morning phase: Person entered. IN: {self.initial_count_in}, OUT: {self.initial_count_out}, Total: {total}")
                            elif event.direction == "OUT":
                                self.initial_count_out += 1
                                total = self.initial_count_in - self.initial_count_out
                                # OPTIMIZED: Throttle logging
                                if self.initial_count_out % 10 == 1:
                                    logger.info(f"Morning phase: Person exited. IN: {self.initial_count_in}, OUT: {self.initial_count_out}, Total: {total}")
                            
                            # Lưu total_morning ngay khi có events (để alert_manager có thể check)
                            # OPTIMIZED: Use background queue instead of blocking write
                            tz = pytz.timezone(self.config.window.timezone)
                            today = datetime.now(tz).strftime("%Y-%m-%d")
                            total_morning = self.initial_count_in - self.initial_count_out
                            # Save daily state (queue for background, fallback to direct write)
                            try:
                                self._io_queue.put_nowait({
                                    'type': 'save_daily_state',
                                    'kwargs': {'date': today, 'total_morning': total_morning}
                                })
                            except queue.Full:
                                logger.warning("I/O queue full, writing daily state directly")
                                self.storage.save_daily_state(date=today, total_morning=total_morning)
                        else:
                            # Realtime monitoring phase: Đếm vào realtime_in/out
                            if event.direction == "IN":
                                self.realtime_in += 1
                                initial_total = self.initial_count_in - self.initial_count_out
                                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                                # OPTIMIZED: Throttle logging
                                if self.realtime_in % 10 == 1:
                                    logger.info(f"Realtime: Person entered. Realtime IN: {self.realtime_in}, Initial Total: {initial_total}, Realtime count: {realtime_count}")
                                
                                # Lưu realtime_in vào state để alert_manager sử dụng
                                # OPTIMIZED: Use background queue instead of blocking write
                                tz = pytz.timezone(self.config.window.timezone)
                                today = datetime.now(tz).strftime("%Y-%m-%d")
                                # Save realtime counters (queue for background, fallback to direct write)
                                try:
                                    self._io_queue.put_nowait({
                                        'type': 'save_daily_state',
                                        'kwargs': {'date': today, 'realtime_in': self.realtime_in}
                                    })
                                except queue.Full:
                                    logger.warning("I/O queue full, writing realtime counters directly")
                                    self.storage.save_daily_state(date=today, realtime_in=self.realtime_in)
                                
                            elif event.direction == "OUT":
                                self.realtime_out += 1
                                initial_total = self.initial_count_in - self.initial_count_out
                                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                                # OPTIMIZED: Throttle logging
                                if self.realtime_out % 10 == 1:
                                    logger.info(f"Realtime: Person exited. Realtime OUT: {self.realtime_out}, Initial Total: {initial_total}, Realtime count: {realtime_count}")
                                
                                # Lưu realtime_out vào state để alert_manager sử dụng
                                # OPTIMIZED: Use background queue instead of blocking write
                                tz = pytz.timezone(self.config.window.timezone)
                                today = datetime.now(tz).strftime("%Y-%m-%d")
                                # Save realtime counters (queue for background, fallback to direct write)
                                try:
                                    self._io_queue.put_nowait({
                                        'type': 'save_daily_state',
                                        'kwargs': {'date': today, 'realtime_out': self.realtime_out}
                                    })
                                except queue.Full:
                                    logger.warning("I/O queue full, writing realtime counters directly")
                                    self.storage.save_daily_state(date=today, realtime_out=self.realtime_out)
                        
                        # OPTIMIZED: Save event to database via background queue (non-blocking)
                        # SQLite (always save for compatibility with existing code)
                        # CRITICAL: Event must be written - try queue first, fallback to direct write
                        try:
                            self._io_queue.put_nowait({
                                'type': 'add_event',
                                'kwargs': {
                                    'track_id': track_id,
                                    'direction': event.direction.lower(),
                                    'camera_id': self.config.camera.camera_id,
                                }
                            })
                        except queue.Full:
                            # Queue full - write directly to ensure no data loss (CRITICAL)
                            logger.warning("I/O queue full, writing event directly to database to prevent data loss")
                            try:
                                self.storage.add_event(
                                    track_id=track_id,
                                    direction=event.direction.lower(),
                                    camera_id=self.config.camera.camera_id,
                                )
                            except Exception as e:
                                logger.error(f"CRITICAL: Direct event write failed: {e}", exc_info=True)
                        
                        # PostgreSQL (if enabled, non-blocking)
                        if self.postgres_writer:
                            try:
                                event_time = datetime.fromtimestamp(event.timestamp)
                                self._io_queue.put_nowait({
                                    'type': 'postgres_event',
                                    'kwargs': {
                                        'event_time': event_time,
                                        'direction': event.direction,
                                        'camera_id': self.config.camera.camera_id,
                                    }
                                })
                            except queue.Full:
                                pass  # Non-critical
                        
                        
                        # OPTIMIZED: Save snapshot via background queue (non-blocking)
                        # MEMORY FIX: Only save snapshot if queue has space (prevents RAM buildup)
                        if self.config.save_snapshots:
                            # Only try to save if queue is not full (avoid memory buildup)
                            if self._io_queue.qsize() < self._io_queue.maxsize * 0.7:  # Only if < 70% full
                                timestamp = time.strftime("%Y%m%d_%H%M%S")
                                snapshot_path = Path(self.config.snapshot_dir) / f"gate_{track_id}_{event.direction}_{timestamp}.jpg"
                                try:
                                    # Make a copy of frame for snapshot (background thread will write it)
                                    frame_copy = frame.copy()
                                    self._io_queue.put_nowait({
                                        'type': 'save_snapshot',
                                        'path': snapshot_path,
                                        'frame': frame_copy
                                    })
                                except queue.Full:
                                    pass  # Silently skip if queue is full
                
                # Self-test insert: If no events exist after 60 seconds, insert a test event
                current_time = time.time()
                if not self_test_inserted and (current_time - self_test_check_time) >= 60:
                    # Check if any events exist
                    try:
                        import sqlite3
                        conn = sqlite3.connect(self.config.db_path, check_same_thread=False)
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM people_events")
                        event_count = cursor.fetchone()[0]
                        conn.close()
                        
                        if event_count == 0:
                            # Insert self-test event
                            test_event_id = self.storage.add_event(
                                track_id=999999,
                                direction='IN',
                                camera_id='self_test'
                            )
                            if test_event_id:
                                logger.info(f"SELF_TEST_EVENT_INSERTED: id={test_event_id}, direction=IN, camera_id=self_test")
                            else:
                                logger.error("SELF_TEST_EVENT_INSERTED: FAILED to insert test event")
                        else:
                            logger.debug(f"Self-test skipped: {event_count} events already exist")
                    except Exception as e:
                        logger.error(f"Self-test insert error: {e}", exc_info=True)
                    
                    self_test_inserted = True
                
                # Log metrics periodically (simplified)
                current_time = time.time()
                if current_time - last_log_time >= 5:  # Every 5 seconds
                    counts = self.gate_counter.get_counts()
                    logger.info(
                        f"FPS={self.camera.get_fps():.1f}, "
                        f"Frames={frame_count}, IN={counts['in']}, OUT={counts['out']}, "
                        f"Active tracks={len(tracks)}"
                    )
                    last_log_time = current_time
                
                # Draw overlay and display
                overlay = self._draw_overlay(frame, tracks, frame_count)
                
                # Display frame
                try:
                    cv2.imshow("People Counter", overlay)
                except Exception as e:
                    logger.error(f"Error displaying frame: {e}", exc_info=True)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    logger.info("User pressed 'q' to quit")
                    break
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def shutdown(self):
        """Shutdown application gracefully."""
        logger.info("Shutting down application...")
        self.running = False
        
        # Stop background I/O worker
        self._stop_io_worker()
        
        # Force final Excel export before shutdown
        if self.excel_export_scheduler:
            try:
                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                from pathlib import Path
                output_file = Path("exports") / "daily" / f"people_counter_{today}.xlsx"
                logger.info("Forcing final Excel export before shutdown...")
                self.excel_export_scheduler._export_daily_excel(today, output_file)
            except Exception as e:
                logger.error(f"Error during final export: {e}", exc_info=True)
            self.excel_export_scheduler.stop()
        
        if self.postgres_writer:
            self.postgres_writer.close()
        
        if self.alert_manager:
            self.alert_manager.stop()
        
        if self.phase_manager:
            self.phase_manager.stop()
        
        if self.time_manager:
            self.time_manager.stop()
        
        if self.scheduler:
            self.scheduler.stop()
        
        if self.camera:
            self.camera.release()
        
        logger.info("Shutdown complete")


def main():
    """Entry point."""
    app = PeopleCounterApp()
    app.run()


if __name__ == "__main__":
    main()

