from PySide6.QtWidgets import QApplication

from reminders.attention_cue import (
    COLOR_CHOICES,
    DEFAULT_COLOR,
    DEFAULT_COLOR_NAME,
    DEFAULT_SPEED_NAME,
    FADE_MS,
    SPEED_CHOICES,
    AttentionFlasher,
    resolve_color,
    resolve_fade_ms,
)

_app = QApplication.instance() or QApplication([])

ORIGINAL_FADE_MS = 350  # the pace that prompted "make it 3x slower"

EXPECTED_COLORS = {"red", "yellow", "blue", "green", "orange", "purple", "pink", "teal", "brown"}


def test_exactly_nine_distinct_colors():
    assert set(COLOR_CHOICES) == EXPECTED_COLORS
    assert len(COLOR_CHOICES) == 9
    # every color must be visually distinct — no accidental duplicates
    assert len({(c.red(), c.green(), c.blue()) for c in COLOR_CHOICES.values()}) == 9


def test_default_color_name_is_a_valid_choice():
    assert DEFAULT_COLOR_NAME in COLOR_CHOICES
    assert resolve_color(DEFAULT_COLOR_NAME) == DEFAULT_COLOR


def test_resolve_color_known_name():
    assert resolve_color("red") == COLOR_CHOICES["red"]


def test_resolve_color_unknown_name_falls_back_to_default():
    """Guards against a corrupted/stale setting value crashing the flash."""
    assert resolve_color("mauve") == DEFAULT_COLOR
    assert resolve_color("") == DEFAULT_COLOR


def test_exactly_three_named_speeds():
    assert set(SPEED_CHOICES) == {"slow", "normal", "fast"}


def test_speeds_are_ordered_slow_to_fast():
    assert SPEED_CHOICES["slow"] > SPEED_CHOICES["normal"] > SPEED_CHOICES["fast"]


def test_default_speed_is_normal_and_at_least_three_times_slower_than_original():
    assert DEFAULT_SPEED_NAME == "normal"
    assert FADE_MS == SPEED_CHOICES[DEFAULT_SPEED_NAME]
    assert FADE_MS >= ORIGINAL_FADE_MS * 3


def test_resolve_fade_ms_known_and_unknown():
    assert resolve_fade_ms("fast") == SPEED_CHOICES["fast"]
    assert resolve_fade_ms("glacial") == FADE_MS  # unknown falls back to default


def test_flash_until_stopped_is_active_until_stop_is_called():
    flasher = AttentionFlasher()
    assert flasher.is_active is False
    flasher.flash_until_stopped(fade_ms=50)
    assert flasher.is_active is True
    flasher.stop()
    assert flasher.is_active is False


def test_flash_until_stopped_loops_forever_until_stopped():
    """setLoopCount(-1) is what makes this an indefinite flash instead of
    a fixed number of breaths — regression guard for that specific call."""
    flasher = AttentionFlasher()
    flasher.flash_until_stopped(fade_ms=50)
    assert flasher._group.loopCount() == -1
    flasher.stop()


def test_restarting_flash_does_not_leak_overlays():
    flasher = AttentionFlasher()
    flasher.flash_until_stopped(fade_ms=50)
    first_count = len(flasher._overlays)
    flasher.flash_until_stopped(fade_ms=50)  # while already active
    assert len(flasher._overlays) == first_count
    flasher.stop()
