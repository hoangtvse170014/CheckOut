# Excel Export Fix - Database-Driven Implementation

## Summary

Excel export has been completely rewritten to be 100% database-driven, ensuring accuracy, reliability, and auditability.

## Key Changes

### 1. New Files Created

#### `export/db_queries.py`
- **Purpose**: Read-only database queries
- **Functions**:
  - `get_total_morning()`: Calculates TOTAL MORNING from events table (IN events during morning phase)
  - `get_realtime_count()`: Calculates REALTIME (total IN - total OUT from all events)
  - `get_missing_periods()`: Identifies periods where REALTIME < TOTAL_MORNING
  - `get_alerts()`: Retrieves alerts from alert_logs table
  - `get_events()`: Retrieves all events for a date
  - `get_all_data_for_date()`: Single function to get all data

#### `export/excel_exporter.py`
- **Purpose**: Excel writing logic with atomic writes
- **Features**:
  - Complete rebuild from database (no memory state)
  - Atomic write: temp file → rename (no corruption)
  - Handles Excel file locks gracefully
  - Proper Excel formatting (headers, filters, frozen panes)

### 2. Modified Files

#### `scheduler/excel_export_scheduler.py`
- Updated `_export_daily_excel()` to use new exporter
- Loads morning times from config

## Data Definitions (100% Database-Driven)

### A. TOTAL MORNING
- **Source**: `events` table
- **Query**: COUNT of events where:
  - `direction = 'IN'`
  - `timestamp` between morning_start and morning_end
- **Config**: Uses `config.production.morning_start` and `config.production.morning_end`

### B. REALTIME
- **Source**: `events` table
- **Calculation**: `SUM(IN) - SUM(OUT)` from all events in the day
- **Never uses**: In-memory counters or daily_state table

### C. MISSING
- **Calculation**: `max(0, TOTAL_MORNING - REALTIME)`
- **Never negative**: Enforced with `max(0, ...)`

### D. MISSING PERIODS
- **Logic**: Iterates through events chronologically
  - Period starts: When cumulative count < TOTAL_MORNING
  - Period ends: When cumulative count >= TOTAL_MORNING
- **Stored**: `start_time`, `end_time`, `duration_minutes`

### E. ALERTS
- **Source**: `alert_logs` table
- **Columns**: `alert_time`, `total_morning`, `realtime`, `missing`

### F. EVENTS
- **Source**: `events` table
- **Columns**: `event_time`, `direction`, `camera_id`

## Excel Structure

**File Name**: `people_counter_YYYY-MM-DD.xlsx`

**Sheets**:
1. **SUMMARY**
   - Date
   - Total Morning
   - Current Realtime
   - Current Missing
   - Last Updated Time

2. **MISSING_PERIODS**
   - start_time
   - end_time
   - duration_minutes

3. **ALERTS**
   - alert_time
   - total_morning
   - realtime
   - missing

4. **EVENTS**
   - event_time
   - direction
   - camera_id

## Export Logic

1. **Frequency**: Every 30 minutes (configurable)
2. **Process**:
   - Query SQLite database directly
   - Rebuild Excel completely from scratch
   - Never append or update incrementally
3. **Atomic Write**:
   - Write to `.tmp.xlsx` file first
   - Only rename to final file when write succeeds
   - If file is locked (open in Excel), skip export and preserve temp file
4. **Safety**:
   - No partial writes (atomic operation)
   - Handles database errors gracefully
   - Logs all operations for audit

## Why This Will Never Be Out of Sync

### 1. **Single Source of Truth**
- SQLite database is the ONLY source
- Excel is always rebuilt from database queries
- No in-memory state used

### 2. **No Memory Dependencies**
- Does not use `daily_state` table values
- Does not use app runtime counters
- Does not depend on app uptime
- Works correctly even after crash + restart

### 3. **Direct Database Queries**
- Every calculation queries `events` table directly
- No intermediate calculations or caching
- Always reflects current database state

### 4. **Atomic Operations**
- Complete rebuild each time
- Temp file → rename ensures no corruption
- No partial writes possible

### 5. **Crash-Safe**
- If export fails, temp file is cleaned up
- If app crashes, next export rebuilds from database
- No state to recover or sync

## SQL Queries Used

### TOTAL MORNING
```sql
SELECT COUNT(*) as count
FROM events
WHERE substr(timestamp, 1, 10) = ?
  AND UPPER(direction) = 'IN'
  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
      CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
      CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
```

### REALTIME COUNT
```sql
SELECT 
    SUM(CASE WHEN UPPER(direction) = 'IN' THEN 1 ELSE 0 END) as in_count,
    SUM(CASE WHEN UPPER(direction) = 'OUT' THEN 1 ELSE 0 END) as out_count
FROM events
WHERE substr(timestamp, 1, 10) = ?
```

### MISSING PERIODS
- Iterates through all events chronologically
- Tracks cumulative count (IN - OUT)
- Detects periods where count < TOTAL_MORNING

### ALERTS
```sql
SELECT alert_time, expected_total, current_total, missing
FROM alert_logs
WHERE substr(alert_time, 1, 10) = ?
ORDER BY alert_time ASC
```

### EVENTS
```sql
SELECT timestamp, direction, camera_id
FROM events
WHERE substr(timestamp, 1, 10) = ?
ORDER BY timestamp ASC
```

## Testing

To test the export:

```python
from export.excel_exporter import export_daily_excel

# Export today's data
export_daily_excel(
    target_date='2026-01-07',
    db_path='data/people_counter.db',
    output_dir='exports/daily',
    morning_start='11:05',
    morning_end='11:14'
)
```

## Notes

1. **Morning Time**: Currently uses config values (11:05-11:14). To change, update `config.production.morning_start` and `config.production.morning_end`.

2. **File Locks**: If Excel file is open, export is skipped. Close the file and wait for next export (30 minutes) or run export manually.

3. **No Breaking Changes**: Existing export functionality is preserved, just made more reliable.

4. **Rolling Summary**: The rolling summary file (last 5 days) uses existing `export_last_5_days_excel.py` which should be updated separately if needed.

