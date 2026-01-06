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
        self.last_email_sent_at = None  # Thời điểm gửi email cuối cùng
        
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
        
        # Lấy total_morning từ state, nếu không có thì tính từ events trong morning phase
        state = self.storage.get_daily_state(date)
        if state and state.get('total_morning') is not None:
            total_morning = state.get('total_morning', 0)
        else:
            # Calculate from events in morning phase
            if self.time_manager:
                morning_start = self.time_manager.morning_start.strftime('%H:%M')
                morning_end = self.time_manager.morning_end.strftime('%H:%M')
                total_morning = self.storage.get_total_morning_from_events(date, morning_start, morning_end)
                logger.info(f"total_morning not in state, calculated from events: {total_morning}")
            else:
                total_morning = 0
        
        # Fail-safe: Don't alert if total_morning == 0 AND no morning events exist
        if total_morning == 0:
            # Check if there are any events in morning phase
            if self.time_manager:
                morning_start = self.time_manager.morning_start.strftime('%H:%M')
                morning_end = self.time_manager.morning_end.strftime('%H:%M')
                morning_events_count = self.storage.get_total_morning_from_events(date, morning_start, morning_end)
                if morning_events_count == 0:
                    logger.debug(f"Alert check skipped: total_morning is 0 and no morning events (likely day off, camera error, or morning phase not ended yet)")
                    return
                else:
                    # Use calculated value even if it's 0 (could be IN=OUT)
                    total_morning = morning_events_count
            else:
                logger.debug(f"Alert check skipped: total_morning is 0 (likely day off, camera error, or morning phase not ended yet)")
                return
        
        # Tính realtime_count: Tổng số người hiện tại (từ tất cả events: IN - OUT)
        # Đơn giản: realtime_count = tổng IN - tổng OUT (tất cả events trong ngày)
        realtime_count = self.storage.get_current_realtime_count(date, self.camera_id)
        
        # Log values for debugging (INFO level để dễ theo dõi)
        logger.info(f"Alert check: date={date}, total_morning={total_morning}, realtime_count={realtime_count}, is_missing={self.is_missing}, missing_detected_at={self.missing_detected_at}")
        
        # Check condition: total_morning > realtime_count (people missing)
        # Thuật toán: nếu total_morning > realtime_count thì thiếu người
        # Đảm bảo gửi mail khi total_morning > realtime_count sau 1 phút
        if total_morning > realtime_count:
            # Nếu chưa phát hiện lần đầu, lưu thời điểm phát hiện
            if self.missing_detected_at is None:
                self.missing_detected_at = now
                missing_count = total_morning - realtime_count
                logger.info(f"Missing people detected: {missing_count} people (total_morning={total_morning} > realtime_count={realtime_count}). Starting 1-minute timer...")
            
            # Tính lại realtime_count để có giá trị mới nhất
            realtime_count_latest = self.storage.get_current_realtime_count(date, self.camera_id)
            missing_count = total_morning - realtime_count_latest
            
            # Kiểm tra đã qua 1 phút chưa (để gửi email lần đầu)
            elapsed_seconds = (now - self.missing_detected_at).total_seconds()
            # Gửi email lần đầu nếu: đã qua 1 phút VÀ chưa gửi email lần nào (last_email_sent_at is None)
            # Note: 60 seconds = 1 minute
            should_send_first_alert = elapsed_seconds >= 60 and self.last_email_sent_at is None
            
            # DEBUG: Log để kiểm tra
            if elapsed_seconds >= 55:  # Gần đến 1 phút
                logger.warning(f"⚠️ About to send email: elapsed={elapsed_seconds:.1f}s, missing={missing_count}, should_send={should_send_first_alert}")
            
            # Kiểm tra có cần gửi lại email định kỳ không (mỗi 30 phút)
            should_send_periodic_alert = False
            if self.last_email_sent_at is not None:
                time_since_last_email = (now - self.last_email_sent_at).total_seconds()
                if time_since_last_email >= (30 * 60):  # 30 phút = 1800 giây
                    should_send_periodic_alert = True
            
            # Log chi tiết về trạng thái gửi email
            logger.info(f"Email send check: elapsed_seconds={elapsed_seconds:.1f}, should_send_first={should_send_first_alert}, should_send_periodic={should_send_periodic_alert}, last_email_sent_at={self.last_email_sent_at}, is_missing={self.is_missing}")
            
            if should_send_first_alert or should_send_periodic_alert:
                # Gửi alert
                if should_send_first_alert:
                    self.is_missing = True
                    self._save_alert_state()
                
                # Chỉ gửi nếu missing_count > 0
                if missing_count > 0:
                    # Send alert với thông báo "Vắng X người"
                    alert_type = "Initial" if should_send_first_alert else "Periodic"
                    message = (
                        f"🚨 Alert: People Missing ({alert_type})\n\n"
                        f"Vắng {missing_count} người\n\n"
                        f"Date: {date}\n"
                        f"Morning Total: {total_morning}\n"
                        f"Realtime: {realtime_count_latest}\n"
                        f"Missing: {missing_count}\n"
                        f"Camera ID: {self.camera_id}\n"
                        f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                    )
                    
                    logger.info(f"Attempting to send alert email: type={alert_type}, enabled={self.notifier.enabled}, channel={self.notifier.channel}")
                    logger.info(f"Email config: from={self.notifier.email_from}, to={self.notifier.email_to}, smtp={self.notifier.email_smtp_host}:{self.notifier.email_smtp_port}")
                    success = self.notifier.send(message)
                    if success:
                        logger.info(f"✅ Email sent successfully: type={alert_type}, missing={missing_count} people")
                    else:
                        logger.error(f"❌ Email send FAILED: type={alert_type}, missing={missing_count} people. Check email configuration.")
                    
                    if success:
                        self.last_email_sent_at = now
                    
                    # Save alert record (to both alerts and alert_logs tables)
                    # Get realtime_in and realtime_out from state for legacy alerts table
                    state = self.storage.get_daily_state(date)
                    realtime_in = state.get('realtime_in', 0) if state else 0
                    
                    self.storage.save_alert(
                        date=date,
                        window_a_out=0,  # Not used in new logic
                        window_b_in=realtime_in,
                        difference=missing_count,
                        camera_id=self.camera_id,
                        notification_channel=self.notifier.channel if success else None,
                        notification_status="sent" if success else "failed",
                        expected_total=total_morning,  # For alert_logs table
                        current_total=realtime_count_latest,  # For alert_logs table
                    )
                    
                    logger.info(f"Alert sent ({alert_type}): total_morning={total_morning}, realtime_count={realtime_count_latest}, missing={missing_count}")
        else:
            # Enough people have returned (total_morning <= realtime_count)
            if self.missing_detected_at is not None:
                # Reset alert state
                self.missing_detected_at = None
                self.is_missing = False
                self.last_email_sent_at = None  # Reset email timer
                self._save_alert_state()
                logger.info(f"Alert reset: All people returned (total_morning={total_morning} <= realtime_count={realtime_count})")
            else:
                logger.debug(f"Alert check: No missing people (total_morning={total_morning} <= realtime_count={realtime_count})")
    
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

