"""Simple web server for camera stream and realtime counters."""

import logging
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
import cv2
import json
import time

logger = logging.getLogger(__name__)


class WebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for web interface."""
    
    app_instance = None
    current_frame = None
    frame_lock = threading.Lock()
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.debug(f"{self.address_string()} - {format % args}")
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self._serve_dashboard()
        elif self.path == '/video':
            self._serve_mjpeg_stream()
        elif self.path == '/api/status':
            self._serve_api_status()
        else:
            self.send_error(404)
    
    def _serve_dashboard(self):
        """Serve HTML dashboard."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>People Counter</title>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="1">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #1a1a1a;
            color: #fff;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: #4CAF50;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .stat-card {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border: 2px solid #4CAF50;
        }
        .stat-value {
            font-size: 36px;
            font-weight: bold;
            color: #4CAF50;
            margin: 10px 0;
        }
        .stat-label {
            font-size: 14px;
            color: #aaa;
            text-transform: uppercase;
        }
        .video-container {
            text-align: center;
            margin: 20px 0;
            background: #000;
            padding: 10px;
            border-radius: 8px;
        }
        img {
            max-width: 100%;
            height: auto;
            border: 2px solid #4CAF50;
        }
        .phase {
            text-align: center;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            font-weight: bold;
        }
        .phase.morning {
            background: #FF9800;
            color: #000;
        }
        .phase.realtime {
            background: #2196F3;
            color: #fff;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>People Counter Dashboard</h1>
        
        <div id="phase" class="phase"></div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Total Morning</div>
                <div class="stat-value" id="total-morning">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Realtime Count</div>
                <div class="stat-value" id="realtime-count">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Realtime IN</div>
                <div class="stat-value" id="realtime-in">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Realtime OUT</div>
                <div class="stat-value" id="realtime-out">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">FPS</div>
                <div class="stat-value" id="fps">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Tracks</div>
                <div class="stat-value" id="active-tracks">-</div>
            </div>
        </div>
        
        <div class="video-container">
            <img src="/video" alt="Camera Stream">
        </div>
    </div>
    
    <script>
        // Update stats from API
        function updateStats() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('total-morning').textContent = data.total_morning || 0;
                    document.getElementById('realtime-count').textContent = data.realtime_count || 0;
                    document.getElementById('realtime-in').textContent = data.realtime_in || 0;
                    document.getElementById('realtime-out').textContent = data.realtime_out || 0;
                    document.getElementById('fps').textContent = data.fps ? data.fps.toFixed(1) : '-';
                    document.getElementById('active-tracks').textContent = data.active_tracks || 0;
                    
                    // Update phase
                    const phaseEl = document.getElementById('phase');
                    if (data.phase === 'MORNING_COUNT') {
                        phaseEl.textContent = '=== MORNING COUNT PHASE ===';
                        phaseEl.className = 'phase morning';
                    } else {
                        phaseEl.textContent = '=== REALTIME MONITORING ===';
                        phaseEl.className = 'phase realtime';
                    }
                })
                .catch(err => console.error('Error fetching stats:', err));
        }
        
        // Update every second
        setInterval(updateStats, 1000);
        updateStats();
    </script>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _serve_mjpeg_stream(self):
        """Serve MJPEG video stream."""
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
        self.end_headers()
        
        while True:
            try:
                with WebHandler.frame_lock:
                    if WebHandler.current_frame is None:
                        time.sleep(0.1)
                        continue
                    frame = WebHandler.current_frame.copy()
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ret:
                    continue
                
                # Send multipart response
                self.wfile.write(b'--jpgboundary\r\n')
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(buffer)))
                self.end_headers()
                self.wfile.write(buffer.tobytes())
                self.wfile.write(b'\r\n')
                
                time.sleep(0.033)  # ~30 FPS
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected
                break
            except Exception as e:
                logger.error(f"Error in MJPEG stream: {e}")
                break
    
    def _serve_api_status(self):
        """Serve JSON API with current status."""
        if WebHandler.app_instance is None:
            data = {
                "error": "App not initialized"
            }
        else:
            app = WebHandler.app_instance
            
            # Get current phase
            phase = "REALTIME_MONITORING"
            if app.time_manager:
                phase = app.time_manager.get_current_phase().value
            
            # Get counters
            tz = app.config.window.timezone
            import pytz
            from datetime import datetime
            today = datetime.now(pytz.timezone(tz)).strftime("%Y-%m-%d")
            state = app.storage.get_daily_state(today)
            
            total_morning = 0
            realtime_in = 0
            realtime_out = 0
            if state:
                total_morning = state.get('total_morning', 0) or 0
                realtime_in = state.get('realtime_in', 0) or 0
                realtime_out = state.get('realtime_out', 0) or 0
            
            realtime_count = total_morning + realtime_in - realtime_out
            
            # Get FPS and active tracks
            fps = app.camera.get_fps() if app.camera else 0
            active_tracks = len(app.gate_counter.track_states) if app.gate_counter else 0
            
            data = {
                "phase": phase,
                "total_morning": total_morning,
                "realtime_count": realtime_count,
                "realtime_in": realtime_in,
                "realtime_out": realtime_out,
                "fps": fps,
                "active_tracks": active_tracks
            }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))


class WebServer:
    """Simple web server for camera stream and dashboard."""
    
    def __init__(self, app_instance, host='0.0.0.0', port=5000):
        """
        Initialize web server.
        
        Args:
            app_instance: PeopleCounterApp instance
            host: Host to bind to (0.0.0.0 for all interfaces)
            port: Port to listen on
        """
        self.app_instance = app_instance
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.running = False
    
    def start(self):
        """Start web server in background thread."""
        WebHandler.app_instance = self.app_instance
        
        def handler(*args, **kwargs):
            return WebHandler(*args, **kwargs)
        
        self.server = HTTPServer((self.host, self.port), handler)
        self.running = True
        
        def run_server():
            logger.info(f"Web server starting on {self.host}:{self.port}")
            try:
                self.server.serve_forever()
            except Exception as e:
                logger.error(f"Web server error: {e}")
        
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        # Get LAN IP and log access URL
        lan_ip = self._get_lan_ip()
        logger.info("=" * 60)
        logger.info(f"Web server started successfully!")
        logger.info(f"Local access: http://localhost:{self.port}")
        if lan_ip:
            logger.info(f"LAN access: http://{lan_ip}:{self.port}")
            logger.info(f"Open from another PC: http://{lan_ip}:{self.port}")
        logger.info("=" * 60)
    
    def stop(self):
        """Stop web server."""
        self.running = False
        if self.server:
            self.server.shutdown()
            logger.info("Web server stopped")
    
    def update_frame(self, frame):
        """Update current frame for MJPEG stream."""
        with WebHandler.frame_lock:
            WebHandler.current_frame = frame
    
    def _get_lan_ip(self):
        """Get LAN IP address."""
        try:
            # Connect to a remote address to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                # Fallback: get hostname IP
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                if ip.startswith("127."):
                    return None
                return ip
            except Exception:
                return None

