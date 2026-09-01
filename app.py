"""Application entry point and orchestration.

AppController owns the local database, the Google Calendar connection, and
the two polling loops described in the spec:

* sync loop (every minute, on the wall-clock :00): pull events for
  selected calendars into the local cache.
* reminder loop (every 30 seconds, on :00 and :30): check the cache for
  events entering the reminder window and fire notifications, with
  duplicate prevention.

Nothing in this module sends calendar data anywhere except to/from Google's
own Calendar API — no analytics, no telemetry, no third-party server.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from apscheduler.executors.pool import ThreadPoolExecutor as APThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from PySide6.QtCore import QObject, QSharedMemory, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

import config
from auth import google_auth
from calendar_app import calendar_service, event_sync
from database.db import Database
from reminders import reminder_service
from reminders.notifications import Notifier
from system import startup

logger = logging.getLogger(__name__)

REMINDER_INTERVAL_SECONDS = 30


class Worker(QThread):
    """Runs a blocking call off the GUI thread so sign-in (which opens a
    browser and waits on the user) never freezes the window."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI, not swallowed
            logger.exception("Background task failed")
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class GatedNotifier:
    """Wraps Notifier so the Settings > Notifications > 'Enable desktop
    notifications' checkbox actually takes effect."""

    def __init__(self, db: Database, notifier: Notifier):
        self._db = db
        self._notifier = notifier

    def notify(self, event) -> None:
        if self._db.get_setting("notifications_enabled", "1") == "1":
            play_sound = self._db.get_setting("sound_enabled", "1") == "1"
            self._notifier.notify(event, play_sound=play_sound)


class AppController(QObject):
    calendars_updated = Signal()
    events_updated = Signal()
    auth_state_changed = Signal(bool)
    connection_status_changed = Signal(str)
    reminder_fired = Signal(object)  # reminder_service.DueEvent

    def __init__(self):
        super().__init__()
        self.db = Database(config.db_path())
        self.notifier = GatedNotifier(self.db, Notifier())
        self.service = None
        self.current_account_email: str | None = None
        self._paused = False
        self._last_reminder_tick = datetime.now(timezone.utc)
        # A single worker thread: the sync job and the reminder job must
        # never run concurrently against the shared sqlite3 connection
        # (Database is not safe for concurrent writers across threads).
        self._scheduler = BackgroundScheduler(
            daemon=True, executors={"default": APThreadPoolExecutor(max_workers=1)}
        )

    # ---- auth ----------------------------------------------------------

    @property
    def is_signed_in(self) -> bool:
        return self.service is not None

    def restore_session(self) -> None:
        """Silently reuse a stored token at startup, if one exists — no
        browser popup, no prompt."""
        if not google_auth.is_signed_in():
            return
        try:
            creds = google_auth.get_credentials(config.client_secret_path())
            self.service = calendar_service.build_service(creds)
            self.auth_state_changed.emit(True)
            self.sync_calendars()
        except Exception:
            logger.exception("Could not restore saved Google session")
            self.connection_status_changed.emit("Google Calendar connection needs to be renewed.")

    def sign_in(self) -> None:
        """Blocking: opens the browser-based consent screen. Call via
        Worker from the UI, never directly on the GUI thread."""
        creds = google_auth.get_credentials(config.client_secret_path())
        self.service = calendar_service.build_service(creds)

    def finish_sign_in(self) -> None:
        self.auth_state_changed.emit(True)
        self.sync_calendars()

    def sign_out(self) -> None:
        google_auth.sign_out()
        self.service = None
        self.current_account_email = None
        self.auth_state_changed.emit(False)

    # ---- sync ------------------------------------------------------

    def sync_calendars(self) -> None:
        if not self.service:
            return
        try:
            calendars = calendar_service.list_calendars(self.service)
            account_email = calendar_service.find_account_email(calendars)
            if account_email is None:
                logger.error("Could not determine the signed-in account's email from its calendar list")
                self.connection_status_changed.emit("Calendar connection unavailable")
                return
            self.current_account_email = account_email
            self.db.backfill_account_email(account_email)
            self.db.upsert_calendars(
                [
                    {
                        "calendar_id": c.calendar_id,
                        "name": c.name,
                        "access_role": c.access_role,
                        "primary": c.primary,
                    }
                    for c in calendars
                ],
                account_email,
            )
            self.connection_status_changed.emit("")
            self.calendars_updated.emit()
        except Exception:
            logger.exception("Failed to list calendars")
            self.connection_status_changed.emit("Calendar connection unavailable")

    def sync_events(self) -> None:
        if not self.service or self._paused:
            return
        try:
            now = datetime.now(timezone.utc)
            horizon = reminder_service.end_of_local_day(now)  # just today, not a rolling 24h window
            for calendar_id in self.db.list_selected_calendar_ids(self.current_account_email):
                occurrences = event_sync.fetch_events(self.service, calendar_id, now, horizon)
                self.db.replace_events_for_calendar(calendar_id, [o.to_row() for o in occurrences])
            self.connection_status_changed.emit("")
            self.events_updated.emit()
        except Exception:
            logger.exception("Failed to sync events")
            self.connection_status_changed.emit("Calendar connection unavailable")

    def sync_calendars_and_events(self) -> None:
        """Refreshing the calendar list every cycle (not just at sign-in)
        means a calendar newly shared with this account shows up on its
        own within one cycle instead of requiring a manual Refresh
        click."""
        self.sync_calendars()
        self.sync_events()

    def sync_then_check_reminders(self) -> None:
        """The wall-clock :00 job: sync, THEN check for due reminders —
        as one function call, so sync is always finished before the
        reminder check that follows it. Two independent jobs both due at
        the same instant would race (the reminder check could run first
        and see stale data, deferring a just-synced event to the next
        :30 tick instead of firing on the same tick as the refresh)."""
        self.sync_calendars_and_events()
        self.reminder_cycle()

    # ---- reminders -------------------------------------------------

    def reminder_cycle(self) -> None:
        if self._paused or not self.service:
            return
        now = datetime.now(timezone.utc)
        if reminder_service.detect_long_gap(self._last_reminder_tick, now, REMINDER_INTERVAL_SECONDS):
            logger.info("Detected a long gap since the last check (sleep/resume) — syncing now.")
            self.sync_events()
        self._last_reminder_tick = now

        try:
            due = reminder_service.run_reminder_cycle(
                self.db, self.notifier, now, self.current_account_email
            )
        except Exception:
            logger.exception("Reminder cycle failed")
            return
        for event in due:
            self.reminder_fired.emit(event)
        if due:
            self.events_updated.emit()

    # ---- settings ----------------------------------------------------

    def set_reminder_minutes(self, minutes: int) -> None:
        self.db.set_setting("reminder_minutes", str(minutes))

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def set_calendar_selected(self, calendar_id: str, selected: bool) -> None:
        self.db.set_calendar_selected(calendar_id, selected)
        self.sync_events()

    # ---- lifecycle ---------------------------------------------------

    def start_scheduler(self) -> None:
        # Wall-clock-aligned (cron), not interval-since-launch: fixed
        # seconds of every minute rather than drifting based on whatever
        # moment the app happened to start.
        #
        # The :00 tick runs sync_then_check_reminders — sync followed by
        # a reminder check IN THE SAME FUNCTION CALL, not as two separate
        # jobs that both happen to be due at :00. Two independent jobs
        # due at the same instant have no guaranteed order between them;
        # a plain sequential call does.
        #
        # 1 API call to list calendars + 1 call per monitored calendar,
        # once a minute — a handful of calls/minute, far below Google's
        # Calendar API quota (600 requests/minute per user).
        self._scheduler.add_job(
            self.sync_then_check_reminders,
            CronTrigger(second=0),
            next_run_time=datetime.now(),
        )
        # The :30 tick is a reminder check only (no sync) — keeps the
        # 30-second reminder cadence between syncs.
        self._scheduler.add_job(
            self.reminder_cycle,
            CronTrigger(second=30),
            next_run_time=datetime.now(),
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        self.db.close()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(config.log_path(), encoding="utf-8"), logging.StreamHandler()],
    )
    # Never let a token/credential object end up in a log line.
    logging.getLogger("google_auth_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description="Desktop Calendar Reminder")
    parser.add_argument(
        "--minimized", action="store_true", help="Start minimized to the system tray (used by Start with Windows)"
    )
    args = parser.parse_args()

    _configure_logging()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if config.icon_path().exists():
        app.setWindowIcon(QIcon(str(config.icon_path())))

    # Single-instance guard: a shared SQLite DB with two processes polling
    # it independently could each decide "not yet notified" at the same
    # moment and send a duplicate reminder — the one thing this app must
    # never do.
    shared_memory = QSharedMemory("CalendarReminderApp-singleton")
    if not shared_memory.create(1):
        QMessageBox.warning(
            None, "Calendar Reminder", "Calendar Reminder is already running (check the system tray)."
        )
        return 1

    from ui.main_window import MainWindow  # imported late so --help stays fast

    controller = AppController()
    controller.restore_session()
    controller.start_scheduler()

    window = MainWindow(controller)
    if not args.minimized:
        window.show()

    from system.tray import TrayIcon

    tray = TrayIcon(controller, window)
    tray.show()

    startup.sync_registration(controller.db.get_setting("start_with_windows", "0") == "1")

    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
