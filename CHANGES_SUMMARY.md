# Changes Summary - People Counter Database & Excel Export Fix

## Files Modified

1. **app/storage.py**
   - Fixed `people_events` schema to use DATETIME and CHECK constraint for direction ('IN'/'OUT')
   - Added comprehensive database verification on startup with logging
   - Added row count logging for key tables at startup
   - Enhanced `add_event()` with:
     - Direction normalization to uppercase 'IN'/'OUT'
     - Comprehensive logging (EVENT_WRITE_ATTEMPT, EVENT_INSERTED)
     - Verification that events are actually saved
   - Fixed database connection to use `check_same_thread=False` and WAL mode

2. **app/main.py**
   - Added self-test insert after 60 seconds if no events exist
   - Enhanced shutdown to force final Excel export
   - Added logging for event saves

3. **scheduler/excel_export_scheduler.py**
   - Changed to use full `export_daily_excel` function from export module
   - Added comprehensive logging (EXCEL_EXPORT_STARTED, EXCEL_EXPORT_COMPLETED)
   - Added row count logging per sheet after export
   - Set export interval back to 30 minutes (was 1 minute for testing)

4. **export/export_daily_excel.py**
   - Enhanced `get_events_for_date()` with fallback for date() function compatibility
   - Already has proper SQLite reading logic

## Key Improvements

### A. Database Verification
- On startup, logs:
  - SQLite file absolute path
  - File existence status
  - Table existence verification
  - Row counts for people_events, events, daily_state tables

### B. Event Write Guarantee
- Every event write attempt is logged with "EVENT_WRITE_ATTEMPT"
- Successful writes log "EVENT_INSERTED" with full details
- Failed writes log errors explicitly
- Events are verified after insert to ensure they were saved
- Direction is normalized to uppercase 'IN'/'OUT' to match CHECK constraint

### C. Self-Test Insert
- After 60 seconds of app running, checks if any events exist
- If no events, automatically inserts a test event:
  - direction = 'IN'
  - camera_id = 'self_test'
  - track_id = 999999
- Logs "SELF_TEST_EVENT_INSERTED" when inserted

### D. Excel Export Pipeline
- Uses full `export_daily_excel()` function that reads from SQLite
- Properly handles DATETIME columns
- Creates all required sheets: SUMMARY, EVENTS, ALERTS, MISSING_PERIODS
- Logs row counts per sheet after export

### E. Scheduler Stability
- Runs every 30 minutes
- Does not stop when main loop is running (runs in background thread)
- Forces final export on shutdown
- Comprehensive logging for all export operations

## Schema Changes

### people_events table (FIXED)
```sql
CREATE TABLE IF NOT EXISTS people_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time DATETIME NOT NULL,
    direction TEXT CHECK(direction IN ('IN','OUT')) NOT NULL,
    camera_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

## Log Examples

### Database Verification (on startup)
```
=== DATABASE VERIFICATION ===
SQLite file path: C:\Users\longv\OneDrive\Documents\Cursor\CheckOut\data\people_counter.db
SQLite file exists: True
Database validation passed: all required tables exist
people_events table row count at startup: 0
events table row count at startup: 0
daily_state table row count at startup: 0
=== DATABASE VERIFICATION COMPLETE ===
```

### Event Insert
```
EVENT_WRITE_ATTEMPT: track_id=5, direction=in->IN, camera_id=camera_01, timestamp=2026-01-06T15:12:25.130000+07:00
EVENT_INSERTED: track_id=5, direction=IN, id=937, timestamp=2026-01-06T15:12:25.130000+07:00
```

### Self-Test Insert
```
SELF_TEST_EVENT_INSERTED: id=1, direction=IN, camera_id=self_test
```

### Excel Export
```
EXCEL_EXPORT_STARTED: date=2026-01-06, file=people_counter_2026-01-06.xlsx
EXCEL_EXPORT_COMPLETED: date=2026-01-06, row_counts={'SUMMARY': 9, 'EVENTS': 15, 'ALERTS': 3, 'MISSING_PERIODS': 2}
```

## Testing Checklist

- [x] Database verification logs on startup
- [x] Events are written with uppercase direction
- [x] Self-test insert after 60 seconds if no events
- [x] Excel export reads from SQLite
- [x] Excel export creates all required sheets
- [x] Scheduler runs every 30 minutes
- [x] Final export on shutdown
- [x] Comprehensive logging throughout

## Notes

- All changes maintain backward compatibility
- No changes to counting logic, detection, or tracking
- Only data persistence and export functionality modified
- System is now stable for non-technical BO users

