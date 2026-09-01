from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon, QMenu

import config


def _default_icon() -> QIcon:
    if config.icon_path().exists():
        return QIcon(str(config.icon_path()))
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, controller, main_window):
        super().__init__(_default_icon())
        self._controller = controller
        self._window = main_window
        self._paused = False

        self.setToolTip("Calendar Reminder")

        menu = QMenu()
        self._open_action = menu.addAction("Open")
        self._open_action.triggered.connect(self._open_window)

        self._pause_action = QAction("Pause Monitoring")
        self._pause_action.setCheckable(True)
        self._pause_action.toggled.connect(self._toggle_pause)
        menu.addAction(self._pause_action)

        refresh_action = menu.addAction("Refresh Calendars")
        refresh_action.triggered.connect(self._refresh)

        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self._open_settings)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

        controller.calendars_updated.connect(self._refresh_tooltip)
        controller.events_updated.connect(self._refresh_tooltip)
        controller.connection_status_changed.connect(self._refresh_tooltip)
        self._refresh_tooltip()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_window()

    def _open_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _toggle_pause(self, checked: bool):
        self._paused = checked
        self._controller.set_paused(checked)
        self._pause_action.setText("Resume Monitoring" if checked else "Pause Monitoring")
        self._refresh_tooltip()

    def _refresh(self):
        self._controller.sync_calendars_and_events()

    def _open_settings(self):
        from ui.settings_window import SettingsDialog

        dialog = SettingsDialog(self._controller, self._window)
        dialog.exec()

    def _quit(self):
        QApplication.instance().quit()

    def _refresh_tooltip(self):
        if self._paused:
            self.setToolTip("Calendar Reminder — Paused")
            return
        count = len(self._controller.db.list_selected_calendar_ids(self._controller.current_account_email))
        self.setToolTip(f"Calendar Reminder — Monitoring {count} calendar{'s' if count != 1 else ''}")
