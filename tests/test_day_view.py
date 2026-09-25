import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

try:
    import winreg  # noqa: F401 — system/startup.py needs it at import time
except ImportError:  # running the suite off Windows
    sys.modules["winreg"] = types.ModuleType("winreg")

import app as app_module  # noqa: E402
from calendar_app import day_view, event_sync  # noqa: E402
from calendar_app.day_view import (  # noqa: E402
    MAX_DAYS_EACH_WAY,
    DayCache,
    DayEvent,
    clamp_day,
    day_bounds,
    format_day_heading,
    sort_day_events,
)
from calendar_app.models import EventOccurrence  # noqa: E402

_app = QApplication.instance() or QApplication([])

CAL = "boss@example.com"
TODAY = date(2026, 9, 25)


def day_event(title, start, is_all_day=False):
    return DayEvent(CAL, "Boss", "blue", title, start, None, None, is_all_day, None)


# ---- pure helpers ---------------------------------------------------------


def test_day_bounds_are_local_midnight_to_midnight():
    start, end = day_bounds(TODAY)
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start.astimezone().date() == TODAY
    assert (start.astimezone().hour, start.astimezone().minute) == (0, 0)
    assert end.astimezone().date() == TODAY + timedelta(days=1)
    assert timedelta(hours=23) <= end - start <= timedelta(hours=25)  # 23/25 on DST days


def test_clamp_day_limits_to_24_months_each_way():
    far_future = TODAY + timedelta(days=5000)
    far_past = TODAY - timedelta(days=5000)
    assert clamp_day(far_future, TODAY) == TODAY + timedelta(days=MAX_DAYS_EACH_WAY)
    assert clamp_day(far_past, TODAY) == TODAY - timedelta(days=MAX_DAYS_EACH_WAY)
    assert clamp_day(TODAY + timedelta(days=10), TODAY) == TODAY + timedelta(days=10)
    assert MAX_DAYS_EACH_WAY >= 365 * 2


def test_all_day_items_sort_first_then_by_time():
    t = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
    events = [day_event("Late", t + timedelta(hours=2)), day_event("Holiday", t, True), day_event("Early", t)]
    assert [e.title for e in sort_day_events(events)] == ["Holiday", "Early", "Late"]


def test_day_heading():
    assert format_day_heading(TODAY, TODAY).startswith("Today — Friday, September 25")
    assert format_day_heading(TODAY + timedelta(days=1), TODAY).startswith("Tomorrow — ")
    assert format_day_heading(TODAY - timedelta(days=1), TODAY).startswith("Yesterday — ")
    assert format_day_heading(TODAY + timedelta(days=10), TODAY) == "Monday, October 5, 2026"


def test_day_cache_expires_but_keeps_a_stale_copy():
    clock = [0.0]
    cache = DayCache(ttl_seconds=300, clock=lambda: clock[0])
    events = [day_event("A", datetime(2026, 9, 25, 15, tzinfo=timezone.utc))]
    assert cache.get("k") is None and cache.stale("k") is None
    cache.put("k", events)
    assert cache.get("k") == events
    clock[0] = 301
    assert cache.get("k") is None  # expired -> caller refetches
    assert cache.stale("k") == events  # ...but can keep showing this meanwhile
    cache.clear()
    assert cache.stale("k") is None


# ---- AppController.fetch_day ------------------------------------------------


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    ctrl = app_module.AppController()
    ctrl.service = object()
    ctrl.current_account_email = CAL
    ctrl.db.upsert_calendars(
        [
            {"calendar_id": CAL, "name": "Boss", "access_role": "reader", "primary": True},
            {"calendar_id": "other@example.com", "name": "Other", "access_role": "reader", "primary": False},
        ],
        CAL,
    )
    ctrl.db.set_calendar_selected(CAL, True)  # "Other" stays unselected
    ctrl.db.set_calendar_flash_color(CAL, "red")
    yield ctrl
    ctrl.db.close()


def occurrence(title, start, calendar_id=CAL, is_all_day=False):
    return EventOccurrence(
        event_id=title, calendar_id=calendar_id, title=title, start=start, end=start + timedelta(minutes=30),
        location="Room 1", is_all_day=is_all_day, status="confirmed", html_link=None, updated_at=start,
    )


def test_fetch_day_asks_google_for_exactly_that_day_on_selected_calendars_only(controller, monkeypatch):
    calls = []
    day = date.today() + timedelta(days=10)
    start, _ = day_bounds(day)

    def fake_fetch(service, calendar_id, time_min, time_max):
        calls.append((calendar_id, time_min, time_max))
        return [occurrence("Late", start + timedelta(hours=15)), occurrence("Early", start + timedelta(hours=9))]

    monkeypatch.setattr(event_sync, "fetch_events", fake_fetch)
    events = controller.fetch_day(day)

    assert calls == [(CAL, *day_bounds(day))]
    assert [e.title for e in events] == ["Early", "Late"]
    assert events[0].calendar_name == "Boss" and events[0].flash_color == "red"
    # Nothing about other days is written to the database.
    assert controller.db.upcoming_events("0000", "9999", CAL) == []


def test_fetch_day_skips_a_calendar_it_lost_access_to(controller, monkeypatch):
    def lost(*_args):
        raise event_sync.CalendarAccessLost(CAL)

    monkeypatch.setattr(event_sync, "fetch_events", lost)
    assert controller.fetch_day(date.today() + timedelta(days=3)) == []


def test_fetch_day_when_signed_out_returns_nothing(controller):
    controller.service = None
    assert controller.fetch_day(date.today()) == []


# ---- MainWindow navigation ----------------------------------------------------


def _wait_for(predicate, timeout_s=5.0):
    import time

    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def test_arrows_step_through_days_and_fetch_each_on_demand(controller, monkeypatch):
    from ui.main_window import DAY_COLUMNS, MainWindow

    requested = []

    def fake_fetch(service, calendar_id, time_min, time_max):
        requested.append(time_min)
        return [occurrence(f"Meeting {len(requested)}", time_min + timedelta(hours=10))]

    monkeypatch.setattr(event_sync, "fetch_events", fake_fetch)
    window = MainWindow(controller)
    today = day_view.local_today()
    assert window._viewing_day is None
    assert not window._today_button.isEnabled()

    window._next_day_button.click()
    assert window._viewing_day == today + timedelta(days=1)
    assert window._today_button.isEnabled()
    assert _wait_for(lambda: window._table.rowCount() == 1)
    assert window._table.horizontalHeaderItem(0).text() == DAY_COLUMNS[0]
    assert window._table.item(0, 2).text() == "Meeting 1"

    # Going back to a day we've already seen uses the cache, no new request.
    window._next_day_button.click()
    assert _wait_for(lambda: len(requested) == 2)
    window._prev_day_button.click()
    QCoreApplication.processEvents()
    assert len(requested) == 2

    window._today_button.click()
    assert window._viewing_day is None
    assert window._table.horizontalHeaderItem(0).text() == "Starts In"


def test_date_picker_jumps_and_is_limited_to_24_months(controller, monkeypatch):
    from PySide6.QtCore import QDate

    from ui.main_window import MainWindow

    monkeypatch.setattr(event_sync, "fetch_events", lambda *a: [])
    window = MainWindow(controller)
    today = day_view.local_today()
    target = today + timedelta(days=40)
    window._date_picker.setDate(QDate(target.year, target.month, target.day))
    assert window._viewing_day == target
    assert _wait_for(lambda: "no meetings" in window._day_heading.text())

    window._show_day(today + timedelta(days=5000))
    assert window._viewing_day == today + timedelta(days=MAX_DAYS_EACH_WAY)
    assert not window._next_day_button.isEnabled()
