"""Local SQLite storage. All queries are parameterized — never format
user- or API-derived strings directly into SQL."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

# Embedded directly rather than read from schema.sql as a separate data
# file: a loose .sql file is invisible to PyInstaller's automatic import
# analysis (it only auto-bundles Python modules), so it silently didn't
# ship in a real packaged build unless remembered as a manual --add-data
# flag on every future build. Keeping the schema as a plain Python string
# makes "it's part of the source" the only thing that has to be true.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendars (
    calendar_id  TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    selected     INTEGER NOT NULL DEFAULT 0,
    access_role  TEXT NOT NULL,
    primary_cal  INTEGER NOT NULL DEFAULT 0,
    flash_color  TEXT NOT NULL DEFAULT 'blue',
    account_email TEXT
);

-- The account_email index is created in Database._migrate(), not here —
-- on a pre-existing database this script only CREATEs tables that don't
-- exist yet, but this index statement would still run unconditionally
-- and fail on a legacy table that doesn't have the column until the
-- migration adds it.

CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT NOT NULL,
    calendar_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    start_time   TEXT NOT NULL,
    end_time     TEXT,
    location     TEXT,
    is_all_day   INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'confirmed',
    html_link    TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (event_id, calendar_id, start_time),
    FOREIGN KEY (calendar_id) REFERENCES calendars(calendar_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);

CREATE TABLE IF NOT EXISTS notifications (
    event_id          TEXT NOT NULL,
    calendar_id       TEXT NOT NULL,
    event_start       TEXT NOT NULL,
    notification_time TEXT NOT NULL,
    sent_at           TEXT NOT NULL,
    PRIMARY KEY (event_id, calendar_id, event_start)
);
"""


class Database:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
        self._migrate()

    def _migrate(self) -> None:
        """CREATE TABLE IF NOT EXISTS in the embedded schema only applies
        to a table that doesn't exist yet — it does nothing for a
        database file that was already created before a column was
        added. Handle
        that here instead of requiring anyone to delete their local db."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(calendars)")}
        with self._conn:
            if "flash_color" not in columns:
                self._conn.execute(
                    "ALTER TABLE calendars ADD COLUMN flash_color TEXT NOT NULL DEFAULT 'blue'"
                )
            if "account_email" not in columns:
                self._conn.execute("ALTER TABLE calendars ADD COLUMN account_email TEXT")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_calendars_account ON calendars(account_email)"
            )

    def close(self) -> None:
        self._conn.close()

    # ---- settings ----------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---- calendars ------------------------------------------------
    #
    # Every calendar row is scoped to the Google account it came from
    # (account_email — see calendar_service.find_account_email). Signing
    # out and back into the same account, or switching to a different
    # one and back, must never lose a calendar's selection/color: rows
    # for an account that isn't currently signed in are simply left
    # alone, never deleted, and never shown until that account is active
    # again.
    #
    # Known limitation: calendar_id is still the primary key, so if the
    # exact same calendar were ever visible to two different Google
    # accounts on this machine, only one account's row would "win". This
    # doesn't happen in the normal single-person-switching-accounts case
    # this feature is for.

    def upsert_calendars(self, calendars: Iterable[dict], account_email: str) -> None:
        with self._conn:
            for cal in calendars:
                existing = self._conn.execute(
                    "SELECT selected, flash_color FROM calendars WHERE calendar_id = ?",
                    (cal["calendar_id"],),
                ).fetchone()
                selected = existing["selected"] if existing else 0
                flash_color = existing["flash_color"] if existing else "blue"
                self._conn.execute(
                    """INSERT INTO calendars
                       (calendar_id, name, selected, access_role, primary_cal, flash_color, account_email)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(calendar_id) DO UPDATE SET
                           name = excluded.name,
                           access_role = excluded.access_role,
                           primary_cal = excluded.primary_cal,
                           account_email = excluded.account_email""",
                    (
                        cal["calendar_id"],
                        cal["name"],
                        selected,
                        cal["access_role"],
                        int(cal.get("primary", False)),
                        flash_color,
                        account_email,
                    ),
                )
            # Drop calendars that no longer appear for THIS account only
            # (removed / access revoked) — never touches other accounts'
            # rows.
            live_ids = [c["calendar_id"] for c in calendars]
            if live_ids:
                placeholders = ",".join("?" for _ in live_ids)
                self._conn.execute(
                    f"DELETE FROM calendars WHERE account_email = ? AND calendar_id NOT IN ({placeholders})",
                    [account_email, *live_ids],
                )
            else:
                self._conn.execute(
                    "DELETE FROM calendars WHERE account_email = ?", (account_email,)
                )

    def backfill_account_email(self, account_email: str) -> None:
        """One-time migration helper: calendar rows created before this
        feature existed have account_email = NULL. The first successful
        sync after upgrading assigns any such orphaned rows to whichever
        account is currently signed in — a reasonable default since,
        before this feature, the app only ever supported one account's
        calendars being present at a time anyway."""
        with self._conn:
            self._conn.execute(
                "UPDATE calendars SET account_email = ? WHERE account_email IS NULL",
                (account_email,),
            )

    def set_calendar_selected(self, calendar_id: str, selected: bool) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE calendars SET selected = ? WHERE calendar_id = ?",
                (int(selected), calendar_id),
            )

    def set_calendar_flash_color(self, calendar_id: str, color_name: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE calendars SET flash_color = ? WHERE calendar_id = ?",
                (color_name, calendar_id),
            )

    def get_calendar_flash_color(self, calendar_id: str, default: str = "blue") -> str:
        row = self._conn.execute(
            "SELECT flash_color FROM calendars WHERE calendar_id = ?", (calendar_id,)
        ).fetchone()
        return row["flash_color"] if row else default

    def list_calendars(self, account_email: str | None) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM calendars WHERE account_email = ? "
            "ORDER BY primary_cal DESC, name COLLATE NOCASE",
            (account_email,),
        ).fetchall()

    def list_selected_calendar_ids(self, account_email: str | None) -> list[str]:
        rows = self._conn.execute(
            "SELECT calendar_id FROM calendars WHERE account_email = ? AND selected = 1",
            (account_email,),
        ).fetchall()
        return [r["calendar_id"] for r in rows]

    # ---- events ------------------------------------------------------

    def replace_events_for_calendar(self, calendar_id: str, events: Iterable[dict]) -> None:
        """Replace the cached event window for one calendar with a fresh set
        (drops events that disappeared, e.g. were cancelled/deleted upstream)."""
        events = list(events)
        with self._conn:
            self._conn.execute("DELETE FROM events WHERE calendar_id = ?", (calendar_id,))
            self._conn.executemany(
                """INSERT INTO events
                   (event_id, calendar_id, title, start_time, end_time, location,
                    is_all_day, status, html_link, updated_at)
                   VALUES (:event_id, :calendar_id, :title, :start_time, :end_time,
                           :location, :is_all_day, :status, :html_link, :updated_at)""",
                events,
            )

    def upcoming_events(
        self, now_iso: str, horizon_iso: str, account_email: str | None
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT e.*, c.name AS calendar_name, c.flash_color FROM events e
               JOIN calendars c ON c.calendar_id = e.calendar_id
               WHERE c.account_email = ?
                 AND c.selected = 1
                 AND e.status != 'cancelled'
                 AND e.is_all_day = 0
                 AND e.start_time >= ? AND e.start_time <= ?
               ORDER BY e.start_time""",
            (account_email, now_iso, horizon_iso),
        ).fetchall()

    # ---- notifications -------------------------------------------------

    def was_notified(self, event_id: str, calendar_id: str, event_start_iso: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM notifications WHERE event_id = ? AND calendar_id = ? AND event_start = ?",
            (event_id, calendar_id, event_start_iso),
        ).fetchone()
        return row is not None

    def mark_notified(
        self,
        event_id: str,
        calendar_id: str,
        event_start_iso: str,
        notification_time_iso: str,
        sent_at_iso: str,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO notifications
                   (event_id, calendar_id, event_start, notification_time, sent_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, calendar_id, event_start_iso, notification_time_iso, sent_at_iso),
            )

    def prune_old_notifications(self, before_iso: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM notifications WHERE event_start < ?", (before_iso,)
            )
