"""UTC helpers shared by the backend modules."""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC and convert aware ones."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_utc(text: str) -> datetime:
    """Parse an ISO-8601 string (optional trailing Z) to an aware UTC datetime."""
    return as_utc(datetime.fromisoformat(text.strip().replace("Z", "+00:00")))


def iso_ms(value: datetime) -> str:
    """Format as YYYY-MM-DDTHH:MM:SS.mmmZ (milliseconds truncated)."""
    return f"{value.strftime('%Y-%m-%dT%H:%M:%S')}.{value.microsecond // 1000:03d}Z"
