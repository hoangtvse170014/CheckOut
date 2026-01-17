"""
FastAPI web server for viewing people count data from database.
Lightweight, read-only, LAN-only access with camera stream.
"""

import logging
import sqlite3
import socket
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from export.db_queries import get_total_morning, get_realtime_count, get_events

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="People Counter API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration - Load from config to match main app
try:
    from app.config import load_config
    _config = load_config()
    MORNING_START = _config.production.morning_start
    MORNING_END = _config.production.morning_end
    REALTIME_MORNING_END = _config.production.realtime_morning_end
    LUNCH_END = _config.production.lunch_end
    TIMEZONE = _config.window.timezone
except Exception as e:
    logger.warning(f"Could not load config, using defaults: {e}")
    MORNING_START = "06:00"
    MORNING_END = "08:30"
    REALTIME_MORNING_END = "11:55"
    LUNCH_END = "13:15"
    TIMEZONE = "Asia/Ho_Chi_Minh"

DB_PATH = "data/people_counter.db"
PORT = 8000

# Camera stream variables (shared)
current_frame = None
frame_lock = threading.Lock()
app_instance = None  # Will be set if main app is running
camera_cap = None  # Direct camera connection for standalone mode

# Realtime data cache from main app (updated via POST endpoint)
realtime_data_cache = {}
realtime_data_lock = threading.Lock()


def init_camera():
    """Initialize camera connection for standalone mode."""
    global camera_cap
    try:
        from app.config import load_config
        config = load_config()
        camera_url = getattr(config.camera, "url", None)
        
        if camera_url:
            logger.info(f"Attempting to initialize camera: {camera_url}")
            if camera_url.isdigit():
                camera_cap = cv2.VideoCapture(int(camera_url))
            else:
                camera_cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)
            
            if camera_cap and camera_cap.isOpened():
                # Set buffer size to reduce latency
                camera_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                logger.info(f"Camera initialized for web server: {camera_url}")
                return True
            else:
                logger.warning("Could not open camera for web server")
                camera_cap = None
                return False
        else:
            logger.warning("No camera URL configured")
            return False
    except Exception as e:
        logger.warning(f"Could not initialize camera: {e}", exc_info=True)
        camera_cap = None
        return False


class StatusResponse(BaseModel):
    """API status response model."""
    date: str
    total_morning: int
    realtime_count: int
    missing_now: bool
    phase: str
    last_update: str


class RealtimeDataUpdate(BaseModel):
    """Model for updating realtime data from main app."""
    date: str
    total_morning: int
    realtime_in: int
    realtime_out: int
    realtime_count: int
    phase: str
    timestamp: str  # ISO timestamp


class EventResponse(BaseModel):
    """Event response model."""
    event_time: str
    direction: str
    camera_id: str


def get_lan_ip() -> Optional[str]:
    """Get LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip.startswith("127."):
                return None
            return ip
        except Exception:
            return None


def update_frame(frame):
    """Update current frame for streaming (called by main app or external)."""
    global current_frame
    try:
        with frame_lock:
            if frame is not None:
                # Make a copy to avoid issues with frame being modified
                if isinstance(frame, np.ndarray):
                    current_frame = frame.copy()
                else:
                    current_frame = frame
            else:
                current_frame = None
    except Exception as e:
        logger.error(f"Error updating frame: {e}")


def set_app_instance(instance):
    """Set app instance to get camera frame from."""
    global app_instance
    app_instance = instance
    logger.info("App instance set for camera stream")
    
    # Try to get initial frame
    if app_instance and hasattr(app_instance, 'camera'):
        try:
            ret, frame = app_instance.camera.read()
            if ret and frame is not None:
                update_frame(frame)
                logger.info("Initial frame captured from app camera")
        except Exception as e:
            logger.warning(f"Could not get initial frame: {e}")


def get_db_data() -> dict:
    """
    Get data from database or app instance or cache.
    Returns dict with total_morning, realtime, missing, last_update.
    Never crashes - returns 0 values if database empty or error.
    """
    try:
        # First priority: Check cache from main app POST endpoint (most up-to-date)
        global realtime_data_cache, realtime_data_lock
        with realtime_data_lock:
            if realtime_data_cache:
                today = datetime.now().strftime("%Y-%m-%d")
                cached_data = realtime_data_cache.get(today)
                if cached_data:
                    # Check if cache is recent (within last 10 seconds)
                    try:
                        timestamp_str = cached_data.get('timestamp', '')
                        if timestamp_str:
                            # Handle timezone-aware and naive timestamps
                            if '+' in timestamp_str or timestamp_str.endswith('Z'):
                                cache_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                now = datetime.now(cache_time.tzinfo) if cache_time.tzinfo else datetime.now()
                            else:
                                # Naive timestamp, assume local time
                                cache_time = datetime.fromisoformat(timestamp_str)
                                now = datetime.now()
                            time_diff = abs((now - cache_time).total_seconds())
                        else:
                            time_diff = 999  # No timestamp, consider stale
                    except Exception:
                        time_diff = 999  # Error parsing, consider stale
                    
                    if time_diff < 10:  # Use cache if less than 10 seconds old
                        realtime = cached_data.get('realtime_count', 0)
                        total_morning = cached_data.get('total_morning', 0)
                        realtime_in = cached_data.get('realtime_in', 0)
                        realtime_out = cached_data.get('realtime_out', 0)
                        missing = max(0, total_morning - realtime) if total_morning > 0 else 0
                        
                        # Extract time from timestamp for last_update
                        timestamp = cached_data.get('timestamp', '')
                        if 'T' in timestamp:
                            time_part = timestamp.split('T')[1].split('+')[0].split('.')[0]
                            last_update = time_part[:8]  # HH:MM:SS
                        else:
                            last_update = datetime.now().strftime("%H:%M:%S")
                        
                        return {
                            "date": today,
                            "total_morning": total_morning,
                            "realtime": realtime,
                            "realtime_in": realtime_in,
                            "realtime_out": realtime_out,
                            "missing": missing,
                            "missing_now": missing > 0,
                            "phase": cached_data.get('phase', 'realtime').lower(),
                            "last_update": last_update
                        }
        
        # Second priority: Try to get from app instance (if same process)
        global app_instance
        if app_instance is not None:
            try:
                # Get from app instance (most accurate and realtime)
                realtime_in = getattr(app_instance, 'realtime_in', 0)
                realtime_out = getattr(app_instance, 'realtime_out', 0)
                
                # Get total_morning from database/state (the frozen value from morning phase)
                # This is the correct way: use the saved value, not calculate from initial_count_in/out
                today = datetime.now().strftime("%Y-%m-%d")
                if hasattr(app_instance, 'storage') and app_instance.storage:
                    state = app_instance.storage.get_daily_state(today)
                    if state and state.get('total_morning') is not None:
                        total_morning = state.get('total_morning', 0)
                    else:
                        # Fallback: if state doesn't exist yet, calculate from morning phase events
                        if hasattr(app_instance, 'time_manager') and app_instance.time_manager:
                            morning_start = app_instance.time_manager.morning_start.strftime('%H:%M')
                            morning_end = app_instance.time_manager.morning_end.strftime('%H:%M')
                            total_morning = app_instance.storage.get_total_morning_from_events(today, morning_start, morning_end)
                        else:
                            # Last resort: use current values
                            initial_count_in = getattr(app_instance, 'initial_count_in', 0)
                            initial_count_out = getattr(app_instance, 'initial_count_out', 0)
                            total_morning = initial_count_in - initial_count_out
                else:
                    # No storage, fallback to database
                    total_morning = 0
                
                # Calculate realtime count: total_morning (from DB) + (realtime_in - realtime_out)
                realtime = total_morning + (realtime_in - realtime_out)
                
                # Get phase
                phase = "REALTIME_MORNING"
                if hasattr(app_instance, 'time_manager') and app_instance.time_manager:
                    phase = app_instance.time_manager.get_current_phase().value
                
                last_update = datetime.now().strftime("%H:%M:%S")
                
                # Calculate missing (never negative)
                missing = max(0, total_morning - realtime) if total_morning > 0 else 0
                
                return {
                    "date": today,
                    "total_morning": total_morning,
                    "realtime": realtime,
                    "realtime_in": realtime_in,
                    "realtime_out": realtime_out,
                    "missing": missing,
                    "missing_now": False,
                    "phase": phase.lower(),
                    "last_update": last_update
                }
            except AttributeError as e:
                logger.debug(f"Could not get data from app instance: {e}, falling back to database")
        
        # Fallback to database if app instance not available
        if not Path(DB_PATH).exists():
            logger.warning(f"Database file not found: {DB_PATH}")
            today = datetime.now().strftime("%Y-%m-%d")
            return {
                "date": today,
                "total_morning": 0,
                "realtime": 0,
                "realtime_in": 0,
                "realtime_out": 0,
                "missing": 0,
                "missing_now": False,
                "phase": "morning",
                "last_update": datetime.now().strftime("%H:%M:%S")
            }
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            # Get today's date
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Try to get from daily_state first (more accurate, matches app logic)
            cursor.execute("""
                SELECT total_morning, realtime_in, realtime_out, is_frozen
                FROM daily_state
                WHERE date = ?
            """, (today,))
            
            state_row = cursor.fetchone()
            
            if state_row:
                total_morning_db = state_row[0]
                realtime_in = state_row[1] or 0
                realtime_out = state_row[2] or 0
                is_frozen = bool(state_row[3]) if state_row[3] is not None else False
                
                # CRITICAL: Use daily_state.total_morning if it exists AND is_frozen=True
                # BUT: Verify if total_morning=0 but there are events in morning phase (might be wrong if app restarted)
                if is_frozen and total_morning_db is not None:
                    total_morning_frozen = total_morning_db
                    
                    # VERIFY: If total_morning=0 but there are events in morning phase, recalculate (app may have restarted)
                    if total_morning_frozen == 0:
                        total_morning_from_events = get_total_morning(cursor, today, MORNING_START, MORNING_END)
                        if total_morning_from_events > 0:
                            # There are events but total_morning=0 - likely app restarted, use calculated value
                            total_morning = total_morning_from_events
                        else:
                            # No events, 0 is correct
                            total_morning = 0
                    else:
                        # Use frozen value (non-zero)
                        total_morning = total_morning_frozen
                else:
                    # Not frozen yet or doesn't exist, calculate from events
                    total_morning = get_total_morning(cursor, today, MORNING_START, MORNING_END)
                
                # Calculate realtime: Use daily_state if available
                # realtime = total_morning (frozen) + (realtime_in - realtime_out)
                realtime = total_morning + (realtime_in - realtime_out)
                # Ensure realtime is never negative
                realtime = max(0, realtime)
            else:
                # Fallback: calculate from events if daily_state not available
                total_morning = get_total_morning(cursor, today, MORNING_START, MORNING_END)
                realtime = get_realtime_count(cursor, today)
                # Ensure realtime is never negative
                realtime = max(0, realtime)
            
            # Calculate missing: missing = total_morning - realtime
            missing = total_morning - realtime
            # Ensure missing is never negative
            missing = max(0, missing)
            
            # Get last update time (last event timestamp or current time)
            cursor.execute("""
                SELECT timestamp
                FROM events
                WHERE substr(timestamp, 1, 10) = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (today,))
            
            last_event = cursor.fetchone()
            if last_event:
                # Extract time from ISO timestamp (e.g., "2026-01-07T11:30:45+07:00")
                timestamp = last_event[0]
                if 'T' in timestamp:
                    time_part = timestamp.split('T')[1].split('+')[0].split('.')[0]
                    last_update = time_part[:8]  # HH:MM:SS
                else:
                    last_update = datetime.now().strftime("%H:%M:%S")
            else:
                last_update = datetime.now().strftime("%H:%M:%S")
            
            # Get realtime_in and realtime_out
            if state_row:
                realtime_in = state_row[1] or 0
                realtime_out = state_row[2] or 0
            else:
                # Calculate from events if daily_state not available
                # realtime_in/out are events AFTER morning phase ends (MORNING_END)
                morning_end_minutes = int(MORNING_END.split(':')[0]) * 60 + int(MORNING_END.split(':')[1])
                
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM events
                    WHERE substr(timestamp, 1, 10) = ?
                      AND UPPER(direction) = 'IN'
                      AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) > ?
                """, (today, morning_end_minutes))
                realtime_in = cursor.fetchone()[0] or 0
                
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM events
                    WHERE substr(timestamp, 1, 10) = ?
                      AND UPPER(direction) = 'OUT'
                      AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) > ?
                """, (today, morning_end_minutes))
                realtime_out = cursor.fetchone()[0] or 0
            
            # Calculate current phase based on time
            now = datetime.now()
            current_time = now.time()
            phase = "morning"  # Default
            
            # Parse time strings
            morning_start_time = datetime.strptime(MORNING_START, "%H:%M").time()
            morning_end_time = datetime.strptime(MORNING_END, "%H:%M").time()
            realtime_morning_end_time = datetime.strptime(REALTIME_MORNING_END, "%H:%M").time()
            lunch_end_time = datetime.strptime(LUNCH_END, "%H:%M").time()
            
            if morning_start_time <= current_time < morning_end_time:
                phase = "morning"
            elif morning_end_time <= current_time < realtime_morning_end_time:
                phase = "realtime"
            elif realtime_morning_end_time <= current_time < lunch_end_time:
                phase = "lunch"
            else:
                phase = "afternoon"
            
            # Check if missing now
            missing_now = missing > 0
            
            return {
                "date": today,
                "total_morning": total_morning,
                "realtime": realtime,
                "realtime_in": realtime_in,
                "realtime_out": realtime_out,
                "missing": missing,
                "missing_now": missing_now,
                "phase": phase,
                "last_update": last_update
            }
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Error getting database data: {e}", exc_info=True)
        # Return safe defaults
        today = datetime.now().strftime("%Y-%m-%d")
        return {
                "date": today,
                "total_morning": 0,
                "realtime": 0,
                "realtime_in": 0,
                "realtime_out": 0,
                "missing": 0,
                "missing_now": False,
                "phase": "morning",
                "last_update": datetime.now().strftime("%H:%M:%S")
            }


@app.post("/api/realtime")
async def update_realtime_data(data: RealtimeDataUpdate):
    """
    Update realtime data from main app.
    This endpoint is called by the main app to push realtime data updates.
    """
    global realtime_data_cache, realtime_data_lock
    try:
        with realtime_data_lock:
            realtime_data_cache[data.date] = {
                "total_morning": data.total_morning,
                "realtime_in": data.realtime_in,
                "realtime_out": data.realtime_out,
                "realtime_count": data.realtime_count,
                "phase": data.phase,
                "timestamp": data.timestamp
            }
        logger.debug(f"Updated realtime data cache for {data.date}: total_morning={data.total_morning}, realtime={data.realtime_count}")
        return {"status": "ok", "message": "Realtime data updated"}
    except Exception as e:
        logger.error(f"Error updating realtime data: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """
    Get current status from database.
    
    Returns:
        StatusResponse with date, total_morning, realtime_count, missing_now, phase, last_update
    """
    try:
        data = get_db_data()
        
        return StatusResponse(
            date=data.get("date", datetime.now().strftime("%Y-%m-%d")),
            total_morning=data.get("total_morning", 0),
            realtime_count=data.get("realtime", 0),
            missing_now=data.get("missing_now", False),
            phase=data.get("phase", "morning"),
            last_update=data.get("last_update", datetime.now().strftime("%H:%M:%S"))
        )
    except Exception as e:
        logger.error(f"Error in /api/status: {e}", exc_info=True)
        # Return safe defaults
        today = datetime.now().strftime("%Y-%m-%d")
        return StatusResponse(
            date=today,
            total_morning=0,
            realtime_count=0,
            missing_now=False,
            phase="morning",
            last_update=datetime.now().strftime("%H:%M:%S")
        )


@app.get("/api/events")
async def get_events_api(limit: int = 50):
    """
    Get recent events from database.
    
    Args:
        limit: Maximum number of events to return (default: 50)
    
    Returns:
        List of events with event_time, direction, camera_id
    """
    try:
        if not Path(DB_PATH).exists():
            return []
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            events = get_events(cursor, today)
            
            # Return most recent events (limit)
            events = events[-limit:] if len(events) > limit else events
            
            # Format timestamps for display
            formatted_events = []
            for event in events:
                timestamp = event['event_time']
                # Extract time part from ISO timestamp
                if 'T' in timestamp:
                    time_part = timestamp.split('T')[1].split('+')[0].split('.')[0]
                    display_time = time_part[:8]  # HH:MM:SS
                else:
                    display_time = timestamp[:8] if len(timestamp) >= 8 else timestamp
                
                formatted_events.append({
                    'event_time': display_time,
                    'direction': event['direction'],
                    'camera_id': event['camera_id']
                })
            
            return formatted_events
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Error getting events: {e}", exc_info=True)
        return []


@app.get("/video")
async def video_stream():
    """
    Serve MJPEG camera stream directly from camera.
    Reads camera directly, no proxy needed.
    """
    import asyncio
    
    async def generate_frames():
        while True:
            frame = None
            
            # Try to get frame from direct camera connection
            if camera_cap is not None and camera_cap.isOpened():
                try:
                    ret, frame = camera_cap.read()
                    if not ret or frame is None:
                        frame = None
                except Exception as e:
                    logger.debug(f"Error reading from camera: {e}")
                    frame = None
            
            # If no frame, create placeholder
            if frame is None:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "Camera not available", (150, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.putText(frame, "Check camera connection", (140, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            # Encode frame as JPEG
            try:
                ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    fb = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + fb + b'\r\n')
            except Exception as e:
                logger.error(f"Error encoding frame: {e}")
            
            await asyncio.sleep(0.033)  # ~30 FPS

    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve HTML dashboard."""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bảng Điều Khiển Đếm Người</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Arial', 'Helvetica', sans-serif;
            background: #1a1a1a;
            min-height: 100vh;
            padding: 0;
            margin: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            box-sizing: border-box;
            border: 14px solid green;
            overflow: hidden;
        }
        
        .container {
            background: #1a1a1a;
            width: 100%;
            height: 100vh;
            padding: 60px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        
        h1 {
            text-align: center;
            color: #ffffff;
            margin-bottom: 80px;
            font-size: 5em;
            font-weight: bold;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 60px;
            width: 100%;
            max-width: 2400px;
            margin-bottom: 60px;
        }
        
        .stat-card {
            background: #2d2d2d;
            border-radius: 30px;
            padding: 80px 60px;
            text-align: center;
            color: white;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            border: 4px solid rgba(255,255,255,0.1);
        }
        
        .stat-label {
            font-size: 2.5em;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 3px;
            margin-bottom: 40px;
            font-weight: 600;
        }
        
        .stat-value {
            font-size: 12em;
            font-weight: bold;
            margin: 40px 0;
            line-height: 1;
            text-shadow: 3px 3px 6px rgba(0,0,0,0.8);
        }
        
        .stat-card.missing {
            background: #8b1a1a;
            border-color: #ff4444;
        }
        
        .stat-card.morning {
            background: #1a3a5c;
            border-color: #4a9eff;
        }
        
        .stat-card.realtime {
            background: #1a5c3a;
            border-color: #4aff9e;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .info {
            text-align: center;
            color: #aaaaaa;
            font-size: 2em;
            margin-top: 40px;
            padding: 30px;
            background: #2d2d2d;
            border-radius: 20px;
            border: 2px solid rgba(255,255,255,0.1);
        }
        
        .time-info {
            font-size: 1.5em;
            color: #888888;
            margin-top: 20px;
        }
        
        .loading {
            text-align: center;
            color: #999;
            font-style: italic;
        }
        
        .error {
            color: #f5576c;
            text-align: center;
            padding: 10px;
            background: #ffe6e6;
            border-radius: 5px;
            margin: 10px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>ĐẾM NGƯỜI</h1>
        
        <div id="phase-indicator" style="text-align: center; padding: 30px; margin-bottom: 60px; border-radius: 20px; font-weight: bold; font-size: 2.5em; background: #2d2d2d; color: white; border: 3px solid rgba(255,255,255,0.2);">
            <span id="phase-text">Đang tải...</span>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card morning">
                <div class="stat-label">Tổng Sáng</div>
                <div class="stat-value" id="total-morning">-</div>
                <div style="font-size: 1.8em; opacity: 0.8; margin-top: 30px;">(06:00 - 08:30)</div>
            </div>
            
            <div class="stat-card realtime">
                <div class="stat-label">Thời Gian Thực</div>
                <div class="stat-value" id="realtime">-</div>
            </div>
            
            <div class="stat-card missing">
                <div class="stat-label">Người Vắng Mặt</div>
                <div class="stat-value" id="missing">-</div>
            </div>
        </div>
        
        <div class="info">
            <div><strong>Cập Nhật Cuối:</strong> <span id="last-update">-</span></div>
            <div class="time-info">
                Tự động làm mới mỗi 1 giây
            </div>
        </div>
        
        <div id="error-message" class="error" style="display: none;"></div>
    </div>
    
    <script>
        function updateDashboard() {
            fetch('/api/status')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('HTTP ' + response.status);
                    }
                    return response.json();
                })
                .then(data => {
                    // Calculate missing count
                    const missingCount = Math.max(0, (data.total_morning ?? 0) - (data.realtime_count ?? 0));
                    
                    // Update border color based on missing_count
                    if (missingCount === 0) {
                        document.body.style.border = '12px solid green';
                    } else {
                        document.body.style.border = '12px solid red';
                    }
                    
                    // Map JSON fields to UI elements
                    const elements = {
                        'total-morning': data.total_morning ?? 0,
                        'realtime': data.realtime_count ?? 0,
                        'missing': missingCount,
                        'last-update': data.last_update || '--'
                    };
                    
                    // Update all elements
                    Object.keys(elements).forEach(id => {
                        const el = document.getElementById(id);
                        if (el) {
                            el.textContent = elements[id];
                        }
                    });
                    
                    // Update phase indicator
                    const phaseText = document.getElementById('phase-text');
                    if (phaseText) {
                        const phaseNames = {
                            'morning': 'ĐẾM SÁNG (06:00-08:30)',
                            'realtime': 'GIÁM SÁT SÁNG THỜI GIAN THỰC (08:30-11:55)',
                            'lunch': 'NGHỈ TRƯA (11:55-13:15)',
                            'afternoon': 'GIÁM SÁT CHIỀU (13:15-kết thúc)'
                        };
                        phaseText.textContent = phaseNames[data.phase] || data.phase.toUpperCase();
                    }
                    
                    // Hide error message if exists
                    const errorEl = document.getElementById('error-message');
                    if (errorEl) errorEl.style.display = 'none';
                })
                .catch(error => {
                    console.error('Dashboard update error:', error);
                    // Show "--" on error
                    ['total-morning', 'realtime', 'missing'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) el.textContent = '--';
                    });
                    
                    const errorEl = document.getElementById('error-message');
                    if (errorEl) {
                        errorEl.textContent = 'Không thể kết nối API. Đang thử lại...';
                        errorEl.style.display = 'block';
                    }
                });
        }
        
        // Force update immediately when script loads
        console.log('Dashboard script loaded');
        
        // Update immediately
        setTimeout(function() {
            console.log('Initial dashboard update...');
            updateDashboard();
        }, 100);
        
        // Initialize dashboard on page load
        function initDashboard() {
            // Update immediately
            updateDashboard();
            
            // Auto-refresh every 1 second
            setInterval(updateDashboard, 1000);
        }
        
        // Start when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initDashboard);
        } else {
            initDashboard();
        }
    </script>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    import uvicorn
    
    # Initialize camera - MUST be done before starting server
    logger.info("Initializing camera...")
    camera_ok = init_camera()
    if camera_ok:
        logger.info("Camera initialized successfully")
    else:
        logger.warning("Camera not available. Stream will show placeholder.")
        logger.warning("   Make sure camera is connected and configured in .env file")
    
    # Get LAN IP
    lan_ip = get_lan_ip()
    
    # Print access information
    print("=" * 60)
    print("FastAPI Web Server Starting...")
    print("=" * 60)
    print(f"Local access: http://localhost:{PORT}")
    if lan_ip:
        print(f"LAN access: http://{lan_ip}:{PORT}")
        print(f"Open from another PC: http://{lan_ip}:{PORT}")
    else:
        print("Could not detect LAN IP address")
    if camera_ok:
        print("Camera: Connected")
    else:
        print("Camera: Not available")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Start server
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        # Release camera when server stops
        if camera_cap is not None:
            camera_cap.release()
            logger.info("Camera released")

