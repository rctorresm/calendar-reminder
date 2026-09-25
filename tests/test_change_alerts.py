"""End-to-end: AppController.sync_events -> change detection -> toast +
event_changed signal, with the Google API replaced by a fake feed. Also
covers the change-alert text and the change alert window/border cue."""

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtWidgets import QApplication

try:
    import winreg  # noqa: F401 — system/startup.py needs it at import time
except ImportError:  # running the suite off Windows
    sys.modules["winreg"] = types.ModuleType("winreg")

import app as app_module  # noqa: E402
from calendar_app import event_sync
from calendar_app.change_detector import ADDED, CHANGED, REMOVED, EventChange, FieldChange
from calendar_app.models import EventOccurrence
from reminders.attention_cue import CHANGE_COLORS, AttentionFlasher, resolve_change_color
from reminders.notifications import describe_change_lines
from ui.change_alert import BANNER_TEXT, ChangeAlertDialog

_app = QApplication.instance() or QApplication([])

CAL = "boss@example.com"


def occurrence(event_id, start, title="Budget review", **overrides):
    fields = dict(
        event_id=event_id,
        calendar_id=CAL,
        title=title,
        start=start,
        end=start + timedelta(minutes=30),
        location=None,
        is_all_day=False,
        status="confirmed",
        html_link=None,
        updated_at=start,
    )
    fields.update(overrides)
    return EventOccurrence(**fields)


class FakeNotifier:
    def __init__(self):
        self.changes = []

    def notify(self, event):
        pass

    def notify_change(self, change):
        self.changes.append(change)


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    ctrl = app_module.AppController()
    ctrl.notifier = FakeNotifier()
    ctrl.service = object()  # "signed in"; fetch_events is faked below
    ctrl.current_account_email = CAL
    ctrl.db.upsert_calendars(
        [{"calendar_id": CAL, "name": "Boss", "access_role": "reader", "primary": True}], CAL
    )
    ctrl.db.set_calendar_selected(CAL, True)

    feed = {"events": []}
    monkeypatch.setattr(event_sync, "fetch_events", lambda service, cal, now, horizon: list(feed["events"]))
    ctrl.feed = feed
    emitted = []
    ctrl.event_changed.connect(emitted.append)
    ctrl.emitted = emitted
    yield ctrl
    ctrl.db.close()


def future(minutes):
    # Stay inside "today" regardless of when the test runs by keeping the
    # offset tiny relative to the local-midnight horizon... except right
    # before midnight, where even a few minutes would cross it.
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _skip_near_midnight():
    local = datetime.now().astimezone()
    if local.hour == 23 and local.minute >= 40:
        pytest.skip("too close to local midnight for a same-day window")


def test_first_sync_is_a_silent_baseline(controller):
    _skip_near_midnight()
    controller.feed["events"] = [occurrence("a", future(10))]
    controller.sync_events()
    assert controller.notifier.changes == []
    assert controller.emitted == []


def test_added_removed_and_changed_are_announced_with_calendar_name(controller):
    _skip_near_midnight()
    a_start = future(10)
    controller.feed["events"] = [occurrence("a", a_start), occurrence("b", future(15))]
    controller.sync_events()

    controller.feed["events"] = [
        occurrence("a", a_start, title="Budget review — new room"),
        occurrence("c", future(12), title="Surprise 1:1"),
    ]
    controller.sync_events()

    kinds = {(c.kind, c.event.event_id) for c in controller.notifier.changes}
    assert kinds == {(CHANGED, "a"), (ADDED, "c"), (REMOVED, "b")}
    assert all(c.calendar_name == "Boss" for c in controller.notifier.changes)
    assert len(controller.emitted) == 3

    # Nothing new on the next sync -> no repeat alerts.
    controller.sync_events()
    assert len(controller.notifier.changes) == 3


def test_change_alerts_setting_off_suppresses_everything(controller):
    _skip_near_midnight()
    controller.db.set_setting("change_alerts_enabled", "0")
    controller.sync_events()
    controller.feed["events"] = [occurrence("new", future(10))]
    controller.sync_events()
    assert controller.notifier.changes == []
    assert controller.emitted == []


def test_losing_access_to_a_calendar_is_not_reported_as_cancellations(controller, monkeypatch):
    _skip_near_midnight()
    controller.feed["events"] = [occurrence("a", future(10))]
    controller.sync_events()

    def lost(*_args):
        raise event_sync.CalendarAccessLost(CAL)

    monkeypatch.setattr(event_sync, "fetch_events", lost)
    controller.sync_events()
    assert controller.notifier.changes == []


def test_unselected_then_reselected_calendar_starts_a_fresh_baseline(controller):
    _skip_near_midnight()
    controller.feed["events"] = [occurrence("a", future(10))]
    controller.sync_events()
    controller.db.set_calendar_selected(CAL, False)
    controller.sync_events()
    controller.db.set_calendar_selected(CAL, True)
    controller.feed["events"] = [occurrence("b", future(20))]
    controller.sync_events()  # baseline again, not "a removed, b added"
    assert controller.notifier.changes == []


# ---- text -------------------------------------------------------------

START = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)


def test_describe_removed_mentions_canceled_or_moved():
    change = EventChange(REMOVED, CAL, occurrence("a", START))
    text = " ".join(describe_change_lines(change))
    assert "canceled" in text and "moved to another day" in text


def test_describe_time_move_shows_old_and_new_time():
    new = occurrence("a", START + timedelta(hours=1))
    change = EventChange(
        CHANGED, CAL, new, previous=occurrence("a", START), fields=(FieldChange("start", START, new.start),)
    )
    (line,) = describe_change_lines(change)
    assert line.startswith("Time moved:") and "→" in line


def test_moved_meeting_does_not_repeat_the_end_time():
    old, new = occurrence("a", START), occurrence("a", START + timedelta(hours=1))
    change = EventChange(
        CHANGED,
        CAL,
        new,
        previous=old,
        fields=(FieldChange("start", old.start, new.start), FieldChange("end", old.end, new.end)),
    )
    assert len(describe_change_lines(change)) == 1


def test_lengthened_meeting_shows_end_time_change():
    old = occurrence("a", START)
    change = EventChange(
        CHANGED, CAL, old, fields=(FieldChange("end", old.end, old.end + timedelta(minutes=30)),)
    )
    (line,) = describe_change_lines(change)
    assert line.startswith("End time changed:")


def test_describe_rename_shows_old_title():
    change = EventChange(
        CHANGED, CAL, occurrence("a", START, title="New"), fields=(FieldChange("title", "Old", "New"),)
    )
    assert describe_change_lines(change) == ['Renamed from "Old".']


# ---- visuals -------------------------------------------------------------


def test_each_kind_has_its_own_color_and_banner():
    assert set(CHANGE_COLORS) == {ADDED, REMOVED, CHANGED}
    colors = {(c.red(), c.green(), c.blue()) for c in CHANGE_COLORS.values()}
    assert len(colors) == 3
    assert len(set(BANNER_TEXT.values())) == 3
    assert resolve_change_color("bogus") is not None


def test_change_blink_loops_until_stopped_and_uses_dashed_border():
    flasher = AttentionFlasher()
    flasher.blink_until_stopped(resolve_change_color(ADDED))
    assert flasher.is_active
    assert flasher._group.loopCount() == -1
    assert all(o._dashed for o in flasher._overlays)
    flasher.stop()
    assert not flasher.is_active


def test_change_alert_dialog_emits_acknowledged_on_close_and_escapes_title():
    change = EventChange(ADDED, CAL, occurrence("a", START, title="<b>x</b>"), calendar_name="Boss")
    dialog = ChangeAlertDialog(change)
    acked = []
    dialog.acknowledged.connect(lambda: acked.append(True))
    dialog.show()
    dialog.close()
    assert acked == [True]
