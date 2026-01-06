"""PostgreSQL client with connection pooling."""

import logging
from typing import Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class PostgresClient:
    """PostgreSQL client with connection pooling for production use."""
    
    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        min_connections: int = 1,
        max_connections: int = 10,
    ):
        """
        Initialize PostgreSQL connection pool.
        
        Args:
            host: Database host
            port: Database port
            database: Database name
            user: Database user
            password: Database password
            min_connections: Minimum pool connections
            max_connections: Maximum pool connections
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.min_connections = min_connections
        self.max_connections = max_connections
        
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._init_pool()
        self._init_schema()
    
    def _init_pool(self):
        """Initialize connection pool."""
        try:
            self._pool = pool.ThreadedConnectionPool(
                self.min_connections,
                self.max_connections,
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
            )
            logger.info(
                f"PostgreSQL connection pool initialized: "
                f"{self.host}:{self.port}/{self.database} "
                f"(pool: {self.min_connections}-{self.max_connections})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
            raise
    
    def _init_schema(self):
        """Initialize database schema (events table)."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            
            # Create events table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    track_id INTEGER NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    camera_id VARCHAR(100) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp 
                ON events(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_date 
                ON events(DATE(timestamp))
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_camera_id 
                ON events(camera_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_direction 
                ON events(direction)
            """)
            
            conn.commit()
            logger.info("PostgreSQL schema initialized (events table)")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to initialize schema: {e}")
            raise
        finally:
            self.put_connection(conn)
    
    def get_connection(self):
        """Get a connection from the pool."""
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")
        
        try:
            conn = self._pool.getconn()
            if conn is None:
                raise RuntimeError("Failed to get connection from pool")
            return conn
        except Exception as e:
            logger.error(f"Failed to get connection from pool: {e}")
            raise
    
    def put_connection(self, conn):
        """Return a connection to the pool."""
        if self._pool is None:
            return
        
        try:
            self._pool.putconn(conn)
        except Exception as e:
            logger.error(f"Failed to return connection to pool: {e}")
            try:
                conn.close()
            except:
                pass
    
    def execute_query(self, query: str, params: tuple = None):
        """Execute a query and return results."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            results = cursor.fetchall()
            conn.commit()
            return results
        except Exception as e:
            conn.rollback()
            logger.error(f"Query execution failed: {e}")
            raise
        finally:
            self.put_connection(conn)
    
    def execute_insert(self, query: str, params: tuple = None) -> int:
        """Execute an INSERT query and return the inserted row ID."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row_id = cursor.fetchone()[0]  # RETURNING id
            conn.commit()
            return row_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Insert execution failed: {e}")
            raise
        finally:
            self.put_connection(conn)
    
    def close_all(self):
        """Close all connections in the pool."""
        if self._pool:
            self._pool.closeall()
            logger.info("PostgreSQL connection pool closed")

