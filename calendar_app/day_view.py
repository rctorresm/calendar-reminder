"""Pure helpers for the main window's day-by-day calendar view.

How the view gets its data:

* Today: the existing list, read from the local cache that the
  once-a-minute sync keeps fresh (upcoming meetings with a countdown). No
  extra API calls.
* Any other day: fetched from Google on demand, only when someone
  actually navigates to that day — one small events.list call per
  monitored calendar, covering just that one day. Kept in memory for
  DAY_CACHE_SECONDS (never written to the database), so flipping back and
  forth between days doesn't re-download them every click.

Navigation is limited to MAX_DAYS_EACH_WAY before/after today.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

MAX_DAYS_EACH_WAY = 730  # ~24 months back and forward
DAY_CACHE_SECONDS = 5 * 60


@dataclass(frozen=True)
class DayEvent:
    calendar_id: str
    calendar_name: str
    flash_color: str
    title: str
    start: datetime  # timezone-aware UTC
    end: datetime | None
    location: str | None
    is_all_day: bool
    html_link: str | None


def local_today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone().date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[local midnight starting `day`, local midnight ending it), as UTC.
    Built from the local date (naive .astimezone() = this machine's
    timezone) so a DST-change day is 23 or 25 hours long, as it should be."""
    start = datetime.combine(day, time()).astimezone().astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time()).astimezone().astimezone(timezone.utc)
    return start, end


def clamp_day(day: date, today: date) -> date:
    earliest = today - timedelta(days=MAX_DAYS_EACH_WAY)
    latest = today + timedelta(days=MAX_DAYS_EACH_WAY)
    return min(max(day, earliest), latest)


def sort_day_events(events: list[DayEvent]) -> list[DayEvent]:
    """All-day items first (like Google Calendar), then by start time."""
    return sorted(events, key=lambda e: (not e.is_all_day, e.start, e.title.lower()))


def format_day_heading(day: date, today: date) -> str:
    delta = (day - today).days
    label = f"{day.strftime('%A, %B')} {day.day}, {day.year}"
    if delta == 0:
        return f"Today — {label}"
    if delta == 1:
        return f"Tomorrow — {label}"
    if delta == -1:
        return f"Yesterday — {label}"
    return label


class DayCache:
    """Per-day results kept for a few minutes. Keys are whatever the
    caller wants (the main window uses (day, selected calendar ids), so
    ticking a calendar on or off never shows a stale list). `clock` is
    injectable so the expiry can be tested without sleeping."""

    def __init__(self, ttl_seconds: float = DAY_CACHE_SECONDS, clock=_time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[object, tuple[float, list[DayEvent]]] = {}

    def get(self, key) -> list[DayEvent] | None:
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] > self._ttl:
            return None
        return entry[1]

    def stale(self, key) -> list[DayEvent] | None:
        """The last result for `key` even if expired — shown while a fresh
        copy downloads, so the list doesn't blink empty every few minutes."""
        entry = self._entries.get(key)
        return entry[1] if entry else None

    def put(self, key, events: list[DayEvent]) -> None:
        self._entries[key] = (self._clock(), events)

    def clear(self) -> None:
        self._entries.clear()
