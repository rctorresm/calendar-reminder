from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QListWidget, QListWidgetItem, QWidget

from ui.color_swatch import ColorSwatchButton

MIN_VISIBLE_ROWS = 5


class _CalendarRow(QWidget):
    """One row: a color swatch (which of the 9 flash colors reminders
    from this calendar use) followed by the checkbox to monitor it."""

    selection_changed = Signal(str, bool)
    color_changed = Signal(str, str)

    def __init__(self, calendar_id: str, label: str, selected: bool, color_name: str, parent=None):
        super().__init__(parent)
        self._calendar_id = calendar_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._swatch = ColorSwatchButton(color_name)
        self._swatch.color_changed.connect(
            lambda name: self.color_changed.emit(self._calendar_id, name)
        )
        layout.addWidget(self._swatch)

        self._checkbox = QCheckBox(label)
        self._checkbox.setChecked(selected)
        self._checkbox.toggled.connect(
            lambda checked: self.selection_changed.emit(self._calendar_id, checked)
        )
        layout.addWidget(self._checkbox, 1)


class CalendarSelectorWidget(QListWidget):
    """List of calendars available to the signed-in account. Each row has
    a color swatch (which of the 9 flash colors its reminders use) and a
    checkbox (monitor this calendar?). Both persist immediately — there
    is no separate 'Save' step for this widget."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        controller.calendars_updated.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        self.clear()
        for row in self._controller.db.list_calendars(self._controller.current_account_email):
            label = row["name"]
            if row["access_role"] == "freeBusyReader":
                label += "  —  Availability only"
            else:
                label += "  —  Full event details"

            row_widget = _CalendarRow(
                row["calendar_id"], label, bool(row["selected"]), row["flash_color"]
            )
            row_widget.selection_changed.connect(self._controller.set_calendar_selected)
            row_widget.color_changed.connect(self._controller.db.set_calendar_flash_color)

            item = QListWidgetItem()
            item.setSizeHint(row_widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row_widget)
        self._update_min_height()

    def _update_min_height(self) -> None:
        """At least MIN_VISIBLE_ROWS rows visible before scrolling is
        needed — computed from the actual row height (font/theme
        dependent) rather than a guessed pixel constant."""
        if self.count() == 0:
            return
        row_height = self.sizeHintForRow(0)
        frame = 2 * self.frameWidth()
        self.setMinimumHeight(row_height * MIN_VISIBLE_ROWS + frame)
