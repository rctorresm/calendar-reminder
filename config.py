"""Local file locations.

User data (the event cache, settings) always lives under
%APPDATA%\\CalendarReminder — nothing is ever written outside the user's
own profile, and nothing here is a network endpoint.

client_secret.json is different: it's read, never written, and it's
looked for in two places, in order:

1. Bundled next to the app itself (the .exe's own folder when packaged,
   or the project root when running from source). This is the file the
   developer embeds before building/distributing the app, so a recipient
   never has to touch Google Cloud Console themselves.
2. %APPDATA%\\CalendarReminder\\client_secret.json — an override. Anyone
   who wants their own isolated OAuth client instead of the bundled
   shared one (see SECURITY.md) can drop their own file here via
   Settings > Account > Import, and it takes priority over the bundled
   one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CalendarReminder"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return config_dir() / "calendar_reminder.db"


def _bundled_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller's bootloader sets sys._MEIPASS to wherever bundled
        # data files actually landed — for a modern (6.x) --onedir build
        # that's a _internal\ subfolder next to the .exe, not the .exe's
        # own directory, so this must be used rather than
        # Path(sys.executable).parent.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _user_override_client_secret_path() -> Path:
    return config_dir() / "client_secret.json"


def client_secret_path() -> Path:
    """The client_secret.json that should actually be used: a
    per-user override if one was imported, otherwise the one bundled
    with the app."""
    override = _user_override_client_secret_path()
    if override.exists():
        return override
    return _bundled_dir() / "client_secret.json"


def user_override_client_secret_path() -> Path:
    """Where Settings > Import writes a per-user override to."""
    return _user_override_client_secret_path()


def log_path() -> Path:
    return config_dir() / "app.log"


def icon_path() -> Path:
    """assets/icon.ico, resolved the same way as client_secret.json —
    next to the .exe when frozen, project root when running from source.
    Callers should check .exists() and fall back gracefully (e.g. a
    built-in Qt icon) since a from-source checkout or a build that forgot
    --add-data "assets;assets" won't have it."""
    return _bundled_dir() / "assets" / "icon.ico"
