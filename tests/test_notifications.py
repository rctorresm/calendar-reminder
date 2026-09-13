from datetime import datetime, timezone

from reminders.notifications import build_reminder_text, format_lead_time
from reminders.reminder_service import DueEvent


def make_due_event(minutes_until_start):
    return DueEvent(
        event_id="abc123",
        calendar_id="john@example.com",
        calendar_name="John",
        title="Dentist Appointment",
        start=datetime(2026, 8, 17, 10, 0, 0, tzinfo=timezone.utc),
        location=None,
        minutes_until_start=minutes_until_start,
    )


def test_format_lead_time_positive():
    assert format_lead_time(5) == "in 5 min"


def test_format_lead_time_zero_reads_as_now():
    assert format_lead_time(0) == "now"


def test_format_lead_time_slightly_negative_reads_as_now():
    """A 0-minute reminder that fired a few seconds after the exact start
    (see LATE_POLL_GRACE_MINUTES) should still read as 'now', not '-1 min'."""
    assert format_lead_time(-1) == "now"


def test_build_reminder_text_for_event_starting_now():
    text = build_reminder_text(make_due_event(0))
    assert "right now" in text
    assert "-0 minutes" not in text
    assert "0 minutes" not in text


def test_build_reminder_text_for_future_event():
    text = build_reminder_text(make_due_event(12))
    assert "in about 12 minutes" in text
