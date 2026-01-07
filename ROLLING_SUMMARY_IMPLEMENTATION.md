# Rolling Summary Implementation - Last 5 Days Excel

## Overview

Implemented automatic rolling summary Excel file that maintains data for exactly 5 days, with automatic cleanup of older files.

## Files Created

### 1. `export/retention_manager.py`
**Purpose**: Manages file retention and cleanup

**Functions**:
- `cleanup_old_daily_files()`: Deletes daily Excel files older than 5 days
- `get_valid_daily_files()`: Returns list of valid daily files (up to 5 most recent)

**Key Features**:
- Automatically deletes files older than retention period
- Returns only the most recent N days of files
- Handles temp files gracefully (ignores .tmp.xlsx files)
- Logs all deletion operations

### 2. `export/rolling_summary_exporter.py`
**Purpose**: Creates rolling summary Excel from daily Excel files

**Functions**:
- `export_rolling_summary()`: Main export function
- `_read_daily_file()`: Reads data from a single daily Excel file
- `_format_summary_excel()`: Applies formatting to summary Excel

**Key Features**:
- Reads ONLY from existing daily Excel files (trusted source)
- Never recalculates or reuses old summary content
- Atomic write (temp file → rename)
- Handles file locks gracefully

### 3. Modified: `scheduler/excel_export_scheduler.py`
- Added `_export_rolling_summary()` method
- Calls rolling summary export:
  - Every 30 minutes (after daily export)
  - On startup
  - At midnight (00:00)

## File Structure

### Summary File Name
**Fixed name**: `people_counter_LAST_5_DAYS.xlsx`

**Location**: `exports/summary/`

### Sheet Structure

#### Sheet 1: DAILY_SUMMARY
| Column | Description |
|--------|-------------|
| Date | Date in YYYY-MM-DD format |
| Total Morning | Total morning count for the day |
| Max Realtime | Maximum realtime count during the day |
| Min Realtime | Minimum realtime count during the day |
| Final Realtime | Last realtime count of the day |
| Total Alerts | Number of alerts for the day |
| Total Missing Periods | Number of missing periods |
| Total Missing Minutes | Sum of all missing period durations |

#### Sheet 2: DAILY_ALERTS
| Column | Description |
|--------|-------------|
| Date | Date in YYYY-MM-DD format |
| alert_time | Alert timestamp |
| total_morning | Total morning count at alert time |
| realtime | Realtime count at alert time |
| missing | Missing count at alert time |

#### Sheet 3: DAILY_MISSING_PERIODS
| Column | Description |
|--------|-------------|
| Date | Date in YYYY-MM-DD format |
| start_time | Period start timestamp |
| end_time | Period end timestamp |
| duration_minutes | Duration in minutes |

## Retention Rules

### Automatic Cleanup
1. **When**: Every 30 minutes (during export cycle)
2. **Action**: Delete daily Excel files older than 5 days
3. **Cutoff**: `today - 5 days`
4. **Example**: If today is 2026-01-10, files dated 2026-01-05 or earlier are deleted

### File Management
- Only daily files (`people_counter_YYYY-MM-DD.xlsx`) are subject to retention
- Temp files (`.tmp.xlsx`) are ignored
- Summary file (`LAST_5_DAYS.xlsx`) is never deleted by retention
- Files are deleted BEFORE building new summary (ensures clean state)

## Build Logic

### Process Flow
1. **Cleanup**: Delete old daily files (older than 5 days)
2. **Scan**: Find all daily Excel files in daily directory
3. **Filter**: Keep only valid files (exclude temp files, exclude summary file)
4. **Sort**: Sort by date ascending
5. **Limit**: Take only the most recent 5 files (or fewer if less exist)
6. **Read**: Read data from each daily Excel file:
   - SUMMARY sheet → daily summary row
   - ALERTS sheet → alerts with date prefix
   - MISSING_PERIODS sheet → missing periods with date prefix
   - EVENTS sheet → calculate max/min realtime
7. **Aggregate**: Combine all data into summary sheets
8. **Write**: Write to temp file, then atomic rename

### Data Sources
- **Trust**: Daily Excel files are the ONLY source
- **No recalculation**: Data is read directly from daily files
- **No memory**: No in-memory state used
- **No database**: Does not query SQLite (trusts daily Excel files)

## Atomic Write Process

1. Create temp file: `people_counter_LAST_5_DAYS.tmp.xlsx`
2. Write all sheets to temp file
3. Format Excel (headers, filters, column widths)
4. Save temp file
5. **Atomic rename**: `temp_file.rename(output_file)`
6. If rename fails (file locked), preserve temp file and skip

## Safety & Stability

### Why This is Safe

1. **Atomic Operations**
   - Complete rebuild each time
   - Temp file → rename ensures no corruption
   - No partial writes possible

2. **File Lock Handling**
   - If summary file is open in Excel, export is skipped
   - Temp file is preserved for debugging
   - Next export cycle will try again

3. **Crash-Safe**
   - No state to recover
   - If export fails, temp file is cleaned up
   - Next export rebuilds from scratch

4. **Data Integrity**
   - Reads only from verified daily Excel files
   - No intermediate calculations
   - No caching or memory state

5. **Automatic Cleanup**
   - Old files deleted before building summary
   - Prevents accumulation of old data
   - Always reflects exactly 5 days

## Usage

### Manual Export
```python
from export.rolling_summary_exporter import export_rolling_summary

# Export rolling summary
export_rolling_summary(
    daily_dir="exports/daily",
    summary_dir="exports/summary",
    max_days=5
)
```

### Automatic Export
- Runs every 30 minutes via scheduler
- Also runs on startup and at midnight

## Example Timeline

### Day 1 (2026-01-05)
- Daily file: `people_counter_2026-01-05.xlsx` created
- Summary: Contains 1 day (2026-01-05)

### Day 2 (2026-01-06)
- Daily file: `people_counter_2026-01-06.xlsx` created
- Summary: Contains 2 days (2026-01-05, 2026-01-06)

### Day 5 (2026-01-09)
- Daily file: `people_counter_2026-01-09.xlsx` created
- Summary: Contains 5 days (2026-01-05 through 2026-01-09)

### Day 6 (2026-01-10)
- Daily file: `people_counter_2026-01-10.xlsx` created
- **Old file deleted**: `people_counter_2026-01-05.xlsx` (older than 5 days)
- Summary: Contains 5 days (2026-01-06 through 2026-01-10)

## Logging

All operations are logged:
- `RETENTION_DELETE`: File deletion
- `RETENTION_CLEANUP`: Cleanup summary
- `ROLLING_SUMMARY_START`: Export start
- `ROLLING_SUMMARY_SUCCESS`: Export success
- `ROLLING_SUMMARY_SKIPPED`: Export skipped (file locked)
- `ROLLING_SUMMARY_ERROR`: Export error

## Notes

1. **BO Access**: Summary file can be opened anytime in Excel without refresh
2. **No Manual Intervention**: Fully automatic
3. **Fixed Name**: Summary file always has the same name (`LAST_5_DAYS.xlsx`)
4. **Backward Compatible**: Does not affect daily export functionality

