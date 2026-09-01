"""Windows toast notifications. Local-only — no network calls happen here."""

from __future__ import annotations

import logging
from datetime import datetime

from reminders.reminder_service import DueEvent

logger = logging.getLogger(__name__)

APP_ID = "CalendarReminderApp"


def format_time_12h(dt: datetime) -> str:
    """12-hour clock time, no leading zero, without relying on the
    non-portable %-I / %#I strftime extensions."""
    local = dt.astimezone()
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


class Notifier:
    def notify(self, event: DueEvent, play_sound: bool = True) -> None:
        title = "Calendar Reminder"
        minutes = round(event.minutes_until_start)
        time_str = format_time_12h(event.start)
        body = f"{event.calendar_name}: {event.title} starts in {minutes} min at {time_str}."
        if event.location:
            body += f" ({event.location})"

        try:
            from winotify import Notification

            # Deliberately left silent (winotify's default). Its toast
            # audio depends on app_id being a properly registered AUMID —
            # a real Start Menu shortcut — which this app's ad-hoc app_id
            # is not, so that audio path isn't reliable. Sound is played
            # separately below via winsound.MessageBeep, a direct Win32
            # call that doesn't depend on any of that registration.
            Notification(app_id=APP_ID, title=title, msg=body, duration="short").show()
        except Exception:
            logger.exception("Failed to show desktop notification for event %s", event.event_id)

        if play_sound:
            try:
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                logger.exception("Failed to play notification sound for event %s", event.event_id)


def build_reminder_text(event: DueEvent) -> str:
    """Text for the 'Copy Reminder' button — plain, human, ready to paste
    into a chat message. The app never sends this automatically."""
    time_str = format_time_12h(event.start)
    return (
        f'Just a reminder that you have "{event.title}" at {time_str}, '
        f"in about {round(event.minutes_until_start)} minutes."
    )
