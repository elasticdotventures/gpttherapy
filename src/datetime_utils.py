"""
Centralized datetime utilities using modern datetime libraries.

This module provides consistent, timezone-aware datetime handling throughout
the GPTTherapy application, replacing manual datetime manipulation with
robust, tested library functionality.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import whenever


def utc_now() -> whenever.Instant:
    """Get current UTC time as a whenever.Instant."""
    return whenever.Instant.now()


def utc_now_iso() -> str:
    """Get current UTC time as ISO 8601 string."""
    return utc_now().format_common_iso()


def utc_now_filename() -> str:
    """Get current UTC time formatted for filenames (YYYYMMDD_HHMMSS)."""
    # Convert to Python datetime for strftime formatting
    dt = utc_now().py_datetime()
    return dt.strftime("%Y%m%d_%H%M%S")


def parse_email_date(date_string: str) -> whenever.Instant:
    """
    Parse email date string to whenever.Instant with proper fallback.

    Args:
        date_string: Email date header value

    Returns:
        whenever.Instant representing the parsed time, or current time if parsing fails
    """
    if not date_string or not date_string.strip():
        return utc_now()

    try:
        # Use stdlib email parsing first (handles RFC 2822 format)
        parsed_dt = parsedate_to_datetime(date_string)

        # Ensure timezone awareness
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=UTC)

        # Convert to whenever.Instant
        return whenever.Instant.from_py_datetime(parsed_dt)

    except (ValueError, TypeError, AttributeError):
        # Fallback: try whenever's parsing capabilities
        try:
            return whenever.Instant.parse_common_iso(date_string)
        except Exception:
            # Last resort: current time
            return utc_now()


def parse_iso_timestamp(iso_string: str) -> whenever.Instant | None:
    """
    Parse ISO 8601 timestamp string to whenever.Instant.

    Args:
        iso_string: ISO 8601 formatted timestamp

    Returns:
        whenever.Instant or None if parsing fails
    """
    if not iso_string or not iso_string.strip():
        return None

    try:
        return whenever.Instant.parse_common_iso(iso_string)
    except Exception:
        return None


def datetime_to_instant(dt: datetime) -> whenever.Instant:
    """
    Convert stdlib datetime to whenever.Instant.

    Args:
        dt: datetime object (will be assumed UTC if naive)

    Returns:
        whenever.Instant
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return whenever.Instant.from_py_datetime(dt)


def time_since(timestamp: str) -> whenever.TimeDelta:
    """
    Calculate time elapsed since an ISO timestamp.

    Args:
        timestamp: ISO 8601 timestamp string

    Returns:
        whenever.TimeDelta representing elapsed time
    """
    past_time = parse_iso_timestamp(timestamp)
    if past_time is None:
        return whenever.hours(0)  # No time elapsed if can't parse

    return utc_now() - past_time


def is_older_than(timestamp: str, hours: int) -> bool:
    """
    Check if a timestamp is older than the specified number of hours.

    Args:
        timestamp: ISO 8601 timestamp string
        hours: Number of hours to check against

    Returns:
        True if timestamp is older than specified hours
    """
    elapsed = time_since(timestamp)
    return elapsed > whenever.hours(hours)


def format_duration(delta: whenever.TimeDelta) -> str:
    """
    Format a TimeDelta into a human-readable string.

    Args:
        delta: TimeDelta to format

    Returns:
        Human-readable duration string
    """
    total_seconds = int(delta.in_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}m"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return f"{days}d {hours}h" if hours > 0 else f"{days}d"


def ensure_utc_instant(
    value: datetime | whenever.Instant | str | None,
) -> whenever.Instant:
    """
    Convert various time representations to UTC whenever.Instant.

    Args:
        value: datetime, whenever.Instant, ISO string, or None

    Returns:
        whenever.Instant in UTC
    """
    if value is None:
        return utc_now()

    if isinstance(value, whenever.Instant):
        return value

    if isinstance(value, datetime):
        return datetime_to_instant(value)

    if isinstance(value, str):
        parsed = parse_iso_timestamp(value)
        return parsed if parsed is not None else utc_now()

    # Fallback for unknown types
    return utc_now()


class TimestampManager:
    """
    Centralized timestamp management for consistent datetime handling.

    Replaces manual timestamp creation throughout the codebase with
    a single source of truth for datetime operations.
    """

    @staticmethod
    def now() -> str:
        """Get current UTC timestamp as ISO 8601 string."""
        return utc_now_iso()

    @staticmethod
    def filename_timestamp() -> str:
        """Get timestamp formatted for filenames."""
        return utc_now_filename()

    @staticmethod
    def parse_email_date(date_string: str) -> str:
        """Parse email date and return as ISO string."""
        return parse_email_date(date_string).format_common_iso()

    @staticmethod
    def is_expired(timestamp: str, timeout_hours: int) -> bool:
        """Check if timestamp has exceeded timeout period."""
        return is_older_than(timestamp, timeout_hours)

    @staticmethod
    def time_until_timeout(timestamp: str, timeout_hours: int) -> str:
        """Get human-readable time remaining until timeout."""
        elapsed = time_since(timestamp)
        timeout_delta = whenever.hours(timeout_hours)

        if elapsed >= timeout_delta:
            return "expired"

        remaining = timeout_delta - elapsed
        return format_duration(remaining)

    @staticmethod
    def age_description(timestamp: str) -> str:
        """Get human-readable age of timestamp."""
        return format_duration(time_since(timestamp))


# Convenience instance for global use
timestamps = TimestampManager()


# Backward compatibility aliases
def get_utc_timestamp() -> str:
    """Backward compatibility alias for utc_now_iso()."""
    return utc_now_iso()


def get_filename_timestamp() -> str:
    """Backward compatibility alias for utc_now_filename()."""
    return utc_now_filename()
