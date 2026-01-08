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
    Calculate TOTAL MORNING: Net number of people during morning phase (IN - OUT).
    
    Definition: total_morning = (IN events - OUT events) during morning_start and morning_end.
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
        morning_start: Morning start time in HH:MM format
        morning_end: Morning end time in HH:MM format
    
    Returns:
        Total morning count (IN - OUT during morning phase)
    """
    try:
        start_hour, start_min = map(int, morning_start.split(':'))
        end_hour, end_min = map(int, morning_end.split(':'))
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min
        
        # Handle ISO 8601 timestamp format with timezone (e.g., '2026-01-07T11:05:01+07:00')
        # Calculate IN - OUT (not just IN count)
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN UPPER(direction) = 'IN' THEN 1 ELSE 0 END) as in_count,
                SUM(CASE WHEN UPPER(direction) = 'OUT' THEN 1 ELSE 0 END) as out_count
            FROM events
            WHERE substr(timestamp, 1, 10) = ?
              AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
              AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
        """, (target_date, start_minutes, end_minutes))
        
        result = cursor.fetchone()
        in_count = result[0] if result and result[0] else 0
        out_count = result[1] if result and result[1] else 0
        
        total_morning = in_count - out_count
        
        logger.debug(f"Total Morning for {target_date}: {total_morning} (IN: {in_count} - OUT: {out_count} between {morning_start}-{morning_end})")
        return total_morning
        
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


def get_alerts(cursor: sqlite3.Cursor, target_date: str, total_morning: int = 0) -> List[Dict]:
    """
    Get ALERTS from alert_logs table.
    If no alerts exist, create alerts from missing_periods (for Excel export).
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
        total_morning: Total morning count (for creating alerts from missing_periods)
    
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
        
        # If no alerts but there are missing_periods, create alerts from missing_periods
        if not alerts:
            missing_periods = get_missing_periods(cursor, target_date, total_morning)
            if missing_periods:
                logger.info(f"No alerts in alert_logs, creating {len(missing_periods)} alerts from missing_periods")
                for period in missing_periods:
                    # Use start_time as alert_time
                    alert_time = period.get('start_time', '')
                    if alert_time:
                        # Calculate missing from period duration (estimate)
                        duration_minutes = period.get('duration_minutes', 0)
                        # Estimate missing count (assume 1 person per 30 minutes)
                        estimated_missing = max(1, duration_minutes // 30) if duration_minutes >= 30 else 0
                        
                        if estimated_missing > 0:
                            alerts.append({
                                'alert_time': alert_time,
                                'total_morning': total_morning,
                                'realtime': max(0, total_morning - estimated_missing),  # Estimate
                                'missing': estimated_missing
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


def get_daily_state(cursor: sqlite3.Cursor, target_date: str) -> Optional[Dict]:
    """
    Get daily_state from database (frozen values).
    
    Args:
        cursor: Database cursor
        target_date: Date in YYYY-MM-DD format
    
    Returns:
        Dict with total_morning, realtime_in, realtime_out, is_frozen, or None
    """
    try:
        cursor.execute("""
            SELECT total_morning, realtime_in, realtime_out, is_frozen, updated_at
            FROM daily_state
            WHERE date = ?
        """, (target_date,))
        
        row = cursor.fetchone()
        if row:
            return {
                'total_morning': row[0] if row[0] is not None else 0,
                'realtime_in': row[1] if row[1] is not None else 0,
                'realtime_out': row[2] if row[2] is not None else 0,
                'is_frozen': bool(row[3]) if row[3] is not None else False,
                'updated_at': row[4] if len(row) > 4 else None
            }
    except sqlite3.OperationalError as e:
        # Table might not exist or column names different
        logger.debug(f"daily_state table query failed: {e}")
    except Exception as e:
        logger.warning(f"Error getting daily_state: {e}")
    
    return None


def get_all_data_for_date(
    cursor: sqlite3.Cursor, 
    target_date: str, 
    morning_start: str, 
    morning_end: str
) -> Dict:
    """
    Get all data for a specific date.
    
    CRITICAL: total_morning must be taken from daily_state (frozen value) if available.
    Only calculate from events if daily_state doesn't exist or total_morning is None.
    
    Returns a dict with:
    - total_morning: int (from daily_state if frozen, else calculated)
    - realtime: int (calculated from daily_state or events)
    - missing: int (never negative)
    - missing_periods: List[Dict]
    - alerts: List[Dict]
    - events: List[Dict]
    - last_updated: str (timestamp of last event or current time)
    """
    # PRIORITY 1: Get from daily_state (frozen value - most accurate)
    daily_state = get_daily_state(cursor, target_date)
    
    # CRITICAL: Use daily_state.total_morning if it exists AND is_frozen=True
    # BUT: Verify if total_morning=0 but there are events in morning phase (might be wrong if app restarted)
    if daily_state and daily_state.get('is_frozen') and daily_state.get('total_morning') is not None:
        total_morning_frozen = daily_state['total_morning']
        
        # VERIFY: If total_morning=0 but there are events in morning phase, recalculate (app may have restarted)
        if total_morning_frozen == 0:
            total_morning_from_events = get_total_morning(cursor, target_date, morning_start, morning_end)
            if total_morning_from_events > 0:
                # There are events but total_morning=0 - likely app restarted, use calculated value
                total_morning = total_morning_from_events
                logger.warning(f"total_morning=0 in daily_state but events found ({total_morning_from_events}), using calculated value (app may have restarted)")
            else:
                # No events, 0 is correct
                total_morning = 0
                logger.info(f"Using frozen total_morning from daily_state: 0 (no events in morning phase)")
        else:
            # Use frozen value (non-zero)
            total_morning = total_morning_frozen
            logger.info(f"Using frozen total_morning from daily_state: {total_morning}")
    else:
        # FALLBACK: Calculate from events (if not frozen yet or doesn't exist)
        total_morning = get_total_morning(cursor, target_date, morning_start, morning_end)
        if daily_state and daily_state.get('total_morning') == 0 and not daily_state.get('is_frozen'):
            logger.info(f"Calculated total_morning from events: {total_morning} (daily_state exists but not frozen yet)")
        else:
            logger.info(f"Calculated total_morning from events: {total_morning} (no daily_state or not frozen)")
    
    # Calculate realtime: Use daily_state if available, else calculate from events
    # CRITICAL: realtime = total_morning (frozen) + (realtime_in - realtime_out)
    # But if total_morning is 0 (not saved yet), calculate from all events
    if daily_state and daily_state.get('total_morning') is not None and daily_state.get('is_frozen'):
        # Use frozen total_morning + realtime changes
        realtime = total_morning + (daily_state.get('realtime_in', 0) - daily_state.get('realtime_out', 0))
        # Ensure realtime is never negative
        realtime = max(0, realtime)
        logger.info(f"Using realtime from daily_state: {realtime} (total_morning={total_morning}, realtime_in={daily_state.get('realtime_in', 0)}, realtime_out={daily_state.get('realtime_out', 0)})")
    else:
        # Fallback: Calculate from all events (if total_morning not frozen yet)
        realtime = get_realtime_count(cursor, target_date)
        # Ensure realtime is never negative
        realtime = max(0, realtime)
        logger.info(f"Calculated realtime from events: {realtime}")
    
    # Calculate missing count: missing = total_morning - realtime
    missing = total_morning - realtime
    # Ensure missing is never negative
    missing = max(0, missing)
    
    missing_periods = get_missing_periods(cursor, target_date, total_morning)
    alerts = get_alerts(cursor, target_date, total_morning)  # Pass total_morning to create alerts from missing_periods if needed
    events = get_events(cursor, target_date)
    
    # Last updated: Use daily_state.updated_at if available, else last event time
    if daily_state and daily_state.get('updated_at'):
        last_updated = daily_state['updated_at']
    else:
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

