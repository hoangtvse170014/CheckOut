"""Morning total manager - tracks total_morning during 07:00-08:40."""

import logging
from datetime import datetime
from typing import Optional
import pytz

from app.storage import Storage

logger = logging.getLogger(__name__)


class MorningTotalManager:
    """Manages morning total count (07:00-08:40)."""
    
    def __init__(
        self,
        storage: Storage,
        timezone: str = "Asia/Bangkok",
        morning_start: str = "16:36",
        morning_end: str = "16:40",
    ):
        """
        Initialize morning total manager.
        
        Args:
            storage: Storage instance for persistence
            timezone: Timezone string
            morning_start: Morning phase start (HH:MM)
            morning_end: Morning phase end (HH:MM)
        """
        self.storage = storage
        self.tz = pytz.timezone(timezone)
        self.morning_start = self._parse_time(morning_start)
        self.morning_end = self._parse_time(morning_end)
        
        # Current state
        self.total_morning = 0
        self.is_frozen = False
        
        # Load state from storage
        self._load_state()
        
        logger.info(
            f"MorningTotalManager initialized: total_morning={self.total_morning}, "
            f"frozen={self.is_frozen}"
        )
    
    def _parse_time(self, time_str: str) -> tuple:
        """Parse time string (HH:MM) to (hour, minute)."""
        parts = time_str.split(":")
        return (int(parts[0]), int(parts[1]))
    
    def _load_state(self):
        """Load state from storage."""
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        state = self.storage.get_daily_state(today)
        
        if state:
            self.total_morning = state.get('total_morning', 0)
            self.is_frozen = state.get('is_frozen', False)
            logger.info(f"Loaded state: total_morning={self.total_morning}, frozen={self.is_frozen}")
        else:
            # Check if we're past morning phase
            now = datetime.now(self.tz)
            if not self.is_morning_phase(now):
                self.is_frozen = True
                logger.info("Past morning phase, state frozen")
    
    def is_morning_phase(self, now: Optional[datetime] = None) -> bool:
        """Check if current time is in morning phase."""
        if now is None:
            now = datetime.now(self.tz)
        
        from datetime import time as dt_time
        current_time = now.time()
        morning_start_time = dt_time(self.morning_start[0], self.morning_start[1])
        morning_end_time = dt_time(self.morning_end[0], self.morning_end[1])
        
        return morning_start_time <= current_time < morning_end_time
    
    def add_morning_entry(self) -> bool:
        """
        Add entry to morning total.
        
        Returns:
            True if added, False if frozen
        """
        if self.is_frozen:
            logger.debug("Morning total is frozen, cannot add entry")
            return False
        
        if not self.is_morning_phase():
            logger.debug("Not in morning phase, cannot add entry")
            return False
        
        self.total_morning += 1
        self._save_state()
        logger.debug(f"Morning entry added: total_morning={self.total_morning}")
        return True
    
    def get_total_morning(self) -> int:
        """Get current morning total."""
        return self.total_morning
    
    def freeze(self):
        """Freeze morning total (called at 14:20)."""
        if not self.is_frozen:
            logger.info(f"Freezing total_morning: {self.total_morning}")
            self.is_frozen = True
            self._save_state()
    
    def reset(self):
        """Reset morning total (called at 00:00)."""
        logger.info("Resetting morning total")
        self.total_morning = 0
        self.is_frozen = False
        self._save_state()
    
    def _save_state(self):
        """Save state to storage."""
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        self.storage.save_daily_state(
            date=today,
            total_morning=self.total_morning,
            is_frozen=self.is_frozen,
        )

