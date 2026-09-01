from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

import config
from reminders.attention_cue import DEFAULT_SPEED_NAME, SPEED_CHOICES
from system import startup
from ui.calendar_selector import CalendarSelectorWidget

REMINDER_OPTIONS = [5, 10, 15, 20, 30]


class SettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Settings")
        self.resize(420, 680)

        layout = QVBoxLayout(self)

        layout.addWidget(self._build_account_group())
        layout.addWidget(self._build_calendars_group())
        layout.addWidget(self._build_reminder_group())
        layout.addWidget(self._build_startup_group())
        layout.addWidget(self._build_notifications_group())

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        controller.auth_state_changed.connect(self._refresh_account_state)

    # ---- Account ---------------------------------------------------

    def _build_account_group(self) -> QGroupBox:
        group = QGroupBox("Account")
        layout = QVBoxLayout(group)

        self._account_label = QLabel()
        layout.addWidget(self._account_label)

        button_row = QHBoxLayout()
        self._reconnect_button = QPushButton("Reconnect Google")
        self._reconnect_button.clicked.connect(self._reconnect)
        self._signout_button = QPushButton("Sign Out")
        self._signout_button.clicked.connect(self._sign_out)
        button_row.addWidget(self._reconnect_button)
        button_row.addWidget(self._signout_button)
        layout.addLayout(button_row)

        import_row = QHBoxLayout()
        import_button = QPushButton("Use my own Google credentials (advanced)…")
        import_button.clicked.connect(self._import_client_secret)
        import_row.addWidget(import_button)
        layout.addLayout(import_row)

        self._refresh_account_state()
        return group

    def _refresh_account_state(self, *_):
        if self._controller.is_signed_in:
            self._account_label.setText("Connected as a Google Calendar account")
        else:
            self._account_label.setText("Not connected")

    def _reconnect(self):
        from app import Worker

        worker = Worker(self._controller.sign_in)
        worker.succeeded.connect(lambda _: self._controller.finish_sign_in())
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Sign-in failed", msg))
        self._worker = worker
        worker.start()

    def _sign_out(self):
        self._controller.sign_out()

    def _import_client_secret(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select your own client_secret.json", "", "JSON files (*.json)"
        )
        if not path:
            return
        import shutil

        try:
            shutil.copyfile(path, config.user_override_client_secret_path())
            QMessageBox.information(
                self,
                "Imported",
                "Your own credentials will now be used instead of the app's built-in ones. "
                "Click 'Reconnect Google' to sign in.",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))

    # ---- Monitored Calendars -------------------------------------------

    def _build_calendars_group(self) -> QGroupBox:
        group = QGroupBox("Monitored Calendars")
        layout = QVBoxLayout(group)
        layout.addWidget(CalendarSelectorWidget(self._controller))
        return group

    # ---- Reminder ----------------------------------------------------

    def _build_reminder_group(self) -> QGroupBox:
        group = QGroupBox("Reminder")
        layout = QFormLayout(group)

        self._reminder_combo = QComboBox()
        for minutes in REMINDER_OPTIONS:
            self._reminder_combo.addItem(f"{minutes} minutes before", minutes)
        current = int(self._controller.db.get_setting("reminder_minutes", "15"))
        index = self._reminder_combo.findData(current)
        if index == -1:
            self._reminder_combo.addItem(f"{current} minutes before", current)
            index = self._reminder_combo.count() - 1
        self._reminder_combo.setCurrentIndex(index)
        self._reminder_combo.currentIndexChanged.connect(self._on_reminder_changed)

        layout.addRow("Notify me:", self._reminder_combo)
        return group

    def _on_reminder_changed(self, index: int):
        minutes = self._reminder_combo.itemData(index)
        self._controller.set_reminder_minutes(minutes)

    # ---- Startup -----------------------------------------------------

    def _build_startup_group(self) -> QGroupBox:
        group = QGroupBox("Startup")
        layout = QVBoxLayout(group)
        self._startup_checkbox = QCheckBox("Start automatically when Windows starts")
        self._startup_checkbox.setChecked(startup.is_enabled())
        self._startup_checkbox.toggled.connect(self._on_startup_toggled)
        layout.addWidget(self._startup_checkbox)
        return group

    def _on_startup_toggled(self, checked: bool):
        self._controller.db.set_setting("start_with_windows", "1" if checked else "0")
        try:
            startup.enable() if checked else startup.disable()
        except OSError as exc:
            QMessageBox.warning(self, "Could not update startup setting", str(exc))

    # ---- Notifications -------------------------------------------------

    def _build_notifications_group(self) -> QGroupBox:
        group = QGroupBox("Notifications")
        layout = QVBoxLayout(group)

        self._notif_checkbox = self._settings_checkbox(
            layout, "Enable desktop notifications", "notifications_enabled"
        )
        self._sound_checkbox = self._settings_checkbox(
            layout, "Play notification sound", "sound_enabled"
        )
        self._flash_checkbox = self._settings_checkbox(
            layout,
            "Flash screen border + show an alert until acknowledged",
            "flash_enabled",
        )

        color_hint = QLabel("Flash color is set per calendar, in Monitored Calendars above.")
        color_hint.setWordWrap(True)
        color_hint.setStyleSheet("color: gray;")
        layout.addWidget(color_hint)

        flash_options = QFormLayout()

        self._flash_speed_combo = QComboBox()
        for name in SPEED_CHOICES:
            self._flash_speed_combo.addItem(name.capitalize(), name)
        current_speed = self._controller.db.get_setting("flash_speed", DEFAULT_SPEED_NAME)
        speed_index = self._flash_speed_combo.findData(current_speed)
        self._flash_speed_combo.setCurrentIndex(max(0, speed_index))
        self._flash_speed_combo.currentIndexChanged.connect(
            lambda i: self._controller.db.set_setting(
                "flash_speed", self._flash_speed_combo.itemData(i)
            )
        )
        flash_options.addRow("Flash speed:", self._flash_speed_combo)

        layout.addLayout(flash_options)
        return group

    def _settings_checkbox(self, layout: QVBoxLayout, label: str, setting_key: str) -> QCheckBox:
        checkbox = QCheckBox(label)
        checkbox.setChecked(self._controller.db.get_setting(setting_key, "1") == "1")
        checkbox.toggled.connect(
            lambda checked: self._controller.db.set_setting(setting_key, "1" if checked else "0")
        )
        layout.addWidget(checkbox)
        return checkbox
