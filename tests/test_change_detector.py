from datetime import datetime, timedelta, timezone

from calendar_app.change_detector import ADDED, CHANGED, REMOVED, detect_changes
from calendar_app.models import EventOccurrence

NOW = datetime(2026, 9, 25, 15, 0, 0, tzinfo=timezone.utc)
HORIZON = datetime(2026, 9, 26, 4, 0, 0, tzinfo=timezone.utc)  # "local midnight tonight"


def make_event(event_id="m1", start_in=60, duration=30, **overrides):
    start = NOW + timedelta(minutes=start_in)
    fields = dict(
        event_id=event_id,
        calendar_id="boss@example.com",
        title="Budget review",
        start=start,
        end=start + timedelta(minutes=duration),
        location=None,
        is_all_day=False,
        status="confirmed",
        html_link="https://calendar.google.com/event?eid=x",
        updated_at=NOW,
    )
    fields.update(overrides)
    return EventOccurrence(**fields)


def test_nothing_changed_means_no_alerts():
    events = [make_event("a"), make_event("b", start_in=120)]
    assert detect_changes(events, list(events), HORIZON, NOW) == []


def test_new_meeting_is_added():
    before = [make_event("a")]
    after = [make_event("a"), make_event("b", start_in=120, title="Surprise 1:1")]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert [(c.kind, c.event.event_id) for c in changes] == [(ADDED, "b")]


def test_removed_meeting_that_had_not_happened_yet():
    before = [make_event("a"), make_event("b", start_in=120)]
    after = [make_event("a")]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert [(c.kind, c.event.event_id) for c in changes] == [(REMOVED, "b")]


def test_meeting_that_simply_ended_is_not_reported_as_removed():
    """Google stops returning a meeting once its END passes timeMin —
    that's not a cancellation."""
    ended = make_event("a", start_in=-30, duration=30)  # ended exactly at NOW
    changes = detect_changes([ended], [], HORIZON, NOW)
    assert changes == []


def test_in_progress_meeting_that_disappears_is_removed():
    running = make_event("a", start_in=-10, duration=30)
    changes = detect_changes([running], [], HORIZON, NOW)
    assert [c.kind for c in changes] == [REMOVED]


def test_midnight_rollover_does_not_flag_tomorrows_meetings_as_added():
    """At midnight the window grows by a day; tomorrow's meetings weren't
    'added', they just came into view."""
    tomorrow = make_event("t", start_in=(HORIZON - NOW).total_seconds() / 60 + 9 * 60)
    changes = detect_changes([], [tomorrow], HORIZON, NOW)
    assert changes == []


def test_meeting_added_right_before_old_horizon_is_still_added():
    late = make_event("late", start_in=(HORIZON - NOW).total_seconds() / 60 - 30)
    changes = detect_changes([], [late], HORIZON, NOW)
    assert [c.kind for c in changes] == [ADDED]


def test_time_moved_is_one_change_not_remove_plus_add():
    before = [make_event("a", start_in=60)]
    after = [make_event("a", start_in=150)]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert len(changes) == 1
    change = changes[0]
    assert change.kind == CHANGED
    assert {f.field for f in change.fields} == {"start", "end"}
    start_change = next(f for f in change.fields if f.field == "start")
    assert start_change.old == before[0].start
    assert start_change.new == after[0].start


def test_title_change():
    before = [make_event("a", title="Budget review")]
    after = [make_event("a", title="Budget review (MOVED ROOMS)")]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert [c.kind for c in changes] == [CHANGED]
    assert [(f.field, f.old, f.new) for f in changes[0].fields] == [
        ("title", "Budget review", "Budget review (MOVED ROOMS)")
    ]


def test_location_change_and_none_vs_empty_is_not_a_change():
    assert detect_changes([make_event("a", location=None)], [make_event("a", location="")], HORIZON, NOW) == []
    changes = detect_changes([make_event("a", location="Room 1")], [make_event("a", location="Zoom")], HORIZON, NOW)
    assert [f.field for f in changes[0].fields] == ["location"]


def test_description_change():
    before = [make_event("a", description="Agenda: Q3 numbers")]
    after = [make_event("a", description="Agenda: Q3 numbers + hiring plan")]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert [f.field for f in changes[0].fields] == ["description"]


def test_description_whitespace_or_none_vs_empty_is_not_a_change():
    assert detect_changes([make_event("a", description=None)], [make_event("a", description="")], HORIZON, NOW) == []
    assert detect_changes([make_event("a", description="Notes")], [make_event("a", description="Notes \n")], HORIZON, NOW) == []


def test_updated_at_alone_is_not_a_change():
    """Google bumps `updated` for RSVPs and other things nobody needs an
    alert for."""
    before = [make_event("a", updated_at=NOW)]
    after = [make_event("a", updated_at=NOW + timedelta(minutes=1))]
    assert detect_changes(before, after, HORIZON, NOW) == []


def test_mixed_changes_are_sorted_by_start_time():
    before = [make_event("keep", start_in=30), make_event("gone", start_in=200), make_event("edit", start_in=100)]
    after = [make_event("keep", start_in=30), make_event("new", start_in=10), make_event("edit", start_in=100, title="X")]
    changes = detect_changes(before, after, HORIZON, NOW)
    assert [(c.kind, c.event.event_id) for c in changes] == [
        (ADDED, "new"),
        (CHANGED, "edit"),
        (REMOVED, "gone"),
    ]


def test_change_keys_are_distinct_per_kind():
    before = [make_event("a")]
    after = [make_event("a", title="Other")]
    changed = detect_changes(before, after, HORIZON, NOW)[0]
    removed = detect_changes(before, [], HORIZON, NOW)[0]
    assert changed.key != removed.key
