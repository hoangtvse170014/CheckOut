"""Alert manager with periodic checking (30-minute interval)."""

import logging
from datetime import datetime
from typing import Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.storage import Storage
from app.notifier import Notifier
from app.time_manager import Phase

logger = logging.getLogger(__name__)


class AlertManager:
    """Manages alert checking with periodic timer."""
    
    def __init__(
        self,
        storage: Storage,
        notifier: Notifier,
        time_manager,
        morning_total_manager,
        camera_id: str,
        timezone: str = "Asia/Bangkok",
        alert_interval_min: int = 30,
    ):
        """
        Initialize alert manager.
        
        Args:
            storage: Storage instance
            notifier: Notifier instance
            time_manager: TimeManager instance
            morning_total_manager: MorningTotalManager instance
            camera_id: Camera identifier
            timezone: Timezone string
            alert_interval_min: Alert check interval in minutes
        """
        self.storage = storage
        self.notifier = notifier
        self.time_manager = time_manager
        self.morning_total_manager = morning_total_manager
        self.camera_id = camera_id
        self.tz = pytz.timezone(timezone)
        self.alert_interval_min = alert_interval_min
        
        # Alert state
        self.is_missing = False
        self.missing_detected_at = None  # Thời điểm phát hiện thiếu người lần đầu
        
        # Load alert state
        self._load_alert_state()
        
        # Scheduler for periodic checks
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._schedule_alert_check()
        
        logger.info(
            f"AlertManager initialized: interval={alert_interval_min}min, "
            f"is_missing={self.is_missing}"
        )
    
    def _load_alert_state(self):
        """Load alert state from storage."""
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        state = self.storage.get_daily_state(today)
        
        if state:
            self.is_missing = state.get('is_missing', False)
            logger.debug(f"Loaded alert state: is_missing={self.is_missing}")
    
    def _schedule_alert_check(self):
        """Schedule periodic alert check (check every 10 seconds to detect 1-minute threshold accurately)."""
        self.scheduler.add_job(
            self._check_and_alert,
            trigger=IntervalTrigger(seconds=10, timezone=self.tz),  # Check every 10 seconds
            id='alert_check',
        )
        logger.info(f"Alert check scheduled every 10 seconds (alert sent after 1 minute of detection)")
    
    def _check_and_alert(self, date: Optional[str] = None, total_morning: Optional[int] = None, realtime_in: Optional[int] = None, now: Optional[datetime] = None):
        """
        Check condition and send alert if needed.
        
        Args:
            date: Date string (YYYY-MM-DD), if None uses today
            total_morning: Morning total, if None gets from manager
            realtime_in: Realtime IN count, if None gets from storage
            now: Current datetime, if None uses now
        """
        if now is None:
            now = datetime.now(self.tz)
        
        if date is None:
            date = now.strftime("%Y-%m-%d")
        
        # Check conditions
        phase = self.time_manager.get_current_phase()
        
        # Only check in REALTIME_MONITORING phase
        if phase != Phase.REALTIME_MONITORING:
            logger.info(f"Alert check skipped: Not in REALTIME_MONITORING phase (current phase: {phase.value})")
            return
        
        # Lấy total_morning, realtime_in và realtime_out từ state (đã được lưu từ logic đếm ban đầu)
        state = self.storage.get_daily_state(date)
        if state:
            total_morning = state.get('total_morning', 0)
            realtime_in = state.get('realtime_in', 0)
            realtime_out = state.get('realtime_out', 0)
        else:
            total_morning = 0
            realtime_in = 0
            realtime_out = 0
        
        # Fail-safe: Don't alert if total_morning == 0
        if total_morning == 0:
            logger.info(f"Alert check skipped: total_morning is 0 (likely day off or camera error), realtime_in={realtime_in}, realtime_out={realtime_out}")
            return
        
        # Tính realtime_count (total realtime) = total_morning + (realtime_in - realtime_out)
        # Theo logic trong main.py: realtime_count = initial_total + (realtime_in - realtime_out)
        # Trong đó initial_total = initial_count_in - initial_count_out = total_morning
        # Vậy realtime_count = total_morning + (realtime_in - realtime_out)
        realtime_count = total_morning + (realtime_in - realtime_out)
        
        # Log values for debugging (INFO level để dễ theo dõi)
        logger.info(f"Alert check: date={date}, total_morning={total_morning}, realtime_in={realtime_in}, realtime_out={realtime_out}, realtime_count={realtime_count}, is_missing={self.is_missing}, missing_detected_at={self.missing_detected_at}")
        
        # Check condition: realtime_count < total_morning (people missing)
        # Điều kiện này đúng khi số người hiện tại < số người buổi sáng
        if realtime_count < total_morning:
            # Nếu chưa phát hiện lần đầu, lưu thời điểm phát hiện
            if self.missing_detected_at is None:
                self.missing_detected_at = now
                initial_missing = total_morning - realtime_count
                logger.info(f"Missing people detected: {initial_missing} people. Starting 1-minute timer...")
            
            # Kiểm tra đã qua 1 phút chưa
            elapsed_seconds = (now - self.missing_detected_at).total_seconds()
            if elapsed_seconds >= 60:  # 1 phút = 60 giây
                if not self.is_missing:
                    # Gửi alert sau 1 phút
                    self.is_missing = True
                    self._save_alert_state()
                    
                    # Tính số người vắng = total_morning - realtime_count (tính lại với giá trị mới nhất)
                    realtime_count_latest = total_morning + (realtime_in - realtime_out)
                    missing_count = total_morning - realtime_count_latest
                    
                    # Send alert với thông báo "Vắng X người"
                    message = (
                        f"🚨 Alert: People Missing\n\n"
                        f"Vắng {missing_count} người\n\n"
                        f"Date: {date}\n"
                        f"Morning Total: {total_morning}\n"
                        f"Realtime: {realtime_count_latest}\n"
                        f"Missing: {missing_count}\n"
                        f"Camera ID: {self.camera_id}\n"
                        f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                    )
                    
                    logger.info(f"Attempting to send alert email: enabled={self.notifier.enabled}, channel={self.notifier.channel}")
                    success = self.notifier.send(message)
                    logger.info(f"Email send result: success={success}")
                    
                    # Save alert record
                    self.storage.save_alert(
                        date=date,
                        window_a_out=0,  # Not used in new logic
                        window_b_in=realtime_in,
                        difference=missing_count,
                        camera_id=self.camera_id,
                        notification_channel=self.notifier.channel if success else None,
                        notification_status="sent" if success else "failed",
                    )
                    
                    logger.info(f"Alert sent after 1 minute: total_morning={total_morning}, realtime_count={realtime_count_latest}, missing={missing_count}")
        else:
            # Enough people have returned (realtime_count >= total_morning)
            if self.missing_detected_at is not None:
                # Reset alert state
                self.missing_detected_at = None
                self.is_missing = False
                self._save_alert_state()
                logger.info(f"Alert reset: All people returned (total_morning={total_morning}, realtime_count={realtime_count})")
            else:
                logger.info(f"Alert check: No missing people (total_morning={total_morning}, realtime_count={realtime_count})")
    
    def _save_alert_state(self):
        """Save alert state to storage."""
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        self.storage.save_daily_state(
            date=today,
            is_missing=self.is_missing,
        )
    
    def reset(self):
        """Reset alert state (called at 00:00)."""
        logger.info("Resetting alert state")
        self.is_missing = False
        self.missing_detected_at = None
        self._save_alert_state()
    
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("AlertManager scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("AlertManager scheduler stopped")

