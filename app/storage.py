"""Data storage using SQLite."""

import logging
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional
from pathlib import Path
import pytz

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage for events and aggregations."""
    
    def __init__(self, db_path: str, timezone: str = "Asia/Bangkok"):
        """
        Initialize storage.
        
        Args:
            db_path: Path to SQLite database
            timezone: Timezone for timestamps
        """
        self.db_path = db_path
        self.timezone = pytz.timezone(timezone)
        
        # Create database directory if needed
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        logger.info(f"Storage initialized: {db_path}")
    
    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Events table: individual crossing events
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
        
        # Alerts table: alert history
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
        
        # Migration: Add realtime_in column if it doesn't exist
        cursor.execute("PRAGMA table_info(daily_state)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'realtime_in' not in columns:
            cursor.execute("ALTER TABLE daily_state ADD COLUMN realtime_in INTEGER DEFAULT 0")
            logger.info("Added realtime_in column to daily_state table")
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_date ON events(date(timestamp))
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_aggregations_date ON aggregations(date)
        """)
        
        conn.commit()
        conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def add_event(
        self,
        track_id: int,
        direction: str,
        camera_id: str,
    ) -> int:
        """
        Add a crossing event.
        
        Args:
            track_id: Track ID
            direction: 'in' or 'out'
            camera_id: Camera identifier
        
        Returns:
            Event ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now(self.timezone)
        timestamp = now.isoformat()
        
        cursor.execute("""
            INSERT INTO events (timestamp, track_id, direction, camera_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, track_id, direction, camera_id, timestamp))
        
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.debug(f"Event added: track_id={track_id}, direction={direction}")
        return event_id
    
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
    ) -> int:
        """
        Save alert record.
        
        Args:
            date: Date string (YYYY-MM-DD)
            window_a_out: OUT count for window A
            window_b_in: IN count for window B
            difference: Difference (OUT_A - IN_B)
            camera_id: Camera identifier
            notification_channel: Notification channel used
            notification_status: Status of notification
        
        Returns:
            Alert ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now(self.timezone).isoformat()
        
        cursor.execute("""
            INSERT INTO alerts 
            (date, window_a_out, window_b_in, difference, camera_id, sent_at, 
             notification_channel, notification_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, window_a_out, window_b_in, difference, camera_id, now,
              notification_channel, notification_status))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Alert saved: date={date}, diff={difference}")
        return alert_id
    
    def save_daily_state(
        self,
        date: str,
        total_morning: Optional[int] = None,
        is_frozen: Optional[bool] = None,
        is_missing: Optional[bool] = None,
        realtime_in: Optional[int] = None,
    ):
        """
        Save daily state.
        
        Args:
            date: Date string (YYYY-MM-DD)
            total_morning: Morning total count
            is_frozen: Whether morning total is frozen
            is_missing: Whether alert is active
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
                (date, total_morning, is_frozen, is_missing, realtime_in, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                date,
                total_morning if total_morning is not None else 0,
                1 if (is_frozen if is_frozen is not None else False) else 0,
                1 if (is_missing if is_missing is not None else False) else 0,
                realtime_in if realtime_in is not None else 0,
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
            # For realtime_in, check if column exists (for backward compatibility)
            realtime_in_value = row['realtime_in'] if 'realtime_in' in row.keys() else 0
            return {
                'total_morning': row['total_morning'],
                'is_frozen': bool(row['is_frozen']),
                'is_missing': bool(row['is_missing']),
                'realtime_in': realtime_in_value,
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

