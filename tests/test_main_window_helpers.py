from PySide6.QtGui import QColor

from ui.main_window import _format_countdown, _tinted


def test_format_countdown_minutes_and_hours():
    assert _format_countdown(14) == "14 min"
    assert _format_countdown(0) == "0 min"
    assert _format_countdown(-5) == "0 min"  # never show a negative countdown
    assert _format_countdown(75) == "1h 15m"
    assert _format_countdown(120) == "2h"


def test_tinted_moves_toward_white_without_changing_hue_direction():
    color = QColor(229, 57, 53)  # red
    tint = _tinted(color, amount=0.75)
    assert tint.red() > color.red() or color.red() == 255
    assert tint.green() > color.green()
    assert tint.blue() > color.blue()
    # still recognizably red-ish: red channel stays the highest
    assert tint.red() >= tint.green()
    assert tint.red() >= tint.blue()


def test_tinted_amount_zero_is_unchanged():
    color = QColor(30, 136, 229)
    assert _tinted(color, amount=0.0) == color


def test_tinted_amount_one_is_white():
    color = QColor(30, 136, 229)
    tint = _tinted(color, amount=1.0)
    assert (tint.red(), tint.green(), tint.blue()) == (255, 255, 255)
