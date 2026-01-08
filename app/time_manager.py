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
    MORNING_COUNT = "MORNING_COUNT"  # 06:00 - 08:30
    REALTIME_MORNING = "REALTIME_MORNING"  # 08:30 - 11:55
    LUNCH_BREAK = "LUNCH_BREAK"  # 11:55 - 13:15
    AFTERNOON_MONITORING = "AFTERNOON_MONITORING"  # 13:15 - end of day


class TimeManager:
    """Manages time-based state transitions and daily resets."""
    
    def __init__(
        self,
        timezone: str = "Asia/Ho_Chi_Minh",
        reset_time: str = "06:00",  # Changed from 00:00 to 06:00 per requirements
        morning_start: str = "06:00",
        morning_end: str = "08:30",
        realtime_morning_end: str = "11:55",
        lunch_end: str = "13:15",
    ):
        """
        Initialize time manager.
        
        Args:
            timezone: Timezone string (default: Asia/Ho_Chi_Minh)
            reset_time: Daily reset time (HH:MM)
            morning_start: Morning count phase start (HH:MM) - default 06:00
            morning_end: Morning count phase end (HH:MM) - default 08:30
            realtime_morning_end: Realtime morning monitoring end (HH:MM) - default 11:55
            lunch_end: Lunch break end (HH:MM) - default 13:15
        """
        self.tz = pytz.timezone(timezone)
        self.reset_time = self._parse_time(reset_time)
        self.morning_start = self._parse_time(morning_start)
        self.morning_end = self._parse_time(morning_end)
        self.realtime_morning_end = self._parse_time(realtime_morning_end)
        self.lunch_end = self._parse_time(lunch_end)
        
        # Current phase
        self.current_phase = self._get_current_phase()
        
        # Callbacks
        self.on_reset: Optional[Callable[[], None]] = None
        self.on_morning_start: Optional[Callable[[], None]] = None
        self.on_morning_end: Optional[Callable[[], None]] = None
        self.on_realtime_morning_start: Optional[Callable[[], None]] = None
        self.on_realtime_morning_end: Optional[Callable[[], None]] = None
        self.on_lunch_start: Optional[Callable[[], None]] = None
        self.on_lunch_end: Optional[Callable[[], None]] = None
        self.on_afternoon_start: Optional[Callable[[], None]] = None
        
        # Scheduler
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._schedule_jobs()
        
        logger.info(
            f"TimeManager initialized: reset={reset_time}, "
            f"morning={morning_start}-{morning_end}, "
            f"realtime_morning={morning_end}-{realtime_morning_end}, "
            f"lunch={realtime_morning_end}-{lunch_end}, "
            f"afternoon={lunch_end}-end, "
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
        
        # FPS OPTIMIZATION: Removed debug logging that was called every frame
        # Debug logging is now only done when phase changes (in get_current_phase())
        
        if self.morning_start <= current_time < self.morning_end:
            return Phase.MORNING_COUNT
        elif self.morning_end <= current_time < self.realtime_morning_end:
            return Phase.REALTIME_MORNING
        elif self.realtime_morning_end <= current_time < self.lunch_end:
            return Phase.LUNCH_BREAK
        else:
            return Phase.AFTERNOON_MONITORING
    
    def _schedule_jobs(self):
        """Schedule time-based jobs."""
        # Daily reset at 06:00 (per requirements: reset and start counting at 06:00)
        # Reset and morning start happen at the same time (06:00)
        self.scheduler.add_job(
            self._on_reset,
            trigger=CronTrigger(hour=self.reset_time.hour, minute=self.reset_time.minute, timezone=self.tz),
            id='daily_reset',
        )
        
        # Morning phase start at 06:00 (same as reset - they happen together)
        self.scheduler.add_job(
            self._on_morning_start,
            trigger=CronTrigger(hour=self.morning_start.hour, minute=self.morning_start.minute, timezone=self.tz),
            id='morning_start',
        )
        
        # Day close at 23:59 (prepare for next day reset)
        self.scheduler.add_job(
            self._on_day_close,
            trigger=CronTrigger(hour=23, minute=59, timezone=self.tz),
            id='day_close',
        )
        
        # Morning phase end at 08:30
        self.scheduler.add_job(
            self._on_morning_end,
            trigger=CronTrigger(hour=self.morning_end.hour, minute=self.morning_end.minute, timezone=self.tz),
            id='morning_end',
        )
        
        # Realtime morning monitoring end at 11:55
        self.scheduler.add_job(
            self._on_realtime_morning_end,
            trigger=CronTrigger(hour=self.realtime_morning_end.hour, minute=self.realtime_morning_end.minute, timezone=self.tz),
            id='realtime_morning_end',
        )
        
        # Lunch break end at 13:15
        self.scheduler.add_job(
            self._on_lunch_end,
            trigger=CronTrigger(hour=self.lunch_end.hour, minute=self.lunch_end.minute, timezone=self.tz),
            id='lunch_end',
        )
        
        logger.info("Time-based jobs scheduled")
    
    def _on_reset(self):
        """Handle daily reset."""
        logger.info("=== DAILY RESET: Resetting all state ===")
        self.current_phase = self._get_current_phase()
        
        if self.on_reset:
            self.on_reset()
    
    def _on_morning_start(self):
        """Handle morning phase start."""
        logger.info("=== MORNING COUNT PHASE STARTED (06:00-08:30) ===")
        self.current_phase = Phase.MORNING_COUNT
        
        if self.on_morning_start:
            self.on_morning_start()
    
    def _on_morning_end(self):
        """Handle morning phase end."""
        logger.info("=== MORNING COUNT PHASE ENDED: Freezing total_morning ===")
        logger.info("=== REALTIME MORNING MONITORING PHASE STARTED (08:30-11:55) ===")
        self.current_phase = Phase.REALTIME_MORNING
        
        if self.on_morning_end:
            self.on_morning_end()
        
        if self.on_realtime_morning_start:
            self.on_realtime_morning_start()
    
    def _on_realtime_morning_end(self):
        """Handle realtime morning monitoring end."""
        logger.info("=== REALTIME MORNING MONITORING PHASE ENDED ===")
        logger.info("=== LUNCH BREAK PHASE STARTED (11:55-13:15) ===")
        self.current_phase = Phase.LUNCH_BREAK
        
        if self.on_realtime_morning_end:
            self.on_realtime_morning_end()
        
        if self.on_lunch_start:
            self.on_lunch_start()
    
    def _on_lunch_end(self):
        """Handle lunch break end."""
        logger.info("=== LUNCH BREAK PHASE ENDED ===")
        logger.info("=== AFTERNOON MONITORING PHASE STARTED (13:15-end) ===")
        self.current_phase = Phase.AFTERNOON_MONITORING
        
        if self.on_lunch_end:
            self.on_lunch_end()
        
        if self.on_afternoon_start:
            self.on_afternoon_start()
    
    def _on_day_close(self):
        """Handle day close at 23:59 - prepare for next day reset."""
        logger.info("=== DAY CLOSE AT 23:59 - Preparing for next day reset ===")
        self.current_phase = self._get_current_phase()
        
        if self.on_day_close:
            self.on_day_close()
    
    def is_morning_phase(self, now: Optional[datetime] = None) -> bool:
        """Check if current time is in morning count phase (06:00-08:30)."""
        if now is None:
            now = datetime.now(self.tz)
        
        current_time = now.time()
        return self.morning_start <= current_time < self.morning_end
    
    def is_monitoring_phase(self, now: Optional[datetime] = None) -> bool:
        """Check if current time is in a monitoring phase (realtime morning or afternoon)."""
        if now is None:
            now = datetime.now(self.tz)
        
        current_time = now.time()
        return (self.morning_end <= current_time < self.realtime_morning_end) or (self.lunch_end <= current_time)
    
    def get_current_session(self, now: Optional[datetime] = None) -> Optional[str]:
        """Get current session: 'morning' or 'afternoon' or None (if lunch or morning count)."""
        if now is None:
            now = datetime.now(self.tz)
        
        phase = self._get_current_phase()
        if phase == Phase.REALTIME_MORNING:
            return 'morning'
        elif phase == Phase.AFTERNOON_MONITORING:
            return 'afternoon'
        return None
    
    def get_current_phase(self) -> Phase:
        """Get current phase."""
        # Update phase based on current time
        new_phase = self._get_current_phase()
        if new_phase != self.current_phase:
            logger.info(f"Phase changed: {self.current_phase.value} -> {new_phase.value} (current time: {datetime.now(self.tz).strftime('%H:%M:%S')})")
            self.current_phase = new_phase
        return self.current_phase
    
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("TimeManager scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("TimeManager scheduler stopped")

