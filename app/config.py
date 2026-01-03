"""Configuration management using Pydantic Settings."""

from typing import Literal, Tuple, Union, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class CameraConfig(BaseSettings):
    """Camera configuration."""
    
    url: str = Field(
        default="0",
        description="Camera URL (RTSP stream URL or USB camera index, e.g., '0' for /dev/video0 or 'rtsp://...')"
    )
    reconnect_delay: float = Field(
        default=5.0,
        description="Delay in seconds before reconnecting on failure"
    )
    max_reconnect_attempts: int = Field(
        default=10,
        description="Maximum reconnection attempts (0 = infinite)"
    )
    fps_cap: int = Field(
        default=0,
        description="Maximum FPS to process (0 = no cap, process all frames for maximum speed)"
    )
    camera_id: str = Field(
        default="camera_01",
        description="Unique camera identifier"
    )
    max_resolution: Optional[int] = Field(
        default=None,
        description="Maximum resolution for detection (resize if larger). None = use original resolution"
    )


class DetectionConfig(BaseSettings):
    """Object detection configuration."""
    
    model_name: str = Field(
        default="yolov8n.pt",
        description="YOLO model name (yolov8n.pt, yolov8s.pt, yolov8m.pt, etc.)"
    )
    conf_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for detections"
    )
    iou_threshold: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="IOU threshold for NMS (lower = keep more overlapping boxes)"
    )
    device: str = Field(
        default="cpu",
        description="Device to run inference on (cpu, cuda for NVIDIA GPU, mps for Apple Silicon)"
    )
    imgsz: Optional[int] = Field(
        default=320,
        description="Input image size for YOLO (320 = fast, 256 = faster, 640 = more accurate)"
    )


class TrackingConfig(BaseSettings):
    """Object tracking configuration."""
    
    tracker_type: Literal["bytetrack", "deepsort"] = Field(
        default="bytetrack",
        description="Tracker type"
    )
    track_thresh: float = Field(
        default=0.5,
        description="Tracking threshold"
    )
    track_buffer: int = Field(
        default=30,
        description="Number of frames to keep lost tracks"
    )
    match_thresh: float = Field(
        default=0.8,
        description="Matching threshold"
    )


class LineConfig(BaseSettings):
    """Line crossing configuration (legacy)."""
    
    line_start: Tuple[int, int] = Field(
        default=(0, 240),
        description="Line start point (x, y) in frame coordinates"
    )
    line_end: Tuple[int, int] = Field(
        default=(640, 240),
        description="Line end point (x, y) in frame coordinates"
    )
    
    class Config:
        extra = "ignore"  # Ignore extra fields from .env


class GateConfig(BaseSettings):
    """Gate counting configuration."""
    
    gate_mode: Literal["HORIZONTAL_BAND", "VERTICAL_BAND", "LINE_BAND", "SEGMENT"] = Field(
        default="SEGMENT",
        description="Gate mode: HORIZONTAL_BAND, VERTICAL_BAND, LINE_BAND, or SEGMENT (segment-crossing)"
    )
    
    # HORIZONTAL_BAND params
    gate_y: float = Field(
        default=240.0,
        description="Center Y coordinate for horizontal band"
    )
    gate_height: float = Field(
        default=40.0,
        description="Height (thickness) of horizontal band in pixels"
    )
    gate_x_min: Optional[float] = Field(
        default=None,
        description="Optional X minimum for horizontal band"
    )
    gate_x_max: Optional[float] = Field(
        default=None,
        description="Optional X maximum for horizontal band"
    )
    
    # VERTICAL_BAND params
    gate_x: float = Field(
        default=320.0,
        description="Center X coordinate for vertical band"
    )
    gate_width: float = Field(
        default=40.0,
        description="Width (thickness) of vertical band in pixels"
    )
    gate_y_min: Optional[float] = Field(
        default=None,
        description="Optional Y minimum for vertical band"
    )
    gate_y_max: Optional[float] = Field(
        default=None,
        description="Optional Y maximum for vertical band"
    )
    
    # Buffer zones for counting (only for VERTICAL_BAND)
    buffer_zone_width: float = Field(
        default=200.0,
        description="Width of buffer zones on each side of gate (pixels)"
    )
    use_buffer_zones: bool = Field(
        default=True,
        description="Enable buffer zones for more accurate counting"
    )
    
    @field_validator('gate_y_min', 'gate_y_max', mode='before')
    @classmethod
    def parse_optional_float(cls, v):
        """Parse empty string as None for optional float fields."""
        if isinstance(v, str) and v.strip() == '':
            return None
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None
    
    # LINE_BAND params
    gate_p1: Optional[Tuple[float, float]] = Field(
        default=None,
        description="Start point (x, y) for line band"
    )
    gate_p2: Optional[Tuple[float, float]] = Field(
        default=None,
        description="End point (x, y) for line band"
    )
    gate_thickness: float = Field(
        default=40.0,
        description="Thickness of line band in pixels"
    )
    
    # Direction mapping (TOP->BOTTOM=OUT, BOTTOM->TOP=IN for horizontal)
    # (LEFT->RIGHT=IN, RIGHT->LEFT=OUT for vertical)
    # Or (LEFT->RIGHT=IN, RIGHT->LEFT=OUT for line)
    direction_mapping_top_bottom: str = Field(
        default="OUT",
        description="Direction for TOP->BOTTOM crossing (horizontal)"
    )
    direction_mapping_bottom_top: str = Field(
        default="IN",
        description="Direction for BOTTOM->TOP crossing (horizontal)"
    )
    direction_mapping_left_right: str = Field(
        default="IN",
        description="Direction for LEFT->RIGHT crossing (vertical)"
    )
    direction_mapping_right_left: str = Field(
        default="OUT",
        description="Direction for RIGHT->LEFT crossing (vertical)"
    )
    
    # Anti-jitter params
    cooldown_sec: float = Field(
        default=0.5,
        description="Cooldown time in seconds to prevent double counting"
    )
    min_frames_in_gate: int = Field(
        default=1,
        description="Minimum frames inside gate before counting"
    )
    min_travel_px: float = Field(
        default=12.0,
        description="Minimum travel distance in pixels to count"
    )
    rearm_dist_px: float = Field(
        default=50.0,
        description="Distance to move away from gate before allowing re-count (pixels)"
    )
    
    # SEGMENT mode params (segment-crossing algorithm)
    gate_p1_x: Optional[float] = Field(
        default=None,
        description="Gate segment start point X coordinate (SEGMENT mode)"
    )
    gate_p1_y: Optional[float] = Field(
        default=None,
        description="Gate segment start point Y coordinate (SEGMENT mode)"
    )
    gate_p2_x: Optional[float] = Field(
        default=None,
        description="Gate segment end point X coordinate (SEGMENT mode)"
    )
    gate_p2_y: Optional[float] = Field(
        default=None,
        description="Gate segment end point Y coordinate (SEGMENT mode)"
    )
    direction_mapping_pos_to_neg: str = Field(
        default="IN",
        description="Direction for POS side -> NEG side crossing (SEGMENT mode)"
    )
    direction_mapping_neg_to_pos: str = Field(
        default="OUT",
        description="Direction for NEG side -> POS side crossing (SEGMENT mode)"
    )
    direction_mapping_up: Optional[str] = Field(
        default=None,
        description="Direction for upward movement (horizontal gate, SEGMENT mode)"
    )
    direction_mapping_down: Optional[str] = Field(
        default=None,
        description="Direction for downward movement (horizontal gate, SEGMENT mode)"
    )
    x_range_min: Optional[float] = Field(
        default=None,
        description="Optional X minimum for gate region (SEGMENT mode)"
    )
    x_range_max: Optional[float] = Field(
        default=None,
        description="Optional X maximum for gate region (SEGMENT mode)"
    )
    
    @field_validator('gate_p1', 'gate_p2', mode='before')
    @classmethod
    def parse_gate_tuple(cls, v):
        """Parse tuple from string or list for gate points."""
        if isinstance(v, str):
            v = v.strip().strip('()[]')
            parts = v.split(',')
            if len(parts) == 2:
                return (float(parts[0].strip()), float(parts[1].strip()))
            raise ValueError(f"Cannot parse tuple from string: {v}")
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return (float(v[0]), float(v[1]))
        return v


class WindowConfig(BaseSettings):
    """Time window configuration."""
    
    timezone: str = Field(
        default="Asia/Bangkok",
        description="Timezone for window calculations"
    )
    window_a_start: str = Field(
        default="12:00",
        description="Window A start time (HH:MM)"
    )
    window_a_end: str = Field(
        default="12:59",
        description="Window A end time (HH:MM)"
    )
    window_b_start: str = Field(
        default="13:00",
        description="Window B start time (HH:MM)"
    )
    window_b_end: str = Field(
        default="13:59",
        description="Window B end time (HH:MM)"
    )


class NotificationConfig(BaseSettings):
    """Notification configuration."""
    
    enabled: bool = Field(
        default=False,
        description="Enable notifications"
    )
    channel: Literal["telegram", "email", "webhook"] = Field(
        default="telegram",
        description="Notification channel"
    )
    
    # Telegram
    telegram_bot_token: str = Field(
        default="",
        description="Telegram bot token"
    )
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat ID"
    )
    
    # Email
    email_smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP host"
    )
    email_smtp_port: int = Field(
        default=587,
        description="SMTP port"
    )
    email_from: str = Field(
        default="",
        description="Email sender address"
    )
    email_to: str = Field(
        default="",
        description="Email recipient address"
    )
    email_password: str = Field(
        default="",
        description="Email password or app password"
    )
    
    # Webhook
    webhook_url: str = Field(
        default="",
        description="Webhook URL for HTTP POST"
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""
    
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format"
    )


class ProductionConfig(BaseSettings):
    """Production scheduler configuration."""
    
    reset_time: str = Field(
        default="00:00",
        description="Daily reset time (HH:MM)"
    )
    morning_start: str = Field(
        default="16:36",
        description="Morning count phase start (HH:MM)"
    )
    morning_end: str = Field(
        default="16:40",
        description="Morning count phase end (HH:MM)"
    )
    alert_interval_min: int = Field(
        default=1,
        description="Alert check interval in minutes"
    )


class Config(BaseSettings):
    """Main application configuration."""
    
    camera: CameraConfig = Field(default_factory=CameraConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    line: LineConfig = Field(default_factory=LineConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    window: WindowConfig = Field(default_factory=WindowConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    production: ProductionConfig = Field(default_factory=ProductionConfig)
    
    # Database
    db_path: str = Field(
        default="people_counter.db",
        description="SQLite database path"
    )
    
    # Snapshot
    save_snapshots: bool = Field(
        default=True,
        description="Save snapshots when alert is triggered"
    )
    snapshot_dir: str = Field(
        default="snapshots",
        description="Directory to save snapshots"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "__"
        case_sensitive = False
        # Disable JSON parsing for complex types to allow custom parsing
        json_schema_extra = {
            "json_encoders": {}
        }


def load_config() -> Config:
    """Load configuration from environment variables."""
    return Config()

