"""A colored-square picker — shows the actual color, not its name, both
for the current selection and for the choices in the popup grid. Used
wherever someone picks one of the 9 fixed flash colors
(reminders/attention_cue.COLOR_CHOICES)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from reminders.attention_cue import COLOR_CHOICES, resolve_color

SWATCH_SIZE = 22
POPUP_COLUMNS = 3


def _swatch_style(color, *, hover_border: bool = False) -> str:
    rgb = f"rgb({color.red()}, {color.green()}, {color.blue()})"
    hover = "QPushButton:hover { border: 2px solid #222; }" if hover_border else ""
    return (
        f"QPushButton {{ background-color: {rgb}; border: 1px solid #888; border-radius: 3px; }}"
        f" {hover}"
    )


class _ColorPickerPopup(QWidget):
    """A borderless grid of color swatches that closes itself as soon as
    focus leaves it (Qt.Popup) — the lightweight way to build a custom
    dropdown that isn't a QMenu full of text labels."""

    color_picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        layout = QGridLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)
        for i, (name, color) in enumerate(COLOR_CHOICES.items()):
            button = QPushButton()
            button.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
            button.setStyleSheet(_swatch_style(color, hover_border=True))
            button.setToolTip(name.capitalize())
            button.clicked.connect(lambda checked=False, n=name: self._pick(n))
            layout.addWidget(button, i // POPUP_COLUMNS, i % POPUP_COLUMNS)

    def _pick(self, name: str) -> None:
        self.color_picked.emit(name)
        self.close()


class ColorSwatchButton(QPushButton):
    """A single colored square showing the current color. Click it to
    open a popup grid of all 9 choices."""

    color_changed = Signal(str)

    def __init__(self, color_name: str, parent=None):
        super().__init__(parent)
        self._color_name = color_name
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.setToolTip(color_name.capitalize())
        self._apply_color(color_name)
        self.clicked.connect(self._open_picker)

    @property
    def color_name(self) -> str:
        return self._color_name

    def _apply_color(self, color_name: str) -> None:
        self._color_name = color_name
        self.setStyleSheet(_swatch_style(resolve_color(color_name)))
        self.setToolTip(color_name.capitalize())

    def _open_picker(self) -> None:
        popup = _ColorPickerPopup(self)
        popup.color_picked.connect(self._on_picked)
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        popup.show()

    def _on_picked(self, color_name: str) -> None:
        self._apply_color(color_name)
        self.color_changed.emit(color_name)
