from PySide6.QtWidgets import QApplication

from ui.calendar_selector import MIN_VISIBLE_ROWS, CalendarSelectorWidget

_app = QApplication.instance() or QApplication([])


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        pass


class _FakeDB:
    def __init__(self, calendars):
        self._calendars = calendars

    def list_calendars(self, account_email):
        return self._calendars

    def set_calendar_flash_color(self, calendar_id, color_name):
        pass


class _FakeController:
    def __init__(self, calendars):
        self.db = _FakeDB(calendars)
        self.calendars_updated = _FakeSignal()
        self.current_account_email = "test@example.com"

    def set_calendar_selected(self, calendar_id, selected):
        pass


def _make_calendars(count):
    return [
        {
            "calendar_id": f"cal{i}",
            "name": f"Calendar {i}",
            "access_role": "reader",
            "selected": 0,
            "flash_color": "blue",
        }
        for i in range(count)
    ]


def test_shows_at_least_five_rows_without_scrolling():
    widget = CalendarSelectorWidget(_FakeController(_make_calendars(8)))
    row_height = widget.sizeHintForRow(0)
    assert widget.minimumHeight() >= row_height * MIN_VISIBLE_ROWS


def test_fewer_than_five_calendars_still_gets_five_row_minimum():
    """The minimum height shouldn't shrink just because there happen to
    be fewer calendars right now — a later sync could add more."""
    widget = CalendarSelectorWidget(_FakeController(_make_calendars(2)))
    row_height = widget.sizeHintForRow(0)
    assert widget.minimumHeight() >= row_height * MIN_VISIBLE_ROWS


def test_no_calendars_does_not_crash():
    widget = CalendarSelectorWidget(_FakeController([]))
    assert widget.count() == 0


def test_row_color_swatch_reflects_stored_color_and_reports_changes():
    calendars = _make_calendars(1)
    calendars[0]["flash_color"] = "purple"
    changes = []

    controller = _FakeController(calendars)
    controller.db.set_calendar_flash_color = lambda cal_id, color: changes.append((cal_id, color))

    widget = CalendarSelectorWidget(controller)
    item = widget.item(0)
    row_widget = widget.itemWidget(item)

    assert row_widget._swatch.color_name == "purple"

    # Simulate picking a different color from the swatch's popup.
    row_widget._swatch._on_picked("red")
    assert changes == [("cal0", "red")]


def test_color_swatch_appears_before_checkbox_in_row_layout():
    widget = CalendarSelectorWidget(_FakeController(_make_calendars(1)))
    row_widget = widget.itemWidget(widget.item(0))
    layout = row_widget.layout()
    assert layout.itemAt(0).widget() is row_widget._swatch
    assert layout.itemAt(1).widget() is row_widget._checkbox
