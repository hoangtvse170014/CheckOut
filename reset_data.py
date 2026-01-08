"""
Script để reset data khi qua ngày mới (0h) và chuẩn bị đếm total morning lúc 6h sáng.
Có thể chạy thủ công hoặc tự động qua scheduler.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DB_PATH = "data/people_counter.db"
TIMEZONE = "Asia/Ho_Chi_Minh"


def reset_daily_data(target_date: str = None):
    """
    Reset data cho ngày mới.
    
    Args:
        target_date: Ngày cần reset (YYYY-MM-DD). Nếu None, dùng ngày hôm nay.
    """
    tz = pytz.timezone(TIMEZONE)
    
    if target_date is None:
        target_date = datetime.now(tz).strftime("%Y-%m-%d")
    
    logger.info(f"=== RESET DATA FOR DATE: {target_date} ===")
    
    if not Path(DB_PATH).exists():
        logger.error(f"Database not found: {DB_PATH}")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. Reset daily_state cho ngày mới
        logger.info(f"Resetting daily_state for {target_date}...")
        cursor.execute("""
            INSERT OR REPLACE INTO daily_state 
            (date, total_morning, is_frozen, is_missing, realtime_in, realtime_out, updated_at)
            VALUES (?, 0, 0, 0, 0, 0, ?)
        """, (target_date, datetime.now(tz).isoformat()))
        
        # 2. Đóng tất cả missing periods còn mở của ngày trước (nếu có)
        yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - 
                     timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Closing any open missing periods from {yesterday}...")
        cursor.execute("""
            UPDATE missing_periods
            SET end_time = ?,
                duration_minutes = CAST((julianday(?) - julianday(start_time)) * 1440 AS INTEGER)
            WHERE substr(start_time, 1, 10) = ? AND end_time IS NULL
        """, (datetime.now(tz).isoformat(), datetime.now(tz).isoformat(), yesterday))
        
        # 3. Log reset action
        logger.info(f"Daily state reset completed for {target_date}")
        logger.info("  - total_morning: 0")
        logger.info("  - is_frozen: False")
        logger.info("  - is_missing: False")
        logger.info("  - realtime_in: 0")
        logger.info("  - realtime_out: 0")
        logger.info("")
        logger.info("System ready to count Total Morning at 06:00")
        
        conn.commit()
        conn.close()
        
        logger.info("=== RESET COMPLETED SUCCESSFULLY ===")
        return True
        
    except Exception as e:
        logger.error(f"Error resetting data: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        return False


def reset_for_today():
    """Reset data cho ngày hôm nay."""
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    return reset_daily_data(today)


def reset_for_yesterday():
    """Reset data cho ngày hôm qua (dùng khi chạy sau 0h)."""
    tz = pytz.timezone(TIMEZONE)
    yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    return reset_daily_data(yesterday)


if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("RESET DATA SCRIPT")
    print("=" * 60)
    print("")
    
    # Check if date argument provided
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
        print(f"Resetting data for date: {target_date}")
        success = reset_daily_data(target_date)
    else:
        # Auto-detect: if before 6 AM, reset yesterday; otherwise reset today
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        current_hour = now.hour
        
        if current_hour < 6:
            # Before 6 AM - reset yesterday's data
            print("Current time is before 6 AM - resetting yesterday's data")
            success = reset_for_yesterday()
        else:
            # After 6 AM - reset today's data
            print("Current time is after 6 AM - resetting today's data")
            success = reset_for_today()
    
    if success:
        print("")
        print("=" * 60)
        print("RESET SUCCESSFUL")
        print("=" * 60)
        print("System is ready to count Total Morning at 06:00")
        sys.exit(0)
    else:
        print("")
        print("=" * 60)
        print("RESET FAILED")
        print("=" * 60)
        sys.exit(1)

