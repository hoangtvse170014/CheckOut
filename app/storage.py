"""Data storage using SQLite - fail-safe with backup mechanism."""

import logging
import sqlite3
import json
import threading
from datetime import datetime
from typing import List, Tuple, Optional
from pathlib import Path
import pytz

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage for events and aggregations."""
    
    def __init__(self, db_path: str, timezone: str = "Asia/Bangkok"):
        """
        Initialize storage - MANDATORY and fail-safe.
        
        Args:
            db_path: Path to SQLite database
            timezone: Timezone for timestamps
            
        Raises:
            RuntimeError: If database initialization fails
        """
        self.db_path = db_path
        self.timezone = pytz.timezone(timezone)
        self._write_lock = threading.Lock()  # Thread-safe writes
        self._backup_failures = 0  # Track backup write failures
        
        # Create database directory if needed
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Create backup directory
        self.backup_dir = Path("backup")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database - CRITICAL: must succeed
        try:
            self._init_db()
            self._validate_database()
            # Log absolute database path for diagnostics
            db_absolute = Path(db_path).resolve()
            logger.info(f"Storage initialized successfully: {db_path}")
            logger.info(f"Database absolute path: {db_absolute}")
        except Exception as e:
            logger.error(f"CRITICAL: Database initialization failed: {e}", exc_info=True)
            raise RuntimeError(f"Cannot start application: Database initialization failed: {e}") from e
    
    def _init_db(self):
        """
        Initialize database schema - creates all required tables.
        
        Raises:
            sqlite3.Error: If database operations fail
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        try:
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            
            # Events table: individual crossing events (legacy schema)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # people_events table: new schema for export compatibility
            # Schema MUST match requirements: DATETIME, CHECK constraint for direction
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS people_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time DATETIME NOT NULL,
                    direction TEXT CHECK(direction IN ('IN','OUT')) NOT NULL,
                    camera_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Aggregations table: hourly/daily aggregations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aggregations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    window_type TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    count_in INTEGER DEFAULT 0,
                    count_out INTEGER DEFAULT 0,
                    camera_id TEXT NOT NULL,
                    calculated_at TEXT NOT NULL,
                    UNIQUE(date, window_type, camera_id)
                )
            """)
            
            # alert_logs table: alert history (for export)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_time TEXT NOT NULL,
                    expected_total INTEGER NOT NULL,
                    current_total INTEGER NOT NULL,
                    missing INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Alerts table: alert history (legacy)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    window_a_out INTEGER NOT NULL,
                    window_b_in INTEGER NOT NULL,
                    difference INTEGER NOT NULL,
                    camera_id TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    notification_channel TEXT,
                    notification_status TEXT
                )
            """)
            
            # daily_summary table: for export
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date TEXT PRIMARY KEY,
                    total_morning INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Daily state table: persistent state per day
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_state (
                    date TEXT PRIMARY KEY,
                    total_morning INTEGER DEFAULT 0,
                    is_frozen INTEGER DEFAULT 0,
                    is_missing INTEGER DEFAULT 0,
                    realtime_in INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Migration: Add realtime_in and realtime_out columns if they don't exist
            cursor.execute("PRAGMA table_info(daily_state)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'realtime_in' not in columns:
                cursor.execute("ALTER TABLE daily_state ADD COLUMN realtime_in INTEGER DEFAULT 0")
                logger.info("Added realtime_in column to daily_state table")
            if 'realtime_out' not in columns:
                cursor.execute("ALTER TABLE daily_state ADD COLUMN realtime_out INTEGER DEFAULT 0")
                logger.info("Added realtime_out column to daily_state table")
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_date ON events(date(timestamp))
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_people_events_event_time ON people_events(event_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_people_events_date ON people_events(date(event_time))
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_aggregations_date ON aggregations(date)
            """)
            
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Database schema initialization failed: {e}", exc_info=True)
            raise
        finally:
            conn.close()
    
    def _validate_database(self):
        """
        Validate that all required tables exist and log database status.
        
        Raises:
            RuntimeError: If any required table is missing
        """
        required_tables = ['events', 'people_events', 'alert_logs', 'daily_summary', 'daily_state']
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        try:
            # Log database file path (absolute)
            db_absolute_path = Path(self.db_path).resolve()
            logger.info(f"=== DATABASE VERIFICATION ===")
            logger.info(f"SQLite file path: {db_absolute_path}")
            logger.info(f"SQLite file exists: {db_absolute_path.exists()}")
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row[0] for row in cursor.fetchall()}
            
            missing_tables = [t for t in required_tables if t not in existing_tables]
            if missing_tables:
                error_msg = f"CRITICAL: Required tables missing: {missing_tables}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            logger.info(f"Database validation passed: all required tables exist")
            
            # Log row counts for key tables
            cursor.execute("SELECT COUNT(*) FROM people_events")
            people_events_count = cursor.fetchone()[0]
            logger.info(f"people_events table row count at startup: {people_events_count}")
            
            cursor.execute("SELECT COUNT(*) FROM events")
            events_count = cursor.fetchone()[0]
            logger.info(f"events table row count at startup: {events_count}")
            
            cursor.execute("SELECT COUNT(*) FROM daily_state")
            daily_state_count = cursor.fetchone()[0]
            logger.info(f"daily_state table row count at startup: {daily_state_count}")
            
            logger.info(f"=== DATABASE VERIFICATION COMPLETE ===")
        finally:
            conn.close()
    
    def _write_backup_event(self, track_id: int, direction: str, camera_id: str, timestamp: str):
        """
        Write event to backup JSONL file if SQLite insert fails.
        
        Args:
            track_id: Track ID
            direction: Event direction
            camera_id: Camera ID
            timestamp: Event timestamp
        """
        try:
            today = datetime.now(self.timezone).strftime('%Y-%m-%d')
            backup_file = self.backup_dir / f"events_{today}.jsonl"
            
            event_data = {
                'timestamp': timestamp,
                'track_id': track_id,
                'direction': direction,
                'camera_id': camera_id,
                'backup_time': datetime.now(self.timezone).isoformat()
            }
            
            with open(backup_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event_data, ensure_ascii=False) + '\n')
            
            logger.warning(f"Event written to backup file: {backup_file.name}")
        except Exception as e:
            self._backup_failures += 1
            logger.error(f"CRITICAL: Backup write also failed: {e}", exc_info=True)
            if self._backup_failures >= 10:
                logger.critical("CRITICAL: Multiple backup failures detected. Event loss may occur!")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def add_event(
        self,
        track_id: int,
        direction: str,
        camera_id: str,
    ) -> Optional[int]:
        """
        Add a crossing event - fail-safe with backup.
        
        Args:
            track_id: Track ID
            direction: 'in' or 'out'
            camera_id: Camera identifier
        
        Returns:
            Event ID if successful, None if failed (but backup written)
        """
        now = datetime.now(self.timezone)
        timestamp = now.isoformat()
        
        # Normalize direction to uppercase 'IN'/'OUT' for people_events table (CHECK constraint)
        direction_upper = direction.upper()
        if direction_upper not in ['IN', 'OUT']:
            logger.error(f"Invalid direction: {direction}, must be 'IN' or 'OUT'")
            direction_upper = 'IN' if direction.lower() in ['in', 'enter'] else 'OUT'
        
        # Log database path being used
        db_absolute = Path(self.db_path).resolve()
        logger.info(f"EVENT_WRITE_ATTEMPT: track_id={track_id}, direction={direction}->{direction_upper}, camera_id={camera_id}, db_path={db_absolute}")
        
        with self._write_lock:  # Thread-safe
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                # Insert into events table (legacy - keep original direction)
                cursor.execute("""
                    INSERT INTO events (timestamp, track_id, direction, camera_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (timestamp, track_id, direction, camera_id, timestamp))
                
                event_id = cursor.lastrowid
                
                # Insert into people_events table (for export - use uppercase direction)
                cursor.execute("""
                    INSERT INTO people_events (event_time, direction, camera_id, created_at)
                    VALUES (?, ?, ?, ?)
                """, (timestamp, direction_upper, camera_id, timestamp))
                
                conn.commit()
                
                # Verify the event was actually saved
                cursor.execute("SELECT COUNT(*) FROM people_events WHERE event_time = ? AND direction = ?", (timestamp, direction_upper))
                verify_count = cursor.fetchone()[0]
                if verify_count == 0:
                    logger.error(f"CRITICAL: Event was NOT saved to database! track_id={track_id}, direction={direction_upper}, timestamp={timestamp}")
                    conn.rollback()
                    conn.close()
                    # Write to backup
                    self._write_backup_event(track_id, direction, camera_id, timestamp)
                    return None
                
                conn.close()
                
                # Log success with database path confirmation
                logger.info(f"EVENT_INSERTED: track_id={track_id}, direction={direction_upper}, id={event_id}, timestamp={timestamp}, db_path={db_absolute}")
                return event_id
                
            except sqlite3.Error as e:
                logger.error(f"EVENT NOT PERSISTED: SQLite insert failed: {e}", exc_info=True)
                conn.rollback()
                if conn:
                    conn.close()
                
                # Write to backup file
                self._write_backup_event(track_id, direction, camera_id, timestamp)
                
                return None
            except Exception as e:
                logger.error(f"EVENT NOT PERSISTED: Unexpected error: {e}", exc_info=True)
                # Write to backup file
                self._write_backup_event(track_id, direction, camera_id, timestamp)
                return None
    
    def get_events_in_window(
        self,
        window_start: datetime,
        window_end: datetime,
        camera_id: str,
    ) -> Tuple[int, int]:
        """
        Get counts for a time window.
        
        Args:
            window_start: Window start time
            window_end: Window end time
            camera_id: Camera identifier
        
        Returns:
            Tuple of (count_in, count_out)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        start_str = window_start.isoformat()
        end_str = window_end.isoformat()
        
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN direction = 'in' THEN 1 ELSE 0 END) as count_in,
                SUM(CASE WHEN direction = 'out' THEN 1 ELSE 0 END) as count_out
            FROM events
            WHERE timestamp >= ? AND timestamp <= ? AND camera_id = ?
        """, (start_str, end_str, camera_id))
        
        row = cursor.fetchone()
        conn.close()
        
        count_in = row['count_in'] or 0
        count_out = row['count_out'] or 0
        
        return count_in, count_out
    
    def save_aggregation(
        self,
        date: str,
        window_type: str,
        window_start: str,
        window_end: str,
        count_in: int,
        count_out: int,
        camera_id: str,
    ):
        """
        Save aggregation for a time window.
        
        Args:
            date: Date string (YYYY-MM-DD)
            window_type: 'A' or 'B'
            window_start: Window start time string
            window_end: Window end time string
            count_in: Count of IN events
            count_out: Count of OUT events
            camera_id: Camera identifier
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now(self.timezone).isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO aggregations 
            (date, window_type, window_start, window_end, count_in, count_out, camera_id, calculated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, window_type, window_start, window_end, count_in, count_out, camera_id, now))
        
        conn.commit()
        conn.close()
        
        logger.info(
            f"Aggregation saved: date={date}, window={window_type}, "
            f"in={count_in}, out={count_out}"
        )
    
    def get_aggregation(
        self,
        date: str,
        window_type: str,
        camera_id: str,
    ) -> Optional[Tuple[int, int]]:
        """
        Get aggregation for a date and window.
        
        Args:
            date: Date string (YYYY-MM-DD)
            window_type: 'A' or 'B'
            camera_id: Camera identifier
        
        Returns:
            Tuple of (count_in, count_out) or None
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT count_in, count_out
            FROM aggregations
            WHERE date = ? AND window_type = ? AND camera_id = ?
        """, (date, window_type, camera_id))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return (row['count_in'], row['count_out'])
        return None
    
    def save_alert(
        self,
        date: str,
        window_a_out: int,
        window_b_in: int,
        difference: int,
        camera_id: str,
        notification_channel: Optional[str] = None,
        notification_status: str = "sent",
        expected_total: Optional[int] = None,
        current_total: Optional[int] = None,
    ) -> int:
        """
        Save alert record - saves to both alerts (legacy) and alert_logs (for export).
        
        Args:
            date: Date string (YYYY-MM-DD)
            window_a_out: OUT count for window A
            window_b_in: IN count for window B
            difference: Difference (missing count)
            camera_id: Camera identifier
            notification_channel: Notification channel used
            notification_status: Status of notification
            expected_total: Expected total (total_morning)
            current_total: Current total (realtime_count)
        
        Returns:
            Alert ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now(self.timezone).isoformat()
        
        try:
            # Save to alerts table (legacy)
            cursor.execute("""
                INSERT INTO alerts 
                (date, window_a_out, window_b_in, difference, camera_id, sent_at, 
                 notification_channel, notification_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, window_a_out, window_b_in, difference, camera_id, now,
                  notification_channel, notification_status))
            
            alert_id = cursor.lastrowid
            
            # Also save to alert_logs table (for export) if expected_total and current_total provided
            if expected_total is not None and current_total is not None:
                cursor.execute("""
                    INSERT INTO alert_logs 
                    (alert_time, expected_total, current_total, missing)
                    VALUES (?, ?, ?, ?)
                """, (now, expected_total, current_total, difference))
            
            conn.commit()
            logger.info(f"Alert saved: date={date}, diff={difference}, status={notification_status}")
            return alert_id
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Failed to save alert: {e}", exc_info=True)
            raise
        finally:
            conn.close()
    
    def save_daily_state(
        self,
        date: str,
        total_morning: Optional[int] = None,
        is_frozen: Optional[bool] = None,
        is_missing: Optional[bool] = None,
        realtime_in: Optional[int] = None,
        realtime_out: Optional[int] = None,
    ):
        """
        Save daily state.
        
        Args:
            date: Date string (YYYY-MM-DD)
            total_morning: Morning total count
            is_frozen: Whether morning total is frozen
            is_missing: Whether alert is active
            realtime_in: Realtime IN count (after morning phase)
            realtime_out: Realtime OUT count (after morning phase)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now(self.timezone).isoformat()
        
        # Get existing state
        cursor.execute("SELECT * FROM daily_state WHERE date = ?", (date,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing
            updates = []
            params = []
            
            if total_morning is not None:
                updates.append("total_morning = ?")
                params.append(total_morning)
            
            if is_frozen is not None:
                updates.append("is_frozen = ?")
                params.append(1 if is_frozen else 0)
            
            if is_missing is not None:
                updates.append("is_missing = ?")
                params.append(1 if is_missing else 0)
            
            if realtime_in is not None:
                updates.append("realtime_in = ?")
                params.append(realtime_in)
            
            if realtime_out is not None:
                updates.append("realtime_out = ?")
                params.append(realtime_out)
            
            updates.append("updated_at = ?")
            params.append(now)
            params.append(date)
            
            cursor.execute(
                f"UPDATE daily_state SET {', '.join(updates)} WHERE date = ?",
                params
            )
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO daily_state 
                (date, total_morning, is_frozen, is_missing, realtime_in, realtime_out, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                date,
                total_morning if total_morning is not None else 0,
                1 if (is_frozen if is_frozen is not None else False) else 0,
                1 if (is_missing if is_missing is not None else False) else 0,
                realtime_in if realtime_in is not None else 0,
                realtime_out if realtime_out is not None else 0,
                now,
            ))
        
        conn.commit()
        conn.close()
    
    def get_daily_state(self, date: str) -> Optional[dict]:
        """
        Get daily state.
        
        Args:
            date: Date string (YYYY-MM-DD)
        
        Returns:
            Dictionary with state or None
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM daily_state WHERE date = ?", (date,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            # sqlite3.Row supports dictionary-like indexing (row['column_name'])
            # Since we control the schema and have migration, we can safely use indexing
            # For realtime_in and realtime_out, check if column exists (for backward compatibility)
            realtime_in_value = row['realtime_in'] if 'realtime_in' in row.keys() else 0
            realtime_out_value = row['realtime_out'] if 'realtime_out' in row.keys() else 0
            return {
                'total_morning': row['total_morning'],
                'is_frozen': bool(row['is_frozen']),
                'is_missing': bool(row['is_missing']),
                'realtime_in': realtime_in_value,
                'realtime_out': realtime_out_value,
            }
        return None
    
    def get_events_count_after(
        self,
        start_time: datetime,
        direction: str,
        camera_id: str,
    ) -> int:
        """
        Get count of events after a specific time.
        
        Args:
            start_time: Start datetime
            direction: "in" or "out"
            camera_id: Camera identifier
        
        Returns:
            Count of events
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        start_iso = start_time.isoformat()
        
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM events
            WHERE timestamp >= ? AND direction = ? AND camera_id = ?
        """, (start_iso, direction, camera_id))
        
        row = cursor.fetchone()
        conn.close()
        
        return row['count'] if row else 0
    
    def get_total_morning_from_events(self, date: str, morning_start: str, morning_end: str) -> int:
        """
        Calculate total_morning from events in morning phase.
        
        Args:
            date: Date string (YYYY-MM-DD)
            morning_start: Morning phase start time (HH:MM)
            morning_end: Morning phase end time (HH:MM)
        
        Returns:
            Total morning count (IN - OUT during morning phase)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Parse times
            start_hour, start_min = map(int, morning_start.split(':'))
            end_hour, end_min = map(int, morning_end.split(':'))
            
            # Query events in morning phase
            # Handle timestamp with timezone format (e.g., '2026-01-07T09:31:01+07:00')
            # Use substr() to parse date and time from ISO 8601 format
            start_minutes = start_hour * 60 + start_min
            end_minutes = end_hour * 60 + end_min
            cursor.execute("""
                SELECT direction, COUNT(*) as count
                FROM events
                WHERE substr(timestamp, 1, 10) = ?
                  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
                  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
                GROUP BY direction
            """, (date, start_minutes, end_minutes))
            
            results = cursor.fetchall()
            in_count = 0
            out_count = 0
            
            # Handle both uppercase (IN/OUT) and lowercase (in/out) directions
            for direction, count in results:
                dir_upper = direction.upper()
                if dir_upper == 'IN':
                    in_count += count
                elif dir_upper == 'OUT':
                    out_count += count
            
            total_morning = in_count - out_count
            logger.debug(f"Calculated total_morning from events: {total_morning} (IN: {in_count}, OUT: {out_count})")
            return total_morning
        finally:
            conn.close()
    
    def get_current_realtime_count(self, date: str, camera_id: str, morning_end_time: Optional[datetime] = None) -> int:
        """
        Get current realtime count of people in office.
        Calculation: total_morning + realtime_in - realtime_out (from daily_state).
        Fallback to events table if daily_state not available.
        
        Args:
            date: Date string (YYYY-MM-DD)
            camera_id: Camera identifier
            morning_end_time: Optional morning end time to count from that point
        
        Returns:
            Current realtime count (total_morning + realtime_in - realtime_out)
        """
        # First, try to get from daily_state (most reliable)
        state = self.get_daily_state(date)
        if state:
            total_morning = state.get('total_morning', 0)
            realtime_in = state.get('realtime_in', 0)
            realtime_out = state.get('realtime_out', 0)
            
            # Calculate: total_morning + realtime_in - realtime_out
            realtime_count = total_morning + realtime_in - realtime_out
            logger.debug(f"Realtime count from daily_state: {realtime_count} (total_morning={total_morning}, realtime_in={realtime_in}, realtime_out={realtime_out})")
            return realtime_count
        
        # Fallback: calculate from events table
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if morning_end_time:
                # Count from morning_end_time onwards
                start_iso = morning_end_time.isoformat()
                cursor.execute("""
                    SELECT 
                        SUM(CASE WHEN direction = 'in' THEN 1 ELSE 0 END) as count_in,
                        SUM(CASE WHEN direction = 'out' THEN 1 ELSE 0 END) as count_out
                    FROM people_events
                    WHERE event_time >= ? AND camera_id = ?
                """, (start_iso, camera_id))
            else:
                # Count all events for the day
                cursor.execute("""
                    SELECT 
                        SUM(CASE WHEN direction = 'in' THEN 1 ELSE 0 END) as count_in,
                        SUM(CASE WHEN direction = 'out' THEN 1 ELSE 0 END) as count_out
                    FROM people_events
                    WHERE date(event_time) = ? AND camera_id = ?
                """, (date, camera_id))
            
            row = cursor.fetchone()
            count_in = row[0] if row and row[0] else 0
            count_out = row[1] if row and row[1] else 0
            
            realtime_count = count_in - count_out
            logger.debug(f"Realtime count from events: {realtime_count} (count_in={count_in}, count_out={count_out})")
            return realtime_count
        except Exception as e:
            logger.warning(f"Error calculating realtime_count from events: {e}")
            return 0
        finally:
            conn.close()

