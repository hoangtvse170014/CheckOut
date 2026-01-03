"""Gate Counter with band-based crossing detection."""

import logging
from typing import Dict, Optional, Tuple, Literal
from dataclasses import dataclass
from enum import Enum
import numpy as np
import time

logger = logging.getLogger(__name__)


class GateMode(Enum):
    """Gate mode types."""
    HORIZONTAL_BAND = "HORIZONTAL_BAND"
    VERTICAL_BAND = "VERTICAL_BAND"
    LINE_BAND = "LINE_BAND"


@dataclass
class GateEvent:
    """Gate crossing event."""
    track_id: int
    timestamp: float
    direction: str  # "IN" or "OUT"
    entry_side: str
    exit_side: str
    frames_in_gate: int
    travel_distance: float


class TrackState:
    """State for a single track."""
    
    def __init__(self):
        self.last_side: Optional[str] = None
        self.in_gate: bool = False  # True if currently inside gate band
        self.entry_side: Optional[str] = None  # Side when first entered gate
        self.exit_side: Optional[str] = None  # Side when exiting gate
        self.frames_in_gate: int = 0
        self.last_point: Optional[Tuple[float, float]] = None
        self.last_ts: float = 0.0
        self.counted: bool = False
        self.last_count_ts: float = 0.0
        self.last_count_point: Optional[Tuple[float, float]] = None  # Point where last count occurred
        self.points_history: list = []  # For travel distance calculation


class GateCounter:
    """Gate counter with band-based crossing detection."""
    
    def __init__(
        self,
        gate_mode: str = "HORIZONTAL_BAND",
        # HORIZONTAL_BAND params
        gate_y: float = 240.0,
        gate_height: float = 40.0,
        gate_x_min: Optional[float] = None,
        gate_x_max: Optional[float] = None,
        # VERTICAL_BAND params
        gate_x: float = 320.0,
        gate_width: float = 40.0,
        gate_y_min: Optional[float] = None,
        gate_y_max: Optional[float] = None,
        buffer_zone_width: float = 100.0,
        use_buffer_zones: bool = True,
        # LINE_BAND params
        gate_p1: Optional[Tuple[float, float]] = None,
        gate_p2: Optional[Tuple[float, float]] = None,
        gate_thickness: float = 40.0,
        # Direction mapping: {("entry_side", "exit_side"): "IN" or "OUT"}
        direction_mapping: Optional[Dict[Tuple[str, str], str]] = None,
        # Anti-jitter params
        cooldown_sec: float = 1.0,
        min_frames_in_gate: int = 2,
        min_travel_px: float = 15.0,
        rearm_dist_px: float = 50.0,  # Distance to move away from gate before allowing re-count
    ):
        """
        Initialize gate counter.
        
        Args:
            gate_mode: "HORIZONTAL_BAND" or "LINE_BAND"
            gate_y: Center Y coordinate for horizontal band
            gate_height: Height (thickness) of horizontal band
            gate_x_min: Optional X minimum for horizontal band
            gate_x_max: Optional X maximum for horizontal band
            gate_p1: Start point (x, y) for line band
            gate_p2: End point (x, y) for line band
            gate_thickness: Thickness of line band
            direction_mapping: Mapping from (entry_side, exit_side) to "IN"/"OUT"
            cooldown_sec: Cooldown time in seconds to prevent double counting
            min_frames_in_gate: Minimum frames inside gate before counting
            min_travel_px: Minimum travel distance in pixels to count
        """
        self.gate_mode = GateMode(gate_mode)
        self.cooldown_sec = cooldown_sec
        self.min_frames_in_gate = min_frames_in_gate
        self.min_travel_px = min_travel_px
        self.rearm_dist_px = rearm_dist_px
        
        # Gate configuration
        if self.gate_mode == GateMode.HORIZONTAL_BAND:
            self.gate_y = gate_y
            self.gate_height = gate_height
            self.gate_x_min = gate_x_min
            self.gate_x_max = gate_x_max
            logger.info(
                f"Horizontal band gate: y={gate_y}, height={gate_height}, "
                f"x_range=[{gate_x_min}, {gate_x_max}]"
            )
        elif self.gate_mode == GateMode.VERTICAL_BAND:
            self.gate_x = gate_x
            self.gate_width = gate_width
            self.gate_y_min = gate_y_min
            self.gate_y_max = gate_y_max
            self.buffer_zone_width = buffer_zone_width
            self.use_buffer_zones = use_buffer_zones
            # Calculate zone boundaries
            self.gate_left = gate_x - gate_width / 2
            self.gate_right = gate_x + gate_width / 2
            self.in_zone_right = self.gate_left  # End of IN zone (left side)
            self.in_zone_left = self.gate_left - buffer_zone_width  # Start of IN zone
            self.out_zone_left = self.gate_right  # Start of OUT zone (right side)
            self.out_zone_right = self.gate_right + buffer_zone_width  # End of OUT zone
            logger.info(
                f"Vertical band gate: x={gate_x}, width={gate_width}, "
                f"y_range=[{gate_y_min}, {gate_y_max}], "
                f"buffer_zones={'enabled' if use_buffer_zones else 'disabled'} "
                f"(width={buffer_zone_width})"
            )
        else:  # LINE_BAND
            if gate_p1 is None or gate_p2 is None:
                raise ValueError("gate_p1 and gate_p2 required for LINE_BAND mode")
            self.gate_p1 = np.array(gate_p1, dtype=np.float32)
            self.gate_p2 = np.array(gate_p2, dtype=np.float32)
            self.gate_thickness = gate_thickness
            self.gate_vec = self.gate_p2 - self.gate_p1
            self.gate_length = np.linalg.norm(self.gate_vec)
            logger.info(
                f"Line band gate: p1={gate_p1}, p2={gate_p2}, thickness={gate_thickness}"
            )
        
        # Direction mapping
        if direction_mapping is None:
            # Default: TOP->BOTTOM = OUT, BOTTOM->TOP = IN (for horizontal)
            # LEFT->RIGHT = IN, RIGHT->LEFT = OUT (for vertical or line)
            if self.gate_mode == GateMode.HORIZONTAL_BAND:
                self.direction_mapping = {
                    ("TOP", "BOTTOM"): "OUT",
                    ("BOTTOM", "TOP"): "IN",
                }
            elif self.gate_mode == GateMode.VERTICAL_BAND:
                self.direction_mapping = {
                    ("LEFT", "RIGHT"): "IN",
                    ("RIGHT", "LEFT"): "OUT",
                }
            else:  # LINE_BAND
                self.direction_mapping = {
                    ("LEFT", "RIGHT"): "IN",
                    ("RIGHT", "LEFT"): "OUT",
                }
        else:
            self.direction_mapping = direction_mapping
        
        # Track states
        self.track_states: Dict[int, TrackState] = {}
        
        # Counts
        self.count_in = 0
        self.count_out = 0
        
        # Events history
        self.events: list[GateEvent] = []
    
    def _get_zone(self, point: Tuple[float, float]) -> str:
        """Get zone of point: IN_ZONE, GATE, or OUT_ZONE (for VERTICAL_BAND with buffer zones)."""
        if self.gate_mode == GateMode.VERTICAL_BAND and self.use_buffer_zones:
            x = point[0]
            if x < self.in_zone_right:
                return "IN_ZONE"
            elif x > self.out_zone_left:
                return "OUT_ZONE"
            else:
                return "GATE"
        # Fallback to side-based logic
        return self._get_side(point)
    
    def _get_side(self, point: Tuple[float, float]) -> str:
        """Get side of point relative to gate."""
        if self.gate_mode == GateMode.HORIZONTAL_BAND:
            y = point[1]
            if y < self.gate_y:
                return "TOP"
            else:
                return "BOTTOM"
        elif self.gate_mode == GateMode.VERTICAL_BAND:
            x = point[0]
            if x < self.gate_x:
                return "LEFT"
            else:
                return "RIGHT"
        else:  # LINE_BAND
            point_vec = np.array(point, dtype=np.float32) - self.gate_p1
            # Cross product to determine side
            cross = np.cross(self.gate_vec, point_vec)
            if cross > 0:
                return "LEFT"
            else:
                return "RIGHT"
    
    def _is_in_gate(self, point: Tuple[float, float]) -> bool:
        """Check if point is inside gate band."""
        if self.gate_mode == GateMode.HORIZONTAL_BAND:
            y = point[1]
            x = point[0]
            
            # Check Y within band
            y_dist = abs(y - self.gate_y)
            if y_dist > self.gate_height / 2:
                return False
            
            # Check X range if specified
            if self.gate_x_min is not None and x < self.gate_x_min:
                return False
            if self.gate_x_max is not None and x > self.gate_x_max:
                return False
            
            return True
        elif self.gate_mode == GateMode.VERTICAL_BAND:
            x = point[0]
            y = point[1]
            
            # Check X within band
            x_dist = abs(x - self.gate_x)
            if x_dist > self.gate_width / 2:
                return False
            
            # Check Y range if specified
            if self.gate_y_min is not None and y < self.gate_y_min:
                return False
            if self.gate_y_max is not None and y > self.gate_y_max:
                return False
            
            return True
        else:  # LINE_BAND
            point_vec = np.array(point, dtype=np.float32) - self.gate_p1
            
            # Project point onto line
            t = np.dot(point_vec, self.gate_vec) / (self.gate_length ** 2)
            
            # Check if projection is within line segment
            if t < 0 or t > 1:
                return False
            
            # Get closest point on line
            closest_point = self.gate_p1 + t * self.gate_vec
            
            # Calculate distance from point to line
            dist = np.linalg.norm(np.array(point, dtype=np.float32) - closest_point)
            
            return dist <= self.gate_thickness / 2
    
    def _calculate_travel_distance(self, state: TrackState) -> float:
        """Calculate travel distance from points history."""
        if len(state.points_history) < 2:
            return 0.0
        
        # Use first and last point in gate
        first_point = state.points_history[0]
        last_point = state.points_history[-1]
        
        return np.linalg.norm(
            np.array(last_point, dtype=np.float32) - np.array(first_point, dtype=np.float32)
        )
    
    def _distance_to_gate(self, point: Tuple[float, float]) -> float:
        """Calculate minimum distance from point to gate."""
        if self.gate_mode == GateMode.VERTICAL_BAND:
            x = point[0]
            x_dist = abs(x - self.gate_x)
            return max(0, x_dist - self.gate_width / 2)
        elif self.gate_mode == GateMode.HORIZONTAL_BAND:
            y = point[1]
            y_dist = abs(y - self.gate_y)
            return max(0, y_dist - self.gate_height / 2)
        else:  # LINE_BAND
            point_vec = np.array(point, dtype=np.float32) - self.gate_p1
            t = np.dot(point_vec, self.gate_vec) / (self.gate_length ** 2)
            t = np.clip(t, 0, 1)
            closest_point = self.gate_p1 + t * self.gate_vec
            dist = np.linalg.norm(np.array(point, dtype=np.float32) - closest_point)
            return max(0, dist - self.gate_thickness / 2)
    
    def update(
        self,
        track_id: int,
        point: Tuple[float, float],
        ts: Optional[float] = None,
    ) -> Optional[GateEvent]:
        """
        Update with new track point. Counts when entering gate band.
        
        Args:
            track_id: Track ID
            point: Bottom-center point of bounding box (x, y)
            ts: Timestamp (defaults to current time)
        
        Returns:
            GateEvent if crossing detected, None otherwise
        """
        if ts is None:
            ts = time.time()
        
        # Get or create track state
        if track_id not in self.track_states:
            self.track_states[track_id] = TrackState()
        
        state = self.track_states[track_id]
        
        # Determine current position relative to gate
        if self.gate_mode == GateMode.VERTICAL_BAND and self.use_buffer_zones:
            current_zone = self._get_zone(point)
            is_in_gate = (current_zone == "GATE")
            current_side = current_zone
        else:
            current_side = self._get_side(point)
            is_in_gate = self._is_in_gate(point)
        
        # Check cooldown
        if state.counted and (ts - state.last_count_ts) < self.cooldown_sec:
            # Still in cooldown, just update state
            state.last_point = point
            state.last_ts = ts
            state.last_side = current_side
            state.in_gate = is_in_gate
            return None
        
        # Check rearm distance: if moved far enough from gate, allow re-count
        if state.counted and state.last_count_point is not None:
            dist_to_gate = self._distance_to_gate(point)
            if dist_to_gate >= self.rearm_dist_px:
                state.counted = False
                logger.debug(f"Track {track_id} rearmed (moved {dist_to_gate:.1f}px from gate)")
        
        event = None
        
        # Simple logic: count when entering gate (if not already counted)
        if is_in_gate and not state.in_gate:
            # Just entered gate - count if conditions met
            if not state.counted:
                # Determine direction based on entry side
                entry_side = state.last_side if state.last_side else current_side
                direction = None
                
                if self.gate_mode == GateMode.VERTICAL_BAND and self.use_buffer_zones:
                    # For buffer zones: IN_ZONE -> GATE = IN, OUT_ZONE -> GATE = OUT
                    if entry_side == "IN_ZONE":
                        direction = "IN"
                    elif entry_side == "OUT_ZONE":
                        direction = "OUT"
                    else:
                        # Fallback: try to map using direction_mapping
                        # Assume exit will be opposite zone
                        if entry_side in ["IN_ZONE", "LEFT"]:
                            direction_key = ("LEFT", "RIGHT")
                        else:
                            direction_key = ("RIGHT", "LEFT")
                        direction = self.direction_mapping.get(direction_key)
                else:
                    # Use direction_mapping with entry_side and assumed exit_side
                    # For horizontal: TOP entry -> assume BOTTOM exit, BOTTOM entry -> assume TOP exit
                    # For vertical/line: LEFT entry -> assume RIGHT exit, RIGHT entry -> assume LEFT exit
                    if self.gate_mode == GateMode.HORIZONTAL_BAND:
                        if entry_side == "TOP":
                            exit_side = "BOTTOM"
                        else:
                            exit_side = "TOP"
                    else:  # VERTICAL_BAND or LINE_BAND
                        if entry_side == "LEFT":
                            exit_side = "RIGHT"
                        else:
                            exit_side = "LEFT"
                    
                    direction_key = (entry_side, exit_side)
                    direction = self.direction_mapping.get(direction_key)
                
                # Fallback if direction_mapping doesn't have the key
                if not direction:
                    # Default logic based on gate mode
                    if self.gate_mode == GateMode.HORIZONTAL_BAND:
                        direction = "IN" if entry_side == "BOTTOM" else "OUT"
                    else:
                        direction = "IN" if entry_side == "LEFT" else "OUT"
                
                # Count
                if direction == "IN":
                    self.count_in += 1
                else:
                    self.count_out += 1
                
                # Create event
                event = GateEvent(
                    track_id=track_id,
                    timestamp=ts,
                    direction=direction,
                    entry_side=state.last_side or current_side,
                    exit_side=current_side,
                    frames_in_gate=1,
                    travel_distance=0.0,
                )
                
                self.events.append(event)
                
                # Mark as counted
                state.counted = True
                state.last_count_ts = ts
                state.last_count_point = point
                
                logger.info(f"Track {track_id} entered gate: {direction}")
        
        # Update state
        state.in_gate = is_in_gate
        state.last_point = point
        state.last_ts = ts
        state.last_side = current_side
        
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
        if self.gate_mode == GateMode.HORIZONTAL_BAND:
            return {
                "type": "horizontal_band",
                "y": self.gate_y,
                "height": self.gate_height,
                "x_min": self.gate_x_min,
                "x_max": self.gate_x_max,
            }
        elif self.gate_mode == GateMode.VERTICAL_BAND:
            geom = {
                "type": "vertical_band",
                "x": self.gate_x,
                "width": self.gate_width,
                "y_min": self.gate_y_min,
                "y_max": self.gate_y_max,
            }
            if self.use_buffer_zones:
                geom.update({
                    "buffer_zone_width": self.buffer_zone_width,
                    "in_zone_left": self.in_zone_left,
                    "in_zone_right": self.in_zone_right,
                    "out_zone_left": self.out_zone_left,
                    "out_zone_right": self.out_zone_right,
                })
            return geom
        else:
            return {
                "type": "line_band",
                "p1": tuple(self.gate_p1),
                "p2": tuple(self.gate_p2),
                "thickness": self.gate_thickness,
            }
    
    def get_direction_arrows(self) -> Dict[str, Tuple[str, Tuple[float, float]]]:
        """Get arrow directions for visualization."""
        arrows = {}
        for (entry, exit), direction in self.direction_mapping.items():
            arrows[direction] = (entry, exit)
        return arrows
    
    def get_track_states(self) -> Dict[int, Dict]:
        """Get current state of all tracks for debug overlay."""
        states = {}
        for track_id, state in self.track_states.items():
            states[track_id] = {
                "in_gate": state.in_gate,
                "entry_side": state.entry_side,
                "exit_side": state.exit_side,
                "frames_in_gate": state.frames_in_gate,
                "counted": state.counted,
                "last_point": state.last_point,
            }
        return states

