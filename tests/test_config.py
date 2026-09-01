import sys
from pathlib import Path

import config


def test_bundled_client_secret_used_when_no_override(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_bundled_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "_user_override_client_secret_path", lambda: tmp_path / "appdata" / "client_secret.json")

    bundled = tmp_path / "client_secret.json"
    bundled.write_text("{}")

    assert config.client_secret_path() == bundled


def test_user_override_takes_priority_over_bundled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_bundled_dir", lambda: tmp_path)
    override_path = tmp_path / "appdata" / "client_secret.json"
    monkeypatch.setattr(config, "_user_override_client_secret_path", lambda: override_path)

    (tmp_path / "client_secret.json").write_text("{}")
    override_path.parent.mkdir()
    override_path.write_text("{}")

    assert config.client_secret_path() == override_path


def test_frozen_bundled_dir_uses_meipass_not_exe_folder(tmp_path, monkeypatch):
    """Regression guard: PyInstaller 6.x --onedir puts bundled data files
    in a _internal\\ subfolder (exposed via sys._MEIPASS), not directly
    next to the .exe. Using Path(sys.executable).parent here would look
    in the wrong place and silently fail to find client_secret.json /
    the icon in a real packaged build."""
    meipass_dir = tmp_path / "dist" / "CalendarReminder" / "_internal"
    exe_dir = tmp_path / "dist" / "CalendarReminder"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "CalendarReminder.exe"))

    assert config._bundled_dir() == Path(str(meipass_dir))


def test_frozen_bundled_dir_falls_back_to_exe_folder_without_meipass(tmp_path, monkeypatch):
    exe_dir = tmp_path / "dist" / "CalendarReminder"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "CalendarReminder.exe"))

    assert config._bundled_dir() == exe_dir
