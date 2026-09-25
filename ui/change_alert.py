"""A must-acknowledge alert window for a meeting that was added, removed,
or edited — the change-alert counterpart to ReminderAlertDialog
(ui/reminder_alert.py), paired with the dashed double-blink border
(AttentionFlasher.blink_until_stopped).

Built to be told apart from a "meeting starting" reminder at a glance,
before reading a word of it:

* A big solid color banner across the top with a symbol and the kind of
  change in capitals: green "+ NEW MEETING", red "✕ MEETING CANCELED /
  MOVED", orange "✎ MEETING CHANGED". A reminder window has no banner.
* It opens in the top-right corner of the screen (stacking downward),
  not dead center where reminders open.

Same acknowledgment rules as the reminder window: closing it any way at
all (OK, titlebar X, Alt+F4) emits `acknowledged`.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from calendar_app.change_detector import ADDED, CHANGED, REMOVED, EventChange
from reminders.attention_cue import resolve_change_color
from reminders.notifications import describe_change_lines, describe_event_time

BANNER_TEXT = {
    ADDED: "+  NEW MEETING",
    REMOVED: "✕  MEETING CANCELED / MOVED",
    CHANGED: "✎  MEETING CHANGED",
}

WINDOW_TITLES = {
    ADDED: "Meeting added",
    REMOVED: "Meeting canceled or moved",
    CHANGED: "Meeting changed",
}

SCREEN_MARGIN = 24
STACK_OFFSET = 36


class ChangeAlertDialog(QDialog):
    acknowledged = Signal()

    def __init__(self, change: EventChange, offset_index: int = 0, parent=None):
        super().__init__(parent)
        self._change = change
        color = resolve_change_color(change.kind)
        rgb = f"rgb({color.red()}, {color.green()}, {color.blue()})"

        self.setWindowTitle(WINDOW_TITLES.get(change.kind, "Meeting changed"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(f"QDialog {{ border: 3px dashed {rgb}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)

        banner = QLabel(BANNER_TEXT.get(change.kind, "MEETING CHANGED"))
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            f"background-color: {rgb}; color: white; font-size: 16pt; font-weight: bold; padding: 14px;"
        )
        layout.addWidget(banner)

        body = QVBoxLayout()
        body.setContentsMargins(16, 8, 16, 0)
        layout.addLayout(body)

        event = change.event
        # html.escape: titles come from other people's calendars — never
        # let one be interpreted as rich-text markup.
        title_label = QLabel(f"<b>{html.escape(event.title)}</b>")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 13pt;")
        if change.kind == REMOVED:
            title_label.setText(f"<b><s>{html.escape(event.title)}</s></b>")
        body.addWidget(title_label)

        when = describe_event_time(event.start, event.is_all_day)
        header_bits = [b for b in (change.calendar_name, when) if b]
        body.addWidget(QLabel(" — ".join(header_bits)))

        for line in describe_change_lines(change):
            detail = QLabel(line)
            detail.setWordWrap(True)
            body.addWidget(detail)

        if change.kind != REMOVED and event.location:
            location_label = QLabel(event.location)
            location_label.setWordWrap(True)
            location_label.setStyleSheet("color: gray;")
            body.addWidget(location_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(16, 8, 16, 0)
        if change.kind in (ADDED, CHANGED) and event.html_link:
            open_button = QPushButton("Open in Google Calendar")
            open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(event.html_link)))
            button_row.addWidget(open_button)
        button_row.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.close)
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

        self.setMinimumWidth(400)
        self.adjustSize()
        self._position(offset_index)

    @property
    def change(self) -> EventChange:
        return self._change

    def _position(self, offset_index: int) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        x = geometry.right() - self.width() - SCREEN_MARGIN
        y = geometry.top() + SCREEN_MARGIN + offset_index * STACK_OFFSET
        self.move(x, y)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.acknowledged.emit()
        super().closeEvent(event)

