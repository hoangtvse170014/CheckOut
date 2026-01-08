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
            trigger=IntervalTrigger(minutes=30, timezone=self.tz),
            id='alert_check',
        )
        logger.info("Alert check scheduled every 30 minutes")
    
    def _check_and_alert(self):
        """Check missing periods and send alerts if needed."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        current_phase = self.time_manager.get_current_phase()
        
        # Only check during monitoring phases (not lunch, not morning count)
        if current_phase not in [Phase.REALTIME_MORNING, Phase.AFTERNOON_MONITORING]:
            logger.debug(f"Alert check skipped: Not in monitoring phase (current phase: {current_phase.value})")
            return
        
        # Get current session
        session = self.time_manager.get_current_session(now)
        if not session:
            return
        
        # Get active missing period duration
        duration_minutes = self.phase_manager.get_active_missing_period_duration(session)
        
        if duration_minutes is None:
            # No active missing period
            return
        
        # Only send alert if duration >= 30 minutes
        if duration_minutes < 30:
            logger.debug(f"Missing period active but duration < 30 minutes: session={session}, duration={duration_minutes}")
            return
        
        # Check if alert already sent for this missing period
        active_period = self.storage.get_active_missing_period(date_str, session)
        if not active_period:
            return
        
        # Check last alert time - if sent within last 30 minutes, skip (to avoid spam)
        # Otherwise, send again (recurring alerts every 30 minutes)
        last_alert_time = self.storage.get_last_alert_time(date_str, session)
        if last_alert_time:
            # Ensure timezone-aware comparison
            if last_alert_time.tzinfo is None:
                last_alert_time = self.tz.localize(last_alert_time)
            if now.tzinfo is None:
                now = self.tz.localize(now)
            
            time_since_last_alert = (now - last_alert_time).total_seconds() / 60  # minutes
            if time_since_last_alert < 30:
                logger.debug(f"Alert sent recently ({time_since_last_alert:.1f} min ago), skipping to avoid spam: session={session}, duration={duration_minutes}min")
                return
            else:
                logger.info(f"Last alert was {time_since_last_alert:.1f} min ago, sending recurring alert: session={session}, duration={duration_minutes}min")
        else:
            # No previous alert - this is the first alert (still needs to be >= 30 min duration)
            if not active_period['alert_sent']:
                logger.info(f"First alert for missing period: session={session}, duration={duration_minutes}min")
            else:
                # alert_sent is True but no alert_logs record - send anyway if duration >= 30
                logger.info(f"Missing period has alert_sent=True but no alert_logs record, sending alert: session={session}, duration={duration_minutes}min")
        
        # If alert_sent is True but last alert was > 30 min ago, we'll send again
        # This allows recurring alerts every 30 minutes
        
        # Send alert
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
        missing_count = total_morning - realtime_count
        
        if missing_count <= 0:
            logger.debug(f"Missing count <= 0, skipping alert: session={session}")
            return
        
        # Format message
        phase_name = "Morning" if session == "morning" else "Afternoon"
        message = (
            f"🚨 Alert: People Missing ({phase_name} Session)\n\n"
            f"Date: {date_str}\n"
            f"Phase: {phase_name}\n"
            f"Missing Start Time: {active_period['start_time']}\n"
            f"Duration: {duration_minutes} minutes\n"
            f"Current Missing Count: {missing_count} people\n"
            f"Total Morning: {total_morning}\n"
            f"Current Realtime: {realtime_count}\n"
            f"Camera ID: {self.camera_id}\n"
            f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        
        logger.info(f"Attempting to send alert email: session={session}, duration={duration_minutes}min, missing={missing_count}")
        logger.info(f"Email config: enabled={self.notifier.enabled}, channel={self.notifier.channel}")
        
        if not self.notifier.enabled:
            logger.warning("Notifications are disabled, skipping email send")
            return
        
        success = self.notifier.send(message)
        
        if success:
            logger.info(f"✅ Email sent successfully: session={session}, duration={duration_minutes}min, missing={missing_count}")
            
            # Mark alert as sent in missing_periods table (for first alert only)
            # We don't reset this to allow recurring alerts
            if not active_period['alert_sent']:
                self.storage.mark_missing_period_alert_sent(active_period['id'])
            
            # Save alert record to alert_logs table (always save for recurring alerts)
            self.storage.save_alert(
                date=date_str,
                window_a_out=0,  # Not used in new logic
                window_b_in=0,  # Not used in new logic
                difference=missing_count,
                camera_id=self.camera_id,
                notification_channel=self.notifier.channel,
                notification_status="sent",
                expected_total=total_morning,
                current_total=realtime_count,
            )
            
            # Update alert_logs with phase information
            conn = self.storage._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE alert_logs
                    SET phase = ?
                    WHERE id = (SELECT MAX(id) FROM alert_logs)
                """, (session,))
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to update alert_logs phase: {e}")
                conn.rollback()
            finally:
                conn.close()
        else:
            logger.error(f"❌ Email send FAILED: session={session}, duration={duration_minutes}min, missing={missing_count}")
    
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
    
    def force_check_and_alert(self):
        """
        Force check and send alert immediately (can be called externally).
        Useful for manual trigger or testing.
        """
        logger.info("Force checking and sending alert...")
        self._check_and_alert()
