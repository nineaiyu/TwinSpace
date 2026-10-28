"""Parsing and human-friendly rendering of "last opened" timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

from twinspace.core.i18n import t


def parse_iso_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, assuming UTC when no zone is present."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_last_opened(
    value: str | None,
    *,
    compact: bool = False,
    now: datetime | None = None,
) -> str:
    """Describe when an app was last opened.

    ``compact`` drops the leading verb for the tight app tiles and table cells,
    e.g. "今天 5:30" instead of "今天 5:30 打开". Returns an empty string when
    ``value`` is missing or is not a timestamp.
    """
    opened = parse_iso_timestamp(value)
    if opened is None:
        return ""

    local = opened.astimezone()
    reference = now.astimezone() if now is not None else datetime.now().astimezone()
    days = (reference.date() - local.date()).days
    clock = f"{local.hour}:{local.minute:02d}"

    if days <= 0:
        key = "last_opened_short_today" if compact else "last_opened_today"
    elif days == 1:
        key = "last_opened_short_yesterday" if compact else "last_opened_yesterday"
    elif days == 2:
        key = "last_opened_short_day_before" if compact else "last_opened_day_before"
    else:
        key = "last_opened_short_days_ago" if compact else "last_opened_days_ago"

    return t(key, time=clock, days=days)
