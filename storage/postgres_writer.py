"""PostgreSQL event writer with connection pooling and reconnection handling."""

import logging
import os
from datetime import datetime
from typing import Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extensions import connection
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class PostgresWriter:
    """PostgreSQL writer for people events with connection pooling."""
    
    def __init__(self):
        """Initialize PostgreSQL connection pool from environment variables."""
        # Read configuration from environment variables
        self.host = os.getenv("POSTGRES_HOST", "localhost")
        self.port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = os.getenv("POSTGRES_DATABASE", "people_counter")
        self.user = os.getenv("POSTGRES_USER", "postgres")
        self.password = os.getenv("POSTGRES_PASSWORD", "")
        
        self._pool: Optional[ThreadedConnectionPool] = None
        self._initialized = False
        
        try:
            self._init_pool()
            self._init_schema()
            self._initialized = True
            logger.info(
                f"PostgresWriter initialized: {self.host}:{self.port}/{self.database}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize PostgresWriter: {e}", exc_info=True)
            # Don't raise - allow system to continue without PostgreSQL
            self._initialized = False
    
    def _init_pool(self):
        """Initialize connection pool."""
        try:
            self._pool = ThreadedConnectionPool(
                1,  # min_connections
                5,  # max_connections
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
            )
            logger.debug("PostgreSQL connection pool created")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    
    def _init_schema(self):
        """Initialize database schema (people_events table)."""
        if not self._pool:
            return
        
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Create people_events table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS people_events (
                    id SERIAL PRIMARY KEY,
                    event_time TIMESTAMPTZ NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    camera_id VARCHAR(100) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
            
            conn.commit()
            logger.debug("PostgreSQL schema initialized (people_events table)")
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to initialize schema: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)
    
    def _get_connection(self) -> connection:
        """Get a connection from the pool with reconnection handling."""
        if not self._pool:
            raise RuntimeError("Connection pool not initialized")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = self._pool.getconn()
                if conn is None:
                    raise RuntimeError("Failed to get connection from pool")
                
                # Test connection
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                
                return conn
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logger.warning(
                    f"Connection error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if conn:
                    try:
                        self._pool.putconn(conn, close=True)
                    except:
                        pass
                
                if attempt < max_retries - 1:
                    # Try to recreate pool on last attempt
                    if attempt == max_retries - 2:
                        try:
                            logger.info("Attempting to recreate connection pool...")
                            if self._pool:
                                self._pool.closeall()
                            self._init_pool()
                        except Exception as pool_error:
                            logger.error(f"Failed to recreate pool: {pool_error}")
                else:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error getting connection: {e}", exc_info=True)
                raise
    
    def _put_connection(self, conn: connection, close: bool = False):
        """Return a connection to the pool."""
        if not self._pool or not conn:
            return
        
        try:
            if close:
                conn.close()
            else:
                self._pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")
            try:
                conn.close()
            except:
                pass
    
    def write_event(
        self,
        event_time: datetime,
        direction: str,
        camera_id: str,
    ) -> bool:
        """
        Write an event to PostgreSQL (non-blocking, handles errors gracefully).
        
        Args:
            event_time: Event timestamp
            direction: Event direction ('in' or 'out')
            camera_id: Camera identifier
        
        Returns:
            True if written successfully, False otherwise (errors are logged)
        """
        if not self._initialized or not self._pool:
            return False
        
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = """
                INSERT INTO people_events (event_time, direction, camera_id, created_at)
                VALUES (%s, %s, %s, %s)
            """
            
            # Ensure event_time is timezone-aware
            if event_time.tzinfo is None:
                # Assume UTC if no timezone info
                from datetime import timezone
                event_time = event_time.replace(tzinfo=timezone.utc)
            
            from datetime import timezone as tz
            created_at = datetime.now(tz.utc) if event_time.tzinfo else datetime.now()
            cursor.execute(query, (event_time, direction.lower(), camera_id, created_at))
            conn.commit()
            
            logger.debug(f"Event written to PostgreSQL: {direction} at {event_time}")
            return True
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            logger.error(f"Failed to write event to PostgreSQL: {e}", exc_info=False)
            return False
        finally:
            if conn:
                self._put_connection(conn)
    
    def close(self):
        """Close all connections in the pool."""
        if self._pool:
            try:
                self._pool.closeall()
                logger.info("PostgreSQL connection pool closed")
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}")
            finally:
                self._pool = None
                self._initialized = False

