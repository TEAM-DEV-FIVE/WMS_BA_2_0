from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.desktop import __main__ as entry
from apps.desktop import lifecycle
from apps.desktop.views.shell import DesktopShell


def test_shutdown_waits_for_inflight_request_and_queued_journal_close():
    entered, release = Event(), Event()
    completed = []
    executor = ThreadPoolExecutor(max_workers=1)

    def request():
        entered.set()
        assert release.wait(5)
        completed.append("request")

    executor.submit(request)
    assert entered.wait(5)
    executor.submit(lambda: completed.append("journal closed"))
    executor.shutdown(wait=False)
    try:
        done = lifecycle.await_workers((executor,))
        assert not done.wait(.05)
        release.set()
        assert done.wait(5)
        assert completed == ["request", "journal closed"]
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_cancel_exit_preserves_window_and_resumes_poll(monkeypatch):
    shell = DesktopShell.__new__(DesktopShell)
    shell.closed = shell.closing = shell.restart_requested = False
    shell.root = Mock()
    shell.poll_id = "poll"
    shell.stop_workers = Mock()
    monkeypatch.setattr("apps.desktop.views.shell.messagebox.askokcancel", lambda *a, **k: False)
    shell.request_reload()
    assert not shell.closing and not shell.restart_requested
    shell.stop_workers.assert_not_called()
    shell.root.destroy.assert_not_called()
    shell.root.after.assert_called_once_with(50, shell.poll)


def test_close_wait_keeps_window_alive_until_workers_finish():
    shell = DesktopShell.__new__(DesktopShell)
    shell.closed = False
    shell.root = Mock()
    shell.exit_progress = Mock()
    shell.shutdown_done = Event()
    shell.close = Mock()
    shell.wait_for_close()
    shell.close.assert_not_called()
    shell.root.after.assert_called_once_with(100, shell.wait_for_close)
    shell.shutdown_done.set()
    shell.wait_for_close()
    shell.close.assert_called_once()
    shell.exit_progress.stop.assert_called_once()


@pytest.mark.parametrize("restart", [False, True])
def test_restart_happens_only_after_cleanup_and_lock_release(monkeypatch, tmp_path, restart):
    steps = []
    root = SimpleNamespace(mainloop=lambda: steps.append("mainloop"), withdraw=lambda: steps.append("hide"))
    shell = SimpleNamespace(
        restart_requested=restart,
        finish=lambda: steps.append("finish"),
        session_view=SimpleNamespace(presenter=SimpleNamespace(api=SimpleNamespace(enable_persistence=lambda: None))),
    )
    monkeypatch.setattr(entry, "settings_for_startup", lambda: SimpleNamespace(local_data_dir=tmp_path))
    monkeypatch.setattr(entry, "application_lock", lambda _: SimpleNamespace(close=lambda: steps.append("unlock")))
    monkeypatch.setattr(entry, "preflight_cache", lambda _: None)
    monkeypatch.setattr(entry, "configure_display", lambda: None)
    monkeypatch.setattr(entry.tk, "Tk", lambda **kwargs: root)
    splash = Mock()
    splash.finish.side_effect = lambda: steps.append("ready")
    monkeypatch.setattr(entry, "StartupSplash", lambda _: splash)
    monkeypatch.setattr(entry, "create_shell", lambda *args: shell)
    monkeypatch.setattr(entry, "restart_application", lambda: steps.append("restart"))
    entry.main()
    splash.finish.assert_called_once()
    splash.close.assert_called_once()
    assert steps == ["hide", "ready", "mainloop", "finish", "unlock"] + (["restart"] if restart else [])


@pytest.mark.parametrize("frozen", [False, True])
def test_restart_uses_current_interpreter_or_packaged_app(monkeypatch, frozen):
    execute = Mock()
    monkeypatch.setattr(lifecycle.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(lifecycle.os, "execv", execute)
    lifecycle.restart_application()
    args = [lifecycle.sys.executable] + ([] if frozen else ["-m", "apps.desktop"])
    execute.assert_called_once_with(lifecycle.sys.executable, args)


@pytest.mark.gui
def test_shell_reload_waits_responsively_and_stops_every_worker(monkeypatch, tmp_path):
    import time
    import tkinter as tk

    from apps.desktop.api.client import DesktopSettings

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    release, entered = Event(), Event()

    def work():
        entered.set()
        assert release.wait(5)

    shell.import_view.presenter.executor.submit(work)
    assert entered.wait(5)
    monkeypatch.setattr("apps.desktop.views.shell.messagebox.askokcancel", lambda *a, **k: True)
    try:
        shell.reload_button.invoke()
        shell.request_close()  # Repeated click must not start a second shutdown.
        assert shell.restart_requested and shell.closing and not shell.closed
        assert all(owner.closed for owner in shell.worker_owners())
        pulse = []
        root.after(0, lambda: pulse.append(True))
        root.update()
        assert pulse and not shell.closed and root.winfo_exists()
        release.set()
        deadline = time.monotonic() + 5
        while not shell.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert shell.closed
    finally:
        release.set()
        shell.close()
        shell.finish()
