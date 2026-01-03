"""Test email notification."""
from app.config import load_config
from app.notifier import Notifier

def test_email():
    """Test sending email."""
    config = load_config()
    
    notifier = Notifier(
        enabled=True,
        channel="email",
        email_smtp_host=config.notification.email_smtp_host,
        email_smtp_port=config.notification.email_smtp_port,
        email_from=config.notification.email_from,
        email_to=config.notification.email_to,
        email_password=config.notification.email_password,
    )
    
    test_message = """🚨 Test Alert: People Counter

This is a test email to verify email notification is working correctly.

Date: Test
Morning Total: 10
Realtime IN: 8
Missing: 2
Camera ID: camera_01
Time: Test Time

If you receive this email, your email configuration is working! ✅
"""
    
    print("Sending test email...")
    success = notifier.send(test_message)
    
    if success:
        print("SUCCESS: Email sent successfully! Check your inbox: ", config.notification.email_to)
    else:
        print("FAILED: Failed to send email. Check the logs for errors.")

if __name__ == "__main__":
    test_email()

