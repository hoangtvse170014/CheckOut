"""Notification system (Telegram, Email, Webhook)."""

import logging
from typing import Optional
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


class Notifier:
    """Notification handler."""
    
    def __init__(
        self,
        enabled: bool = False,
        channel: str = "telegram",
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        email_smtp_host: str = "smtp.gmail.com",
        email_smtp_port: int = 587,
        email_from: str = "",
        email_to: str = "",
        email_password: str = "",
        webhook_url: str = "",
    ):
        """
        Initialize notifier.
        
        Args:
            enabled: Enable notifications
            channel: 'telegram', 'email', or 'webhook'
            telegram_bot_token: Telegram bot token
            telegram_chat_id: Telegram chat ID
            email_smtp_host: SMTP host
            email_smtp_port: SMTP port
            email_from: Email sender
            email_to: Email recipient
            email_password: Email password
            webhook_url: Webhook URL
        """
        self.enabled = enabled
        self.channel = channel.lower()
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.email_smtp_host = email_smtp_host
        self.email_smtp_port = email_smtp_port
        self.email_from = email_from
        self.email_to = email_to
        self.email_password = email_password
        self.webhook_url = webhook_url
        
        if not enabled:
            logger.info("Notifications disabled")
        else:
            logger.info(f"Notifier initialized: channel={channel}")
    
    def send(self, message: str) -> bool:
        """
        Send notification.
        
        Args:
            message: Message to send
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.debug("Notifications disabled, skipping")
            return False
        
        try:
            if self.channel == "telegram":
                return self._send_telegram(message)
            elif self.channel == "email":
                return self._send_email(message)
            elif self.channel == "webhook":
                return self._send_webhook(message)
            else:
                logger.error(f"Unknown notification channel: {self.channel}")
                return False
        except Exception as e:
            logger.error(f"Error sending notification: {e}", exc_info=True)
            return False
    
    def _send_telegram(self, message: str) -> bool:
        """Send Telegram message."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials not configured")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            
            logger.info("Telegram notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
    
    def _send_email(self, message: str) -> bool:
        """Send email."""
        if not self.email_from or not self.email_to or not self.email_password:
            logger.warning("Email credentials not configured")
            return False
        
        try:
            msg = MIMEMultipart()
            msg["From"] = self.email_from
            msg["To"] = self.email_to
            msg["Subject"] = "People Counter Alert"
            
            msg.attach(MIMEText(message, "plain"))
            
            with smtplib.SMTP(self.email_smtp_host, self.email_smtp_port) as server:
                server.starttls()
                server.login(self.email_from, self.email_password)
                server.send_message(msg)
            
            logger.info("Email notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False
    
    def _send_webhook(self, message: str) -> bool:
        """Send webhook POST request."""
        if not self.webhook_url:
            logger.warning("Webhook URL not configured")
            return False
        
        try:
            payload = {
                "message": message,
                "timestamp": str(logging.Formatter().formatTime(logging.LogRecord(
                    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
                ))),
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            
            logger.info("Webhook notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            return False

