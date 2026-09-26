from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from calendar_app.change_detector import ADDED, CHANGED, REMOVED, EventChange
from calendar_app.models import EventOccurrence
from database.db import Database
from reminders.notifications import google_calendar_url
from reminders.reminder_service import DueEvent, run_reminder_cycle
from ui.change_alert import ChangeAlertDialog
from ui.reminder_alert import ReminderAlertDialog

_app = QApplication.instance() or QApplication([])

CAL = "john@example.com"
LINK = "https://www.google.com/calendar/event?eid=abc123"
# Local noon, so the "day" part of the URL is the same in every timezone.
START = datetime(2026, 9, 28, 12, 0).astimezone().astimezone(timezone.utc)
DAY_URL = "https://calendar.google.com/calendar/r/day/2026/9/28"


def test_url_prefers_the_meetings_own_link():
    assert google_calendar_url(LINK, START) == LINK


def test_url_falls_back_to_that_day_without_a_link():
    assert google_calendar_url(None, START) == DAY_URL


def test_url_for_a_canceled_meeting_opens_the_day_not_the_dead_link():
    assert google_calendar_url(LINK, START, prefer_day=True) == DAY_URL


def test_all_day_event_day_is_not_shifted_by_timezone():
    all_day = datetime(2026, 9, 28, tzinfo=timezone.utc)  # how parse_event stores 2026-09-28
    assert google_calendar_url(None, all_day, is_all_day=True) == DAY_URL


# ---- reminder window --------------------------------------------------------


def test_reminder_window_has_the_button_and_it_targets_the_meeting():
    event = DueEvent("m1", CAL, "John", "Budget review", START, None, 5, html_link=LINK)
    dialog = ReminderAlertDialog(event, QColor("blue"))
    assert dialog._open_button.text() == "Open in Google Calendar"
    assert dialog._open_url == LINK


def test_reminder_window_without_a_link_still_has_the_button():
    dialog = ReminderAlertDialog(DueEvent("m1", CAL, "John", "Budget review", START, None, 5), QColor("blue"))
    assert dialog._open_url == DAY_URL


def test_link_flows_from_the_database_into_the_reminder(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_calendars([{"calendar_id": CAL, "name": "John", "access_role": "owner", "primary": True}], CAL)
    db.set_calendar_selected(CAL, True)
    db.replace_events_for_calendar(
        CAL,
        [
            {
                "event_id": "m1",
                "calendar_id": CAL,
                "title": "Budget review",
                "start_time": START.isoformat(),
                "end_time": (START + timedelta(minutes=30)).isoformat(),
                "location": None,
                "is_all_day": 0,
                "status": "confirmed",
                "html_link": LINK,
                "updated_at": START.isoformat(),
            }
        ],
    )

    class Notifier:
        def notify(self, event):
            pass

    (event,) = run_reminder_cycle(db, Notifier(), now=START - timedelta(minutes=10), account_email=CAL)
    assert event.html_link == LINK
    db.close()


# ---- change alerts: now on every kind -----------------------------------------------


def occurrence(link=LINK):
    return EventOccurrence("m1", CAL, "Budget review", START, START + timedelta(minutes=30), None, False,
                           "confirmed", link, START)


@pytest.mark.parametrize(
    "kind,expected",
    [(ADDED, LINK), (CHANGED, LINK), (REMOVED, DAY_URL)],
)
def test_every_change_alert_has_the_button(kind, expected):
    from PySide6.QtWidgets import QPushButton

    dialog = ChangeAlertDialog(EventChange(kind, CAL, occurrence(), calendar_name="John"), QColor("blue"))
    assert any(b.text() == "Open in Google Calendar" for b in dialog.findChildren(QPushButton))
    assert dialog._open_url == expected
