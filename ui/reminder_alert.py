"""A must-acknowledge alert window for a fired reminder, shown alongside
the indefinite screen-border flash (reminders/attention_cue.py).

Closing it — the OK button, the titlebar X, Alt+F4, anything — counts as
acknowledgment via closeEvent, which is what tells MainWindow to stop the
flash (see MainWindow._on_alert_acknowledged). Non-modal: it shouldn't
block using other apps while it's up, just stay visibly on top until
dismissed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from reminders.notifications import format_time_12h
from reminders.reminder_service import DueEvent


class ReminderAlertDialog(QDialog):
    acknowledged = Signal()

    def __init__(self, event: DueEvent, accent_color: QColor, offset_index: int = 0, parent=None):
        super().__init__(parent)
        self._event = event
        self.setWindowTitle("Calendar Reminder")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QDialog { border: 3px solid rgb(%d, %d, %d); }"
            % (accent_color.red(), accent_color.green(), accent_color.blue())
        )

        layout = QVBoxLayout(self)

        title_label = QLabel(f"<b>{event.title}</b>")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 14pt;")
        layout.addWidget(title_label)

        minutes = round(event.minutes_until_start)
        time_str = format_time_12h(event.start)
        detail_label = QLabel(f"{event.calendar_name} — starts in {minutes} min at {time_str}")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)

        if event.location:
            location_label = QLabel(event.location)
            location_label.setWordWrap(True)
            location_label.setStyleSheet("color: gray;")
            layout.addWidget(location_label)

        button_row = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

        self.setMinimumWidth(360)
        self.adjustSize()
        self._position(offset_index)

    @property
    def event(self) -> DueEvent:
        return self._event

    def _position(self, offset_index: int) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        x = geometry.center().x() - self.width() // 2
        y = geometry.center().y() - self.height() // 2 + offset_index * 48
        self.move(x, y)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.acknowledged.emit()
        super().closeEvent(event)
