"""Gate Counter using segment-crossing algorithm for fast counting."""

import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SegmentEvent:
    """Segment crossing event."""
    track_id: int
    timestamp: float
    direction: str  # "IN" or "OUT"
    prev_point: Tuple[float, float]
    cur_point: Tuple[float, float]
    prev_side: int
    cur_side: int


class TrackState:
    """State for a single track."""
    
    def __init__(self):
        self.last_point: Optional[Tuple[float, float]] = None
        self.last_ts: float = 0.0
        self.last_side: int = 0  # +1, -1, or 0
        self.last_count_ts: float = 0.0


class GateCounterSegment:
    """Gate counter using segment-crossing algorithm."""
    
    def __init__(
        self,
        gate_p1: Tuple[float, float],
        gate_p2: Tuple[float, float],
        cooldown_sec: float = 2.0,  # Increased default cooldown to prevent double counting
        min_travel_px: float = 12.0,
        direction_mapping_pos_to_neg: str = "IN",
        direction_mapping_neg_to_pos: str = "OUT",
        direction_mapping_up: Optional[str] = None,
        direction_mapping_down: Optional[str] = None,
        x_range_min: Optional[float] = None,
        x_range_max: Optional[float] = None,
    ):
        """
        Initialize segment-based gate counter.
        
        Args:
            gate_p1: Start point (x, y) of gate segment
            gate_p2: End point (x, y) of gate segment
            cooldown_sec: Cooldown time in seconds to prevent double counting
            min_travel_px: Minimum travel distance in pixels to count
            direction_mapping_pos_to_neg: Direction for +1 -> -1 crossing
            direction_mapping_neg_to_pos: Direction for -1 -> +1 crossing
            direction_mapping_up: Direction for upward movement (if gate is horizontal)
            direction_mapping_down: Direction for downward movement (if gate is horizontal)
            x_range_min: Optional X minimum for gate region
            x_range_max: Optional X maximum for gate region
        """
        self.gate_p1 = np.array(gate_p1, dtype=np.float32)
        self.gate_p2 = np.array(gate_p2, dtype=np.float32)
        self.gate_vec = self.gate_p2 - self.gate_p1
        self.cooldown_sec = cooldown_sec
        self.min_travel_px = min_travel_px
        self.x_range_min = x_range_min
        self.x_range_max = x_range_max
        
        # Check if gate is horizontal (for UP/DOWN mapping)
        self.is_horizontal = abs(self.gate_p1[1] - self.gate_p2[1]) < 1.0
        
        # Direction mapping
        if self.is_horizontal and direction_mapping_up is not None:
            # Use UP/DOWN mapping for horizontal gate
            self.direction_mapping = {
                "UP": direction_mapping_up,
                "DOWN": direction_mapping_down,
            }
            logger.info(f"Horizontal gate: UP={direction_mapping_up}, DOWN={direction_mapping_down}")
        else:
            # Use POS_TO_NEG/NEG_TO_POS mapping
            self.direction_mapping = {
                "POS_TO_NEG": direction_mapping_pos_to_neg,
                "NEG_TO_POS": direction_mapping_neg_to_pos,
            }
            logger.info(f"General gate: POS_TO_NEG={direction_mapping_pos_to_neg}, NEG_TO_POS={direction_mapping_neg_to_pos}")
        
        # Track states
        self.track_states: Dict[int, TrackState] = {}
        
        # Counts
        self.count_in = 0
        self.count_out = 0
        
        # Events history
        self.events: list[SegmentEvent] = []
        
        logger.info(
            f"GateCounterSegment initialized: gate_p1={gate_p1}, gate_p2={gate_p2}, "
            f"cooldown={cooldown_sec}s, min_travel={min_travel_px}px"
        )
    
    def _get_side(self, point: Tuple[float, float]) -> int:
        """
        Get side of point relative to gate line.
        
        Returns:
            +1 if point is on one side (POS)
            -1 if point is on other side (NEG)
            0 if point is on the line
        """
        point_vec = np.array(point, dtype=np.float32) - self.gate_p1
        # Cross product: (gate_p2 - gate_p1) x (point - gate_p1)
        cross = np.cross(self.gate_vec, point_vec)
        
        # For vertical gate (dx ≈ 0), use x coordinate directly
        if abs(self.gate_vec[0]) < 1e-6:  # Vertical gate
            if abs(point[0] - self.gate_p1[0]) < 2.0:  # Within 2px tolerance
                return 0
            elif point[0] < self.gate_p1[0]:
                return -1  # NEG (left side)
            else:
                return 1   # POS (right side)
        
        # For horizontal or diagonal gate, use cross product
        if abs(cross) < 1e-6:  # On the line
            return 0
        elif cross > 0:
            return 1  # POS side
        else:
            return -1  # NEG side
    
    def _orientation(self, p: np.ndarray, q: np.ndarray, r: np.ndarray) -> int:
        """
        Find orientation of ordered triplet (p, q, r).
        
        Returns:
            0: Collinear
            1: Clockwise
            2: Counterclockwise
        """
        val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        if abs(val) < 1e-9:
            return 0
        return 1 if val > 0 else 2
    
    def _on_segment(self, p: np.ndarray, q: np.ndarray, r: np.ndarray) -> bool:
        """Check if point q lies on segment pr."""
        if self._orientation(p, q, r) != 0:
            return False
        return (
            q[0] <= max(p[0], r[0]) and q[0] >= min(p[0], r[0]) and
            q[1] <= max(p[1], r[1]) and q[1] >= min(p[1], r[1])
        )
    
    def _segment_intersect(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        q1: Tuple[float, float],
        q2: Tuple[float, float],
    ) -> bool:
        """
        Check if two segments intersect.
        
        Args:
            p1, p2: Endpoints of first segment
            q1, q2: Endpoints of second segment (gate)
        
        Returns:
            True if segments intersect, False otherwise
        """
        p1_arr = np.array(p1, dtype=np.float32)
        p2_arr = np.array(p2, dtype=np.float32)
        q1_arr = np.array(q1, dtype=np.float32)
        q2_arr = np.array(q2, dtype=np.float32)
        
        # Find the four orientations needed
        o1 = self._orientation(p1_arr, p2_arr, q1_arr)
        o2 = self._orientation(p1_arr, p2_arr, q2_arr)
        o3 = self._orientation(q1_arr, q2_arr, p1_arr)
        o4 = self._orientation(q1_arr, q2_arr, p2_arr)
        
        # General case: segments intersect if orientations are different
        if o1 != o2 and o3 != o4:
            return True
        
        # Special cases: collinear points
        if o1 == 0 and self._on_segment(p1_arr, q1_arr, p2_arr):
            return True
        if o2 == 0 and self._on_segment(p1_arr, q2_arr, p2_arr):
            return True
        if o3 == 0 and self._on_segment(q1_arr, p1_arr, q2_arr):
            return True
        if o4 == 0 and self._on_segment(q1_arr, p2_arr, q2_arr):
            return True
        
        return False
    
    def update(
        self,
        track_id: int,
        point: Tuple[float, float],
        ts: Optional[float] = None,
    ) -> Optional[SegmentEvent]:
        """
        Update with new track point and check for segment crossing.
        
        Args:
            track_id: Track ID
            point: Bottom-center point (x, y) of bounding box
            ts: Timestamp (defaults to current time)
        
        Returns:
            SegmentEvent if crossing detected, None otherwise
        """
        if ts is None:
            ts = time.time()
        
        # Get or create track state
        if track_id not in self.track_states:
            self.track_states[track_id] = TrackState()
        
        state = self.track_states[track_id]
        
        # Check if we have a previous point
        if state.last_point is None:
            state.last_point = point
            state.last_ts = ts
            state.last_side = self._get_side(point)
            return None
        
        # Check cooldown
        if (ts - state.last_count_ts) < self.cooldown_sec:
            # Still in cooldown, update state but don't check crossing
            cooldown_remaining = self.cooldown_sec - (ts - state.last_count_ts)
            if track_id % 10 == 0:  # Log every 10th frame to avoid spam
                logger.debug(f"Track {track_id}: In cooldown ({cooldown_remaining:.2f}s remaining)")
            state.last_point = point
            state.last_ts = ts
            state.last_side = self._get_side(point)
            return None
        
        # Calculate travel distance
        travel_distance = np.linalg.norm(
            np.array(point, dtype=np.float32) - np.array(state.last_point, dtype=np.float32)
        )
        
        if travel_distance < self.min_travel_px:
            # Not enough movement, update state but don't check crossing
            if track_id % 30 == 0:  # Log occasionally
                logger.debug(f"Track {track_id}: Travel distance {travel_distance:.1f}px < min {self.min_travel_px}px")
            state.last_point = point
            state.last_ts = ts
            state.last_side = self._get_side(point)
            return None
        
        # Check X range if specified
        if self.x_range_min is not None and point[0] < self.x_range_min:
            state.last_point = point
            state.last_ts = ts
            state.last_side = self._get_side(point)
            return None
        
        if self.x_range_max is not None and point[0] > self.x_range_max:
            state.last_point = point
            state.last_ts = ts
            state.last_side = self._get_side(point)
            return None
        
        # Get current side
        cur_side = self._get_side(point)
        
        # Always check intersection when side changes (for debugging)
        intersects = False
        if state.last_side != cur_side and state.last_side != 0 and cur_side != 0:
            # Side changed - check if segment intersects gate
            intersects = self._segment_intersect(
                state.last_point,
                point,
                tuple(self.gate_p1),
                tuple(self.gate_p2),
            )
            
            # Log side changes for debugging (INFO level for visibility)
            logger.info(
                f"Track {track_id}: Side changed ({state.last_side} -> {cur_side}), "
                f"intersects={intersects}, travel={travel_distance:.1f}px, "
                f"last_point={state.last_point}, cur_point={point}, "
                f"gate_p1={tuple(self.gate_p1)}, gate_p2={tuple(self.gate_p2)}"
            )
        elif state.last_side != cur_side:
            # Side changed but one side is 0 (on the line)
            logger.debug(
                f"Track {track_id}: Side changed ({state.last_side} -> {cur_side}) but one side is 0 (on line)"
            )
        
        # Check if side changed and both sides are non-zero
        if state.last_side == 0 or cur_side == 0:
            # On the line, update state
            state.last_point = point
            state.last_ts = ts
            state.last_side = cur_side
            return None
        
        if state.last_side == cur_side:
            # Same side, no crossing
            state.last_point = point
            state.last_ts = ts
            return None
        
        # Side changed - check if segment intersects gate (already computed above)
        if not intersects:
            # No intersection, update state
            state.last_point = point
            state.last_ts = ts
            state.last_side = cur_side
            return None
        
        # REMOVED: Duplicate check that was causing issues
        
        # Valid crossing detected!
        # Determine direction
        if self.is_horizontal and "UP" in self.direction_mapping:
            # Horizontal gate: use UP/DOWN
            if point[1] < state.last_point[1]:
                direction_key = "UP"
            else:
                direction_key = "DOWN"
        else:
            # General gate: use POS_TO_NEG/NEG_TO_POS
            if state.last_side == 1 and cur_side == -1:
                direction_key = "POS_TO_NEG"
            elif state.last_side == -1 and cur_side == 1:
                direction_key = "NEG_TO_POS"
            else:
                # Should not happen, but handle gracefully
                state.last_point = point
                state.last_ts = ts
                state.last_side = cur_side
                return None
        
        direction = self.direction_mapping.get(direction_key)
        if not direction:
            logger.warning(f"No direction mapping for {direction_key}")
            state.last_point = point
            state.last_ts = ts
            state.last_side = cur_side
            return None
        
        # Count!
        if direction == "IN":
            self.count_in += 1
        else:
            self.count_out += 1
        
        # Create event
        event = SegmentEvent(
            track_id=track_id,
            timestamp=ts,
            direction=direction,
            prev_point=state.last_point,
            cur_point=point,
            prev_side=state.last_side,
            cur_side=cur_side,
        )
        
        self.events.append(event)
        
        # Mark as counted and set cooldown
        state.last_count_ts = ts
        
        logger.info(
            f"Track {track_id} crossed gate: {direction} "
            f"(side {state.last_side} -> {cur_side}), "
            f"travel={travel_distance:.1f}px"
        )
        
        # Update state
        state.last_point = point
        state.last_ts = ts
        state.last_side = cur_side
        
        return event
    
    def get_counts(self) -> Dict[str, int]:
        """Get current counts."""
        return {"in": self.count_in, "out": self.count_out}
    
    def reset_daily(self, date: Optional[str] = None):
        """Reset counts for new day."""
        self.count_in = 0
        self.count_out = 0
        self.track_states.clear()
        self.events.clear()
        logger.info(f"Counts reset for date: {date or 'today'}")
    
    def get_gate_geometry(self) -> Dict:
        """Get gate geometry for visualization."""
        return {
            "type": "segment",
            "p1": tuple(self.gate_p1),
            "p2": tuple(self.gate_p2),
            "x_range_min": self.x_range_min,
            "x_range_max": self.x_range_max,
        }

