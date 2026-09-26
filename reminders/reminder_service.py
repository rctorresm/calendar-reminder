"""Reminder decision logic.

`find_due_events` is pure (no DB, no clock, no I/O) so it can be unit
tested directly. `run_reminder_cycle` wires it to the database and the
notifier.

Design note on the "tolerance window" from the spec: rather than only
firing within a narrow band around the exact threshold (e.g. 14-16 minutes
for a 15-minute reminder), this fires for the *entire* window from "now"
through the threshold: -LATE_POLL_GRACE_MINUTES <= minutes_until_start <=
threshold. Combined with the notifications table (event_id + calendar_id +
start_time) as the dedupe key, this is strictly safer than a narrow band:

* A slow/delayed poll cycle can never skip past a narrow window and miss
  the event entirely.
* Waking from sleep 3 minutes before an event still notifies immediately
  (spec section 34) — no separate code path needed.
* Duplicate prevention still guarantees exactly one notification per
  (event, start time), because after the first notification the DB check
  short-circuits every later cycle.

LATE_POLL_GRACE_MINUTES exists for the "at event start time" (0-minute)
setting: the check runs on a clock-aligned tick (every 30s), so a poll can
land a few seconds after the exact start second, at which point
minutes_until_start has already gone slightly negative. Without this grace
window, a 0-minute reminder would silently never fire. It's small and
fixed rather than tied to the configured threshold, so it doesn't change
behavior for any other setting beyond the same tiny window.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_REMINDER_MINUTES = 15
# The optional backup ("second") reminder: off unless the person turns it
# on in Settings > Reminder. Same choices as the main reminder.
DEFAULT_BACKUP_REMINDER_MINUTES = 5
LATE_POLL_GRACE_MINUTES = 1

# Settings > Reminder > "Snooze for". Fixed list on purpose.
SNOOZE_OPTIONS = [3, 5, 10, 15, 20, 30, 60]
DEFAULT_SNOOZE_MINUTES = 5


@dataclass(frozen=True)
class DueEvent:
    event_id: str
    calendar_id: str
    calendar_name: str
    title: str
    start: datetime
    location: str | None
    minutes_until_start: float
    # True when an earlier reminder for this same meeting already went out
    # (the optional backup reminder) — shown as "Second reminder".
    is_second: bool = False


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def end_of_local_day(now: datetime, extra_days: int = 0) -> datetime:
    """UTC-aware timestamp for local midnight tonight — the start of
    tomorrow in the machine's own timezone. Used to bound syncing and
    display to whole local days rather than a rolling 24-hour window from
    whatever moment 'now' happens to be, which would bleed into
    tomorrow.

    extra_days pushes it out by that many more whole days (extra_days=6
    is the end of the 7-day window: today + the next six days)."""
    local_date = now.astimezone().date() + timedelta(days=1 + extra_days)
    # A naive datetime's .astimezone() treats it as local wall-clock time,
    # so this lands on real local midnight even across a DST change.
    return datetime.combine(local_date, time()).astimezone().astimezone(timezone.utc)


def find_due_events(events, now: datetime, threshold_minutes: int) -> list[DueEvent]:
    """events: iterable of row-like objects with event_id, calendar_id,
    calendar_name, title, start_time (ISO string), location, status,
    is_all_day. Returns events whose start is between now and
    now + threshold_minutes (plus a small grace period for events that
    just started, see LATE_POLL_GRACE_MINUTES above), not cancelled, not
    all-day."""
    due: list[DueEvent] = []
    for e in events:
        if e["status"] == "cancelled" or e["is_all_day"]:
            continue
        start = _parse_iso(e["start_time"])
        minutes_until = (start - now).total_seconds() / 60
        if -LATE_POLL_GRACE_MINUTES <= minutes_until <= threshold_minutes:
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


def reminder_slots(db) -> dict[str, int]:
    """{slot: minutes before start} for every reminder that's switched on.
    "main" always; "backup" only when enabled in Settings and set to a
    different time than the main one (the same time would just be the
    same reminder twice)."""
    slots = {"main": int(db.get_setting("reminder_minutes", str(DEFAULT_REMINDER_MINUTES)))}
    if db.get_setting("backup_reminder_enabled", "0") == "1":
        backup = int(db.get_setting("backup_reminder_minutes", str(DEFAULT_BACKUP_REMINDER_MINUTES)))
        if backup != slots["main"]:
            slots["backup"] = backup
    return slots


def run_reminder_cycle(
    db, notifier, now: datetime | None = None, account_email: str | None = None
) -> list[DueEvent]:
    """One reminder check. With the backup reminder on, each meeting gets
    up to two reminders — one when it enters each slot's window. If both
    windows are entered at the same check (e.g. the app was only opened 3
    minutes before the meeting), it's ONE reminder, not two back to back:
    every slot that's due gets marked as sent together."""
    now = now or datetime.now(timezone.utc)
    slots = reminder_slots(db)
    threshold_minutes = max(slots.values())
    horizon = now + timedelta(minutes=threshold_minutes + 5)
    # The DB query's lower bound must allow the same grace period find_due_events
    # does below, or it silently excludes an event the instant "now" ticks past
    # its start -- before find_due_events ever gets a chance to still call it
    # due. Without this, "at event start time" (threshold_minutes=0) could
    # never actually fire: the query would drop the event from its result set
    # a moment after start, every single cycle from then on.
    query_floor = now - timedelta(minutes=LATE_POLL_GRACE_MINUTES)

    events = db.upcoming_events(query_floor.isoformat(), horizon.isoformat(), account_email)
    due = find_due_events(events, now, threshold_minutes)

    notified: list[DueEvent] = []
    for event in due:
        start_iso = event.start.isoformat()
        sent = {slot for slot in slots if db.was_notified(event.event_id, event.calendar_id, start_iso, slot)}
        due_now = {
            slot
            for slot, minutes in slots.items()
            if slot not in sent and event.minutes_until_start <= minutes
        }
        if not due_now:
            continue
        event = replace(event, is_second=bool(sent))
        notifier.notify(event)
        for slot in due_now:
            db.mark_notified(
                event.event_id,
                event.calendar_id,
                start_iso,
                now.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                slot=slot,
            )
        notified.append(event)

    db.prune_old_notifications((now - timedelta(days=1)).isoformat())
    return notified


class SnoozeBook:
    """Reminders someone hit Snooze on, and when each should come back.

    Wall-clock (not a Qt timer) and checked by the regular 30-second
    reminder tick, so a snooze still comes due correctly after the PC
    sleeps through it — at most one tick late, same as a normal reminder.
    Written from the GUI thread (the Snooze button) and read from the
    scheduler thread (the reminder tick), hence the lock. In memory only:
    quitting the app drops pending snoozes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[tuple, tuple[DueEvent, datetime]] = {}

    @staticmethod
    def key(event: DueEvent) -> tuple:
        return (event.event_id, event.calendar_id, event.start.isoformat())

    def add(self, event: DueEvent, minutes: int, now: datetime) -> datetime:
        fire_at = now + timedelta(minutes=minutes)
        with self._lock:
            self._pending[self.key(event)] = (event, fire_at)  # re-snoozing replaces
        return fire_at

    def pop_due(self, now: datetime) -> list[DueEvent]:
        """Snoozed reminders whose time has come, with minutes_until_start
        recomputed for `now`. Each is removed as it's returned."""
        with self._lock:
            due_keys = [k for k, (_, fire_at) in self._pending.items() if fire_at <= now]
            events = [self._pending.pop(k)[0] for k in due_keys]
        return [replace(e, minutes_until_start=(e.start - now).total_seconds() / 60) for e in events]

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()


def detect_long_gap(
    last_tick: datetime, now: datetime, expected_interval_seconds: float, multiplier: float = 3.0
) -> bool:
    """True if wall-clock time jumped further than a normal poll interval
    would explain — the signal that the machine was asleep and we should
    sync + check reminders immediately instead of waiting for the next
    scheduled tick (spec section 34)."""
    return (now - last_tick).total_seconds() > expected_interval_seconds * multiplier
