from PySide6.QtWidgets import QApplication, QPushButton

from reminders.attention_cue import COLOR_CHOICES
from ui.color_swatch import POPUP_COLUMNS, ColorSwatchButton, _ColorPickerPopup

_app = QApplication.instance() or QApplication([])


def test_swatch_starts_with_given_color():
    swatch = ColorSwatchButton("purple")
    assert swatch.color_name == "purple"
    assert swatch.toolTip() == "Purple"


def test_swatch_has_no_text_label():
    """The whole point of this widget is showing the color, not its
    name, as the persistent visible control."""
    swatch = ColorSwatchButton("blue")
    assert swatch.text() == ""


def test_popup_has_one_button_per_color():
    popup = _ColorPickerPopup()
    buttons = popup.findChildren(QPushButton)
    assert len(buttons) == len(COLOR_CHOICES) == 9


def test_popup_emits_correct_color_name_when_a_swatch_is_clicked():
    popup = _ColorPickerPopup()
    received = []
    popup.color_picked.connect(received.append)

    names = list(COLOR_CHOICES)
    red_index = names.index("red")
    popup.findChildren(QPushButton)[red_index].click()

    assert received == ["red"]


def test_picking_updates_the_swatch_button_and_emits():
    """Exercises ColorSwatchButton's own handler for a pick — the part
    that actually changes state, as opposed to _open_picker, which is
    just popup plumbing."""
    swatch = ColorSwatchButton("blue")
    received = []
    swatch.color_changed.connect(received.append)

    swatch._on_picked("red")

    assert swatch.color_name == "red"
    assert swatch.toolTip() == "Red"
    assert received == ["red"]


def test_popup_layout_uses_three_columns():
    assert POPUP_COLUMNS == 3
