# Database Connection Guide

## Database Location
- **Path**: `data/people_counter.db`
- **Absolute Path**: `C:\Users\longv\OneDrive\Documents\Cursor\CheckOut\data\people_counter.db`
- **Type**: SQLite3

## Connection Methods

### 1. Python Script
```python
import sqlite3

# Connect to database
conn = sqlite3.connect('data/people_counter.db', check_same_thread=False)
conn.row_factory = sqlite3.Row  # For dict-like access
cursor = conn.cursor()

# Execute query
cursor.execute("SELECT * FROM people_events LIMIT 10")
rows = cursor.fetchall()

# Close connection
conn.close()
```

### 2. Command Line (SQLite CLI)
```bash
sqlite3 data/people_counter.db
```

Then run SQL queries:
```sql
.tables                    -- List all tables
.schema people_events      -- Show table schema
SELECT * FROM people_events LIMIT 10;
.exit                     -- Exit
```

### 3. Using Provided Scripts

**View all data:**
```bash
python view_database.py
```

**Interactive query:**
```bash
python query_database.py
```

**Run specific query:**
```bash
python query_database.py "SELECT * FROM people_events ORDER BY event_time DESC LIMIT 10"
```

## Database Schema

### Main Tables

#### `people_events`
- `id` INTEGER PRIMARY KEY
- `event_time` DATETIME NOT NULL
- `direction` TEXT CHECK(direction IN ('IN','OUT'))
- `camera_id` TEXT
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP

#### `daily_state`
- `date` TEXT PRIMARY KEY
- `total_morning` INTEGER DEFAULT 0
- `is_frozen` INTEGER DEFAULT 0
- `is_missing` INTEGER DEFAULT 0
- `realtime_in` INTEGER DEFAULT 0
- `realtime_out` INTEGER DEFAULT 0
- `updated_at` TEXT NOT NULL

#### `alert_logs`
- `id` INTEGER PRIMARY KEY
- `alert_time` TEXT NOT NULL
- `expected_total` INTEGER NOT NULL
- `current_total` INTEGER NOT NULL
- `missing` INTEGER NOT NULL
- `created_at` TEXT DEFAULT (datetime('now'))

#### `events` (legacy)
- `id` INTEGER PRIMARY KEY
- `timestamp` TEXT NOT NULL
- `track_id` INTEGER NOT NULL
- `direction` TEXT NOT NULL
- `camera_id` TEXT NOT NULL
- `created_at` TEXT NOT NULL

## Common Queries

### Get today's events
```sql
SELECT * FROM people_events 
WHERE date(event_time) = date('now')
ORDER BY event_time DESC;
```

### Get current state
```sql
SELECT * FROM daily_state 
WHERE date = date('now');
```

### Get today's alerts
```sql
SELECT * FROM alert_logs 
WHERE date(alert_time) = date('now')
ORDER BY alert_time DESC;
```

### Count events by direction
```sql
SELECT 
    direction,
    COUNT(*) as count
FROM people_events
WHERE date(event_time) = date('now')
GROUP BY direction;
```

### Get missing people status
```sql
SELECT 
    date,
    total_morning,
    realtime_in,
    realtime_out,
    (total_morning + realtime_in - realtime_out) as current_count,
    (total_morning - (total_morning + realtime_in - realtime_out)) as missing
FROM daily_state
WHERE date = date('now');
```

## Database Tools

### SQLite Browser (GUI)
Download from: https://sqlitebrowser.org/

1. Open SQLite Browser
2. Open Database → Select `data/people_counter.db`
3. Browse Data tab to view tables
4. Execute SQL tab to run queries

### VS Code Extension
Install "SQLite Viewer" extension in VS Code to browse database directly.

### Python Libraries
- `sqlite3` (built-in)
- `pandas`: `pd.read_sql_query()` for easy data analysis

## Backup Database
```bash
# Copy database file
cp data/people_counter.db data/people_counter_backup.db

# Or use SQLite backup
sqlite3 data/people_counter.db ".backup data/people_counter_backup.db"
```

