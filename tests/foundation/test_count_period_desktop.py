import socket
import threading
import time

import httpx
import pyotp
import pytest
import uvicorn
from sqlalchemy import text
from test_count_period import counting, orders, receiving  # noqa: F401

from apps.desktop.api.client import DesktopSettings

pytestmark = [pytest.mark.integration, pytest.mark.gui]


@pytest.fixture
def count_ui(counting):  # noqa: F811
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell

    f = counting
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        until = time.monotonic() + 5
        while not server.started and time.monotonic() < until:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        shell.notebook.select(shell.count_view)

        def wait(predicate):
            until = time.monotonic() + 15
            while not predicate() and time.monotonic() < until:
                root.update()
                time.sleep(0.005)
            assert predicate(), shell.count_view.variables["status"].get() + " / " + shell.period_view.variables["status"].get()

        def idle(view=None):
            view = view or shell.count_view
            wait(lambda: view.presenter.pending is None and not view.busy)

        def login(name):
            session = shell.session_view
            if session.presenter.api._tokens:
                session.logout()
                wait(lambda: session.status.get() == "Đã đăng xuất.")
            if name == "director":
                f.iam.advance(31)  # The fixture already consumed the previous TOTP.
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            if name == "director":
                wait(lambda: session.presenter.pending is None and session.presenter.api._challenge is not None)
                session.code.set(pyotp.TOTP(f.director_secret).at(f.iam.now))
                session.mfa()
            wait(lambda: bool(shell.count_view.warehouses))
            shell.count_view.presenter.load()
            idle()

        f.shell, f.wait_ui, f.idle_ui, f.login_ui = shell, wait, idle, login
        yield f
    finally:
        if shell:
            shell.close()
            shell.finish()
        f.shell = f.wait_ui = f.idle_ui = f.login_ui = None
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def act(f, action, view=None):
    view = view or f.shell.count_view
    view.variables["reason"].set("Kiểm thử GUI " + action)
    view.action(action)
    f.idle_ui(view)


def test_count_gui_create_blind_rounds_approve_post_timeout_recover(count_ui, monkeypatch):
    f = count_ui
    f.count_received()
    f.login_ui("manager")
    view = f.shell.count_view
    view.new()
    for resource in ("locations", "users"):
        view.presenter.catalog(resource)
        f.idle_ui()
    view.location_selector.current(next(i for i, r in enumerate(view.catalogs["locations"]) if r["id"] == f.location["id"]))
    view.counter1_selector.current(next(i for i, r in enumerate(view.catalogs["users"]) if r["id"] == str(f.buyer)))
    view.counter2.current(next(i for i, r in enumerate(view.catalogs["users"]) if r["id"] == str(f.picker)))
    view.add_scope()
    view.variables["business_date"].set("2026-10-02")
    view.variables["reason"].set("Tạo kiểm kê qua GUI")
    view.create_button.invoke()
    f.idle_ui()
    assert view.doc["status"] == "DRAFT"
    doc_id = view.doc["id"]
    act(f, "freeze")
    assert view.doc["lines"][0]["snapshot_quantity"] == "100.000000"
    for name in ("buyer", "counter-two"):
        f.login_ui(name)
        view.presenter.read(doc_id)
        f.idle_ui()
        assert view.doc["mode"] == "BLIND"
        assert "snapshot_quantity" not in view.doc["lines"][0]
        assert view.lines["displaycolumns"] == ("sku", "owner", "trace", "location", "round")
        line = view.doc["lines"][0]
        view.lines.selection_set(line["id"])
        view.select_line()
        view.variables["quantity"].set("98")
        view.variables["reason"].set("Đếm độc lập tại vị trí")
        view.observe_button.invoke()
        f.idle_ui()
        assert view.doc["status"] == "COUNTED" and not view.history.get_children()
    f.login_ui("manager")
    view.presenter.read(doc_id)
    f.idle_ui()
    act(f, "submit")
    assert view.buttons["post"].instate(["disabled"])
    for name in ("controller", "director"):
        f.login_ui(name)
        view.presenter.read(doc_id)
        f.idle_ui()
        act(f, "approve")
    f.login_ui("controller")
    view.presenter.read(doc_id)
    f.idle_ui()
    api = view.presenter.api
    original = api.client.request
    lost = False
    def timeout(method, url, **kwargs):
        nonlocal lost
        response = original(method, url, **kwargs)
        if method == "POST" and str(url).endswith("/post") and not lost:
            lost = True
            raise httpx.ReadTimeout("Lost committed response")
        return response
    with monkeypatch.context() as patch:
        patch.setattr(api.client, "request", timeout)
        act(f, "post")
    assert lost and view.presenter.uncertain and view.doc["status"] != "POSTED"
    view.operation_button.invoke()
    f.idle_ui()
    assert view.doc["status"] == "POSTED" and not view.presenter.uncertain
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 98
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='ADJUST'")).scalar_one() == 1


def test_period_gui_open_close_controller_confirmation_and_director_reopen(count_ui):
    f = count_ui
    f.login_ui("controller")
    view = f.shell.period_view
    f.shell.notebook.select(view)
    view.presenter.load()
    f.idle_ui(view)
    view.variables["starts_on"].set("2026-11-01")
    view.variables["ends_on"].set("2026-11-30")
    act(f, "create", view)
    assert view.doc["status"] == "OPEN"
    period_id = view.doc["id"]
    act(f, "close", view)
    assert view.doc["status"] == "CLOSED"
    act(f, "confirm-reopen", view)
    assert view.doc["confirmation_id"]
    f.login_ui("director")
    view.presenter.read(period_id)
    f.idle_ui(view)
    act(f, "reopen", view)
    assert view.doc["status"] == "OPEN" and view.doc["version"] == 4
