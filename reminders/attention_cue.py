"""A click-through, colored border "breathing" pulse across every
connected monitor — a visual attention cue for when a reminder fires and
the main window isn't in focus.

The pulse loops indefinitely once started (fade in + fade out, repeated)
and only stops when explicitly told to — paired with a
ReminderAlertDialog (ui/reminder_alert.py) that requires the person to
actually acknowledge it. A fixed number of flashes can be missed entirely
if someone's turned away from their screen for that whole window; looping
until acknowledged can't be missed that way.

Each breath is a smooth fade (not an abrupt blink), which reads as a calm
pulse rather than an alarm — calm blue by default rather than an alarm
color. Never steals focus or blocks clicks (WA_ShowWithoutActivating +
WA_TransparentForMouseEvents) — it shouldn't interrupt whatever's being
typed; only the alert dialog itself is interactive.

Must only be touched from the Qt GUI thread — it creates QWidgets and
QVariantAnimations. AppController's reminder cycle runs on a background
scheduler thread, so this is triggered from MainWindow's reminder_fired
slot, not from the scheduler job itself.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QSequentialAnimationGroup, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

# Fixed palette by design, not a free-form picker — every option here is
# deliberately distinct and clearly visible both as a border flash and as
# a pastel row tint; a free-form picker would be more flexible but also
# more to get wrong (illegible-on-some-monitors colors, near-invisible
# pastels, two people picking near-identical shades).
COLOR_CHOICES: dict[str, QColor] = {
    "red": QColor(229, 57, 53),
    "yellow": QColor(253, 216, 53),
    "blue": QColor(30, 136, 229),
    "green": QColor(67, 160, 71),
    "orange": QColor(251, 140, 0),
    "purple": QColor(142, 36, 170),
    "pink": QColor(236, 64, 122),
    "teal": QColor(0, 137, 123),
    "brown": QColor(109, 76, 65),
}
DEFAULT_COLOR_NAME = "blue"
DEFAULT_COLOR = COLOR_CHOICES[DEFAULT_COLOR_NAME]

BORDER_WIDTH = 20  # fixed pixels, not screen % — same physical width on every monitor

# Fade duration (ms) for one leg (fade-in OR fade-out) — a full breath is
# 2x this. "normal" is a calm ~2.4s breath; not a fixed single speed so
# it can be tuned without another round-trip to me.
SPEED_CHOICES: dict[str, int] = {
    "slow": 1800,
    "normal": 1200,
    "fast": 700,
}
DEFAULT_SPEED_NAME = "normal"
FADE_MS = SPEED_CHOICES[DEFAULT_SPEED_NAME]


class _BorderOverlay(QWidget):
    def __init__(self, geometry, color: QColor, border_width: int):
        super().__init__()
        self._color = color
        self._border_width = border_width
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(geometry)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color)
        pen.setWidth(self._border_width)
        painter.setPen(pen)
        half = self._border_width // 2
        painter.drawRect(self.rect().adjusted(half, half, -half, -half))


def resolve_color(name: str) -> QColor:
    return COLOR_CHOICES.get(name, DEFAULT_COLOR)


def resolve_fade_ms(speed_name: str) -> int:
    return SPEED_CHOICES.get(speed_name, FADE_MS)


class AttentionFlasher:
    """Owns the overlay widgets and the breathing animation. Starting a
    new sequence while one is already running restarts it cleanly instead
    of piling up widgets."""

    def __init__(self):
        self._overlays: list[_BorderOverlay] = []
        self._group: QSequentialAnimationGroup | None = None

    def flash_until_stopped(
        self,
        color: QColor = DEFAULT_COLOR,
        border_width: int = BORDER_WIDTH,
        fade_ms: int = FADE_MS,
    ) -> None:
        """Breathe indefinitely until stop() is called."""
        self._cleanup()
        screens = QApplication.screens()
        if not screens:
            return

        self._overlays = [_BorderOverlay(s.geometry(), color, border_width) for s in screens]
        for overlay in self._overlays:
            overlay.setWindowOpacity(0.0)
            overlay.setVisible(True)

        self._group = QSequentialAnimationGroup()
        self._group.addAnimation(self._make_fade(0.0, 1.0, fade_ms))  # inhale
        self._group.addAnimation(self._make_fade(1.0, 0.0, fade_ms))  # exhale
        self._group.setLoopCount(-1)  # infinite — stop() is the only way out
        self._group.start()

    def stop(self) -> None:
        self._cleanup()

    @property
    def is_active(self) -> bool:
        return bool(self._overlays)

    def _make_fade(self, start: float, end: float, duration_ms: int) -> QVariantAnimation:
        anim = QVariantAnimation()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.valueChanged.connect(self._set_opacity)
        return anim

    def _set_opacity(self, value) -> None:
        for overlay in self._overlays:
            overlay.setWindowOpacity(float(value))

    def _cleanup(self) -> None:
        if self._group is not None:
            self._group.stop()
            self._group = None
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays = []
