"""Alert manager - sends email alerts when missing period >= 30 minutes, and recurring every 30 minutes."""

import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.storage import Storage
from app.notifier import Notifier
from app.time_manager import TimeManager, Phase
from app.phase_manager import PhaseManager

logger = logging.getLogger(__name__)


class AlertManager:
    """Manages email alerts for missing periods (>= 30 minutes)."""
    
    def __init__(
        self,
        config,
        storage: Storage,
        notifier: Notifier,
        time_manager: TimeManager,
        phase_manager: PhaseManager,
        camera_id: str,
        timezone: str = "Asia/Ho_Chi_Minh",
    ):
        """
        Initialize alert manager.
        
        Args:
            config: Application config
            storage: Storage instance
            notifier: Notifier instance
            time_manager: TimeManager instance
            phase_manager: PhaseManager instance
            camera_id: Camera identifier
            timezone: Timezone string
        """
        self.config = config
        self.storage = storage
        self.notifier = notifier
        self.time_manager = time_manager
        self.phase_manager = phase_manager
        self.camera_id = camera_id
        self.tz = pytz.timezone(timezone)
        
        # Scheduler for periodic checks (every 30 minutes as per requirements)
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._schedule_alert_check()
        
        logger.info("AlertManager initialized")
    
    def _schedule_alert_check(self):
        """Schedule periodic alert check (every 30 minutes as per requirements)."""
        self.scheduler.add_job(
            self._check_and_alert,
            trigger=IntervalTrigger(minutes=30, timezone=self.tz),  # Check every 30 minutes
            id='alert_check',
        )
        logger.info("Alert check scheduled every 30 minutes")
    
    def _check_and_alert(self):
        """Check missing periods and send alerts if needed (every 30 minutes)."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        current_time = now.time()

        print(f"[ALERT_CHECK] Running: time={now.strftime('%H:%M:%S')}")
        logger.info(f"🔔 Alert check running: time={now.strftime('%H:%M:%S')}")

        # PAUSE ALERTS DURING LUNCH BREAK (11:55 - 13:15)
        lunch_start = datetime.strptime("11:55", "%H:%M").time()
        lunch_end = datetime.strptime("13:15", "%H:%M").time()

        if lunch_start <= current_time <= lunch_end:
            print(f"[ALERT_CHECK] Skipped: Lunch break pause (11:55-13:15)")
            logger.debug(f"Alert check skipped: Lunch break pause")
            return

        # Get current session
        session = self.time_manager.get_current_session(now)
        if not session:
            print(f"[ALERT_CHECK] Skipped: No session for time {now.strftime('%H:%M:%S')}")
            logger.debug(f"Alert check skipped: No session for time {now.strftime('%H:%M:%S')}")
            return

        print(f"[ALERT_CHECK] Session: {session}")
        logger.debug(f"Alert check: session={session}")

        # Get active missing period
        active_period = self.storage.get_active_missing_period(date_str, session)
        if not active_period:
            print(f"[ALERT_CHECK] No active missing period for session={session}")
            logger.debug(f"Alert check: No active missing period for session={session}")
            return

        # Calculate duration
        start_time = datetime.fromisoformat(active_period['start_time'].replace('Z', '+00:00'))
        duration_minutes = (now - start_time).total_seconds() / 60

        print(f"[ALERT_CHECK] Active missing period: session={session}, duration={duration_minutes:.1f} minutes")
        logger.info(f"Alert check: Active missing period found: session={session}, duration={duration_minutes:.1f} minutes")
        
        # Get current missing count
        state = self.storage.get_daily_state(date_str)
        morning_start = self.time_manager.morning_start.strftime('%H:%M')
        morning_end = self.time_manager.morning_end.strftime('%H:%M')

        # Calculate TOTAL_MORNING
        total_morning = self.storage.get_total_morning_from_events(date_str, morning_start, morning_end)
        if state and state.get('total_morning') is not None and state.get('is_frozen') and state.get('total_morning', 0) > 0:
            total_morning = state.get('total_morning', 0)

        # Calculate REALTIME_PRESENT
        realtime_count = self.storage.get_current_realtime_count(date_str, self.camera_id)
        realtime_count = max(0, realtime_count)

        # Calculate MISSING = TOTAL_MORNING - REALTIME_PRESENT
        missing_count = total_morning - realtime_count
        missing_count = max(0, missing_count)

        print(f"[ALERT_CHECK] TOTAL_MORNING={total_morning}, REALTIME_PRESENT={realtime_count}, MISSING={missing_count}")
        logger.info(f"Alert check: TOTAL_MORNING={total_morning}, REALTIME_PRESENT={realtime_count}, MISSING={missing_count}")

        # RULE: Chỉ gửi email mỗi 30 phút một lần khi MISSING > 0
        # Check if already alerted in the last 30 minutes
        last_alert_time = self.storage.get_last_alert_time(date_str, session)

        if last_alert_time:
            time_since_last_alert = (now - last_alert_time).total_seconds() / 60  # minutes
            if time_since_last_alert < 30.0:
                remaining_minutes = 30.0 - time_since_last_alert
                print(f"[ALERT_CHECK] Alert sent {time_since_last_alert:.1f} min ago, waiting {remaining_minutes:.1f} min, MISSING={missing_count}")
                logger.debug(f"Alert cooldown active: {time_since_last_alert:.1f} min ago, skipping")
                return

        # RULE: Send email ONLY IF MISSING > 0 (no minimum duration required)
        if missing_count <= 0:
            print(f"[ALERT_CHECK] No missing people (MISSING={missing_count}), skipping alert")
            logger.debug(f"No missing people, skipping alert: MISSING={missing_count}")
            return
        
        # RULE: Send email ONLY IF missing lasts >= 30 minutes AND not alerted before for this period
        print(f"[ALERT_CHECK] Sending alert: MISSING={missing_count} for {duration_minutes:.1f} minutes")

        # Create alert message with required content
        subject = f"Alert: Staff Missing - {session.title()} Session"
        message = f"""
🚨 STAFF MISSING ALERT

Date: {date_str}
Time: {now.strftime('%H:%M:%S')}

TOTAL_MORNING: {total_morning}
REALTIME_PRESENT: {realtime_count}
MISSING: {missing_count}

Missing duration: {duration_minutes:.1f} minutes

Please check the area and ensure staff safety.

Camera ID: {self.camera_id}
"""

        # Send notification (non-blocking)
        success = self.notifier.send(message)

        if success:
            print(f"[ALERT_CHECK] ✅ Email sent successfully: MISSING={missing_count}")
            logger.info(f"✅ Alert email sent: session={session}, missing={missing_count}, duration={duration_minutes:.1f} min")

            # Mark missing period as alerted
            self._mark_missing_period_alerted(active_period['id'])

            # Log the alert to database
            self._log_alert(session, duration_minutes, missing_count, "scheduled_30min")
        else:
            print(f"[ALERT_CHECK] ❌ Email send failed: MISSING={missing_count}")
            
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("AlertManager scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("AlertManager scheduler stopped")
    
    def reset(self):
        """Reset alert state (called at daily reset)."""
        logger.info("Resetting AlertManager state")
    
    def trigger_immediate_alert(self, session: str = None, total_morning: int = None, realtime_count: int = None):
        """
        Trigger alert immediately when missing people are detected.
        Bypasses time-based conditions and sends alert right away.

        Args:
            session: Session to check ('morning' or 'afternoon'). If None, uses current session.
            total_morning: Total morning count (optional, will calculate if not provided)
            realtime_count: Current realtime count (optional, will calculate if not provided)
        """
        try:
            if session is None:
                session = self.time_manager.get_current_session()

            # Get current missing count - use provided values or calculate
            if total_morning is None:
                # Calculate total_morning from events for today
                today = datetime.now(self.tz).strftime("%Y-%m-%d")
                morning_start = self.config.production.morning_start
                morning_end = self.config.production.morning_end
                total_morning = self.storage.get_total_morning_from_events(today, morning_start, morning_end)

            if realtime_count is None:
                realtime_count = self.storage.get_current_realtime_count()

            if total_morning <= 0:
                logger.debug("No total_morning data available, skipping immediate alert")
                return

            missing_count = total_morning - realtime_count
            if missing_count <= 0:
                logger.debug(f"No missing people (missing_count={missing_count}), skipping immediate alert")
                return

            # Check if we have an active missing period
            today = datetime.now(self.tz).strftime("%Y-%m-%d")
            active_period = self.storage.get_active_missing_period(today, session)
            if not active_period:
                logger.debug(f"No active missing period for session {session}, skipping immediate alert")
                return

            # Calculate duration
            now = datetime.now(self.tz)
            start_time = active_period['start_time']
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            duration_minutes = (now - start_time).total_seconds() / 60

            # Send immediate alert
            logger.info(f"🚨 IMMEDIATE ALERT: Triggering alert for missing people - session={session}, missing={missing_count}, duration={duration_minutes:.1f}min")

            # Create alert message
            subject = f"Alert: People Missing ({session.title()} Session)"
            message = f"""
🚨 ALERT: People Missing - {session.title()} Session

Missing Count: {missing_count} people
Duration: {duration_minutes:.1f} minutes
Total Morning: {total_morning}
Current Count: {realtime_count}

This alert was triggered immediately upon detection.
Please check the area and ensure safety.

Camera ID: {self.camera_id}
Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}
"""

            # Send notification
            success = self.notifier.send(message)

            if success:
                logger.info(f"✅ IMMEDIATE ALERT sent successfully: session={session}, missing={missing_count}")
                # Log the alert
                self._log_alert(session, duration_minutes, missing_count, "immediate")
            else:
                logger.error(f"❌ IMMEDIATE ALERT failed: session={session}, missing={missing_count}")

        except Exception as e:
            logger.error(f"Failed to trigger immediate alert: {e}", exc_info=True)

    def force_check_and_alert(self):
        """
        Force check and send alert immediately (can be called externally).
        Useful for manual trigger or testing.
        """
        logger.info("Force checking and sending alert...")
        self._check_and_alert()
