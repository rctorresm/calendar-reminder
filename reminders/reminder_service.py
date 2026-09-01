"""Reminder decision logic.

`find_due_events` is pure (no DB, no clock, no I/O) so it can be unit
tested directly. `run_reminder_cycle` wires it to the database and the
notifier.

Design note on the "tolerance window" from the spec: rather than only
firing within a narrow band around the exact threshold (e.g. 14-16 minutes
for a 15-minute reminder), this fires for the *entire* window from "now"
through the threshold: 0 <= minutes_until_start <= threshold. Combined with
the notifications table (event_id + calendar_id + start_time) as the
dedupe key, this is strictly safer than a narrow band:

* A slow/delayed poll cycle can never skip past a narrow window and miss
  the event entirely.
* Waking from sleep 3 minutes before an event still notifies immediately
  (spec section 34) — no separate code path needed.
* Duplicate prevention still guarantees exactly one notification per
  (event, start time), because after the first notification the DB check
  short-circuits every later cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_REMINDER_MINUTES = 15


@dataclass(frozen=True)
class DueEvent:
    event_id: str
    calendar_id: str
    calendar_name: str
    title: str
    start: datetime
    location: str | None
    minutes_until_start: float


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def end_of_local_day(now: datetime) -> datetime:
    """UTC-aware timestamp for local midnight tonight — the start of
    tomorrow in the machine's own timezone. Used to bound syncing and
    display to 'just today' rather than a rolling 24-hour window from
    whatever moment 'now' happens to be, which would bleed into
    tomorrow."""
    local_now = now.astimezone()
    local_midnight_tonight = (local_now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_midnight_tonight.astimezone(timezone.utc)


def find_due_events(events, now: datetime, threshold_minutes: int) -> list[DueEvent]:
    """events: iterable of row-like objects with event_id, calendar_id,
    calendar_name, title, start_time (ISO string), location, status,
    is_all_day. Returns events whose start is between now and
    now + threshold_minutes, inclusive, not started, not cancelled, not
    all-day."""
    due: list[DueEvent] = []
    for e in events:
        if e["status"] == "cancelled" or e["is_all_day"]:
            continue
        start = _parse_iso(e["start_time"])
        minutes_until = (start - now).total_seconds() / 60
        if 0 <= minutes_until <= threshold_minutes:
            due.append(
                DueEvent(
                    event_id=e["event_id"],
                    calendar_id=e["calendar_id"],
                    calendar_name=e["calendar_name"],
                    title=e["title"],
                    start=start,
                    location=e["location"],
                    minutes_until_start=minutes_until,
                )
            )
    return due


def run_reminder_cycle(
    db, notifier, now: datetime | None = None, account_email: str | None = None
) -> list[DueEvent]:
    now = now or datetime.now(timezone.utc)
    threshold_minutes = int(db.get_setting("reminder_minutes", str(DEFAULT_REMINDER_MINUTES)))
    horizon = now + timedelta(minutes=threshold_minutes + 5)

    events = db.upcoming_events(now.isoformat(), horizon.isoformat(), account_email)
    due = find_due_events(events, now, threshold_minutes)

    notified: list[DueEvent] = []
    for event in due:
        if db.was_notified(event.event_id, event.calendar_id, event.start.isoformat()):
            continue
        notifier.notify(event)
        db.mark_notified(
            event.event_id,
            event.calendar_id,
            event.start.isoformat(),
            now.isoformat(),
            datetime.now(timezone.utc).isoformat(),
        )
        notified.append(event)

    db.prune_old_notifications((now - timedelta(days=1)).isoformat())
    return notified


def detect_long_gap(
    last_tick: datetime, now: datetime, expected_interval_seconds: float, multiplier: float = 3.0
) -> bool:
    """True if wall-clock time jumped further than a normal poll interval
    would explain — the signal that the machine was asleep and we should
    sync + check reminders immediately instead of waiting for the next
    scheduled tick (spec section 34)."""
    return (now - last_tick).total_seconds() > expected_interval_seconds * multiplier
