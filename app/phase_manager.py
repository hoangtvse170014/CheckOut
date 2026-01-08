"""Phase manager - tracks missing periods and state transitions every 1 minute."""

import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.storage import Storage
from app.time_manager import TimeManager, Phase

logger = logging.getLogger(__name__)


class PhaseManager:
    """Manages phase transitions and missing period tracking."""
    
    def __init__(
        self,
        storage: Storage,
        time_manager: TimeManager,
        camera_id: str,
        timezone: str = "Asia/Ho_Chi_Minh",
    ):
        """
        Initialize phase manager.
        
        Args:
            storage: Storage instance
            time_manager: TimeManager instance
            camera_id: Camera identifier
            timezone: Timezone string
        """
        self.storage = storage
        self.time_manager = time_manager
        self.camera_id = camera_id
        self.tz = pytz.timezone(timezone)
        
        # Track active missing periods per session
        self.active_missing_periods = {}  # session -> period_id
        
        # Scheduler for periodic checks (every 1 minute)
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._schedule_phase_check()
        
        logger.info("PhaseManager initialized")
    
    def _schedule_phase_check(self):
        """Schedule periodic phase check (every 1 minute)."""
        self.scheduler.add_job(
            self._check_phase_and_missing,
            trigger=IntervalTrigger(minutes=1, timezone=self.tz),
            id='phase_check',
        )
        logger.info("Phase check scheduled every 1 minute")
    
    def _check_phase_and_missing(self):
        """Check current phase and track missing periods."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        current_phase = self.time_manager.get_current_phase()
        
        # Only check missing during monitoring phases (not lunch, not morning count)
        if current_phase not in [Phase.REALTIME_MORNING, Phase.AFTERNOON_MONITORING]:
            # Close any active missing periods if we're not in monitoring phase
            for session in list(self.active_missing_periods.keys()):
                period_id = self.active_missing_periods[session]
                self.storage.close_missing_period(period_id, now)
                del self.active_missing_periods[session]
                logger.info(f"Closed missing period for session {session} (entered non-monitoring phase)")
            return
        
        # Get current session
        session = self.time_manager.get_current_session(now)
        if not session:
            return
        
        # Get total_morning and realtime_count
        state = self.storage.get_daily_state(date_str)
        if state and state.get('total_morning') is not None:
            total_morning = state.get('total_morning', 0)
        else:
            # Calculate from events
            morning_start = self.time_manager.morning_start.strftime('%H:%M')
            morning_end = self.time_manager.morning_end.strftime('%H:%M')
            total_morning = self.storage.get_total_morning_from_events(date_str, morning_start, morning_end)
        
        realtime_count = self.storage.get_current_realtime_count(date_str, self.camera_id)
        # Ensure realtime_count is never negative
        realtime_count = max(0, realtime_count)
        
        # Check if missing: missing = total_morning - realtime
        missing_count = total_morning - realtime_count
        is_missing = missing_count > 0
        
        if is_missing:
            # Check if we already have an active missing period for this session
            if session not in self.active_missing_periods:
                # Start new missing period
                period_id = self.storage.create_missing_period(now, session)
                self.active_missing_periods[session] = period_id
                logger.info(f"Missing period started: session={session}, period_id={period_id}, missing={total_morning - realtime_count}")
            else:
                # Update existing period (check duration for alert)
                period_id = self.active_missing_periods[session]
                active_period = self.storage.get_active_missing_period(date_str, session)
                if active_period:
                    start_time = datetime.fromisoformat(active_period['start_time'].replace('Z', '+00:00'))
                    if start_time.tzinfo is None:
                        start_time = self.tz.localize(start_time)
                    
                    duration_minutes = int((now - start_time).total_seconds() / 60)
                    logger.debug(f"Missing period active: session={session}, duration={duration_minutes} minutes")
        else:
            # No missing - close active period if exists
            if session in self.active_missing_periods:
                period_id = self.active_missing_periods[session]
                self.storage.close_missing_period(period_id, now)
                del self.active_missing_periods[session]
                logger.info(f"Missing period closed: session={session}, period_id={period_id}")
    
    def get_active_missing_period_duration(self, session: str) -> Optional[int]:
        """
        Get duration in minutes of active missing period for a session.
        
        Args:
            session: 'morning' or 'afternoon'
        
        Returns:
            Duration in minutes or None if no active period
        """
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        active_period = self.storage.get_active_missing_period(date_str, session)
        
        if not active_period:
            # Check if there's a missing period in database even if not in active_missing_periods
            # This handles the case where app restarted but missing period still exists
            return None
        
        start_time = datetime.fromisoformat(active_period['start_time'].replace('Z', '+00:00'))
        if start_time.tzinfo is None:
            start_time = self.tz.localize(start_time)
        
        duration_minutes = int((now - start_time).total_seconds() / 60)
        return duration_minutes
    
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("PhaseManager scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("PhaseManager scheduler stopped")
    
    def reset(self):
        """Reset state (called at daily reset)."""
        logger.info("Resetting PhaseManager state")
        self.active_missing_periods = {}

