"""Windows toast notifications. Local-only — no network calls happen here."""

from __future__ import annotations

import logging
from datetime import datetime

from calendar_app.change_detector import ADDED, CHANGED, REMOVED, WATCH_DAYS, EventChange
from reminders.reminder_service import LATE_POLL_GRACE_MINUTES, DueEvent

logger = logging.getLogger(__name__)

APP_ID = "CalendarReminderApp"


def format_time_12h(dt: datetime) -> str:
    """12-hour clock time, no leading zero, without relying on the
    non-portable %-I / %#I strftime extensions."""
    local = dt.astimezone()
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def format_lead_time(minutes: int) -> str:
    """Phrasing for how far out an event is. A reminder set to fire 'at
    event start time' rounds to 0, and the late-poll grace window (see
    reminder_service.LATE_POLL_GRACE_MINUTES) can even make it slightly
    negative if the check ran a few seconds after the exact start — both
    should read as 'now', not '0 min' or a negative number."""
    return "now" if minutes <= 0 else f"in {minutes} min"


def format_start_phrase(minutes: int) -> str:
    """'starts in 5 min' / 'starts now' / 'started 4 min ago' — the last one
    only happens for a snoozed reminder that comes back after the meeting
    has begun."""
    if minutes < -LATE_POLL_GRACE_MINUTES:
        return f"started {-minutes} min ago"
    return f"starts {format_lead_time(minutes)}"


CHANGE_HEADLINES = {
    ADDED: "New meeting added",
    REMOVED: "Meeting canceled or moved",
    CHANGED: "Meeting changed",
}


def _local_date(dt: datetime, is_all_day: bool):
    # All-day events are stored as UTC midnight of their calendar date
    # (see event_sync.parse_event); converting that to local time would
    # shift it to the previous day west of UTC.
    return dt.date() if is_all_day else dt.astimezone().date()


def format_day(dt: datetime, is_all_day: bool = False, now: datetime | None = None) -> str:
    """'today', 'tomorrow', or e.g. 'Mon, Sep 28' — portable (no %-d)."""
    today = (now or datetime.now()).astimezone().date()
    day = _local_date(dt, is_all_day)
    delta = (day - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"{day.strftime('%a, %b')} {day.day}"


def google_calendar_url(
    html_link: str | None, start: datetime, is_all_day: bool = False, prefer_day: bool = False
) -> str:
    """Where "Open in Google Calendar" goes: the meeting itself when Google
    gave us its link, otherwise (or with prefer_day, used for a canceled /
    moved meeting whose own link would just say "event not found") that
    day in Google Calendar's day view."""
    if html_link and not prefer_day:
        return html_link
    day = _local_date(start, is_all_day)
    return f"https://calendar.google.com/calendar/r/day/{day.year}/{day.month}/{day.day}"


def describe_event_time(start: datetime, is_all_day: bool, now: datetime | None = None) -> str:
    """e.g. 'today at 3:00 PM', 'tomorrow (all day)', 'Mon, Sep 28 at 9:30 AM'."""
    day = format_day(start, is_all_day, now)
    return f"{day} (all day)" if is_all_day else f"{day} at {format_time_12h(start)}"


def _describe_moved(old: datetime, new: datetime, is_all_day: bool, now: datetime | None) -> str:
    if _local_date(old, is_all_day) == _local_date(new, is_all_day):
        return f"{format_time_12h(old)} → {format_time_12h(new)}"
    return f"{describe_event_time(old, is_all_day, now)} → {describe_event_time(new, is_all_day, now)}"


def describe_change_lines(change: EventChange, now: datetime | None = None) -> list[str]:
    """Human-readable "what's different" lines, shared by the toast and
    the change alert window."""
    event = change.event
    if change.kind == ADDED:
        return [f"Scheduled for {describe_event_time(event.start, event.is_all_day, now)}."]
    if change.kind == REMOVED:
        return [
            f"Was scheduled for {describe_event_time(event.start, event.is_all_day, now)}.",
            f"It was canceled or deleted, or moved more than {WATCH_DAYS} days out.",
        ]
    lines = []
    by_field = {f.field: f for f in change.fields}
    start, end = by_field.get("start"), by_field.get("end")
    # A meeting that was just moved (same length) reads as one "Time
    # moved" line, not a second, redundant "End time changed" line.
    moved_whole = bool(start and end and end.old and end.new and end.new - start.new == end.old - start.old)
    for f in change.fields:
        if f.field == "end" and moved_whole:
            continue
        if f.field == "title":
            lines.append(f'Renamed from "{f.old}".')
        elif f.field == "start":
            lines.append(f"Time moved: {_describe_moved(f.old, f.new, event.is_all_day, now)}.")
        elif f.field == "end":
            old = format_time_12h(f.old) if f.old else "—"
            new = format_time_12h(f.new) if f.new else "—"
            lines.append(f"End time changed: {old} → {new}.")
        elif f.field == "location":
            lines.append(f"Location changed: {f.old or '(none)'} → {f.new or '(none)'}.")
        elif f.field == "description":
            # Descriptions can be long (and are often HTML), so say that it
            # changed rather than trying to show a diff of it.
            if not f.new:
                lines.append("Description (notes/agenda) was removed.")
            elif not f.old:
                lines.append("A description (notes/agenda) was added.")
            else:
                lines.append("Description (notes/agenda) was updated.")
        elif f.field == "all_day":
            lines.append("Changed to an all-day event." if f.new else "No longer an all-day event.")
    return lines


def _play_sound() -> None:
    import winsound

    winsound.MessageBeep(winsound.MB_ICONASTERISK)


def _show_toast(title: str, body: str) -> None:
    from winotify import Notification

    # Deliberately left silent (winotify's default). Its toast audio
    # depends on app_id being a properly registered AUMID — a real Start
    # Menu shortcut — which this app's ad-hoc app_id is not, so that audio
    # path isn't reliable. Sound is played separately via
    # winsound.MessageBeep, a direct Win32 call that doesn't depend on any
    # of that registration.
    Notification(app_id=APP_ID, title=title, msg=body, duration="short").show()


class Notifier:
    def notify_change(self, change: EventChange, play_sound: bool = True) -> None:
        title = CHANGE_HEADLINES[change.kind]
        prefix = f"{change.calendar_name}: " if change.calendar_name else ""
        body = f"{prefix}{change.event.title}. " + " ".join(describe_change_lines(change))
        try:
            _show_toast(title, body)
        except Exception:
            logger.exception("Failed to show change notification for event %s", change.event.event_id)
        if play_sound:
            try:
                _play_sound()
            except Exception:
                logger.exception("Failed to play change notification sound")

    def notify(self, event: DueEvent, play_sound: bool = True) -> None:
        title = "Calendar Reminder — second reminder" if event.is_second else "Calendar Reminder"
        minutes = round(event.minutes_until_start)
        time_str = format_time_12h(event.start)
        body = f"{event.calendar_name}: {event.title} {format_start_phrase(minutes)} at {time_str}."
        if event.location:
            body += f" ({event.location})"

        try:
            _show_toast(title, body)
        except Exception:
            logger.exception("Failed to show desktop notification for event %s", event.event_id)

        if play_sound:
            try:
                _play_sound()
            except Exception:
                logger.exception("Failed to play notification sound for event %s", event.event_id)


def build_reminder_text(event: DueEvent) -> str:
    """Text for the 'Copy Reminder' button — plain, human, ready to paste
    into a chat message. The app never sends this automatically."""
    time_str = format_time_12h(event.start)
    minutes = round(event.minutes_until_start)
    if minutes < -LATE_POLL_GRACE_MINUTES:
        return f'Just a reminder that "{event.title}" started at {time_str}.'
    timing = "right now" if minutes <= 0 else f"in about {minutes} minutes"
    return f'Just a reminder that you have "{event.title}" at {time_str}, {timing}.'
