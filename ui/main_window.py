from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import QCloseEvent, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config
from calendar_app import day_view
from reminders.attention_cue import (
    DEFAULT_SPEED_NAME,
    AttentionFlasher,
    resolve_color,
    resolve_fade_ms,
)
from reminders import reminder_service
from reminders.notifications import build_reminder_text, format_time_12h
from ui.change_alert import ChangeAlertDialog
from ui.reminder_alert import ReminderAlertDialog

COLUMNS = ["Starts In", "Calendar", "Event", "Time"]
DAY_COLUMNS = ["Time", "Calendar", "Event", "Location"]

# Looking at another day snaps back to today after this long without
# touching the arrows/date picker, so the window left open on some other
# day doesn't hide what's coming up next.
RETURN_TO_TODAY_MS = 10 * 60 * 1000


def _format_time_range(event) -> str:
    if event.is_all_day:
        return "All day"
    if event.end is None:
        return format_time_12h(event.start)
    return f"{format_time_12h(event.start)} – {format_time_12h(event.end)}"


def _format_countdown(minutes: float) -> str:
    minutes = max(0, round(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def _tinted(color: QColor, amount: float = 0.75) -> QColor:
    """A pastel version of `color`, blended toward white by `amount`
    (0 = original color, 1 = white) — used as a row background so the
    calendar's flash color is recognizable at a glance without making
    the default black text hard to read against it."""

    def blend(channel: int) -> int:
        return int(channel + (255 - channel) * amount)

    return QColor(blend(color.red()), blend(color.green()), blend(color.blue()))


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._onboarded = False
        self._attention_flasher = AttentionFlasher()
        self._open_alerts: dict[tuple, ReminderAlertDialog] = {}
        # Meeting added/removed/changed alerts get their own flasher (a
        # different, dashed double-blink border) and their own set of open
        # windows, so a reminder and a change alert never overwrite each
        # other's cue.
        self._change_flasher = AttentionFlasher()
        self._open_change_alerts: dict[tuple, ChangeAlertDialog] = {}
        self.setWindowTitle("Calendar Reminder")
        if config.icon_path().exists():
            self.setWindowIcon(QIcon(str(config.icon_path())))
        self.resize(720, 480)

        central = QWidget()
        layout = QVBoxLayout(central)

        self._signin_bar = self._build_signin_bar()
        layout.addWidget(self._signin_bar)

        toolbar_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self._open_settings)
        toolbar_row.addWidget(refresh_button)
        toolbar_row.addWidget(settings_button)
        toolbar_row.addStretch()
        layout.addLayout(toolbar_row)

        layout.addLayout(self._build_day_nav())

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_context_menu)
        layout.addWidget(self._table)

        self.setCentralWidget(central)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_label = QLabel("")
        status_bar.addWidget(self._status_label)

        controller.auth_state_changed.connect(lambda _signed_in: self._day_cache.clear())
        controller.auth_state_changed.connect(self._on_auth_state_changed)
        controller.events_updated.connect(self._reload_table)
        controller.calendars_updated.connect(self._reload_table)
        controller.connection_status_changed.connect(self._on_connection_status)
        controller.reminder_fired.connect(self._on_reminder_fired)
        controller.event_changed.connect(self._on_event_changed)

        self._on_auth_state_changed(controller.is_signed_in)
        self._reload_table()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(30_000)
        self._countdown_timer.timeout.connect(self._reload_table)
        self._countdown_timer.start()

    # ---- sign-in banner ------------------------------------------------

    def _build_signin_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        self._signin_button = QPushButton("Sign in with Google")
        self._signin_button.clicked.connect(self._sign_in)
        row.addWidget(QLabel("Connect your Google Calendar to get started."))
        row.addStretch()
        row.addWidget(self._signin_button)
        return bar

    def _sign_in(self):
        from app import Worker

        self._signin_button.setEnabled(False)
        self._signin_button.setText("Waiting for Google sign-in in your browser…")

        worker = Worker(self._controller.sign_in)
        worker.succeeded.connect(self._on_sign_in_succeeded)
        worker.failed.connect(self._on_sign_in_failed)
        self._signin_worker = worker
        worker.start()

    def _on_sign_in_succeeded(self, _result):
        self._controller.finish_sign_in()
        self._maybe_run_onboarding()

    def _on_sign_in_failed(self, message: str):
        self._signin_button.setEnabled(True)
        self._signin_button.setText("Sign in with Google")
        QMessageBox.warning(self, "Sign-in failed", message)

    def _on_auth_state_changed(self, signed_in: bool):
        self._signin_bar.setVisible(not signed_in)
        if signed_in:
            self._maybe_run_onboarding()

    def _maybe_run_onboarding(self):
        has_calendars = bool(self._controller.db.list_calendars(self._controller.current_account_email))
        if self._onboarded or has_calendars:
            self._onboarded = True
            return
        self._onboarded = True
        QTimer.singleShot(0, self._show_onboarding_dialog)

    def _show_onboarding_dialog(self):
        from ui.calendar_selector import CalendarSelectorWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("Choose calendars to monitor")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select the calendars you'd like Calendar Reminder to watch:"))
        layout.addWidget(CalendarSelectorWidget(self._controller))
        done_button = QPushButton("Done")
        done_button.clicked.connect(dialog.accept)
        layout.addWidget(done_button)
        dialog.resize(420, 460)
        dialog.exec()

    # ---- day navigation (calendar view) ------------------------------
    #
    # _viewing_day is None while showing today — the existing live list
    # from the local cache. Any other day is fetched from Google on demand
    # (see calendar_app/day_view.py for why, and what it costs).

    def _build_day_nav(self) -> QHBoxLayout:
        self._viewing_day: date | None = None
        self._day_cache = day_view.DayCache()
        self._day_workers: set = set()
        self._day_error: str | None = None

        row = QHBoxLayout()
        self._prev_day_button = QPushButton("◀")
        self._prev_day_button.setToolTip("Previous day")
        self._prev_day_button.setFixedWidth(40)
        self._prev_day_button.clicked.connect(lambda: self._step_day(-1))
        self._today_button = QPushButton("Today")
        self._today_button.clicked.connect(lambda: self._show_day(None))
        self._next_day_button = QPushButton("▶")
        self._next_day_button.setToolTip("Next day")
        self._next_day_button.setFixedWidth(40)
        self._next_day_button.clicked.connect(lambda: self._step_day(1))

        self._date_picker = QDateEdit()
        self._date_picker.setCalendarPopup(True)
        self._date_picker.setDisplayFormat("ddd, MMM d, yyyy")
        self._date_picker.dateChanged.connect(self._on_date_picked)

        self._day_heading = QLabel()
        self._day_heading.setStyleSheet("font-weight: bold;")

        row.addWidget(self._prev_day_button)
        row.addWidget(self._today_button)
        row.addWidget(self._next_day_button)
        row.addWidget(self._date_picker)
        row.addSpacing(12)
        row.addWidget(self._day_heading, 1)

        self._return_to_today_timer = QTimer(self)
        self._return_to_today_timer.setSingleShot(True)
        self._return_to_today_timer.setInterval(RETURN_TO_TODAY_MS)
        self._return_to_today_timer.timeout.connect(lambda: self._show_day(None))
        return row

    def _current_day(self) -> date:
        return self._viewing_day or day_view.local_today()

    def _step_day(self, delta: int) -> None:
        self._show_day(self._current_day() + timedelta(days=delta))

    def _on_date_picked(self, qdate: QDate) -> None:
        self._show_day(date(qdate.year(), qdate.month(), qdate.day()))

    def _show_day(self, day: date | None) -> None:
        today = day_view.local_today()
        if day is not None:
            day = day_view.clamp_day(day, today)
        self._viewing_day = None if day == today else day
        self._day_error = None
        if self._viewing_day is None:
            self._return_to_today_timer.stop()
        else:
            self._return_to_today_timer.start()
        self._reload_table()

    def _sync_day_nav(self, today: date) -> None:
        day = self._current_day()
        self._date_picker.blockSignals(True)
        earliest = today - timedelta(days=day_view.MAX_DAYS_EACH_WAY)
        latest = today + timedelta(days=day_view.MAX_DAYS_EACH_WAY)
        self._date_picker.setDateRange(
            QDate(earliest.year, earliest.month, earliest.day), QDate(latest.year, latest.month, latest.day)
        )
        self._date_picker.setDate(QDate(day.year, day.month, day.day))
        self._date_picker.blockSignals(False)
        self._prev_day_button.setEnabled(day > earliest)
        self._next_day_button.setEnabled(day < latest)
        self._today_button.setEnabled(self._viewing_day is not None)
        self._day_heading.setText(day_view.format_day_heading(day, today))

    def _day_cache_key(self, day: date) -> tuple:
        selected = self._controller.db.list_selected_calendar_ids(self._controller.current_account_email)
        return (day, tuple(sorted(selected)))

    def _render_other_day(self, day: date) -> None:
        self._table.setColumnCount(len(DAY_COLUMNS))
        self._table.setHorizontalHeaderLabels(DAY_COLUMNS)

        if not self._controller.is_signed_in:
            self._table.setRowCount(0)
            self._day_heading.setText(self._day_heading.text() + "  ·  sign in to see this day")
            return

        key = self._day_cache_key(day)
        events = self._day_cache.get(key)
        if events is None:
            if self._day_error:
                self._table.setRowCount(0)
                self._day_heading.setText(self._day_heading.text() + f"  ·  {self._day_error}")
                return
            self._fetch_day(day, key)
            events = self._day_cache.stale(key)
            if events is None:
                self._table.setRowCount(0)
                self._day_heading.setText(self._day_heading.text() + "  ·  loading…")
                return

        if not events:
            self._day_heading.setText(self._day_heading.text() + "  ·  no meetings")
        self._table.setRowCount(len(events))
        db = self._controller.db
        for i, event in enumerate(events):
            cells = [_format_time_range(event), event.calendar_name, event.title, event.location or ""]
            # Live lookup, not the cached color, so a color change in
            # Settings shows up right away.
            background = _tinted(resolve_color(db.get_calendar_flash_color(event.calendar_id, event.flash_color)))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setBackground(background)
                self._table.setItem(i, col, item)
        self._table.resizeColumnToContents(0)  # "11:00 AM – 11:45 AM" must not be cut off

    def _fetch_day(self, day: date, key: tuple) -> None:
        if any(w.key == key for w in self._day_workers):
            return  # already on its way
        from app import Worker

        worker = Worker(self._controller.fetch_day, day)
        worker.key = key
        worker.succeeded.connect(lambda events, w=worker: self._on_day_fetched(w, events))
        worker.failed.connect(lambda message, w=worker: self._on_day_fetch_failed(w, message))
        self._day_workers.add(worker)
        worker.start()

    def wait_for_background_work(self, timeout_ms: int = 5000) -> None:
        """Let any in-flight day fetch finish before the database is
        closed underneath it (quitting while a day is still loading)."""
        for worker in list(self._day_workers):
            worker.wait(timeout_ms)

    def _on_day_fetched(self, worker, events) -> None:
        self._day_workers.discard(worker)
        self._day_cache.put(worker.key, events)
        if self._viewing_day is not None and self._day_cache_key(self._viewing_day) == worker.key:
            self._reload_table()

    def _on_day_fetch_failed(self, worker, _message: str) -> None:
        self._day_workers.discard(worker)
        if self._viewing_day is not None and self._day_cache_key(self._viewing_day) == worker.key:
            self._day_error = "couldn't load this day — check your connection, then press Refresh"
            self._reload_table()

    # ---- table ---------------------------------------------------------

    def _refresh(self):
        self._day_cache.clear()
        self._day_error = None
        self._controller.sync_calendars_and_events()
        self._reload_table()

    def _open_settings(self):
        from ui.settings_window import SettingsDialog

        SettingsDialog(self._controller, self).exec()

    def _reload_table(self):
        today = day_view.local_today()
        if self._viewing_day == today:  # midnight passed while looking at "tomorrow"
            self._viewing_day = None
        self._sync_day_nav(today)
        if self._viewing_day is not None:
            self._render_other_day(self._viewing_day)
            return

        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        now = datetime.now(timezone.utc)
        horizon = reminder_service.end_of_local_day(now).isoformat()  # just today
        rows = self._controller.db.upcoming_events(
            now.isoformat(), horizon, self._controller.current_account_email
        )

        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            start = datetime.fromisoformat(row["start_time"])
            minutes = (start - now).total_seconds() / 60
            self._table.setItem(i, 0, QTableWidgetItem(_format_countdown(minutes)))
            self._table.setItem(i, 1, QTableWidgetItem(row["calendar_name"]))
            self._table.setItem(i, 2, QTableWidgetItem(row["title"]))
            self._table.setItem(i, 3, QTableWidgetItem(format_time_12h(start)))
            self._table.item(i, 0).setData(Qt.ItemDataRole.UserRole, dict(row))

            background = _tinted(resolve_color(row["flash_color"]))
            for col in range(len(COLUMNS)):
                self._table.item(i, col).setBackground(background)

    def _show_row_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        if self._viewing_day is not None:
            return  # "Copy Reminder" is about upcoming meetings — today's list only
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        item = self._table.item(row, 0)
        data = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Reminder")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == copy_action:
            self._copy_reminder(data)

    def _copy_reminder(self, row: dict):
        from reminders.reminder_service import DueEvent

        start = datetime.fromisoformat(row["start_time"])
        now = datetime.now(timezone.utc)
        due_event = DueEvent(
            event_id=row["event_id"],
            calendar_id=row["calendar_id"],
            calendar_name=row["calendar_name"],
            title=row["title"],
            start=start,
            location=row["location"],
            minutes_until_start=(start - now).total_seconds() / 60,
        )
        QApplication.clipboard().setText(build_reminder_text(due_event))
        self.statusBar().showMessage("Reminder text copied to clipboard", 3000)

    # ---- status / lifecycle --------------------------------------------

    def _on_connection_status(self, message: str):
        self._status_label.setText(message)

    def _on_reminder_fired(self, event):
        self._reload_table()
        if self._controller.db.get_setting("flash_enabled", "1") != "1":
            return

        key = (event.event_id, event.calendar_id, event.start.isoformat())
        if key in self._open_alerts:
            return  # already showing an alert for this exact occurrence

        color = resolve_color(self._controller.db.get_calendar_flash_color(event.calendar_id))

        dialog = ReminderAlertDialog(
            event,
            accent_color=color,
            offset_index=self._open_alert_count(),
            snooze_minutes=self._controller.snooze_minutes(),
        )
        dialog.snoozed.connect(lambda: self._controller.snooze(event))
        dialog.acknowledged.connect(lambda: self._on_alert_acknowledged(key))
        self._open_alerts[key] = dialog
        dialog.show()

        # The flash is shared across every open alert. It starts with the
        # first one's color; if a later alert from a different-colored
        # calendar arrives while it's already flashing, the color doesn't
        # change — it keeps reflecting whichever alert has been open
        # longest (see _on_alert_acknowledged for what happens when that
        # one gets dismissed while others remain).
        if not self._attention_flasher.is_active:
            self._start_flash(color)

    def _open_alert_count(self) -> int:
        """Reminders and change alerts share one stack in the middle of the
        main screen, so each new window is nudged past all open ones."""
        return len(self._open_alerts) + len(self._open_change_alerts)

    def _on_alert_acknowledged(self, key: tuple) -> None:
        self._open_alerts.pop(key, None)
        if not self._open_alerts:
            self._attention_flasher.stop()
            return
        # The border always reflects the oldest still-open alert — restart
        # it with that alert's color in case the one just dismissed was
        # the one driving the current color.
        oldest_dialog = next(iter(self._open_alerts.values()))
        color = resolve_color(self._controller.db.get_calendar_flash_color(oldest_dialog.event.calendar_id))
        self._start_flash(color)

    def _on_event_changed(self, change):
        self._reload_table()
        if self._controller.db.get_setting("flash_enabled", "1") != "1":
            return
        key = change.key
        if key in self._open_change_alerts:
            return
        calendar_color = resolve_color(self._controller.db.get_calendar_flash_color(change.calendar_id))
        dialog = ChangeAlertDialog(change, calendar_color, offset_index=self._open_alert_count())
        dialog.acknowledged.connect(lambda: self._on_change_alert_acknowledged(key))
        self._open_change_alerts[key] = dialog
        dialog.show()
        if not self._change_flasher.is_active:
            self._change_flasher.blink_until_stopped()

    def _on_change_alert_acknowledged(self, key: tuple) -> None:
        self._open_change_alerts.pop(key, None)
        if not self._open_change_alerts:
            self._change_flasher.stop()

    def _start_flash(self, color) -> None:
        fade_ms = resolve_fade_ms(self._controller.db.get_setting("flash_speed", DEFAULT_SPEED_NAME))
        self._attention_flasher.flash_until_stopped(color=color, fade_ms=fade_ms)

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()
