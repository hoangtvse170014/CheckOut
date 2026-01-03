"""Object tracking using ByteTrack or DeepSORT."""

import logging
from typing import List, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)

try:
    from ultralytics.trackers import BYTETracker
    BYTETRACK_AVAILABLE = True
except ImportError:
    try:
        # Try alternative import path for newer ultralytics versions
        from ultralytics.tracker import BYTETracker
        BYTETRACK_AVAILABLE = True
    except ImportError:
        BYTETRACK_AVAILABLE = False
        logger.warning("ByteTrack not available from ultralytics")

try:
    from deep_sort_realtime import DeepSort
    DEEPSORT_AVAILABLE = True
except ImportError:
    DEEPSORT_AVAILABLE = False
    logger.warning("DeepSORT not available")


class Tracker:
    """Object tracker wrapper."""
    
    def __init__(
        self,
        tracker_type: str = "bytetrack",
        track_thresh: float = 0.5,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
    ):
        """
        Initialize tracker.
        
        Args:
            tracker_type: 'bytetrack' or 'deepsort'
            track_thresh: Tracking threshold
            track_buffer: Number of frames to keep lost tracks
            match_thresh: Matching threshold
        """
        self.tracker_type = tracker_type.lower()
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        
        if self.tracker_type == "bytetrack":
            if not BYTETRACK_AVAILABLE:
                logger.warning(
                    "ByteTrack not available. Install lap package: pip install lap. "
                    "Falling back to None tracker - will use YOLO's built-in tracker only."
                )
                self.tracker = None
                return
            try:
                # ByteTrack in ultralytics requires an args object with all parameters
                # Create a simple namespace-like object with all required attributes
                from types import SimpleNamespace
                args = SimpleNamespace()
                args.track_thresh = track_thresh
                args.track_buffer = track_buffer
                args.match_thresh = match_thresh
                # Additional ByteTrack parameters
                args.track_high_thresh = track_thresh + 0.1  # Usually higher than track_thresh
                args.track_low_thresh = track_thresh - 0.1   # Usually lower than track_thresh
                args.new_track_thresh = track_thresh
                args.proximity_thresh = 0.5
                args.appearance_thresh = 0.25
                
                self.tracker = BYTETracker(args=args)
                logger.info("Initialized ByteTrack tracker")
            except (TypeError, AttributeError) as e:
                # Fallback: try with default parameters (no args)
                try:
                    logger.warning(f"ByteTrack initialization with custom params failed ({e}), trying defaults")
                    # Try with minimal required args
                    from types import SimpleNamespace
                    args = SimpleNamespace()
                    # Set minimal required attributes
                    args.track_thresh = 0.5
                    args.track_buffer = 30
                    args.match_thresh = 0.8
                    args.track_high_thresh = 0.6
                    args.track_low_thresh = 0.4
                    args.new_track_thresh = 0.5
                    args.proximity_thresh = 0.5
                    args.appearance_thresh = 0.25
                    self.tracker = BYTETracker(args=args)
                    logger.info("Initialized ByteTrack tracker with default parameters")
                except Exception as e2:
                    # Last resort: try without args (may not work)
                    logger.warning(f"ByteTrack initialization failed again ({e2}), trying no args")
                    self.tracker = BYTETracker()
                    logger.info("Initialized ByteTrack tracker (no args)")
            
        elif self.tracker_type == "deepsort":
            if not DEEPSORT_AVAILABLE:
                raise ImportError("DeepSORT not available. Install deep-sort-realtime")
            self.tracker = DeepSort(
                max_age=track_buffer,
                n_init=3,
            )
            logger.info("Initialized DeepSORT tracker")
        else:
            raise ValueError(f"Unknown tracker type: {tracker_type}")
    
    def update(
        self,
        detections: List[Tuple[float, float, float, float, float]],
        frame: Optional[np.ndarray] = None,
    ) -> List[Tuple[int, float, float, float, float, float]]:
        """
        Update tracker with new detections.
        
        Args:
            detections: List of (x1, y1, x2, y2, conf)
            frame: Optional frame for DeepSORT feature extraction
        
        Returns:
            List of tracks as (track_id, x1, y1, x2, y2, conf)
        """
        # If tracker is None (ByteTrack not available), return empty list
        if self.tracker is None:
            return []
        
        if not detections:
            if self.tracker_type == "bytetrack":
                tracks = self.tracker.update(np.array([]), frame)
                return []
            else:
                return self.tracker.update_tracks([], frame=frame)
        
        try:
            if self.tracker_type == "bytetrack":
                # ByteTrack in ultralytics expects a Results object, not numpy array
                # Create a mock Results object from detections
                from ultralytics.engine.results import Results
                from ultralytics.utils import ops
                import torch
                
                if not detections:
                    tracks = self.tracker.update([], frame)
                    return []
                
                # Convert detections to tensor format
                boxes_list = []
                conf_list = []
                for x1, y1, x2, y2, conf in detections:
                    boxes_list.append([x1, y1, x2, y2])
                    conf_list.append(conf)
                
                if not boxes_list:
                    return []
                
                boxes_tensor = torch.tensor(boxes_list, dtype=torch.float32)
                conf_tensor = torch.tensor(conf_list, dtype=torch.float32)
                
                # Create a minimal Results object
                # ByteTrack.update expects results with boxes.xyxy, boxes.conf, and results.conf
                class MockResults:
                    def __init__(self, boxes, conf):
                        self.boxes = type('Boxes', (), {
                            'xyxy': boxes,
                            'conf': conf,
                            'data': torch.cat([boxes, conf.unsqueeze(1)], dim=1)
                        })()
                        # ByteTrack also needs results.conf directly
                        self.conf = conf
                
                mock_results = MockResults(boxes_tensor, conf_tensor)
                # ByteTrack.update may expect a list of results or subscriptable
                # Wrap in list and make subscriptable
                results_list = [mock_results]
                tracks = self.tracker.update(results_list, frame)
                
                # Convert to list of (track_id, x1, y1, x2, y2, conf)
                result = []
                if tracks is not None and len(tracks) > 0:
                    # ByteTrack returns numpy array with shape (n, 6): [x1, y1, x2, y2, track_id, conf]
                    for track in tracks:
                        if isinstance(track, np.ndarray) and len(track) >= 6:
                            x1, y1, x2, y2, track_id, conf = track[0], track[1], track[2], track[3], track[4], track[5]
                            result.append((int(track_id), float(x1), float(y1), float(x2), float(y2), float(conf)))
                        elif isinstance(track, np.ndarray) and len(track) >= 5:
                            # Alternative format: [x1, y1, x2, y2, track_id]
                            x1, y1, x2, y2, track_id = track[0], track[1], track[2], track[3], track[4]
                            # Use average confidence from detections
                            conf = 0.5
                            result.append((int(track_id), float(x1), float(y1), float(x2), float(y2), float(conf)))
                return result
                
            else:  # DeepSORT
                # DeepSORT expects detections as list of tuples: ((x1, y1, x2, y2), conf, class)
                dets = [((x1, y1, x2, y2), conf, 0) for x1, y1, x2, y2, conf in detections]
                tracks = self.tracker.update_tracks(dets, frame=frame)
                
                result = []
                for track in tracks:
                    if track.is_confirmed():
                        track_id = track.track_id
                        ltrb = track.to_ltrb()
                        x1, y1, x2, y2 = ltrb
                        conf = track.get_det_conf() if hasattr(track, 'get_det_conf') else 0.5
                        result.append((track_id, float(x1), float(y1), float(x2), float(y2), float(conf)))
                return result
                
        except Exception as e:
            logger.error(f"Error during tracking: {e}", exc_info=True)
            return []

