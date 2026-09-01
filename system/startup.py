"""'Start with Windows' via the per-user Run registry key.

Deliberately uses HKEY_CURRENT_USER, never HKEY_LOCAL_MACHINE — this needs
no admin/elevation, and only affects the signed-in user's own account, not
the whole machine. Standard library `winreg` only; no third-party registry
tools.
"""

from __future__ import annotations

import logging
import sys
import winreg

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "CalendarReminderApp"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        # Packaged with PyInstaller: sys.executable IS the app.
        return f'"{sys.executable}" --minimized'
    # Running from source under a normal Python interpreter.
    script = sys.argv[0]
    return f'"{sys.executable}" "{script}" --minimized'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def enable() -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass


def sync_registration(enabled: bool) -> None:
    """Re-apply the user's saved preference on every launch so the
    registry entry stays correct even if the app was moved/reinstalled."""
    try:
        if enabled:
            enable()
        else:
            disable()
    except OSError:
        logger.exception("Could not update the 'Start with Windows' registry entry")
