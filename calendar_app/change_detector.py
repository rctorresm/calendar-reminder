"""Spot meetings that were added, removed, or edited between two syncs.

`detect_changes` is pure (no DB, no clock, no I/O) so it can be unit tested
directly. AppController keeps the previous sync's events per calendar in
memory and hands both lists here after every successful fetch.

The sync window is "now through local midnight tonight" (see
AppController.sync_events), and that window moves on its own. Two things
drop out of it or into it without anyone touching the calendar, and must
never be reported as a change:

* A meeting that has simply ended. Google's timeMin filters on END time,
  so once a meeting is over it stops coming back from the API. It only
  counts as removed if it was still upcoming or in progress (end > now).
* Tomorrow's meetings at midnight. The window grows by a day, so a whole
  day of meetings shows up at once. A meeting only counts as added if it
  starts inside the window the PREVIOUS sync covered (start <
  previous_horizon), i.e. it would have been returned last time if it had
  existed then.

Matching is by event_id alone, not (event_id, start): with
singleEvents=True a recurring meeting's instance keeps the same id when
just that one instance is rescheduled, and a one-off meeting always keeps
its id. So a time change shows up as "changed", not as a remove + add.

Compared: title, start, end, location, all-day, and description (the
meeting's notes/agenda). `updated_at` is deliberately ignored: Google bumps it
for things like an attendee RSVPing, which would be pure noise here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from calendar_app.models import EventOccurrence

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"


@dataclass(frozen=True)
class FieldChange:
    field: str  # "title" | "start" | "end" | "location" | "all_day" | "description"
    old: object
    new: object


@dataclass(frozen=True)
class EventChange:
    kind: str  # ADDED | REMOVED | CHANGED
    calendar_id: str
    event: EventOccurrence  # the new version (or the last-known one, for REMOVED)
    previous: EventOccurrence | None = None  # the old version, for CHANGED
    fields: tuple[FieldChange, ...] = field(default_factory=tuple)
    calendar_name: str = ""  # filled in by AppController, for display

    @property
    def key(self) -> tuple:
        return (self.kind, self.calendar_id, self.event.event_id, self.event.start.isoformat())


def _field_changes(old: EventOccurrence, new: EventOccurrence) -> tuple[FieldChange, ...]:
    changes: list[FieldChange] = []
    if old.title != new.title:
        changes.append(FieldChange("title", old.title, new.title))
    if old.start != new.start:
        changes.append(FieldChange("start", old.start, new.start))
    if old.end != new.end:
        changes.append(FieldChange("end", old.end, new.end))
    if (old.location or "") != (new.location or ""):
        changes.append(FieldChange("location", old.location, new.location))
    if old.is_all_day != new.is_all_day:
        changes.append(FieldChange("all_day", old.is_all_day, new.is_all_day))
    # Trailing whitespace edits aren't a meaningful change.
    if (old.description or "").strip() != (new.description or "").strip():
        changes.append(FieldChange("description", old.description, new.description))
    return tuple(changes)


def _still_relevant(event: EventOccurrence, now: datetime) -> bool:
    """True if the event hadn't finished yet — so its disappearance can't be
    explained by it simply having ended."""
    return (event.end or event.start) > now


def detect_changes(
    previous: Iterable[EventOccurrence],
    current: Iterable[EventOccurrence],
    previous_horizon: datetime,
    now: datetime,
) -> list[EventChange]:
    """Compare one calendar's previous sync against its current one.

    previous_horizon: the timeMax the previous sync used.
    now: the timeMin the CURRENT sync used (must be the same instant, so
    "ended" means exactly what Google's filter meant by it)."""
    old_by_id = {e.event_id: e for e in previous}
    new_by_id = {e.event_id: e for e in current}
    changes: list[EventChange] = []

    for event_id, new in new_by_id.items():
        old = old_by_id.get(event_id)
        if old is None:
            if new.start < previous_horizon:
                changes.append(EventChange(ADDED, new.calendar_id, new))
            continue
        fields = _field_changes(old, new)
        if fields:
            changes.append(EventChange(CHANGED, new.calendar_id, new, previous=old, fields=fields))

    for event_id, old in old_by_id.items():
        if event_id not in new_by_id and _still_relevant(old, now):
            changes.append(EventChange(REMOVED, old.calendar_id, old))

    changes.sort(key=lambda c: c.event.start)
    return changes
