from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
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
from reminders.attention_cue import (
    DEFAULT_SPEED_NAME,
    AttentionFlasher,
    resolve_color,
    resolve_fade_ms,
)
from reminders import reminder_service
from reminders.notifications import build_reminder_text, format_time_12h
from ui.reminder_alert import ReminderAlertDialog

COLUMNS = ["Starts In", "Calendar", "Event", "Time"]


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

        controller.auth_state_changed.connect(self._on_auth_state_changed)
        controller.events_updated.connect(self._reload_table)
        controller.calendars_updated.connect(self._reload_table)
        controller.connection_status_changed.connect(self._on_connection_status)
        controller.reminder_fired.connect(self._on_reminder_fired)

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

    # ---- table ---------------------------------------------------------

    def _refresh(self):
        self._controller.sync_calendars_and_events()

    def _open_settings(self):
        from ui.settings_window import SettingsDialog

        SettingsDialog(self._controller, self).exec()

    def _reload_table(self):
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

        dialog = ReminderAlertDialog(event, accent_color=color, offset_index=len(self._open_alerts))
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

    def _start_flash(self, color) -> None:
        fade_ms = resolve_fade_ms(self._controller.db.get_setting("flash_speed", DEFAULT_SPEED_NAME))
        self._attention_flasher.flash_until_stopped(color=color, fade_ms=fade_ms)

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()
