"""Where must-acknowledge alert windows open: the center of the MAIN
screen only, for both meeting reminders (ui/reminder_alert.py) and
meeting-change alerts (ui/change_alert.py). The flashing screen border is
separate and still covers every monitor (reminders/attention_cue.py).

When several are open at once, each later one is nudged down and to the
right so every window's title stays visible instead of stacking exactly
on top of the previous one.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

STACK_OFFSET = 36


def center_on_primary_screen(widget: QWidget, offset_index: int = 0) -> None:
    screen = QApplication.primaryScreen()
    if not screen:
        return
    geometry = screen.availableGeometry()
    x = geometry.center().x() - widget.width() // 2 + offset_index * STACK_OFFSET
    y = geometry.center().y() - widget.height() // 2 + offset_index * STACK_OFFSET
    # Never push a window off the bottom/right of the main screen.
    x = max(geometry.left(), min(x, geometry.right() - widget.width()))
    y = max(geometry.top(), min(y, geometry.bottom() - widget.height()))
    widget.move(x, y)
