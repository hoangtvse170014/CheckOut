"""Main application entry point."""

import logging
import signal
import sys
import time
from pathlib import Path
import cv2
import numpy as np

from app.config import load_config
from app.camera import CameraStream
from app.detector import PersonDetector
from app.tracker import Tracker
from app.vision.gate_counter import GateCounter
from app.vision.gate_counter_segment import GateCounterSegment
from app.storage import Storage
from app.scheduler import WindowScheduler
from app.notifier import Notifier

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
        
        # Storage
        self.storage = Storage(
            db_path=self.config.db_path,
            timezone=self.config.window.timezone,
        )
        
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
        
        logger.info("All components initialized")
    
    def _draw_overlay(self, frame: np.ndarray, tracks: list = None) -> np.ndarray:
        """Draw overlay on frame with gate visualization."""
        overlay = frame.copy()
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
        if self.start_time:
            elapsed_time = time.time() - self.start_time
            is_initial_phase = elapsed_time < self.initial_phase_duration
            
            if is_initial_phase:
                # Phase 1: Hiển thị Total (IN - OUT trong 1 phút đầu)
                remaining_time = int(self.initial_phase_duration - elapsed_time)
                total = self.initial_count_in - self.initial_count_out
                info_text = [
                    f"=== INITIAL COUNT PHASE ===",
                    f"Time remaining: {remaining_time}s",
                    f"Total: {total} (IN: {self.initial_count_in} - OUT: {self.initial_count_out})",
                    f"FPS: {self.camera.get_fps():.1f}",
                    f"Active Tracks: {len(tracks) if tracks else 0}",
                    "Press 'q' to quit"
                ]
            else:
                # Phase 2: Hiển thị Total và Realtime
                initial_total = self.initial_count_in - self.initial_count_out
                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                info_text = [
                    f"=== REALTIME TRACKING ===",
                    f"Total: {initial_total} (initial: IN {self.initial_count_in} - OUT {self.initial_count_out})",
                    f"Realtime: {realtime_count} (Total + IN - OUT)",
                    f"  + IN: {self.realtime_in} | - OUT: {self.realtime_out}",
                    f"FPS: {self.camera.get_fps():.1f}",
                    f"Active Tracks: {len(tracks) if tracks else 0}",
                    "Press 'q' to quit"
                ]
        else:
            # Fallback if start_time not set
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
    
    def run(self):
        """Run main loop."""
        logger.info("Starting People Counter MVP...")
        
        # Initialize components
        self._initialize_components()
        
        # Connect camera
        if not self.camera.connect():
            logger.error("Failed to connect to camera, exiting")
            return
        
        # Start scheduler
        self.scheduler.start()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.running = True
        logger.info("Main loop started")
        
        # Initialize office occupancy tracking
        self.start_time = time.time()
        self.initial_count_in = 0
        self.initial_count_out = 0
        self.realtime_in = 0
        self.realtime_out = 0
        logger.info("Office occupancy tracking initialized: 1-minute initial count phase (IN and OUT)")
        
        # Create snapshot directory if needed
        if self.config.save_snapshots:
            Path(self.config.snapshot_dir).mkdir(parents=True, exist_ok=True)
        
        frame_count = 0
        last_log_time = time.time()
        
        try:
            while self.running:
                # Profile total loop time
                loop_start = time.time()
                
                # Read frame
                read_start = time.time()
                success, frame = self.camera.read()
                read_time = time.time() - read_start
                if not success or frame is None:
                    continue
                
                frame_count += 1
                
                # Resize frame if max_resolution is set (for high-res cameras - faster detection)
                original_frame = frame
                frame_scale = 1.0
                if self.config.camera.max_resolution is not None:
                    h, w = frame.shape[:2]
                    max_dim = max(h, w)
                    if max_dim > self.config.camera.max_resolution:
                        scale = self.config.camera.max_resolution / max_dim
                        new_w = int(w * scale)
                        new_h = int(h * scale)
                        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                        frame_scale = scale
                
                # Detect and track using YOLO's built-in tracker (simpler and more reliable)
                try:
                    detect_start = time.time()
                    tracks = self.detector.detect_and_track(frame, persist=True)
                    detect_time = time.time() - detect_start
                    # Scale coordinates back to original resolution if frame was resized
                    if frame_scale != 1.0:
                        tracks = [
                            (tid, x1/frame_scale, y1/frame_scale, x2/frame_scale, y2/frame_scale, conf)
                            for tid, x1, y1, x2, y2, conf in tracks
                        ]
                        frame = original_frame  # Use original frame for overlay
                    
                        
                except Exception as e:
                    logger.warning(f"Detect and track failed, falling back to separate detect+track: {e}", exc_info=True)
                    # Fallback to separate detect + track
                    detections = self.detector.detect(frame)
                    # Scale coordinates back to original resolution if frame was resized
                    if frame_scale != 1.0:
                        detections = [
                            (x1/frame_scale, y1/frame_scale, x2/frame_scale, y2/frame_scale, conf)
                            for x1, y1, x2, y2, conf in detections
                        ]
                        frame = original_frame  # Use original frame for tracking
                    tracks = self.tracker.update(detections, frame)
                    
                    # Debug: log if no tracks detected
                    if frame_count % 30 == 0:
                        if len(detections) == 0:
                            logger.debug(f"No detections in frame {frame_count} (fallback mode)")
                        elif len(tracks) == 0:
                            logger.debug(f"{len(detections)} detections but no tracks in frame {frame_count}")
                
                # Update gate counter with bottom-center points
                # IMPORTANT: Update counter for EVERY track EVERY frame
                current_ts = time.time()
                elapsed_time = current_ts - self.start_time
                is_initial_phase = elapsed_time < self.initial_phase_duration
                
                for track_id, x1, y1, x2, y2, conf in tracks:
                    # Use bottom-center of bounding box as tracking point
                    bottom_center = ((x1 + x2) / 2, y2)
                    # Update counter (tracks position every frame, counts when entering gate)
                    event = self.gate_counter.update(track_id, bottom_center, current_ts)
                    
                    if event:
                        # Track office occupancy based on phase
                        if is_initial_phase:
                            # Phase 1: Đếm cả IN và OUT trong 1 phút đầu
                            if event.direction == "IN":
                                self.initial_count_in += 1
                                total = self.initial_count_in - self.initial_count_out
                                logger.info(f"Initial phase: Person entered. IN: {self.initial_count_in}, OUT: {self.initial_count_out}, Total: {total}")
                            elif event.direction == "OUT":
                                self.initial_count_out += 1
                                total = self.initial_count_in - self.initial_count_out
                                logger.info(f"Initial phase: Person exited. IN: {self.initial_count_in}, OUT: {self.initial_count_out}, Total: {total}")
                        else:
                            # Phase 2: Realtime tracking sau 1 phút
                            if event.direction == "IN":
                                self.realtime_in += 1
                                initial_total = self.initial_count_in - self.initial_count_out
                                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                                logger.info(f"Realtime: Person entered. Realtime IN: {self.realtime_in}, Initial Total: {initial_total}, Realtime count: {realtime_count}")
                            elif event.direction == "OUT":
                                self.realtime_out += 1
                                initial_total = self.initial_count_in - self.initial_count_out
                                realtime_count = initial_total + (self.realtime_in - self.realtime_out)
                                logger.info(f"Realtime: Person exited. Realtime OUT: {self.realtime_out}, Initial Total: {initial_total}, Realtime count: {realtime_count}")
                        
                        # Save event to database
                        self.storage.add_event(
                            track_id=track_id,
                            direction=event.direction.lower(),
                            camera_id=self.config.camera.camera_id,
                        )
                        
                        # Save snapshot if enabled
                        if self.config.save_snapshots:
                            timestamp = time.strftime("%Y%m%d_%H%M%S")
                            snapshot_path = Path(self.config.snapshot_dir) / f"gate_{track_id}_{event.direction}_{timestamp}.jpg"
                            cv2.imwrite(str(snapshot_path), frame)
                
                # Log metrics periodically
                current_time = time.time()
                loop_time = current_time - loop_start
                
                if current_time - last_log_time >= 5:  # Every 5 seconds for debugging
                    counts = self.gate_counter.get_counts()
                    logger.info(
                        f"Metrics: FPS={self.camera.get_fps():.1f}, "
                        f"Frames={frame_count}, IN={counts['in']}, OUT={counts['out']}, "
                        f"Active tracks={len(tracks)}, "
                        f"Loop={loop_time*1000:.1f}ms, Read={read_time*1000:.1f}ms, Detect={detect_time*1000:.1f}ms"
                    )
                    last_log_time = current_time
                
                # Display frame with overlay (include tracks for visualization)
                # Draw overlay every frame to avoid flickering
                overlay = self._draw_overlay(frame, tracks)
                cv2.imshow("People Counter", overlay)
                if cv2.waitKey(1) & 0xFF == ord('q'):
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
        """Shutdown application."""
        logger.info("Shutting down...")
        
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

