"""Object detection using YOLO."""

import logging
from typing import List, Tuple, Optional
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class PersonDetector:
    """Person detector using YOLO."""
    
    # COCO class ID for person
    PERSON_CLASS_ID = 0
    
    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.5,
        device: str = "cpu",
        imgsz: Optional[int] = None,
    ):
        """
        Initialize person detector.
        
        Args:
            model_name: YOLO model name (yolov8n.pt, yolov8s.pt, etc.)
            conf_threshold: Confidence threshold
            iou_threshold: IOU threshold for NMS
            device: Device to run inference on (cpu, cuda, mps)
        """
        self.model_name = model_name
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        self.imgsz = imgsz
        
        logger.info(f"Loading YOLO model: {model_name} on {device}, imgsz={imgsz}")
        try:
            self.model = YOLO(model_name)
            self.model.to(device)
            logger.info(f"Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            raise
    
    def detect(self, frame: np.ndarray) -> List[Tuple[float, float, float, float, float]]:
        """
        Detect persons in frame.
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of detections as (x1, y1, x2, y2, conf) in pixel coordinates
        """
        try:
            results = self.model.predict(
                frame,
                conf=self.conf_threshold,
                iou=self.iou_threshold,
                classes=[self.PERSON_CLASS_ID],  # Only detect persons
                imgsz=self.imgsz,  # Use specified image size for faster processing
                verbose=False,
                half=False,  # Use full precision for better accuracy
                agnostic_nms=False,  # Class-aware NMS
            )
            
            detections = []
            if results and len(results) > 0:
                result = results[0]
                if result.boxes is not None:
                    boxes = result.boxes.xyxy.cpu().numpy()  # x1, y1, x2, y2
                    confidences = result.boxes.conf.cpu().numpy()
                    
                    for box, conf in zip(boxes, confidences):
                        x1, y1, x2, y2 = box
                        detections.append((float(x1), float(y1), float(x2), float(y2), float(conf)))
            
            return detections
            
        except Exception as e:
            logger.error(f"Error during detection: {e}", exc_info=True)
            return []
    
    def detect_and_track(self, frame: np.ndarray, persist: bool = True) -> List[Tuple[int, float, float, float, float, float]]:
        """
        Detect and track persons in frame using YOLO's built-in tracker.
        
        Args:
            frame: Input frame (BGR format)
            persist: Whether to persist tracks across frames
        
        Returns:
            List of tracks as (track_id, x1, y1, x2, y2, conf)
        """
        try:
            results = self.model.track(
                frame,
                conf=self.conf_threshold,
                iou=self.iou_threshold,
                classes=[self.PERSON_CLASS_ID],
                persist=persist,
                tracker="bytetrack.yaml",  # Use ByteTrack tracker
                imgsz=self.imgsz,  # Use specified image size for faster processing
                verbose=False,
                stream=False,  # Don't use stream mode - returns list instead of generator
            )
            
            tracks = []
            if results and len(results) > 0:
                result = results[0]
                # Check if we have detections (even without tracking IDs)
                if result.boxes is not None:
                    boxes = result.boxes.xyxy.cpu().numpy()
                    confidences = result.boxes.conf.cpu().numpy()
                    
                    # Debug: log if we have detections but no track IDs
                    if len(boxes) > 0 and result.boxes.id is None:
                        logger.debug(f"Found {len(boxes)} detections but no track IDs yet (tracking may need more frames)")
                    
                    # Check if we have track IDs
                    if result.boxes.id is not None:
                        track_ids = result.boxes.id.cpu().numpy().astype(int)
                        for box, track_id, conf in zip(boxes, track_ids, confidences):
                            x1, y1, x2, y2 = box
                            tracks.append((int(track_id), float(x1), float(y1), float(x2), float(y2), float(conf)))
                    elif len(boxes) > 0:
                        # If no track IDs yet, assign temporary IDs based on box position
                        # This can happen in the first few frames before tracking stabilizes
                        for box, conf in zip(boxes, confidences):
                            x1, y1, x2, y2 = box
                            # Use a temporary ID based on box center
                            temp_id = int((x1 + x2) / 2) + int((y1 + y2) * 1000)
                            tracks.append((temp_id, float(x1), float(y1), float(x2), float(y2), float(conf)))
            
            return tracks
            
        except Exception as e:
            logger.error(f"Error during detect and track: {e}", exc_info=True)
            return []

