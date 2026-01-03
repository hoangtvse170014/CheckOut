"""Time-based state manager for daily reset and phase transitions."""

import logging
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Callable, Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class Phase(Enum):
    """System phases."""
    MORNING_COUNT = "MORNING_COUNT"  # 07:00 - 08:40
    REALTIME_MONITORING = "REALTIME_MONITORING"  # After 08:40


class TimeManager:
    """Manages time-based state transitions and daily resets."""
    
    def __init__(
        self,
        timezone: str = "Asia/Bangkok",
        reset_time: str = "00:00",
        morning_start: str = "16:00",
        morning_end: str = "16:05",
    ):
        """
        Initialize time manager.
        
        Args:
            timezone: Timezone string
            reset_time: Daily reset time (HH:MM)
            morning_start: Morning count phase start (HH:MM)
            morning_end: Morning count phase end (HH:MM)
        """
        self.tz = pytz.timezone(timezone)
        self.reset_time = self._parse_time(reset_time)
        self.morning_start = self._parse_time(morning_start)
        self.morning_end = self._parse_time(morning_end)
        
        # Current phase
        self.current_phase = self._get_current_phase()
        
        # Callbacks
        self.on_reset: Optional[Callable[[], None]] = None
        self.on_morning_start: Optional[Callable[[], None]] = None
        self.on_morning_end: Optional[Callable[[], None]] = None
        
        # Scheduler
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._schedule_jobs()
        
        logger.info(
            f"TimeManager initialized: reset={reset_time}, "
            f"morning={morning_start}-{morning_end}, "
            f"current_phase={self.current_phase.value}"
        )
    
    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string (HH:MM) to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    
    def _get_current_phase(self) -> Phase:
        """Get current phase based on system time."""
        now = datetime.now(self.tz)
        current_time = now.time()
        
        if self.morning_start <= current_time < self.morning_end:
            return Phase.MORNING_COUNT
        else:
            return Phase.REALTIME_MONITORING
    
    def _schedule_jobs(self):
        """Schedule time-based jobs."""
        # Daily reset at 00:00
        self.scheduler.add_job(
            self._on_reset,
            trigger=CronTrigger(hour=self.reset_time.hour, minute=self.reset_time.minute, timezone=self.tz),
            id='daily_reset',
        )
        
        # Morning phase start at 07:00
        self.scheduler.add_job(
            self._on_morning_start,
            trigger=CronTrigger(hour=self.morning_start.hour, minute=self.morning_start.minute, timezone=self.tz),
            id='morning_start',
        )
        
        # Morning phase end at 08:40
        self.scheduler.add_job(
            self._on_morning_end,
            trigger=CronTrigger(hour=self.morning_end.hour, minute=self.morning_end.minute, timezone=self.tz),
            id='morning_end',
        )
        
        logger.info("Time-based jobs scheduled")
    
    def _on_reset(self):
        """Handle daily reset."""
        logger.info("=== DAILY RESET: Resetting all state ===")
        self.current_phase = Phase.REALTIME_MONITORING
        
        if self.on_reset:
            self.on_reset()
    
    def _on_morning_start(self):
        """Handle morning phase start."""
        logger.info("=== MORNING COUNT PHASE STARTED ===")
        self.current_phase = Phase.MORNING_COUNT
        
        if self.on_morning_start:
            self.on_morning_start()
    
    def _on_morning_end(self):
        """Handle morning phase end."""
        logger.info("=== MORNING COUNT PHASE ENDED: Freezing total_morning ===")
        self.current_phase = Phase.REALTIME_MONITORING
        
        if self.on_morning_end:
            self.on_morning_end()
    
    def is_morning_phase(self, now: Optional[datetime] = None) -> bool:
        """Check if current time is in morning phase."""
        if now is None:
            now = datetime.now(self.tz)
        
        current_time = now.time()
        return self.morning_start <= current_time < self.morning_end
    
    def get_current_phase(self) -> Phase:
        """Get current phase."""
        # Update phase based on current time
        self.current_phase = self._get_current_phase()
        return self.current_phase
    
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("TimeManager scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("TimeManager scheduler stopped")

