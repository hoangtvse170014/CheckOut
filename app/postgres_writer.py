"""PostgreSQL event writer with non-blocking queue-based insertion."""

import logging
import queue
import threading
from datetime import datetime
from typing import Optional
import pytz

from app.postgres_client import PostgresClient

logger = logging.getLogger(__name__)


class PostgresWriter:
    """Non-blocking event writer using background thread and queue."""
    
    def __init__(self, postgres_client: PostgresClient, timezone: str = "Asia/Bangkok"):
        """
        Initialize PostgreSQL writer.
        
        Args:
            postgres_client: Initialized PostgresClient instance
            timezone: Timezone for timestamps
        """
        self.client = postgres_client
        self.timezone = pytz.timezone(timezone)
        
        # Queue for events (thread-safe)
        self.event_queue = queue.Queue(maxsize=1000)
        
        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        
        # Statistics
        self._stats = {
            "events_written": 0,
            "events_failed": 0,
            "queue_size": 0,
        }
    
    def start(self):
        """Start the background writer thread."""
        if self._running:
            logger.warning("PostgresWriter already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        logger.info("PostgresWriter started")
    
    def stop(self, timeout: float = 5.0):
        """Stop the background writer thread and flush queue."""
        if not self._running:
            return
        
        logger.info("Stopping PostgresWriter, flushing queue...")
        self._running = False
        self._stop_event.set()
        
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning("PostgresWriter thread did not stop within timeout")
        
        logger.info(
            f"PostgresWriter stopped. Stats: "
            f"written={self._stats['events_written']}, "
            f"failed={self._stats['events_failed']}"
        )
    
    def add_event(
        self,
        track_id: int,
        direction: str,
        camera_id: str,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Add an event to the write queue (non-blocking).
        
        Args:
            track_id: Track ID
            direction: 'in' or 'out'
            camera_id: Camera identifier
            timestamp: Event timestamp (defaults to now)
        
        Returns:
            True if queued successfully, False if queue is full
        """
        if not self._running:
            logger.warning("PostgresWriter not running, event discarded")
            return False
        
        if timestamp is None:
            timestamp = datetime.now(self.timezone)
        else:
            # Ensure timezone-aware
            if timestamp.tzinfo is None:
                timestamp = self.timezone.localize(timestamp)
        
        event = {
            "track_id": track_id,
            "direction": direction.lower(),
            "camera_id": camera_id,
            "timestamp": timestamp,
        }
        
        try:
            self.event_queue.put_nowait(event)
            return True
        except queue.Full:
            logger.warning("Event queue is full, event discarded")
            self._stats["events_failed"] += 1
            return False
    
    def _worker(self):
        """Background worker thread that processes events from queue."""
        logger.info("PostgresWriter worker thread started")
        
        while self._running or not self.event_queue.empty():
            try:
                # Wait for event with timeout to allow checking stop event
                try:
                    event = self.event_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Insert event into database
                try:
                    self._insert_event(event)
                    self._stats["events_written"] += 1
                except Exception as e:
                    logger.error(f"Failed to insert event: {e}", exc_info=True)
                    self._stats["events_failed"] += 1
                
                self.event_queue.task_done()
            except Exception as e:
                logger.error(f"Error in PostgresWriter worker: {e}", exc_info=True)
        
        logger.info("PostgresWriter worker thread stopped")
    
    def _insert_event(self, event: dict):
        """Insert a single event into PostgreSQL."""
        query = """
            INSERT INTO events (timestamp, track_id, direction, camera_id, created_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """
        params = (
            event["timestamp"],
            event["track_id"],
            event["direction"],
            event["camera_id"],
            event["timestamp"],
        )
        
        event_id = self.client.execute_insert(query, params)
        logger.debug(
            f"Event inserted: id={event_id}, track_id={event['track_id']}, "
            f"direction={event['direction']}"
        )
    
    def get_stats(self) -> dict:
        """Get writer statistics."""
        self._stats["queue_size"] = self.event_queue.qsize()
        return self._stats.copy()
    
    def flush(self, timeout: float = 5.0):
        """Wait for all queued events to be written."""
        logger.info(f"Flushing event queue (size: {self.event_queue.qsize()})")
        self.event_queue.join()  # Wait for all tasks to complete
        logger.info("Event queue flushed")

