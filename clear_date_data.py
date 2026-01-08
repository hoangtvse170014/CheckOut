"""Clear all data for a specific date from database."""
import sqlite3
from datetime import datetime

date_to_clear = "2026-01-07"
db_path = "data/people_counter.db"

print(f"Clearing all data for date: {date_to_clear}")
print(f"Database: {db_path}")
print()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Count records before deletion
    cursor.execute("SELECT COUNT(*) FROM events WHERE substr(timestamp, 1, 10) = ?", (date_to_clear,))
    events_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM daily_state WHERE date = ?", (date_to_clear,))
    daily_state_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE substr(alert_time, 1, 10) = ?", (date_to_clear,))
    alerts_count = cursor.fetchone()[0]
    
    print(f"Records to delete:")
    print(f"  Events: {events_count}")
    print(f"  Daily State: {daily_state_count}")
    print(f"  Alerts: {alerts_count}")
    print()
    
    # Delete events
    cursor.execute("DELETE FROM events WHERE substr(timestamp, 1, 10) = ?", (date_to_clear,))
    events_deleted = cursor.rowcount
    print(f"[OK] Deleted {events_deleted} events")
    
    # Delete daily_state
    cursor.execute("DELETE FROM daily_state WHERE date = ?", (date_to_clear,))
    daily_state_deleted = cursor.rowcount
    print(f"[OK] Deleted {daily_state_deleted} daily_state records")
    
    # Delete alert_logs
    cursor.execute("DELETE FROM alert_logs WHERE substr(alert_time, 1, 10) = ?", (date_to_clear,))
    alerts_deleted = cursor.rowcount
    print(f"[OK] Deleted {alerts_deleted} alert records")
    
    # Commit changes
    conn.commit()
    print()
    print("[SUCCESS] All data for", date_to_clear, "has been cleared!")
    
except Exception as e:
    conn.rollback()
    print(f"[ERROR] Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()

