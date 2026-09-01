from datetime import datetime, timedelta, timezone

from reminders.reminder_service import detect_long_gap, end_of_local_day, find_due_events

NOW = datetime(2026, 8, 17, 10, 0, 0, tzinfo=timezone.utc)


def make_event(minutes_from_now, **overrides):
    event = {
        "event_id": "abc123",
        "calendar_id": "john@example.com",
        "calendar_name": "John",
        "title": "Dentist Appointment",
        "start_time": (NOW + timedelta(minutes=minutes_from_now)).isoformat(),
        "location": None,
        "status": "confirmed",
        "is_all_day": 0,
    }
    event.update(overrides)
    return event


def test_event_within_threshold_is_due():
    events = [make_event(14)]
    due = find_due_events(events, NOW, threshold_minutes=15)
    assert len(due) == 1
    assert due[0].event_id == "abc123"


def test_event_outside_threshold_is_not_due():
    events = [make_event(20)]
    due = find_due_events(events, NOW, threshold_minutes=15)
    assert due == []


def test_event_already_started_is_not_due():
    events = [make_event(-5)]
    due = find_due_events(events, NOW, threshold_minutes=15)
    assert due == []


def test_cancelled_event_excluded():
    events = [make_event(10, status="cancelled")]
    assert find_due_events(events, NOW, threshold_minutes=15) == []


def test_all_day_event_excluded():
    events = [make_event(10, is_all_day=1)]
    assert find_due_events(events, NOW, threshold_minutes=15) == []


def test_wake_from_sleep_notifies_immediately_within_window():
    """Computer sleeps, wakes 12 minutes before a 15-min-reminder event —
    should be due right away, not wait for the 'normal' 15-minute mark."""
    events = [make_event(12)]
    due = find_due_events(events, NOW, threshold_minutes=15)
    assert len(due) == 1


def test_event_moved_is_evaluated_at_new_time():
    original = make_event(20, start_time=(NOW + timedelta(hours=1)).isoformat())
    moved = make_event(10)
    due = find_due_events([original, moved], NOW, threshold_minutes=15)
    assert len(due) == 1
    assert due[0].start == (NOW + timedelta(minutes=10))


def test_multiple_calendars_same_time_both_due():
    events = [
        make_event(10, event_id="e1", calendar_id="john@example.com", calendar_name="John"),
        make_event(10, event_id="e2", calendar_id="sarah@example.com", calendar_name="Sarah"),
    ]
    due = find_due_events(events, NOW, threshold_minutes=15)
    assert {d.event_id for d in due} == {"e1", "e2"}


def test_sleep_gap_detected():
    last_tick = NOW
    resumed_at = NOW + timedelta(minutes=47)
    assert detect_long_gap(last_tick, resumed_at, expected_interval_seconds=30) is True


def test_normal_tick_not_flagged_as_gap():
    last_tick = NOW
    next_tick = NOW + timedelta(seconds=30)
    assert detect_long_gap(last_tick, next_tick, expected_interval_seconds=30) is False


def test_end_of_local_day_is_local_midnight_tonight():
    """Whatever the machine's local timezone is, the boundary must land
    exactly on local midnight — not a rolling 24h window from 'now'."""
    boundary = end_of_local_day(NOW)
    local_boundary = boundary.astimezone()
    assert (local_boundary.hour, local_boundary.minute, local_boundary.second, local_boundary.microsecond) == (
        0,
        0,
        0,
        0,
    )
    local_now = NOW.astimezone()
    assert local_boundary.date() == local_now.date() + timedelta(days=1)


def test_end_of_local_day_is_within_24_hours_of_now():
    boundary = end_of_local_day(NOW)
    assert NOW < boundary <= NOW + timedelta(hours=24)
