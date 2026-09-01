from datetime import timezone

from calendar_app.event_sync import parse_event


def test_normal_timed_event():
    item = {
        "id": "abc123",
        "status": "confirmed",
        "summary": "Dentist Appointment",
        "start": {"dateTime": "2026-08-17T10:30:00-07:00"},
        "end": {"dateTime": "2026-08-17T11:00:00-07:00"},
        "updated": "2026-08-01T00:00:00Z",
    }
    event = parse_event(item, "john@example.com")
    assert event is not None
    assert event.event_id == "abc123"
    assert event.is_all_day is False
    assert event.status == "confirmed"
    # 10:30 PDT (-07:00) == 17:30 UTC
    assert event.start.astimezone(timezone.utc).hour == 17
    assert event.start.astimezone(timezone.utc).minute == 30


def test_cancelled_event_is_dropped():
    item = {
        "id": "abc123",
        "status": "cancelled",
        "start": {"dateTime": "2026-08-17T10:30:00-07:00"},
    }
    assert parse_event(item, "john@example.com") is None


def test_all_day_event_flagged():
    item = {
        "id": "holiday1",
        "status": "confirmed",
        "summary": "Labor Day",
        "start": {"date": "2026-09-07"},
        "end": {"date": "2026-09-08"},
    }
    event = parse_event(item, "us_holidays@group.v.calendar.google.com")
    assert event is not None
    assert event.is_all_day is True


def test_missing_title_gets_placeholder():
    item = {
        "id": "abc123",
        "status": "confirmed",
        "start": {"dateTime": "2026-08-17T10:30:00-07:00"},
        "end": {"dateTime": "2026-08-17T11:00:00-07:00"},
    }
    event = parse_event(item, "john@example.com")
    assert event.title == "(No title)"


def test_recurring_occurrences_have_distinct_start_times():
    """singleEvents=True expansion: same event id, different start times —
    each occurrence must be independently addressable (event_id + start)."""
    base = {
        "id": "recurring1",
        "status": "confirmed",
        "summary": "Weekly Sync",
        "end": {"dateTime": "2026-08-17T10:00:00-07:00"},
    }
    occ1 = parse_event({**base, "start": {"dateTime": "2026-08-17T09:30:00-07:00"}}, "cal1")
    occ2 = parse_event({**base, "start": {"dateTime": "2026-08-24T09:30:00-07:00"}}, "cal1")
    assert occ1.event_id == occ2.event_id
    assert occ1.start != occ2.start


def test_utc_z_suffix_parses():
    item = {
        "id": "z1",
        "status": "confirmed",
        "start": {"dateTime": "2026-08-17T10:30:00Z"},
        "end": {"dateTime": "2026-08-17T11:00:00Z"},
    }
    event = parse_event(item, "cal1")
    assert event.start.tzinfo is not None
    assert event.start.utcoffset().total_seconds() == 0
