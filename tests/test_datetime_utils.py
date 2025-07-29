"""
Tests for datetime utilities module.

Verifies that the new datetime handling using whenever library
works correctly and provides consistent, timezone-aware timestamps.
"""

from datetime import UTC, datetime

import whenever

from src.datetime_utils import (
    datetime_to_instant,
    ensure_utc_instant,
    format_duration,
    is_older_than,
    parse_email_date,
    parse_iso_timestamp,
    time_since,
    timestamps,
    utc_now,
    utc_now_filename,
    utc_now_iso,
)


class TestBasicDateTimeFunctions:
    """Test basic datetime utility functions."""

    def test_utc_now_returns_instant(self) -> None:
        """Test that utc_now returns a whenever.Instant."""
        now = utc_now()
        assert isinstance(now, whenever.Instant)

    def test_utc_now_iso_format(self) -> None:
        """Test that utc_now_iso returns proper ISO format."""
        iso_string = utc_now_iso()

        # Should be a string
        assert isinstance(iso_string, str)

        # Should end with Z (UTC marker)
        assert iso_string.endswith("Z")

        # Should be parseable back to an Instant
        parsed = whenever.Instant.parse_common_iso(iso_string)
        assert isinstance(parsed, whenever.Instant)

    def test_utc_now_filename_format(self) -> None:
        """Test filename timestamp format."""
        filename_ts = utc_now_filename()

        # Should match YYYYMMDD_HHMMSS format
        assert len(filename_ts) == 15
        assert filename_ts[8] == "_"
        assert filename_ts[:8].isdigit()  # YYYYMMDD
        assert filename_ts[9:].isdigit()  # HHMMSS


class TestEmailDateParsing:
    """Test email date parsing functionality."""

    def test_parse_standard_email_date(self) -> None:
        """Test parsing standard RFC 2822 email date."""
        date_str = "Mon, 1 Jan 2023 12:00:00 +0000"
        parsed = parse_email_date(date_str)

        assert isinstance(parsed, whenever.Instant)
        # Should represent 2023-01-01 12:00:00 UTC
        iso_str = parsed.format_common_iso()
        assert "2023-01-01T12:00:00Z" == iso_str

    def test_parse_email_date_with_timezone(self) -> None:
        """Test parsing email date with timezone offset."""
        date_str = "Tue, 2 Jan 2023 15:30:00 -0500"  # EST
        parsed = parse_email_date(date_str)

        assert isinstance(parsed, whenever.Instant)
        # Should be converted to UTC (20:30:00)
        iso_str = parsed.format_common_iso()
        assert "2023-01-02T20:30:00Z" == iso_str

    def test_parse_invalid_email_date_fallback(self) -> None:
        """Test that invalid date strings fall back to current time."""
        invalid_date = "not a valid date"
        parsed = parse_email_date(invalid_date)

        # Should still return an Instant (current time)
        assert isinstance(parsed, whenever.Instant)

        # Should be recent (within last few seconds)
        now = utc_now()
        diff = now - parsed
        assert diff.in_seconds() < 5

    def test_parse_empty_email_date(self) -> None:
        """Test parsing empty or None date string."""
        for empty_val in ["", None, "   "]:
            parsed = parse_email_date(empty_val)
            assert isinstance(parsed, whenever.Instant)


class TestTimestampParsing:
    """Test ISO timestamp parsing."""

    def test_parse_iso_timestamp_valid(self) -> None:
        """Test parsing valid ISO timestamp."""
        iso_str = "2023-01-01T12:00:00Z"
        parsed = parse_iso_timestamp(iso_str)

        assert parsed is not None
        assert isinstance(parsed, whenever.Instant)
        assert parsed.format_common_iso() == iso_str

    def test_parse_iso_timestamp_invalid(self) -> None:
        """Test parsing invalid ISO timestamp."""
        invalid_iso = "not an iso timestamp"
        parsed = parse_iso_timestamp(invalid_iso)

        assert parsed is None

    def test_parse_iso_timestamp_empty(self) -> None:
        """Test parsing empty timestamp."""
        for empty_val in ["", None, "   "]:
            parsed = parse_iso_timestamp(empty_val)
            assert parsed is None


class TestDateTimeConversion:
    """Test datetime conversion utilities."""

    def test_datetime_to_instant_aware(self) -> None:
        """Test converting timezone-aware datetime to Instant."""
        dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        instant = datetime_to_instant(dt)

        assert isinstance(instant, whenever.Instant)
        assert instant.format_common_iso() == "2023-01-01T12:00:00Z"

    def test_datetime_to_instant_naive(self) -> None:
        """Test converting naive datetime to Instant (assumes UTC)."""
        dt = datetime(2023, 1, 1, 12, 0, 0)  # No timezone
        instant = datetime_to_instant(dt)

        assert isinstance(instant, whenever.Instant)
        assert instant.format_common_iso() == "2023-01-01T12:00:00Z"


class TestTimeCalculations:
    """Test time calculation utilities."""

    def test_time_since_calculation(self) -> None:
        """Test time_since calculation."""
        # Create a timestamp from 1 hour ago
        one_hour_ago = utc_now().subtract(hours=1)
        timestamp_str = one_hour_ago.format_common_iso()

        elapsed = time_since(timestamp_str)

        # Should be approximately 1 hour (allowing for small timing differences)
        hours_elapsed = elapsed.in_hours()
        assert 0.99 < hours_elapsed < 1.01

    def test_is_older_than(self) -> None:
        """Test is_older_than check."""
        # Create timestamps
        two_hours_ago = utc_now().subtract(hours=2).format_common_iso()
        thirty_minutes_ago = utc_now().subtract(minutes=30).format_common_iso()

        # Test older than 1 hour
        assert is_older_than(two_hours_ago, 1) is True
        assert is_older_than(thirty_minutes_ago, 1) is False

    def test_format_duration(self) -> None:
        """Test duration formatting."""
        # Test various durations
        assert format_duration(whenever.seconds(30)) == "30s"
        assert format_duration(whenever.minutes(5)) == "5m"
        assert format_duration(whenever.hours(2)) == "2h"
        assert format_duration(whenever.hours(25)) == "1d 1h"

        # Test mixed duration
        duration = whenever.hours(1) + whenever.minutes(30)
        assert format_duration(duration) == "1h 30m"


class TestEnsureUtcInstant:
    """Test ensure_utc_instant conversion function."""

    def test_ensure_instant_from_instant(self) -> None:
        """Test that Instant passes through unchanged."""
        original = utc_now()
        result = ensure_utc_instant(original)
        assert result == original

    def test_ensure_instant_from_datetime(self) -> None:
        """Test conversion from datetime."""
        dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = ensure_utc_instant(dt)

        assert isinstance(result, whenever.Instant)
        assert result.format_common_iso() == "2023-01-01T12:00:00Z"

    def test_ensure_instant_from_string(self) -> None:
        """Test conversion from ISO string."""
        iso_str = "2023-01-01T12:00:00Z"
        result = ensure_utc_instant(iso_str)

        assert isinstance(result, whenever.Instant)
        assert result.format_common_iso() == iso_str

    def test_ensure_instant_from_none(self) -> None:
        """Test that None returns current time."""
        result = ensure_utc_instant(None)

        assert isinstance(result, whenever.Instant)
        # Should be current time (within a few seconds)
        now = utc_now()
        diff = now - result
        assert diff.in_seconds() < 5


class TestTimestampManager:
    """Test the TimestampManager convenience class."""

    def test_timestamp_manager_now(self) -> None:
        """Test TimestampManager.now() method."""
        ts = timestamps.now()

        assert isinstance(ts, str)
        assert ts.endswith("Z")

        # Should be parseable
        parsed = whenever.Instant.parse_common_iso(ts)
        assert isinstance(parsed, whenever.Instant)

    def test_timestamp_manager_filename(self) -> None:
        """Test TimestampManager.filename_timestamp() method."""
        ts = timestamps.filename_timestamp()

        assert isinstance(ts, str)
        assert len(ts) == 15
        assert ts[8] == "_"

    def test_timestamp_manager_parse_email_date(self) -> None:
        """Test TimestampManager.parse_email_date() method."""
        date_str = "Mon, 1 Jan 2023 12:00:00 +0000"
        result = timestamps.parse_email_date(date_str)

        assert isinstance(result, str)
        assert result == "2023-01-01T12:00:00Z"

    def test_timestamp_manager_is_expired(self) -> None:
        """Test TimestampManager.is_expired() method."""
        # Create timestamp from 2 hours ago
        old_timestamp = utc_now().subtract(hours=2).format_common_iso()
        recent_timestamp = utc_now().subtract(minutes=30).format_common_iso()

        assert timestamps.is_expired(old_timestamp, 1) is True
        assert timestamps.is_expired(recent_timestamp, 1) is False

    def test_timestamp_manager_time_until_timeout(self) -> None:
        """Test TimestampManager.time_until_timeout() method."""
        # Create timestamp from 30 minutes ago, with 1 hour timeout
        timestamp = utc_now().subtract(minutes=30).format_common_iso()

        remaining = timestamps.time_until_timeout(timestamp, 1)

        # Should have ~30 minutes remaining
        assert "30m" in remaining or "29m" in remaining or "31m" in remaining

    def test_timestamp_manager_age_description(self) -> None:
        """Test TimestampManager.age_description() method."""
        # Create timestamp from 2 hours ago
        timestamp = utc_now().subtract(hours=2).format_common_iso()

        age = timestamps.age_description(timestamp)

        assert "2h" in age


class TestBackwardCompatibility:
    """Test backward compatibility functions."""

    def test_get_utc_timestamp(self) -> None:
        """Test backward compatibility alias."""
        from src.datetime_utils import get_utc_timestamp

        ts = get_utc_timestamp()
        assert isinstance(ts, str)
        assert ts.endswith("Z")

    def test_get_filename_timestamp(self) -> None:
        """Test backward compatibility alias."""
        from src.datetime_utils import get_filename_timestamp

        ts = get_filename_timestamp()
        assert isinstance(ts, str)
        assert len(ts) == 15
        assert ts[8] == "_"


class TestIntegrationWithExistingCode:
    """Test integration with existing codebase patterns."""

    def test_storage_timestamp_pattern(self) -> None:
        """Test that our timestamps work with storage patterns."""
        # Simulate what storage.py does
        timestamp = timestamps.now()

        # Should be a valid ISO string
        assert isinstance(timestamp, str)
        assert timestamp.endswith("Z")

        # Should be parseable back
        parsed = parse_iso_timestamp(timestamp)
        assert parsed is not None

    def test_email_parser_timestamp_pattern(self) -> None:
        """Test that our timestamps work with email parser patterns."""
        # Simulate email date parsing
        email_date = "Mon, 1 Jan 2023 15:30:00 -0500"
        parsed_instant = parse_email_date(email_date)
        python_dt = parsed_instant.py_datetime()

        # Should be a valid Python datetime
        assert isinstance(python_dt, datetime)
        assert python_dt.tzinfo is not None  # Should be timezone-aware

    def test_monitoring_timestamp_pattern(self) -> None:
        """Test that our timestamps work with monitoring patterns."""
        # Simulate monitoring timestamp creation
        timestamp = timestamps.now()

        # Should work in monitoring contexts
        assert isinstance(timestamp, str)
        assert len(timestamp) > 19  # ISO format is at least 20 chars
