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
from reminders.attention_cue import CHANGE_STRIPE_DARK, COLOR_CHOICES, AttentionFlasher
from reminders.notifications import describe_change_lines
from ui.change_alert import HEADINGS, ChangeAlertDialog

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
    assert "canceled" in text and "more than 5 days out" in text


def test_sync_looks_five_local_days_ahead(controller, monkeypatch):
    seen = {}

    def fake_fetch(service, cal, now, horizon):
        seen["now"], seen["horizon"] = now, horizon
        return []

    monkeypatch.setattr(event_sync, "fetch_events", fake_fetch)
    controller.sync_events()
    local_now = seen["now"].astimezone()
    local_end = seen["horizon"].astimezone()
    assert (local_end.date() - local_now.date()).days == 5
    assert (local_end.hour, local_end.minute) == (0, 0)


def test_change_to_a_meeting_four_days_out_is_announced(controller):
    later = future(4 * 24 * 60 - 12 * 60)  # well inside day 5 whatever the time of day
    controller.feed["events"] = [occurrence("m", later)]
    controller.sync_events()
    controller.feed["events"] = [occurrence("m", later, title="Monday planning (moved rooms)")]
    controller.sync_events()
    assert [c.kind for c in controller.notifier.changes] == [CHANGED]


# Local noon (naive .astimezone() = this machine's timezone), so "today"
# and "Mon, Sep 28" mean the same thing in any timezone the suite runs in.
LOCAL_NOON_FRIDAY = datetime(2026, 9, 25, 12, 0).astimezone()


def test_added_and_removed_wording_names_the_day():
    now = LOCAL_NOON_FRIDAY
    monday = now + timedelta(days=3)
    added = describe_change_lines(EventChange(ADDED, CAL, occurrence("a", monday)), now=now)
    assert added[0].startswith("Scheduled for ") and "Sep 28" in added[0]
    today = describe_change_lines(EventChange(ADDED, CAL, occurrence("a", now + timedelta(hours=1))), now=now)
    assert "today at" in today[0]


def test_moving_to_another_day_shows_both_days():
    now = LOCAL_NOON_FRIDAY
    old, new = occurrence("a", now + timedelta(hours=1)), occurrence("a", now + timedelta(days=3, hours=1))
    change = EventChange(
        CHANGED, CAL, new, previous=old,
        fields=(FieldChange("start", old.start, new.start), FieldChange("end", old.end, new.end)),
    )
    (line,) = describe_change_lines(change, now=now)
    assert "today at" in line and "Sep 28" in line


def test_all_day_event_day_is_not_shifted_by_timezone():
    from reminders.notifications import format_day

    now = datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc)
    all_day = datetime(2026, 9, 28, tzinfo=timezone.utc)  # how parse_event stores 2026-09-28
    assert format_day(all_day, is_all_day=True, now=now) in ("Mon, Sep 28",)


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


def test_describe_description_added_updated_removed():
    def line(old, new):
        change = EventChange(CHANGED, CAL, occurrence("a", START), fields=(FieldChange("description", old, new),))
        return describe_change_lines(change)[0]

    assert "added" in line(None, "Agenda")
    assert "updated" in line("Agenda", "New agenda")
    assert "removed" in line("Agenda", None)


def test_describe_rename_shows_old_title():
    change = EventChange(
        CHANGED, CAL, occurrence("a", START, title="New"), fields=(FieldChange("title", "Old", "New"),)
    )
    assert describe_change_lines(change) == ['Renamed from "Old".']


# ---- visuals -------------------------------------------------------------


def test_each_kind_has_its_own_icon_and_heading_but_no_color_of_its_own():
    assert set(HEADINGS) == {ADDED, REMOVED, CHANGED}
    assert len(set(HEADINGS.values())) == 3
    # The change cue must never be a color a calendar could have.
    dark = (CHANGE_STRIPE_DARK.red(), CHANGE_STRIPE_DARK.green(), CHANGE_STRIPE_DARK.blue())
    assert dark not in {(c.red(), c.green(), c.blue()) for c in COLOR_CHOICES.values()}


def test_change_blink_loops_until_stopped_and_uses_striped_border():
    flasher = AttentionFlasher()
    flasher.blink_until_stopped()
    assert flasher.is_active
    assert flasher._group.loopCount() == -1
    assert all(o._striped for o in flasher._overlays)
    flasher.stop()
    assert not flasher.is_active


def test_reminder_flash_is_not_striped():
    flasher = AttentionFlasher()
    flasher.flash_until_stopped(fade_ms=50)
    assert not any(o._striped for o in flasher._overlays)
    flasher.stop()


def test_change_alert_dialog_shows_the_right_icon_and_acknowledges_on_close():
    for kind in (ADDED, REMOVED, CHANGED):
        change = EventChange(kind, CAL, occurrence("a", START, title="<b>x</b>"), calendar_name="Boss")
        dialog = ChangeAlertDialog(change, COLOR_CHOICES["red"])
        assert dialog._icon.kind == kind
        dialog._icon.grab()  # paints without error
        acked = []
        dialog.acknowledged.connect(lambda: acked.append(True))
        dialog.show()
        dialog.close()
        assert acked == [True]
