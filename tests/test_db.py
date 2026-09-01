import sqlite3

import pytest

from database.db import Database

ACCOUNT_A = "john@example.com"
ACCOUNT_B = "sarah@example.com"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_calendar_selection_roundtrip(db):
    db.upsert_calendars(
        [
            {"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False},
            {"calendar_id": "cal2@x.com", "name": "Cal2", "access_role": "reader", "primary": False},
        ],
        ACCOUNT_A,
    )
    db.set_calendar_selected("cal1@x.com", True)
    assert db.list_selected_calendar_ids(ACCOUNT_A) == ["cal1@x.com"]


def test_selection_survives_calendar_metadata_refresh(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.set_calendar_selected("cal1@x.com", True)
    # Re-sync with a renamed calendar — selection state must be preserved.
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1 Renamed", "access_role": "reader", "primary": False}],
        ACCOUNT_A,
    )
    assert db.list_selected_calendar_ids(ACCOUNT_A) == ["cal1@x.com"]


def test_removed_calendar_is_dropped(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.upsert_calendars([], ACCOUNT_A)
    assert db.list_calendars(ACCOUNT_A) == []


def test_duplicate_notification_prevention(db):
    assert db.was_notified("abc123", "john@example.com", "2026-08-17T10:30:00+00:00") is False
    db.mark_notified(
        "abc123",
        "john@example.com",
        "2026-08-17T10:30:00+00:00",
        "2026-08-17T10:15:00+00:00",
        "2026-08-17T10:15:01+00:00",
    )
    assert db.was_notified("abc123", "john@example.com", "2026-08-17T10:30:00+00:00") is True
    # A second mark_notified for the exact same key must not raise or duplicate.
    db.mark_notified(
        "abc123",
        "john@example.com",
        "2026-08-17T10:30:00+00:00",
        "2026-08-17T10:16:00+00:00",
        "2026-08-17T10:16:01+00:00",
    )


def test_event_moved_is_a_distinct_notification_key(db):
    """abc123 at 10:30 and abc123 at 11:30 must be tracked independently."""
    db.mark_notified(
        "abc123",
        "john@example.com",
        "2026-08-17T10:30:00+00:00",
        "2026-08-17T10:15:00+00:00",
        "2026-08-17T10:15:01+00:00",
    )
    assert db.was_notified("abc123", "john@example.com", "2026-08-17T11:30:00+00:00") is False


def test_new_calendar_defaults_to_blue_flash_color(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    assert db.get_calendar_flash_color("cal1@x.com") == "blue"


def test_flash_color_roundtrip(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.set_calendar_flash_color("cal1@x.com", "purple")
    assert db.get_calendar_flash_color("cal1@x.com") == "purple"


def test_flash_color_survives_calendar_metadata_refresh(db):
    """Re-syncing calendar names/roles from Google must not reset a color
    the person deliberately picked — same principle as `selected`."""
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.set_calendar_flash_color("cal1@x.com", "orange")
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1 Renamed", "access_role": "reader", "primary": False}],
        ACCOUNT_A,
    )
    assert db.get_calendar_flash_color("cal1@x.com") == "orange"


def test_get_flash_color_for_unknown_calendar_returns_default(db):
    assert db.get_calendar_flash_color("nonexistent@example.com") == "blue"


# ---- per-account scoping (switching Google accounts must not lose data) --


def test_switching_accounts_does_not_delete_the_other_accounts_calendars(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "John's calendar", "access_role": "reader", "primary": True}],
        ACCOUNT_A,
    )
    db.set_calendar_flash_color("cal1@x.com", "teal")
    db.set_calendar_selected("cal1@x.com", True)

    # Switch to a completely different account with different calendars.
    db.upsert_calendars(
        [{"calendar_id": "cal2@x.com", "name": "Sarah's calendar", "access_role": "reader", "primary": True}],
        ACCOUNT_B,
    )

    # Account A's calendar (and its color/selection) must still be there.
    assert [row["calendar_id"] for row in db.list_calendars(ACCOUNT_A)] == ["cal1@x.com"]
    assert db.get_calendar_flash_color("cal1@x.com") == "teal"
    assert db.list_selected_calendar_ids(ACCOUNT_A) == ["cal1@x.com"]

    # Account B only sees its own calendar, not account A's.
    assert [row["calendar_id"] for row in db.list_calendars(ACCOUNT_B)] == ["cal2@x.com"]


def test_returning_to_a_previous_account_shows_its_remembered_color(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "John's calendar", "access_role": "reader", "primary": True}],
        ACCOUNT_A,
    )
    db.set_calendar_flash_color("cal1@x.com", "pink")

    # Switch away, then switch back — re-syncing the same account's
    # calendars again (as a real sign-back-in would).
    db.upsert_calendars(
        [{"calendar_id": "cal2@x.com", "name": "Sarah's calendar", "access_role": "reader", "primary": True}],
        ACCOUNT_B,
    )
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "John's calendar", "access_role": "reader", "primary": True}],
        ACCOUNT_A,
    )

    assert db.get_calendar_flash_color("cal1@x.com") == "pink"


def test_removed_calendar_only_dropped_within_its_own_account(db):
    """upsert_calendars([], account) must scope its cleanup DELETE to
    that account — not wipe every other account's calendars too."""
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.upsert_calendars(
        [{"calendar_id": "cal2@x.com", "name": "Cal2", "access_role": "reader", "primary": False}], ACCOUNT_B
    )
    db.upsert_calendars([], ACCOUNT_A)  # account A now has zero calendars

    assert db.list_calendars(ACCOUNT_A) == []
    assert [row["calendar_id"] for row in db.list_calendars(ACCOUNT_B)] == ["cal2@x.com"]


def test_backfill_account_email_assigns_only_orphaned_rows(db):
    db.upsert_calendars(
        [{"calendar_id": "cal1@x.com", "name": "Cal1", "access_role": "reader", "primary": False}], ACCOUNT_A
    )
    db.backfill_account_email(ACCOUNT_B)  # must not steal an already-assigned row
    assert [row["calendar_id"] for row in db.list_calendars(ACCOUNT_A)] == ["cal1@x.com"]


def test_migration_adds_account_email_and_flash_color_to_a_pre_existing_database(tmp_path):
    """Simulates a real user's already-created database from before these
    columns existed — CREATE TABLE IF NOT EXISTS alone would silently
    skip adding them, so this must go through the explicit migration
    path. Right after migration, orphaned rows (account_email IS NULL)
    correctly don't show up for any account until backfill_account_email
    runs — exactly what the first sync after upgrading does."""
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute(
        """CREATE TABLE calendars (
               calendar_id TEXT PRIMARY KEY,
               name        TEXT NOT NULL,
               selected    INTEGER NOT NULL DEFAULT 0,
               access_role TEXT NOT NULL,
               primary_cal INTEGER NOT NULL DEFAULT 0
           )"""
    )
    raw.execute(
        "INSERT INTO calendars (calendar_id, name, selected, access_role, primary_cal) "
        "VALUES ('john@example.com', 'John', 1, 'reader', 0)"
    )
    raw.commit()
    raw.close()

    database = Database(db_path)
    try:
        assert database.get_calendar_flash_color("john@example.com") == "blue"
        assert database.list_selected_calendar_ids(ACCOUNT_A) == []  # orphaned — not backfilled yet

        database.backfill_account_email(ACCOUNT_A)
        assert database.list_selected_calendar_ids(ACCOUNT_A) == ["john@example.com"]
    finally:
        database.close()
