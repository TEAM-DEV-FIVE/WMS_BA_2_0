import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.desktop import __main__ as entry
from apps.desktop.views.startup_splash import StartupSplash


@pytest.mark.gui
def test_main_window_is_hidden_until_ready_then_splash_is_removed():
    root = tk.Tk()
    root.withdraw()
    splash = StartupSplash(root, minimum_ms=80)
    try:
        assert root.state() == "withdrawn"
        assert splash.window.winfo_viewable()
        splash.stage("Đang tải giao diện…", .55)
        assert root.state() == "withdrawn"
        splash.finish()
        assert root.state() == "withdrawn"
        deadline = time.monotonic() + 2
        while not splash.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert splash.closed and splash.timer is None
        assert not splash.window.winfo_exists()
        assert root.state() == "normal"
        assert splash.photo is None
    finally:
        splash.close()
        root.destroy()


@pytest.mark.gui
def test_closing_splash_cancels_reveal_and_does_not_show_root():
    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    splash = StartupSplash(root, minimum_ms=100)
    try:
        splash.finish()
        splash.close()
        splash.close()
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert root.state() == "withdrawn"
        assert not errors and splash.timer is None
    finally:
        root.destroy()


def test_cache_failure_closes_splash_and_releases_lock_without_building_shell(monkeypatch, tmp_path):
    root, splash, lock, build, error_dialog = Mock(), Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(entry, "settings_for_startup", lambda: SimpleNamespace(local_data_dir=tmp_path))
    monkeypatch.setattr(entry, "application_lock", lambda _: lock)
    monkeypatch.setattr(entry, "configure_display", lambda: None)
    monkeypatch.setattr(entry.tk, "Tk", lambda **kwargs: root)
    monkeypatch.setattr(entry, "StartupSplash", lambda _: splash)
    monkeypatch.setattr(entry, "create_shell", build)
    monkeypatch.setattr(entry.messagebox, "showerror", error_dialog)
    monkeypatch.setattr(entry, "preflight_cache", Mock(side_effect=ValueError("Invalid cache")))
    with pytest.raises(SystemExit):
        entry.main()
    root.withdraw.assert_called_once()
    build.assert_not_called()
    splash.finish.assert_not_called()
    assert splash.close.called
    error_dialog.assert_called_once()
    root.destroy.assert_called_once()
    lock.close.assert_called_once()
