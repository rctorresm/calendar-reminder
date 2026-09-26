"""A must-acknowledge alert window for a fired reminder, shown alongside
the indefinite screen-border flash (reminders/attention_cue.py).

Closing it — the OK button, the titlebar X, Alt+F4, anything — counts as
acknowledgment via closeEvent, which is what tells MainWindow to stop the
flash (see MainWindow._on_alert_acknowledged). Non-modal: it shouldn't
block using other apps while it's up, just stay visibly on top until
dismissed.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from reminders.notifications import build_reminder_text, format_start_phrase, format_time_12h
from reminders.reminder_service import DEFAULT_SNOOZE_MINUTES, DueEvent
from ui.alert_position import center_on_primary_screen


def snooze_label(minutes: int) -> str:
    return "1 hour" if minutes == 60 else f"{minutes} min"


class ReminderAlertDialog(QDialog):
    acknowledged = Signal()
    snoozed = Signal()  # emitted just before the window closes via Snooze

    def __init__(
        self,
        event: DueEvent,
        accent_color: QColor,
        offset_index: int = 0,
        parent=None,
        snooze_minutes: int = DEFAULT_SNOOZE_MINUTES,
    ):
        super().__init__(parent)
        self._event = event
        self.setWindowTitle("Calendar Reminder — second reminder" if event.is_second else "Calendar Reminder")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QDialog { border: 3px solid rgb(%d, %d, %d); }"
            % (accent_color.red(), accent_color.green(), accent_color.blue())
        )

        layout = QVBoxLayout(self)

        if event.is_second:
            second_label = QLabel("SECOND REMINDER")
            second_label.setStyleSheet("color: gray; font-weight: bold; letter-spacing: 1px;")
            layout.addWidget(second_label)

        title_label = QLabel(f"<b>{html.escape(event.title)}</b>")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 14pt;")
        layout.addWidget(title_label)

        minutes = round(event.minutes_until_start)
        time_str = format_time_12h(event.start)
        detail_label = QLabel(f"{event.calendar_name} — {format_start_phrase(minutes)} at {time_str}")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)

        if event.location:
            location_label = QLabel(event.location)
            location_label.setWordWrap(True)
            location_label.setStyleSheet("color: gray;")
            layout.addWidget(location_label)

        button_row = QHBoxLayout()
        self._copy_button = QPushButton("Copy Reminder")
        self._copy_button.clicked.connect(self._copy_reminder)
        self._snooze_button = QPushButton(f"Snooze {snooze_label(snooze_minutes)}")
        self._snooze_button.setToolTip("Hide this reminder and bring it back later (change the time in Settings)")
        self._snooze_button.clicked.connect(self._snooze)
        ok_button = QPushButton("OK")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.close)
        button_row.addWidget(self._copy_button)
        button_row.addStretch()
        button_row.addWidget(self._snooze_button)
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

        self.setMinimumWidth(360)
        self.adjustSize()
        self._position(offset_index)

    @property
    def event(self) -> DueEvent:
        return self._event

    def _copy_reminder(self) -> None:
        """Copies plain, human-ready reminder text to the clipboard — the
        app never sends it automatically. Doesn't close the dialog or
        count as acknowledgment; only OK (or closing the window) does."""
        QApplication.clipboard().setText(build_reminder_text(self._event))
        self._copy_button.setText("Copied!")
        QTimer.singleShot(1500, lambda: self._copy_button.setText("Copy Reminder"))

    def _snooze(self) -> None:
        """Closing still counts as acknowledged (stops the flash); snoozed
        tells MainWindow to schedule it to come back."""
        self.snoozed.emit()
        self.close()

    def _position(self, offset_index: int) -> None:
        center_on_primary_screen(self, offset_index)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.acknowledged.emit()
        super().closeEvent(event)
