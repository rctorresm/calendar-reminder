from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from database.db import Database
from reminders.reminder_service import DueEvent, reminder_slots, run_reminder_cycle
from ui.alert_position import STACK_OFFSET, center_on_primary_screen
from ui.reminder_alert import ReminderAlertDialog

_app = QApplication.instance() or QApplication([])

CAL = "john@example.com"
START = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)


class FakeNotifier:
    def __init__(self):
        self.notified = []

    def notify(self, event):
        self.notified.append(event)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.upsert_calendars([{"calendar_id": CAL, "name": "John", "access_role": "owner", "primary": True}], CAL)
    database.set_calendar_selected(CAL, True)
    database.replace_events_for_calendar(
        CAL,
        [
            {
                "event_id": "evt1",
                "calendar_id": CAL,
                "title": "Budget review",
                "start_time": START.isoformat(),
                "end_time": (START + timedelta(minutes=30)).isoformat(),
                "location": None,
                "is_all_day": 0,
                "status": "confirmed",
                "html_link": None,
                "updated_at": START.isoformat(),
            }
        ],
    )
    yield database
    database.close()


def run_at(db, notifier, minutes_before):
    return run_reminder_cycle(db, notifier, now=START - timedelta(minutes=minutes_before), account_email=CAL)


# ---- settings ---------------------------------------------------------------


def test_backup_is_off_by_default(db):
    assert reminder_slots(db) == {"main": 15}


def test_backup_on_adds_a_second_slot(db):
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "5")
    assert reminder_slots(db) == {"main": 15, "backup": 5}


def test_backup_at_the_same_time_as_main_is_just_one_reminder(db):
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "15")
    assert reminder_slots(db) == {"main": 15}


# ---- firing -----------------------------------------------------------------


def test_off_by_default_means_exactly_one_reminder(db):
    notifier = FakeNotifier()
    for minutes_before in (15, 10, 5, 1, 0):
        run_at(db, notifier, minutes_before)
    assert len(notifier.notified) == 1
    assert notifier.notified[0].is_second is False


def test_main_15_backup_5_fires_twice_second_is_labeled(db):
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "5")
    notifier = FakeNotifier()
    for minutes_before in (15, 10, 6):
        run_at(db, notifier, minutes_before)
    assert [e.is_second for e in notifier.notified] == [False]
    for minutes_before in (5, 3, 0):
        run_at(db, notifier, minutes_before)
    assert [e.is_second for e in notifier.notified] == [False, True]


def test_backup_can_come_before_main(db):
    db.set_setting("reminder_minutes", "5")
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "30")
    notifier = FakeNotifier()
    run_at(db, notifier, 30)  # backup's window opens first
    run_at(db, notifier, 5)  # then the main one
    assert [e.is_second for e in notifier.notified] == [False, True]


def test_both_due_at_the_same_check_is_one_reminder_not_two(db):
    """App opened 3 minutes before the meeting: both windows are already
    open — show one reminder, and don't fire the other on the next tick."""
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "5")
    notifier = FakeNotifier()
    run_at(db, notifier, 3)
    run_at(db, notifier, 2.5)
    run_at(db, notifier, 0)
    assert len(notifier.notified) == 1


def test_turning_backup_on_after_main_already_fired_still_sends_it(db):
    notifier = FakeNotifier()
    run_at(db, notifier, 15)
    db.set_setting("backup_reminder_enabled", "1")
    db.set_setting("backup_reminder_minutes", "5")
    run_at(db, notifier, 5)
    assert [e.is_second for e in notifier.notified] == [False, True]


def test_existing_notification_rows_still_mean_main_was_sent(db):
    """Rows written before the backup reminder existed use the plain
    event_id — they must keep counting as 'main reminder sent'."""
    db.mark_notified("evt1", CAL, START.isoformat(), START.isoformat(), START.isoformat())
    assert db.was_notified("evt1", CAL, START.isoformat()) is True
    assert db.was_notified("evt1", CAL, START.isoformat(), slot="backup") is False


# ---- window -------------------------------------------------------------------


def due(is_second):
    return DueEvent("evt1", CAL, "John", "Budget review", START, None, 5, is_second=is_second)


def test_second_reminder_window_is_labeled():
    first = ReminderAlertDialog(due(False), QColor("blue"))
    second = ReminderAlertDialog(due(True), QColor("blue"))
    assert "second" not in first.windowTitle().lower()
    assert "second reminder" in second.windowTitle().lower()
    assert any(lbl.text() == "SECOND REMINDER" for lbl in second.findChildren(QLabel))
    assert not any(lbl.text() == "SECOND REMINDER" for lbl in first.findChildren(QLabel))


def test_alert_windows_open_centered_on_the_main_screen_and_cascade():
    screen = QApplication.primaryScreen().availableGeometry()
    w = QWidget()
    w.resize(300, 200)
    center_on_primary_screen(w, 0)
    assert w.geometry().center().x() == pytest.approx(screen.center().x(), abs=2)
    assert w.geometry().center().y() == pytest.approx(screen.center().y(), abs=2)
    w2 = QWidget()
    w2.resize(300, 200)
    center_on_primary_screen(w2, 1)
    assert w2.x() - w.x() == STACK_OFFSET and w2.y() - w.y() == STACK_OFFSET


def test_cascade_never_pushes_a_window_off_the_main_screen():
    screen = QApplication.primaryScreen().availableGeometry()
    w = QWidget()
    w.resize(300, 200)
    center_on_primary_screen(w, 500)
    assert screen.contains(QRect(w.pos(), w.size()))
