import socket
import threading
import time
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_move_quality import movement, receiving  # noqa: F401
from test_orders import ok, orders  # noqa: F401

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.moves import MovePresenter
from apps.desktop.views.shell import DesktopShell
from packages.contracts.identity import SessionTokens


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.loaded, self.saved, self.errors = [], [], []
    def workflow_busy(self):
        assert threading.get_ident() == self.main
    def workflow_clear(self):
        assert threading.get_ident() == self.main
        self.loaded.clear()
    def workflow_loaded(self, *data):
        assert threading.get_ident() == self.main
        self.loaded.append(data)
    def workflow_saved(self, data):
        assert threading.get_ident() == self.main
        self.saved.append(data)
    def workflow_error(self, message):
        assert threading.get_ident() == self.main
        self.errors.append(message)
    def workflow_signed_out(self, message):
        self.workflow_clear()


def make_presenter(respond):
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="test-access", refresh_token="test-refresh", expires_in=900)
    view = View()
    presenter = MovePresenter(view, api)
    presenter.reset(uuid4(), uuid4())
    return presenter, api, view


def finish_request(presenter):
    presenter.pending.result(timeout=5)
    presenter.drain()


def test_move_quality_presenter_timeout_reuses_exact_key_body_and_operation_not_found():
    calls = []
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["move.post"])
        if "/operations/" in request.url.path:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "No ACK yet", "request_id": str(uuid4())})
        calls.append((request.method, request.url.path, request.content, request.headers["Idempotency-Key"]))
        if len(calls) == 1:
            raise httpx.ReadTimeout("After commit")
        return httpx.Response(200, json={"id": request.url.path.split("/")[-2], "number": "MOVE-TEST",
            "kind": "INTERNAL_MOVE", "status": "COMPLETED", "warehouse_id": presenter.warehouse_id,
            "version": 4, "transaction_id": str(uuid4()), "request_id": str(uuid4())})
    presenter, api, view = make_presenter(respond)
    try:
        body = {"expected_version": 3, "execution_key": str(uuid4()), "reason": "Test move"}
        original = deepcopy(body)
        presenter.command("POST", "moves/" + str(uuid4()) + "/post", body)
        body["reason"] = "Mutated by form"
        finish_request(presenter)
        assert presenter.uncertain[2] == original and len(calls) == 1
        assert not presenter.command("POST", "moves", {})
        presenter.operation()
        finish_request(presenter)
        assert presenter.uncertain and len(calls) == 1
        presenter.retry()
        finish_request(presenter)
        assert calls[0] == calls[1] and not presenter.uncertain and view.saved
    finally:
        presenter.close()
        presenter.finish()
        api.close()


def test_move_quality_presenter_scope_reset_busy_and_worker_thread():
    started, release = threading.Event(), threading.Event()
    main = threading.get_ident()
    def respond(request):
        assert threading.get_ident() != main
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["move.post"])
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json={"items": [{"private": "old scope"}], "next_after": None})
    presenter, api, view = make_presenter(respond)
    try:
        presenter.load()
        assert started.wait(5)
        future = presenter.pending
        assert not presenter.load() and not presenter.command("POST", "moves", {})
        presenter.reset(uuid4(), uuid4())
        release.set()
        future.result(timeout=5)
        presenter.drain()
        assert not view.loaded
    finally:
        release.set()
        presenter.close()
        presenter.finish()
        api.close()


def test_move_quality_presenter_pending_command_isolated_by_user_and_warehouse():
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["move.post"])
        raise httpx.ReadTimeout("Test")
    presenter, api, _ = make_presenter(respond)
    try:
        scope = presenter.scope
        presenter.command("POST", "moves", {"reason": "Keep exact body"})
        finish_request(presenter)
        command = presenter.uncertain
        presenter.reset(uuid4(), scope[1])
        assert not presenter.uncertain and not presenter.retry()
        presenter.reset(scope[0], uuid4())
        assert not presenter.uncertain
        presenter.reset(*scope)
        assert presenter.uncertain == command
        api.clear()
        presenter.drain()
        assert presenter.user_id is None
    finally:
        presenter.close()
        presenter.finish()
        api.close()


@pytest.mark.parametrize("code", ["FORBIDDEN", "NOT_FOUND", "INVALID_ACK"])
def test_move_quality_presenter_keeps_uncertain_command_when_replay_cannot_confirm(code):
    calls = []
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["move.post"])
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("Response lost after possible commit")
        if code == "INVALID_ACK":
            return httpx.Response(200, json={"id": str(uuid4()), "status": "COMPLETED"})
        return httpx.Response(403 if code == "FORBIDDEN" else 404,
                              json={"code": code, "message": "Current permission revoked", "request_id": str(uuid4())})
    presenter, api, view = make_presenter(respond)
    try:
        presenter.command("POST", "moves/" + str(uuid4()) + "/post",
                          {"expected_version": 3, "execution_key": str(uuid4()), "reason": "Reconcile"})
        finish_request(presenter)
        command = presenter.uncertain
        presenter.retry()
        finish_request(presenter)
        assert presenter.uncertain == command and not view.saved
        assert calls[0].content == calls[1].content
        assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    finally:
        presenter.close()
        presenter.finish()
        api.close()


def wait(root, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert predicate()


@pytest.mark.integration
@pytest.mark.gui
def test_move_quality_tk_http_decision_putaway_approval_and_logout(movement):  # noqa: F811
    import tkinter as tk
    f = movement
    source = f.received()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        session, quality, move = shell.session_view, shell.quality_view, shell.move_view
        def login(name):
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            wait(root, lambda: session.presenter.pending is None)
            assert quality.presenter.user_id and move.presenter.user_id
        def done(view):
            wait(root, lambda: view.presenter.pending is None and not view.busy)
        login("manager")
        shell.notebook.select(quality)
        quality.load_button.invoke()
        done(quality)
        quality.table.selection_set(source["id"])
        quality.select()
        done(quality)
        quality.variables["accepted"].set("75")
        quality.variables["rejected"].set("5")
        quality.variables["reason"].set("Kiểm định từ giao diện")
        quality.decide_button.invoke()
        done(quality)
        assert len(quality.decisions) == 2, quality.variables["status"].get()
        decisions = list(quality.decisions.values())
        assert quality.source["remaining_base"] == "0.000000"
        login("buyer")
        quality.presenter.read(source["id"])
        done(quality)
        assert quality.decide_button.instate(["disabled"])
        shell.notebook.select(move)
        move.load_button.invoke()
        done(move)
        move.new_button.invoke()
        for path in ["moves/stock", "moves/locations"]:
            move.presenter.load(path)
            done(move)
        stock_index = next(i for i, row in enumerate(move.stock) if row["stock_item_id"] == source["stock_item_id"])
        for q in decisions:
            move.stock_selector.current(stock_index)
            dest = f.bin["id"] if q["result"] == "ACCEPT" else f.quarantine["id"]
            move.location_selector.current(next(i for i, row in enumerate(move.locations) if row["id"] == dest))
            move.variables["quantity"].set(q["quantity"])
            move.variables["quality_id"].set(q["id"])
            move.add_button.invoke()
        move.variables["day"].set("2026-10-02")
        move.variables["reason"].set("Cất 75 và cách ly 5")
        move.buttons["save"].invoke()
        done(move)
        assert move.doc and move.doc["status"] == "DRAFT", move.variables["status"].get()
        doc_id = move.doc["id"]
        move.variables["reason"].set("Gửi duyệt cất hàng")
        move.buttons["submit"].invoke()
        done(move)
        assert move.doc["status"] == "SUBMITTED"
        login("controller")
        move.presenter.read(doc_id)
        done(move)
        move.variables["reason"].set("Duyệt độc lập")
        move.buttons["approve"].invoke()
        done(move)
        assert move.doc["status"] == "APPROVED"
        login("buyer")
        move.presenter.read(doc_id)
        done(move)
        move.variables["reason"].set("Ghi sổ theo phê duyệt")
        move.buttons["post"].invoke()
        done(move)
        assert move.doc["status"] == "COMPLETED", move.variables["status"].get()
        assert not move.presenter.uncertain
        assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "20.000000"
        session.logout()
        assert move.doc is None and not move.lines and not quality.sources and not quality.decisions
        wait(root, lambda: session.presenter.pending is None)
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.gui
def test_move_quality_layout_900_by_690_and_cleanup():
    import tkinter as tk

    from packages.contracts.identity import CurrentUser, WarehouseSummary
    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        user = CurrentUser(id=uuid4(), username="test-user", display_name="Test", is_active=True,
                           mfa_verified=False, global_permissions=[])
        warehouse = WarehouseSummary(id=uuid4(), code="UI", name="Test warehouse")
        shell.session_changed(user, [warehouse])
        for view in [shell.quality_view, shell.move_view]:
            shell.notebook.select(view)
            view.permissions = ["quality.decide", "move.draft", "move.post"]
            view.enable()
            root.update()
            controls = [view.load_button, view.selector, view.retry_button, view.reason_entry]
            if view is shell.move_view:
                controls += [view.stock_selector, view.location_selector, view.quality_entry, view.day_entry, *view.buttons.values()]
            else:
                controls += [view.decide_button, view.history_button, view.history_next, *view.entries]
            for widget in controls:
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.close()
        shell.finish()
        assert shell.move_view.variables == {} and shell.quality_view.variables == {}
    finally:
        if not shell.closed:
            shell.close()
            shell.finish()
