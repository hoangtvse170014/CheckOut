"""
Read-only database queries for Excel export.
SQLite is the single source of truth.
"""

import sqlite3
import logging
from datetime import datetime, time as dt_time
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def get_total_morning(cursor: sqlite3.Cursor, target_date: str, morning_start: str, morning_end: str) -> int:
    """
    Calculate TOTAL MORNING: Total number of people who entered during morning phase.
    
    Definition: Events where direction='IN' and event_time between morning_start and morning_end.
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
        morning_start: Morning start time in HH:MM format
        morning_end: Morning end time in HH:MM format
    
    Returns:
        Total morning count (IN events during morning phase)
    """
    try:
        start_hour, start_min = map(int, morning_start.split(':'))
        end_hour, end_min = map(int, morning_end.split(':'))
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min
        
        # Handle ISO 8601 timestamp format with timezone (e.g., '2026-01-07T11:05:01+07:00')
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM events
            WHERE substr(timestamp, 1, 10) = ?
              AND UPPER(direction) = 'IN'
              AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
              AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
        """, (target_date, start_minutes, end_minutes))
        
        result = cursor.fetchone()
        count = result[0] if result else 0
        
        logger.debug(f"Total Morning for {target_date}: {count} (IN events between {morning_start}-{morning_end})")
        return count
        
    except Exception as e:
        logger.error(f"Error calculating total_morning: {e}", exc_info=True)
        return 0


def get_realtime_count(cursor: sqlite3.Cursor, target_date: str) -> int:
    """
    Calculate REALTIME: Number of people currently inside.
    
    Definition: total IN - total OUT (from all events in the day).
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
    
    Returns:
        Realtime count (IN - OUT)
    """
    try:
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN UPPER(direction) = 'IN' THEN 1 ELSE 0 END) as in_count,
                SUM(CASE WHEN UPPER(direction) = 'OUT' THEN 1 ELSE 0 END) as out_count
            FROM events
            WHERE substr(timestamp, 1, 10) = ?
        """, (target_date,))
        
        result = cursor.fetchone()
        in_count = result[0] if result and result[0] else 0
        out_count = result[1] if result and result[1] else 0
        
        realtime = in_count - out_count
        logger.debug(f"Realtime count for {target_date}: {realtime} (IN: {in_count}, OUT: {out_count})")
        return realtime
        
    except Exception as e:
        logger.error(f"Error calculating realtime count: {e}", exc_info=True)
        return 0


def get_missing_periods(cursor: sqlite3.Cursor, target_date: str, total_morning: int) -> List[Dict]:
    """
    Get MISSING PERIODS from missing_periods table.
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
        total_morning: Total morning count (not used, kept for compatibility)
    
    Returns:
        List of missing period dicts with: start_time, end_time, duration_minutes, session
    """
    try:
        # Get missing periods from database
        cursor.execute("""
            SELECT start_time, end_time, duration_minutes, session, alert_sent
            FROM missing_periods
            WHERE substr(start_time, 1, 10) = ?
            ORDER BY start_time ASC
        """, (target_date,))
        
        rows = cursor.fetchall()
        
        periods = []
        for row in rows:
            start_time, end_time, duration_minutes, session, alert_sent = row
            periods.append({
                'start_time': start_time,
                'end_time': end_time if end_time else '',  # Empty string if still active
                'duration_minutes': duration_minutes if duration_minutes else 0,
                'session': session,
                'alert_sent': bool(alert_sent) if alert_sent is not None else False,
            })
        
        return periods
    except sqlite3.Error as e:
        logger.warning(f"Error getting missing periods: {e}")
        return []


def get_alerts(cursor: sqlite3.Cursor, target_date: str) -> List[Dict]:
    """
    Get ALERTS from alert_logs table.
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
    
    Returns:
        List of alert dicts with: alert_time, total_morning, realtime, missing
    """
    try:
        # Check if alert_logs table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='alert_logs'
        """)
        if not cursor.fetchone():
            logger.debug("alert_logs table does not exist")
            return []
        
        cursor.execute("""
            SELECT alert_time, expected_total, current_total, missing
            FROM alert_logs
            WHERE substr(alert_time, 1, 10) = ?
            ORDER BY alert_time ASC
        """, (target_date,))
        
        alerts = []
        for row in cursor.fetchall():
            alert_time, expected_total, current_total, missing = row
            alerts.append({
                'alert_time': alert_time,
                'total_morning': expected_total,  # expected_total is total_morning
                'realtime': current_total,  # current_total is realtime
                'missing': missing
            })
        
        logger.debug(f"Found {len(alerts)} alerts for {target_date}")
        return alerts
        
    except Exception as e:
        logger.error(f"Error getting alerts: {e}", exc_info=True)
        return []


def get_events(cursor: sqlite3.Cursor, target_date: str) -> List[Dict]:
    """
    Get all EVENTS for the day.
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
    
    Returns:
        List of event dicts with: event_time, direction, camera_id
    """
    try:
        cursor.execute("""
            SELECT timestamp, direction, camera_id
            FROM events
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY timestamp ASC
        """, (target_date,))
        
        events = []
        for row in cursor.fetchall():
            event_time, direction, camera_id = row
            events.append({
                'event_time': event_time,
                'direction': direction.upper(),  # Normalize to uppercase
                'camera_id': camera_id or ''
            })
        
        logger.debug(f"Found {len(events)} events for {target_date}")
        return events
        
    except Exception as e:
        logger.error(f"Error getting events: {e}", exc_info=True)
        return []


def get_all_data_for_date(
    cursor: sqlite3.Cursor, 
    target_date: str, 
    morning_start: str, 
    morning_end: str
) -> Dict:
    """
    Get all data for a specific date.
    
    Returns a dict with:
    - total_morning: int
    - realtime: int
    - missing: int (never negative)
    - missing_periods: List[Dict]
    - alerts: List[Dict]
    - events: List[Dict]
    - last_updated: str (timestamp of last event or current time)
    """
    total_morning = get_total_morning(cursor, target_date, morning_start, morning_end)
    realtime = get_realtime_count(cursor, target_date)
    missing = max(0, total_morning - realtime)  # Never negative
    
    missing_periods = get_missing_periods(cursor, target_date, total_morning)
    alerts = get_alerts(cursor, target_date)
    events = get_events(cursor, target_date)
    
    # Last updated: timestamp of last event or current time if no events
    last_updated = events[-1]['event_time'] if events else datetime.now().isoformat()
    
    return {
        'total_morning': total_morning,
        'realtime': realtime,
        'missing': missing,
        'missing_periods': missing_periods,
        'alerts': alerts,
        'events': events,
        'last_updated': last_updated
    }

