"""Scheduler for time windows and alerts."""

import logging
from datetime import datetime, time as dt_time
from typing import Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.storage import Storage
from app.notifier import Notifier

logger = logging.getLogger(__name__)


class WindowScheduler:
    """Scheduler for time windows and alert checking."""
    
    def __init__(
        self,
        storage: Storage,
        notifier: Notifier,
        camera_id: str,
        timezone: str = "Asia/Bangkok",
        window_a_start: str = "12:00",
        window_a_end: str = "12:59",
        window_b_start: str = "13:00",
        window_b_end: str = "13:59",
    ):
        """
        Initialize scheduler.
        
        Args:
            storage: Storage instance
            notifier: Notifier instance
            camera_id: Camera identifier
            timezone: Timezone string
            window_a_start: Window A start time (HH:MM)
            window_a_end: Window A end time (HH:MM)
            window_b_start: Window B start time (HH:MM)
            window_b_end: Window B end time (HH:MM)
        """
        self.storage = storage
        self.notifier = notifier
        self.camera_id = camera_id
        self.tz = pytz.timezone(timezone)
        
        # Parse window times
        self.window_a_start = self._parse_time(window_a_start)
        self.window_a_end = self._parse_time(window_a_end)
        self.window_b_start = self._parse_time(window_b_start)
        self.window_b_end = self._parse_time(window_b_end)
        
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        
        # Schedule aggregation at end of each window
        self._schedule_aggregations()
        
        # Schedule alert check after window B ends
        self._schedule_alert_check()
        
        logger.info(
            f"Scheduler initialized: Window A={window_a_start}-{window_a_end}, "
            f"Window B={window_b_start}-{window_b_end}, timezone={timezone}"
        )
    
    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string (HH:MM) to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    
    def _schedule_aggregations(self):
        """Schedule aggregation tasks."""
        # Aggregate window A at end of window A (minute 59)
        hour_a = self.window_a_end.hour
        self.scheduler.add_job(
            self._aggregate_window_a,
            trigger=CronTrigger(hour=hour_a, minute=59, timezone=self.tz),
            id='aggregate_window_a',
        )
        
        # Aggregate window B at end of window B (minute 59)
        hour_b = self.window_b_end.hour
        self.scheduler.add_job(
            self._aggregate_window_b,
            trigger=CronTrigger(hour=hour_b, minute=59, timezone=self.tz),
            id='aggregate_window_b',
        )
        
        logger.info("Aggregation jobs scheduled")
    
    def _schedule_alert_check(self):
        """Schedule alert check after window B ends."""
        hour_b = self.window_b_end.hour
        minute_b = self.window_b_end.minute
        
        # Check alert 1 minute after window B ends
        check_minute = (minute_b + 1) % 60
        check_hour = hour_b if minute_b < 59 else (hour_b + 1) % 24
        
        self.scheduler.add_job(
            self._check_and_send_alert,
            trigger=CronTrigger(hour=check_hour, minute=check_minute, timezone=self.tz),
            id='check_alert',
        )
        
        logger.info(f"Alert check scheduled at {check_hour:02d}:{check_minute:02d}")
    
    def _aggregate_window_a(self):
        """Aggregate window A data."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        
        # Get window start and end for today
        window_start = self.tz.localize(
            datetime.combine(now.date(), self.window_a_start)
        )
        window_end = self.tz.localize(
            datetime.combine(now.date(), self.window_a_end)
        )
        
        count_in, count_out = self.storage.get_events_in_window(
            window_start, window_end, self.camera_id
        )
        
        self.storage.save_aggregation(
            date=date_str,
            window_type="A",
            window_start=self.window_a_start.strftime("%H:%M"),
            window_end=self.window_a_end.strftime("%H:%M"),
            count_in=count_in,
            count_out=count_out,
            camera_id=self.camera_id,
        )
        
        logger.info(f"Window A aggregated: OUT={count_out}, IN={count_in}")
    
    def _aggregate_window_b(self):
        """Aggregate window B data."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        
        # Get window start and end for today
        window_start = self.tz.localize(
            datetime.combine(now.date(), self.window_b_start)
        )
        window_end = self.tz.localize(
            datetime.combine(now.date(), self.window_b_end)
        )
        
        count_in, count_out = self.storage.get_events_in_window(
            window_start, window_end, self.camera_id
        )
        
        self.storage.save_aggregation(
            date=date_str,
            window_type="B",
            window_start=self.window_b_start.strftime("%H:%M"),
            window_end=self.window_b_end.strftime("%H:%M"),
            count_in=count_in,
            count_out=count_out,
            camera_id=self.camera_id,
        )
        
        logger.info(f"Window B aggregated: OUT={count_out}, IN={count_in}")
    
    def _check_and_send_alert(self):
        """Check condition and send alert if needed."""
        now = datetime.now(self.tz)
        date_str = now.strftime("%Y-%m-%d")
        
        # Get aggregations
        agg_a = self.storage.get_aggregation(date_str, "A", self.camera_id)
        agg_b = self.storage.get_aggregation(date_str, "B", self.camera_id)
        
        if not agg_a or not agg_b:
            logger.warning(f"Incomplete aggregations for {date_str}, skipping alert check")
            return
        
        count_in_a, count_out_a = agg_a
        count_in_b, count_out_b = agg_b
        
        # Check condition: OUT_A > IN_B
        if count_out_a > count_in_b:
            difference = count_out_a - count_in_b
            
            # Send notification
            message = (
                f"🚨 Alert: People Count Discrepancy\n\n"
                f"Date: {date_str}\n"
                f"Window A (OUT): {count_out_a}\n"
                f"Window B (IN): {count_in_b}\n"
                f"Difference: {difference}\n"
                f"Camera ID: {self.camera_id}\n"
                f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            
            success = self.notifier.send(message)
            
            # Save alert record
            self.storage.save_alert(
                date=date_str,
                window_a_out=count_out_a,
                window_b_in=count_in_b,
                difference=difference,
                camera_id=self.camera_id,
                notification_channel=self.notifier.channel if success else None,
                notification_status="sent" if success else "failed",
            )
            
            logger.info(f"Alert sent: OUT_A={count_out_a} > IN_B={count_in_b}, diff={difference}")
        else:
            logger.debug(f"No alert needed: OUT_A={count_out_a} <= IN_B={count_in_b}")
    
    def start(self):
        """Start scheduler."""
        self.scheduler.start()
        logger.info("Scheduler started")
    
    def stop(self):
        """Stop scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")
    
    def trigger_manual_check(self):
        """Manually trigger alert check (for testing)."""
        self._check_and_send_alert()

