import socket
import threading
import time

import httpx
import pyotp
import pytest
import uvicorn
from test_custom_fields import custom, field, ok, orders  # noqa: F401

from apps.desktop.api.client import DesktopSettings

pytestmark = [pytest.mark.integration, pytest.mark.gui]
# ruff: noqa: F811


@pytest.fixture
def custom_ui(custom):
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell

    f = custom
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        until = time.monotonic()+5
        while not server.started and time.monotonic()<until:
            time.sleep(0.01)
        assert server.started
        shell = DesktopShell(tk.Tk(), DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        view = shell.custom_fields_view
        shell.notebook.select(view)
        shell.root.geometry("800x620")

        def wait(predicate):
            until = time.monotonic()+15
            while not predicate() and time.monotonic()<until:
                shell.root.update()
                time.sleep(0.005)
            assert predicate(), view.variables["status"].get()

        def idle():
            wait(lambda: view.presenter.pending is None and not view.busy)

        def login(name, secret=None):
            session = shell.session_view
            if session.presenter.api._tokens:
                session.logout()
                wait(lambda: session.status.get() == "Đã đăng xuất.")
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            if secret:
                wait(lambda: session.presenter.pending is None and session.presenter.api._challenge is not None)
                session.code.set(pyotp.TOTP(secret).at(f.orders.iam.now))
                session.mfa()
            wait(lambda: view.presenter.user_id is not None)

        f.shell, f.view, f.wait, f.idle, f.login = shell, view, wait, idle, login
        yield f
    finally:
        if shell:
            shell.close()
            shell.finish()
        f.shell = f.view = f.wait = f.idle = f.login = None
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def test_gui_admin_without_warehouse_and_metadata_entry_timeout_retry_history(custom_ui, monkeypatch):
    f, view = custom_ui, custom_ui.view
    admin, secret = f.orders.iam.user("gui-admin", mfa=True)
    f.orders.iam.grant(admin, "SYSADMIN")
    f.login("gui-admin", secret)
    assert not view.warehouses
    view.tabs.select(1)
    view.schema_button.invoke()
    f.idle()
    assert view.definition and view.definition["version"] == 0
    for values in [dict(code="note", label="Ghi chú", value_type="TEXT"),
                   dict(code="checked", label="Đã kiểm tra", value_type="BOOLEAN")]:
        for name, value in values.items():
            view.variables[name].set(value)
        view.add_button.invoke()
    assert len(view.fields) == 2
    view.variables["reason"].set("Cấu hình từ GUI")
    view.publish_button.invoke()
    f.idle()
    assert "xác nhận phiên bản 1" in view.variables["status"].get()
    f.login("buyer")
    doc = ok(f.orders.create(), 201)
    view.tabs.select(0)
    view.targets_button.invoke()
    f.idle()
    view.target_selector.current(next(i for i, r in enumerate(view.targets) if r["id"] == doc["id"]))
    view.select_target()
    f.idle()
    assert set(view.inputs) == {"note", "checked"}
    view.inputs["note"].set("Nhập từ metadata")
    view.inputs["checked"].set("Có")
    view.variables["reason"].set("Bổ sung chứng từ")
    api, original = view.presenter.api, view.presenter.api.client.request
    lost = False
    def timeout(method, url, **kwargs):
        nonlocal lost
        response = original(method, url, **kwargs)
        if method == "PUT" and "custom-fields/documents/" in str(url) and not lost:
            assert response.status_code == 200, response.text
            lost = True
            raise httpx.ReadTimeout("after committed metadata")
        return response
    with monkeypatch.context() as patch:
        patch.setattr(api.client, "request", timeout)
        view.save_button.invoke()
        f.idle()
    assert lost and view.presenter.uncertain and view.record["version"] == doc["version"], (view.variables["status"].get(), view.save_button.state(), view.record)
    assert view.save_button.instate(["disabled"])
    view.retry_button.invoke()
    f.idle()
    assert not view.presenter.uncertain and view.record is None
    view.read_button.invoke()
    f.idle()
    assert view.record["values"] == {"note": "Nhập từ metadata", "checked": True}
    view.history_button.invoke()
    f.idle()
    assert len(view.history_table.get_children()) == 1
    view.canvas.yview_moveto(1)
    f.shell.root.update()
    assert view.history_table.winfo_rooty()+view.history_table.winfo_height() <= f.shell.root.winfo_rooty()+f.shell.root.winfo_height()
    f.login("manager")
    assert view.record is None and not view.inputs and not view.history_table.get_children()
    assert view.variables["target_id"].get() == ""


def test_gui_50_metadata_fields_scroll_and_late_response_on_logout(custom_ui, monkeypatch):
    f, view = custom_ui, custom_ui.view
    ok(f.publish([field(f"description_{i}") for i in range(50)]))
    doc = ok(f.orders.create(), 201)
    f.login("buyer")
    view.variables["target_id"].set(doc["id"])
    view.read()
    f.idle()
    assert len(view.inputs) == 50
    view.canvas.yview_moveto(1)
    f.shell.root.update()
    last = view.input_widgets[-1][0]
    assert last.winfo_rooty() >= f.shell.root.winfo_rooty()
    assert last.winfo_rooty()+last.winfo_height() <= f.shell.root.winfo_rooty()+f.shell.root.winfo_height()
    started, release = threading.Event(), threading.Event()
    original = view.presenter.api.get
    def delayed(path):
        data = original(path)
        if path.startswith("custom-fields/"):
            started.set()
            assert release.wait(10)
        return data
    with monkeypatch.context() as patch:
        patch.setattr(view.presenter.api, "get", delayed)
        view.read()
        f.wait(started.is_set)
        finished = threading.Event()
        view.presenter.pending.add_done_callback(lambda done: finished.set())
        view.session_changed()
        release.set()
        # Shell.poll may already drain the stale result before this wait checks
        # the queue. Wait for completion after its enqueue callback instead.
        f.wait(finished.is_set)
        view.presenter.drain()
    assert view.record is None and not view.inputs and view.presenter.user_id is None
