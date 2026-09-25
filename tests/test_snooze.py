import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

try:
    import winreg  # noqa: F401 — system/startup.py needs it at import time
except ImportError:  # running the suite off Windows
    sys.modules["winreg"] = types.ModuleType("winreg")

import app as app_module  # noqa: E402
from reminders.notifications import build_reminder_text, format_start_phrase  # noqa: E402
from reminders.reminder_service import (  # noqa: E402
    DEFAULT_SNOOZE_MINUTES,
    SNOOZE_OPTIONS,
    DueEvent,
    SnoozeBook,
)
from ui.reminder_alert import ReminderAlertDialog, snooze_label  # noqa: E402

_app = QApplication.instance() or QApplication([])

CAL = "boss@example.com"
NOW = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)


def due(start, event_id="m1", title="Budget review"):
    return DueEvent(event_id, CAL, "Boss", title, start, None, (start - NOW).total_seconds() / 60)


def test_snooze_options_are_exactly_what_was_asked_for():
    assert SNOOZE_OPTIONS == [3, 5, 10, 15, 20, 30, 60]
    assert DEFAULT_SNOOZE_MINUTES in SNOOZE_OPTIONS
    assert snooze_label(60) == "1 hour"
    assert snooze_label(3) == "3 min"


# ---- SnoozeBook -------------------------------------------------------------


def test_snoozed_reminder_comes_back_only_after_the_snooze_time():
    book = SnoozeBook()
    event = due(NOW + timedelta(minutes=15))
    book.add(event, 5, NOW)
    assert book.pop_due(NOW + timedelta(minutes=4, seconds=59)) == []
    back = book.pop_due(NOW + timedelta(minutes=5))
    assert [e.event_id for e in back] == ["m1"]
    assert back[0].minutes_until_start == pytest.approx(10)  # recomputed, not the stale 15
    assert book.pop_due(NOW + timedelta(minutes=30)) == []  # fires once
    assert len(book) == 0


def test_snoozing_the_same_reminder_again_replaces_the_earlier_snooze():
    book = SnoozeBook()
    event = due(NOW + timedelta(minutes=30))
    book.add(event, 3, NOW)
    book.add(event, 20, NOW)
    assert len(book) == 1
    assert book.pop_due(NOW + timedelta(minutes=3)) == []
    assert len(book.pop_due(NOW + timedelta(minutes=20))) == 1


# ---- wording once the meeting has started ----------------------------------------


def test_start_phrase():
    assert format_start_phrase(5) == "starts in 5 min"
    assert format_start_phrase(0) == "starts now"
    assert format_start_phrase(-1) == "starts now"  # still within the late-poll grace
    assert format_start_phrase(-7) == "started 7 min ago"


def test_copy_text_for_a_meeting_that_already_started():
    text = build_reminder_text(due(NOW - timedelta(minutes=10)))
    assert "started at" in text


# ---- AppController ------------------------------------------------------------


class FakeNotifier:
    def __init__(self):
        self.notified = []

    def notify(self, event):
        self.notified.append(event)

    def notify_change(self, change):
        pass


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    ctrl = app_module.AppController()
    ctrl.notifier = FakeNotifier()
    ctrl.service = object()
    ctrl.current_account_email = CAL
    ctrl.db.upsert_calendars([{"calendar_id": CAL, "name": "Boss", "access_role": "reader", "primary": True}], CAL)
    ctrl.db.set_calendar_selected(CAL, True)
    fired = []
    ctrl.reminder_fired.connect(fired.append)
    ctrl.fired = fired
    yield ctrl
    ctrl.db.close()


def store(ctrl, event):
    ctrl.db.replace_events_for_calendar(
        CAL,
        [
            {
                "event_id": event.event_id,
                "calendar_id": CAL,
                "title": event.title,
                "start_time": event.start.isoformat(),
                "end_time": (event.start + timedelta(minutes=30)).isoformat(),
                "location": None,
                "is_all_day": 0,
                "status": "confirmed",
                "html_link": None,
                "updated_at": NOW.isoformat(),
            }
        ],
    )


def test_snooze_minutes_setting_defaults_and_rejects_junk(controller):
    assert controller.snooze_minutes() == DEFAULT_SNOOZE_MINUTES
    controller.db.set_setting("snooze_minutes", "30")
    assert controller.snooze_minutes() == 30
    for junk in ("7", "abc", ""):
        controller.db.set_setting("snooze_minutes", junk)
        assert controller.snooze_minutes() == DEFAULT_SNOOZE_MINUTES


def test_snoozed_reminder_fires_again_like_the_original(controller):
    event = due(datetime.now(timezone.utc) + timedelta(minutes=15))
    store(controller, event)
    controller.snooze(event, 3)
    later = datetime.now(timezone.utc) + timedelta(minutes=3, seconds=1)
    controller._fire_due_snoozes(later)
    assert [e.event_id for e in controller.notifier.notified] == ["m1"]  # toast + sound
    assert [e.event_id for e in controller.fired] == ["m1"]  # window + flash
    assert controller.fired[0].minutes_until_start == pytest.approx(12, abs=0.1)


def test_snoozed_reminder_is_dropped_if_meeting_was_canceled_or_moved(controller):
    event = due(datetime.now(timezone.utc) + timedelta(minutes=15))
    store(controller, event)
    controller.snooze(event, 3)
    controller.db.replace_events_for_calendar(CAL, [])  # canceled / moved / over
    controller._fire_due_snoozes(datetime.now(timezone.utc) + timedelta(minutes=4))
    assert controller.notifier.notified == []
    assert controller.fired == []


def test_signing_out_drops_pending_snoozes(controller, monkeypatch):
    monkeypatch.setattr(app_module.google_auth, "sign_out", lambda: None)
    controller.snooze(due(datetime.now(timezone.utc) + timedelta(minutes=15)), 3)
    controller.sign_out()
    assert len(controller._snoozes) == 0


# ---- the reminder window ---------------------------------------------------------


def test_snooze_button_shows_the_setting_and_emits_snoozed_then_closes():
    dialog = ReminderAlertDialog(due(NOW + timedelta(minutes=15)), QColor("blue"), snooze_minutes=60)
    assert dialog._snooze_button.text() == "Snooze 1 hour"
    events = []
    dialog.snoozed.connect(lambda: events.append("snoozed"))
    dialog.acknowledged.connect(lambda: events.append("acknowledged"))
    dialog.show()
    dialog._snooze_button.click()
    assert events == ["snoozed", "acknowledged"]  # acknowledged -> flash stops
    assert not dialog.isVisible()


def test_ok_does_not_snooze():
    dialog = ReminderAlertDialog(due(NOW + timedelta(minutes=15)), QColor("blue"))
    events = []
    dialog.snoozed.connect(lambda: events.append("snoozed"))
    dialog.show()
    dialog.close()
    assert events == []
