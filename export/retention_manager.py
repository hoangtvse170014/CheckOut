"""
Retention manager - automatically deletes daily Excel files older than 5 days.
"""

import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


def cleanup_old_daily_files(daily_dir: str = "exports/daily", retention_days: int = 5) -> Tuple[int, List[str]]:
    """
    Delete daily Excel files older than retention_days.
    
    Args:
        daily_dir: Directory containing daily Excel files
        retention_days: Number of days to retain (default: 5)
    
    Returns:
        Tuple of (deleted_count, deleted_files_list)
    """
    try:
        daily_path = Path(daily_dir)
        if not daily_path.exists():
            logger.debug(f"Daily directory does not exist: {daily_dir}")
            return 0, []
        
        # Calculate cutoff date
        cutoff_date = date.today() - timedelta(days=retention_days)
        
        # Find all daily Excel files
        pattern = "people_counter_*.xlsx"
        daily_files = list(daily_path.glob(pattern))
        
        # Filter out temp files
        daily_files = [f for f in daily_files if not f.name.endswith('.tmp.xlsx')]
        
        deleted_count = 0
        deleted_files = []
        
        for file_path in daily_files:
            try:
                # Parse date from filename (people_counter_YYYY-MM-DD.xlsx)
                file_date = _parse_date_from_filename(file_path.name)
                
                if file_date and file_date < cutoff_date:
                    # File is older than retention period
                    file_path.unlink()
                    deleted_count += 1
                    deleted_files.append(file_path.name)
                    logger.info(f"RETENTION_DELETE: {file_path.name} (date: {file_date}, cutoff: {cutoff_date})")
                    
            except Exception as e:
                logger.warning(f"Error processing file {file_path.name}: {e}")
        
        if deleted_count > 0:
            logger.info(f"RETENTION_CLEANUP: Deleted {deleted_count} file(s) older than {retention_days} days")
        else:
            logger.debug(f"RETENTION_CLEANUP: No files to delete (retention: {retention_days} days)")
        
        return deleted_count, deleted_files
        
    except Exception as e:
        logger.error(f"Error in retention cleanup: {e}", exc_info=True)
        return 0, []


def get_valid_daily_files(daily_dir: str = "exports/daily", max_days: int = 5) -> List[Tuple[date, Path]]:
    """
    Get list of daily Excel files, sorted by date, limited to max_days most recent.
    
    Args:
        daily_dir: Directory containing daily Excel files
        max_days: Maximum number of days to return
    
    Returns:
        List of tuples (date, Path) sorted by date ascending
    """
    try:
        daily_path = Path(daily_dir)
        if not daily_path.exists():
            return []
        
        # Find all daily Excel files
        pattern = "people_counter_*.xlsx"
        daily_files = list(daily_path.glob(pattern))
        
        # Filter out temp files and summary files
        daily_files = [
            f for f in daily_files 
            if not f.name.endswith('.tmp.xlsx') and 'LAST_5_DAYS' not in f.name
        ]
        
        # Parse dates and filter valid files
        files_with_dates = []
        for file_path in daily_files:
            file_date = _parse_date_from_filename(file_path.name)
            if file_date:
                files_with_dates.append((file_date, file_path))
        
        # Sort by date ascending
        files_with_dates.sort(key=lambda x: x[0])
        
        # Return only the most recent max_days files
        if len(files_with_dates) > max_days:
            # Keep only the most recent max_days
            files_with_dates = files_with_dates[-max_days:]
        
        logger.debug(f"Found {len(files_with_dates)} valid daily files (max: {max_days} days)")
        return files_with_dates
        
    except Exception as e:
        logger.error(f"Error getting valid daily files: {e}", exc_info=True)
        return []


def _parse_date_from_filename(filename: str) -> Optional[date]:
    """
    Parse date from filename like 'people_counter_2026-01-07.xlsx'.
    
    Args:
        filename: Filename to parse
    
    Returns:
        date object or None if parsing fails
    """
    try:
        # Remove extension
        name = filename.replace('.xlsx', '').replace('.tmp', '')
        # Extract date part (should be last part after underscore)
        parts = name.split('_')
        if len(parts) >= 3:
            # Date is last 3 parts: YYYY-MM-DD
            date_str = '_'.join(parts[-3:])
            return datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception as e:
        logger.debug(f"Could not parse date from filename {filename}: {e}")
    return None

