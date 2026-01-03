"""Line crossing detection and counting logic."""

import logging
from typing import Dict, Tuple, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class LineCounter:
    """Count people crossing a virtual line."""
    
    def __init__(
        self,
        line_start: Tuple[int, int],
        line_end: Tuple[int, int],
        min_track_length: int = 5,
        cooldown_frames: int = 30,
    ):
        """
        Initialize line counter.
        
        Args:
            line_start: Line start point (x, y)
            line_end: Line end point (x, y)
            min_track_length: Minimum track length before counting
            cooldown_frames: Cooldown frames to prevent double counting
        """
        self.line_start = np.array(line_start, dtype=np.float32)
        self.line_end = np.array(line_end, dtype=np.float32)
        self.min_track_length = min_track_length
        self.cooldown_frames = cooldown_frames
        
        # Track history: track_id -> list of (frame_idx, centroid_x, centroid_y)
        self.track_history: Dict[int, List[Tuple[int, float, float]]] = {}
        
        # Counted tracks: track_id -> (frame_idx, direction)
        self.counted_tracks: Dict[int, Tuple[int, str]] = {}
        
        # Frame counter
        self.frame_idx = 0
        
        # Counts
        self.count_in = 0
        self.count_out = 0
        
        # Calculate line vector and normal
        self.line_vec = self.line_end - self.line_start
        self.line_length = np.linalg.norm(self.line_vec)
        
        logger.info(
            f"Line counter initialized: line from {line_start} to {line_end}, "
            f"min_track_length={min_track_length}, cooldown={cooldown_frames}"
        )
    
    def _get_centroid(self, x1: float, y1: float, x2: float, y2: float) -> Tuple[float, float]:
        """Calculate bounding box centroid."""
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def _point_to_line_distance(self, point: np.ndarray) -> float:
        """
        Calculate signed distance from point to line.
        Positive = on one side, Negative = on other side.
        """
        # Vector from line_start to point
        point_vec = point - self.line_start
        
        # Project point_vec onto line_vec
        t = np.dot(point_vec, self.line_vec) / (self.line_length ** 2)
        
        # Clamp t to [0, 1] to get closest point on line segment
        t = np.clip(t, 0, 1)
        closest_point = self.line_start + t * self.line_vec
        
        # Vector from closest point to actual point
        to_point = point - closest_point
        
        # Calculate signed distance (perpendicular to line)
        # Use cross product to determine side
        cross = np.cross(self.line_vec, to_point)
        distance = np.linalg.norm(to_point)
        
        # Sign: positive if cross > 0 (one side), negative if cross < 0 (other side)
        return distance if cross >= 0 else -distance
    
    def _has_crossed_line(
        self,
        track_id: int,
        current_centroid: Tuple[float, float],
    ) -> Optional[str]:
        """
        Check if track has crossed the line.
        
        Returns:
            'in' if crossed from side A to side B, 'out' if crossed from side B to side A,
            None if no crossing detected
        """
        if track_id not in self.track_history:
            return None
        
        history = self.track_history[track_id]
        if len(history) < self.min_track_length:
            return None
        
        # Check if already counted
        if track_id in self.counted_tracks:
            counted_frame, _ = self.counted_tracks[track_id]
            if self.frame_idx - counted_frame < self.cooldown_frames:
                return None
        
        # Get first and last positions
        first_frame, first_x, first_y = history[0]
        last_frame, last_x, last_y = history[-1]
        
        # Calculate signed distances
        first_point = np.array([first_x, first_y], dtype=np.float32)
        last_point = np.array([last_x, last_y], dtype=np.float32)
        
        first_dist = self._point_to_line_distance(first_point)
        last_dist = self._point_to_line_distance(last_point)
        
        # Check if crossed (sign changed)
        if first_dist * last_dist < 0:  # Different signs = crossed
            # Determine direction: if first_dist < 0 and last_dist > 0, moved from side A to B = IN
            # If first_dist > 0 and last_dist < 0, moved from side B to A = OUT
            if first_dist < 0 and last_dist > 0:
                return "in"
            elif first_dist > 0 and last_dist < 0:
                return "out"
        
        return None
    
    def update(self, tracks: List[Tuple[int, float, float, float, float, float]]) -> List[Tuple[int, str]]:
        """
        Update with new tracks and detect line crossings.
        
        Args:
            tracks: List of (track_id, x1, y1, x2, y2, conf)
        
        Returns:
            List of (track_id, direction) for new crossings
        """
        self.frame_idx += 1
        crossings = []
        
        # Get current track IDs
        current_track_ids = {track_id for track_id, _, _, _, _, _ in tracks}
        
        # Update history for active tracks
        for track_id, x1, y1, x2, y2, conf in tracks:
            centroid = self._get_centroid(x1, y1, x2, y2)
            
            if track_id not in self.track_history:
                self.track_history[track_id] = []
            
            self.track_history[track_id].append((self.frame_idx, centroid[0], centroid[1]))
            
            # Keep only recent history (last 60 frames)
            if len(self.track_history[track_id]) > 60:
                self.track_history[track_id] = self.track_history[track_id][-60:]
        
        # Check for crossings
        for track_id, x1, y1, x2, y2, conf in tracks:
            centroid = self._get_centroid(x1, y1, x2, y2)
            direction = self._has_crossed_line(track_id, centroid)
            
            if direction:
                # Mark as counted
                self.counted_tracks[track_id] = (self.frame_idx, direction)
                
                # Update counts
                if direction == "in":
                    self.count_in += 1
                else:
                    self.count_out += 1
                
                crossings.append((track_id, direction))
                logger.info(f"Track {track_id} crossed line: {direction.upper()}")
        
        # Clean up old tracks (not seen for cooldown_frames * 2)
        tracks_to_remove = []
        for track_id in self.track_history:
            if track_id not in current_track_ids:
                # Check if it's been a while since last seen
                if track_id in self.track_history and self.track_history[track_id]:
                    last_frame, _, _ = self.track_history[track_id][-1]
                    if self.frame_idx - last_frame > self.cooldown_frames * 2:
                        tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            if track_id in self.track_history:
                del self.track_history[track_id]
            if track_id in self.counted_tracks:
                del self.counted_tracks[track_id]
        
        return crossings
    
    def get_counts(self) -> Tuple[int, int]:
        """Get current counts (in, out)."""
        return self.count_in, self.count_out
    
    def reset_counts(self):
        """Reset counts (useful for new time window)."""
        self.count_in = 0
        self.count_out = 0
        logger.info("Counts reset")
    
    def get_line_points(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Get line start and end points."""
        return (
            (int(self.line_start[0]), int(self.line_start[1])),
            (int(self.line_end[0]), int(self.line_end[1])),
        )

