"""Fix missing period start_time to be from afternoon session start (13:00)."""

import sqlite3
from datetime import datetime
import pytz
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import load_config

print("=" * 70)
print("SUA MISSING PERIOD START_TIME VE 13:00 (BAT DAU AFTERNOON SESSION)")
print("=" * 70)

tz = pytz.timezone("Asia/Ho_Chi_Minh")
today = datetime.now(tz).strftime('%Y-%m-%d')
now = datetime.now(tz)

config = load_config()
conn = sqlite3.connect(config.db_path)
cursor = conn.cursor()

# Get afternoon start time (13:00 today)
afternoon_start = now.replace(hour=13, minute=0, second=0, microsecond=0)

print(f"\nCurrent time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Afternoon session start: {afternoon_start.strftime('%Y-%m-%d %H:%M:%S')}")

# Close any existing active periods for afternoon session
print(f"\n[1] Closing existing active periods for afternoon session...")
cursor.execute("""
    UPDATE missing_periods
    SET end_time = ?,
        duration_minutes = CAST((julianday(?) - julianday(start_time)) * 1440 AS INTEGER)
    WHERE substr(start_time, 1, 10) = ?
      AND session = 'afternoon'
      AND end_time IS NULL
""", (now.isoformat(), now.isoformat(), today))

closed_count = cursor.rowcount
conn.commit()
print(f"   - Closed {closed_count} active period(s)")

# Create new missing period with start_time from 13:00
print(f"\n[2] Creating new missing period with start_time from 13:00...")
cursor.execute("""
    INSERT INTO missing_periods (start_time, session, alert_sent)
    VALUES (?, 'afternoon', 0)
""", (afternoon_start.isoformat(),))

period_id = cursor.lastrowid
conn.commit()
print(f"   - Created missing period: ID={period_id}")
print(f"   - Start time: {afternoon_start.isoformat()}")

# Calculate duration
duration_minutes = (now - afternoon_start).total_seconds() / 60
print(f"   - Duration: {duration_minutes:.1f} minutes")

ALERT_TOTAL_MINUTES = 30.5
if duration_minutes >= ALERT_TOTAL_MINUTES:
    print(f"   - [OK] Du thoi gian de gui mail! (>= {ALERT_TOTAL_MINUTES} minutes)")
else:
    remaining = (ALERT_TOTAL_MINUTES - duration_minutes) * 60
    print(f"   - [INFO] Con {remaining:.0f} giay nua ({remaining/60:.1f} phut)")

# Verify
print(f"\n[3] Verifying missing period...")
cursor.execute("""
    SELECT id, start_time, end_time, session, alert_sent
    FROM missing_periods
    WHERE id = ?
""", (period_id,))

period = cursor.fetchone()
if period:
    pid, start, end, sess, alert_sent = period
    print(f"   - ID: {pid}")
    print(f"   - Start: {start}")
    print(f"   - End: {end if end else 'None (ACTIVE)'}")
    print(f"   - Session: {sess}")
    print(f"   - Alert sent: {bool(alert_sent)}")
    print(f"   - Status: {'ACTIVE' if end is None else 'CLOSED'}")
else:
    print("   - [ERROR] Missing period not found!")

conn.close()

print("\n" + "=" * 70)
print("Done! Missing period da duoc tao voi start_time tu 13:00.")
print("Bay gio chay force_alert_check_now.py de test.")
print("=" * 70)
