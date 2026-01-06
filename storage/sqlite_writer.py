"""SQLite event writer with thread-safe operations."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SQLiteWriter:
    """Thread-safe SQLite writer for people events and daily summaries."""
    
    def __init__(self, db_path: str = "data/people_counter.db"):
        """
        Initialize SQLite writer.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        
        # Create directory if it doesn't exist
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database connection (thread-safe)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
        
        try:
            self._init_connection()
            self._init_schema()
            self._initialized = True
            logger.info(f"SQLiteWriter initialized: {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLiteWriter: {e}", exc_info=True)
            self._initialized = False
    
    def _init_connection(self):
        """Initialize SQLite connection with thread-safe settings."""
        try:
            # check_same_thread=False allows multi-threaded access
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10.0  # Wait up to 10 seconds if database is locked
            )
            # Use row factory for dictionary-like access
            self._conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()
            logger.debug("SQLite connection initialized with WAL mode")
        except Exception as e:
            logger.error(f"Failed to create SQLite connection: {e}")
            raise
    
    def _init_schema(self):
        """Initialize database schema (people_events and daily_summary tables)."""
        if not self._conn:
            return
        
        try:
            cursor = self._conn.cursor()
            
            # Create people_events table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS people_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_people_events_event_time 
                ON people_events(event_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_people_events_camera_id 
                ON people_events(camera_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_people_events_date 
                ON people_events(date(event_time))
            """)
            
            # Create daily_summary table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date TEXT PRIMARY KEY,
                    total_morning INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Create index for daily_summary
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_summary_date 
                ON daily_summary(date)
            """)
            
            self._conn.commit()
            logger.debug("SQLite schema initialized (people_events and daily_summary tables)")
        except Exception as e:
            if self._conn:
                self._conn.rollback()
            logger.error(f"Failed to initialize schema: {e}", exc_info=True)
            raise
    
    def write_event(
        self,
        event_time: datetime,
        direction: str,
        camera_id: str,
    ) -> bool:
        """
        Write an event to SQLite (thread-safe, handles errors gracefully).
        
        Args:
            event_time: Event timestamp
            direction: Event direction ('in' or 'out')
            camera_id: Camera identifier
        
        Returns:
            True if written successfully, False otherwise (errors are logged)
        """
        if not self._initialized or not self._conn:
            return False
        
        try:
            cursor = self._conn.cursor()
            
            # Convert datetime to ISO format string
            event_time_str = event_time.isoformat() if isinstance(event_time, datetime) else str(event_time)
            created_at_str = datetime.now().isoformat()
            
            query = """
                INSERT INTO people_events (event_time, direction, camera_id, created_at)
                VALUES (?, ?, ?, ?)
            """
            
            cursor.execute(query, (event_time_str, direction.lower(), camera_id, created_at_str))
            self._conn.commit()
            
            logger.debug(f"Event written to SQLite: {direction} at {event_time_str}")
            return True
            
        except sqlite3.OperationalError as e:
            if self._conn:
                try:
                    self._conn.rollback()
                except:
                    pass
            logger.error(f"SQLite operational error writing event: {e}", exc_info=False)
            return False
        except Exception as e:
            if self._conn:
                try:
                    self._conn.rollback()
                except:
                    pass
            logger.error(f"Failed to write event to SQLite: {e}", exc_info=False)
            return False
    
    def upsert_daily_summary(
        self,
        date: str,
        total_morning: int,
    ) -> bool:
        """
        Insert or update daily summary (thread-safe, handles errors gracefully).
        
        Args:
            date: Date string (YYYY-MM-DD)
            total_morning: Morning total count
        
        Returns:
            True if written successfully, False otherwise (errors are logged)
        """
        if not self._initialized or not self._conn:
            return False
        
        try:
            cursor = self._conn.cursor()
            
            updated_at_str = datetime.now().isoformat()
            
            query = """
                INSERT INTO daily_summary (date, total_morning, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_morning = excluded.total_morning,
                    updated_at = excluded.updated_at
            """
            
            cursor.execute(query, (date, total_morning, updated_at_str))
            self._conn.commit()
            
            logger.debug(f"Daily summary upserted: date={date}, total_morning={total_morning}")
            return True
            
        except sqlite3.OperationalError as e:
            if self._conn:
                try:
                    self._conn.rollback()
                except:
                    pass
            logger.error(f"SQLite operational error upserting daily summary: {e}", exc_info=False)
            return False
        except Exception as e:
            if self._conn:
                try:
                    self._conn.rollback()
                except:
                    pass
            logger.error(f"Failed to upsert daily summary: {e}", exc_info=False)
            return False
    
    def close(self):
        """Close SQLite connection."""
        if self._conn:
            try:
                self._conn.close()
                logger.info("SQLite connection closed")
            except Exception as e:
                logger.warning(f"Error closing SQLite connection: {e}")
            finally:
                self._conn = None
                self._initialized = False

