"""A must-acknowledge alert window for a meeting that was added, removed,
or edited — the change-alert counterpart to ReminderAlertDialog
(ui/reminder_alert.py), paired with the striped double-blink border
(AttentionFlasher.blink_until_stopped).

Built to be told apart from a "meeting starting" reminder at a glance,
before reading a word of it:

* A dark banner across the top with a big white icon: a plus for a new
  meeting, an X for canceled/moved, a pencil for changed. A reminder
  window has no banner and no icon.
* It opens in the top-right corner of the screen (stacking downward),
  not dead center where reminders open.

The banner is the same dark color for every kind of change, on purpose.
Color in this app means "whose calendar" (each calendar's flash color),
so it's shown only as a small dot next to the calendar's name — the icon
alone says what happened.

Same acknowledgment rules as the reminder window: closing it any way at
all (OK, titlebar X, Alt+F4) emits `acknowledged`.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calendar_app.change_detector import ADDED, CHANGED, REMOVED, EventChange
from reminders.attention_cue import CHANGE_STRIPE_DARK
from reminders.notifications import describe_change_lines, describe_event_time

HEADINGS = {
    ADDED: "NEW MEETING",
    REMOVED: "MEETING CANCELED / MOVED",
    CHANGED: "MEETING CHANGED",
}

WINDOW_TITLES = {
    ADDED: "Meeting added",
    REMOVED: "Meeting canceled or moved",
    CHANGED: "Meeting changed",
}

ICON_SIZE = 56
SCREEN_MARGIN = 24
STACK_OFFSET = 36


def _rgb(color: QColor) -> str:
    return f"rgb({color.red()}, {color.green()}, {color.blue()})"


class ChangeIcon(QWidget):
    """The big plus / X / pencil. Drawn with QPainter rather than a font
    glyph so it's equally bold on every machine, whatever fonts it has."""

    def __init__(self, kind: str, color: QColor = QColor("white"), parent=None):
        super().__init__(parent)
        self._kind = kind
        self._color = color
        self.setFixedSize(ICON_SIZE, ICON_SIZE)

    @property
    def kind(self) -> str:
        return self._kind

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = ICON_SIZE / 2
        r = ICON_SIZE * 0.4
        if self._kind == CHANGED:
            self._draw_pencil(p, c, r)
        else:
            pen = QPen(self._color)
            pen.setWidthF(r * 0.34)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            if self._kind == ADDED:
                p.drawLine(QPointF(c - r, c), QPointF(c + r, c))
                p.drawLine(QPointF(c, c - r), QPointF(c, c + r))
            else:  # REMOVED
                d = r * 0.8
                p.drawLine(QPointF(c - d, c - d), QPointF(c + d, c + d))
                p.drawLine(QPointF(c - d, c + d), QPointF(c + d, c - d))

    def _draw_pencil(self, p: QPainter, c: float, r: float) -> None:
        p.save()
        p.translate(c, c)
        p.rotate(-45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        width, length = r * 0.55, r * 1.5
        half = length * 0.55
        p.drawRect(QRectF(-half, -width / 2, length * 1.1, width))  # body
        p.drawPolygon(  # tip
            QPolygonF([QPointF(half + 2, -width / 2), QPointF(half + 2, width / 2), QPointF(half + width * 1.1, 0)])
        )
        p.drawRect(QRectF(-half - width * 0.55, -width / 2, width * 0.4, width))  # eraser
        p.restore()


class ChangeAlertDialog(QDialog):
    acknowledged = Signal()

    def __init__(self, change: EventChange, calendar_color: QColor, offset_index: int = 0, parent=None):
        super().__init__(parent)
        self._change = change
        dark = _rgb(CHANGE_STRIPE_DARK)

        self.setWindowTitle(WINDOW_TITLES.get(change.kind, "Meeting changed"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(f"QDialog {{ border: 3px dashed {dark}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)

        banner = QWidget()
        banner.setObjectName("banner")
        banner.setStyleSheet(f"#banner {{ background-color: {dark}; }}")
        banner_row = QHBoxLayout(banner)
        banner_row.setContentsMargins(18, 12, 18, 12)
        banner_row.setSpacing(18)
        self._icon = ChangeIcon(change.kind)
        banner_row.addWidget(self._icon)
        heading = QLabel(HEADINGS.get(change.kind, "MEETING CHANGED"))
        heading.setStyleSheet("color: white; font-size: 16pt; font-weight: bold;")
        banner_row.addWidget(heading, 1)
        layout.addWidget(banner)

        body = QVBoxLayout()
        body.setContentsMargins(16, 8, 16, 0)
        layout.addLayout(body)

        event = change.event
        # html.escape: titles come from other people's calendars — never
        # let one be interpreted as rich-text markup.
        title_html = html.escape(event.title)
        if change.kind == REMOVED:
            title_html = f"<s>{title_html}</s>"
        title_label = QLabel(f"<b>{title_html}</b>")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 13pt;")
        body.addWidget(title_label)

        # Whose calendar: the calendar's own color, as a dot — the only
        # place color appears in this window.
        when = describe_event_time(event.start, event.is_all_day)
        calendar_bits = [html.escape(b) for b in (change.calendar_name, when) if b]
        calendar_label = QLabel(
            f'<span style="color: {_rgb(calendar_color)}; font-size: 14pt;">●</span> ' + " — ".join(calendar_bits)
        )
        body.addWidget(calendar_label)

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

        self.setMinimumWidth(420)
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
