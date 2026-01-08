"""Camera stream ingestion with reconnection logic."""

import time
import logging
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraStream:
    """Camera stream handler with automatic reconnection."""
    
    def __init__(
        self,
        url: str,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 10,
        fps_cap: int = 10,
    ):
        """
        Initialize camera stream.
        
        Args:
            url: Camera URL (RTSP stream or USB camera index)
            reconnect_delay: Delay in seconds before reconnecting
            max_reconnect_attempts: Maximum reconnection attempts (0 = infinite)
            fps_cap: Maximum FPS to process (0 = no cap)
        """
        self.url = url
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.fps_cap = fps_cap
        
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame_count = 0
        self.last_frame_time = 0.0
        self.reconnect_count = 0
        self.is_connected = False
        
        # FPS calculation
        self.fps_start_time = time.time()
        self.fps_frame_count = 0
        self.current_fps = 0.0
        
    def connect(self) -> bool:
        """Connect to camera stream."""
        try:
            # Parse URL - if it's a digit, treat as USB camera index
            if self.url.isdigit():
                url_int = int(self.url)
                logger.info(f"Connecting to USB camera index: {url_int}")
                self.cap = cv2.VideoCapture(url_int)
            else:
                logger.info(f"Connecting to RTSP stream: {self.url}")
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera: {self.url}")
                return False
            
            # Set buffer size to reduce latency (1 = minimal buffer for real-time)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # For high resolution cameras, try to set optimal properties
            # Get actual resolution
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            logger.info(f"Camera properties: {width}x{height} @ {fps:.2f} FPS")
            
            # Try to set higher FPS for faster scanning (prioritize speed)
            # Try 60 FPS first, then 30 FPS if 60 is not supported
            target_fps_list = [60, 30]
            for target_fps in target_fps_list:
                self.cap.set(cv2.CAP_PROP_FPS, target_fps)
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                if actual_fps >= target_fps * 0.9:  # Accept if within 90% of target
                    logger.info(f"Camera FPS set to: {actual_fps:.2f} (requested {target_fps})")
                    break
                elif actual_fps > fps:
                    logger.info(f"Camera FPS improved to: {actual_fps:.2f} (requested {target_fps})")
                    break
            
            # Test read
            ret, frame = self.cap.read()
            if not ret or frame is None:
                logger.error("Failed to read initial frame")
                self.cap.release()
                self.cap = None
                return False
            
            self.is_connected = True
            self.reconnect_count = 0
            logger.info(f"Successfully connected to camera: {self.url}")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to camera: {e}", exc_info=True)
            if self.cap:
                self.cap.release()
                self.cap = None
            self.is_connected = False
            return False
    
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read frame from camera.
        
        Returns:
            Tuple of (success, frame)
        """
        if not self.is_connected or self.cap is None:
            if not self._should_reconnect():
                return False, None
            if not self.connect():
                return False, None
        
        # FPS capping - DISABLED for maximum performance (fps_cap should be 0)
        # Removed FPS cap check to allow maximum camera FPS
        # if self.fps_cap > 0:
        #     current_time = time.time()
        #     min_interval = 1.0 / self.fps_cap
        #     if current_time - self.last_frame_time < min_interval:
        #         _ = self.cap.read()
        #         return False, None
        #     self.last_frame_time = current_time
        
        try:
            ret, frame = self.cap.read()
            
            if not ret or frame is None:
                logger.warning("Failed to read frame, attempting reconnection...")
                self.is_connected = False
                self.cap.release()
                self.cap = None
                
                if self._should_reconnect():
                    time.sleep(self.reconnect_delay)
                    if self.connect():
                        return self.read()
                
                return False, None
            
            self.frame_count += 1
            self.fps_frame_count += 1
            
            # Calculate FPS every second
            elapsed = time.time() - self.fps_start_time
            if elapsed >= 1.0:
                self.current_fps = self.fps_frame_count / elapsed
                self.fps_frame_count = 0
                self.fps_start_time = time.time()
            
            return True, frame
            
        except Exception as e:
            logger.error(f"Error reading frame: {e}", exc_info=True)
            self.is_connected = False
            if self.cap:
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = None
            
            if self._should_reconnect():
                time.sleep(self.reconnect_delay)
                if self.connect():
                    return self.read()
            
            return False, None
    
    def _should_reconnect(self) -> bool:
        """Check if reconnection should be attempted."""
        if self.max_reconnect_attempts == 0:
            return True
        if self.reconnect_count < self.max_reconnect_attempts:
            self.reconnect_count += 1
            return True
        return False
    
    def get_fps(self) -> float:
        """Get current FPS."""
        return self.current_fps
    
    def get_frame_count(self) -> int:
        """Get total frame count."""
        return self.frame_count
    
    def release(self):
        """Release camera resources."""
        if self.cap:
            try:
                self.cap.release()
            except:
                pass
            self.cap = None
        self.is_connected = False
        logger.info("Camera released")

