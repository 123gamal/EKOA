"""Datetime utility functions — all times are UTC-aware."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware :class:`datetime`.

    Returns:
        ``datetime`` with ``tzinfo`` set to :data:`datetime.timezone.utc`.
    """
    return datetime.now(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 string.

    If the datetime is naïve (no ``tzinfo``), it is assumed to be UTC and
    the ``Z`` suffix is appended.

    Args:
        dt: The datetime to format.

    Returns:
        ISO-8601 formatted string (e.g. ``"2026-07-16T12:05:36+00:00"``).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 formatted string into a timezone-aware datetime.

    Strings that end with ``Z`` are treated as UTC.

    Args:
        value: ISO-8601 datetime string.

    Returns:
        Parsed ``datetime`` with ``tzinfo``.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    # Python's fromisoformat doesn't handle 'Z' until 3.11
    cleaned = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
