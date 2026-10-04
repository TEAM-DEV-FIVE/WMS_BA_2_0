import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_move_quality import movement, receiving  # noqa: F401
from test_move_quality_desktop import View, finish_request, wait
from test_orders import orders  # noqa: F401
from test_returns import returning  # noqa: F401

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.returns import ReturnPresenter
from apps.desktop.views.shell import DesktopShell
from packages.contracts.identity import SessionTokens


def presenter(respond):
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="test-access", refresh_token="test-refresh", expires_in=900)
    view = View()
    view.kind = "SUPPLIER_RETURN"
    p = ReturnPresenter(view, api)
    p.reset(uuid4(), uuid4())
    return p, api, view


def test_returns_presenter_keeps_exact_command_until_matching_ack():
    calls = []
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["return.post"])
        if "/operations/" in request.url.path:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "Chưa có ACK", "request_id": str(uuid4())})
        calls.append((request.content, request.headers["Idempotency-Key"]))
        if len(calls) == 1:
            raise httpx.ReadTimeout("Lost ACK")
        return httpx.Response(200, json={"id": request.url.path.split("/")[-2], "number": "SR-TEST", "kind": "SUPPLIER_RETURN",
            "status": "COMPLETED", "warehouse_id": p.warehouse_id, "version": 4, "transaction_id": str(uuid4()), "request_id": str(uuid4())})
    p, api, view = presenter(respond)
    try:
        body = dict(expected_version=3, execution_key=str(uuid4()), reason="Ghi sổ")
        p.command("POST", f"returns/{uuid4()}/post", body)
        body["reason"] = "Changed form"
        finish_request(p)
        command = p.uncertain
        p.operation()
        finish_request(p)
        assert p.uncertain == command and not view.saved
        assert not p.command("POST", "returns", {})
        p.retry()
        finish_request(p)
        assert calls[0] == calls[1] and not p.uncertain and view.saved
    finally:
        p.close()
        p.finish()
        api.close()


def test_returns_presenter_discards_old_scope_response_and_preserves_user_command():
    started, release = threading.Event(), threading.Event()
    main = threading.get_ident()
    def respond(request):
        assert threading.get_ident() != main
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["return.draft"])
        started.set()
        assert release.wait(5)
        if request.method != "GET":
            raise httpx.ReadTimeout("Lost command")
        return httpx.Response(200, json={"items": [], "next_after": None})
    p, api, view = presenter(respond)
    try:
        scope = p.scope
        p.load()
        assert started.wait(5)
        future = p.pending
        p.reset(uuid4(), uuid4())
        release.set()
        future.result(timeout=5)
        p.drain()
        assert not view.loaded
        p.reset(*scope)
        p.command("POST", "returns", {"reason": "Keep command"})
        finish_request(p)
        command = p.uncertain
        p.reset(uuid4(), scope[1])
        assert not p.uncertain
        p.reset(*scope)
        assert p.uncertain == command
        api.clear()
        p.drain()
        assert p.user_id is None
    finally:
        release.set()
        p.close()
        p.finish()
        api.close()


@pytest.mark.integration
@pytest.mark.gui
@pytest.mark.parametrize("kind", ["CUSTOMER_RETURN", "SUPPLIER_RETURN"])
def test_returns_tk_http_create_approve_lost_ack_reconcile_and_logout(returning, kind, tmp_path, monkeypatch):  # noqa: F811
    import tkinter as tk
    f = returning
    if kind == "CUSTOMER_RETURN":
        source, _, _ = f.issued_source("1", "GUI-RETURN-SERIAL")
        quantity, location = "1", f.quarantine["id"]
    else:
        f.received("10")
        source = f.return_sources()["items"][0]
        quantity, location = "4", f.location["id"]
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1", local_data_dir=tmp_path))
        view = shell.customer_return_view if kind == "CUSTOMER_RETURN" else shell.supplier_return_view
        session = shell.session_view
        def login(name):
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            wait(root, lambda: session.presenter.pending is None)
            assert view.presenter.user_id
        def done():
            wait(root, lambda: view.presenter.pending is None and not view.busy)
        login("buyer")
        shell.notebook.select(view)
        view.load_button.invoke()
        done()
        view.new_button.invoke()
        for path in ("returns/sources", "returns/locations"):
            view.presenter.load(path)
            done()
        view.source_selector.current(next(i for i, row in enumerate(view.sources) if row["id"] == source["id"]))
        view.location_selector.current(next(i for i, row in enumerate(view.locations) if row["id"] == location))
        view.variables["quantity"].set(quantity)
        view.add_button.invoke()
        view.variables["day"].set("2026-10-02")
        view.variables["reason"].set("Lập phiếu qua giao diện")
        view.buttons["save"].invoke()
        done()
        assert view.doc and view.doc["status"] == "DRAFT", view.variables["status"].get()
        doc_id = view.doc["id"]
        view.variables["reason"].set("Gửi duyệt")
        view.buttons["submit"].invoke()
        done()
        assert view.doc["status"] == "SUBMITTED"
        login("controller")
        view.presenter.read(doc_id)
        done()
        view.variables["reason"].set("Duyệt độc lập")
        view.buttons["approve"].invoke()
        done()
        assert view.doc["status"] == "APPROVED"
        login("manager")
        view.presenter.read(doc_id)
        done()
        client = view.presenter.api.client
        request = client.request
        def lose_ack(method, path, **kwargs):
            response = request(method, path, **kwargs)
            if method == "POST" and path == f"returns/{doc_id}/post":
                assert response.status_code == 200
                raise httpx.ReadTimeout("Injected loss after real HTTP/PG commit")
            return response
        with monkeypatch.context() as patch:
            patch.setattr(client, "request", lose_ack)
            view.variables["reason"].set("Ghi sổ thực tế")
            view.buttons["post"].invoke()
            done()
        assert view.presenter.uncertain and view.doc["status"] == "APPROVED"
        view.operation_button.invoke()
        done()
        assert view.doc["status"] == "COMPLETED" and not view.presenter.uncertain, view.variables["status"].get()
        if kind == "CUSTOMER_RETURN":
            view.line_table.selection_set("0")
            view.warranty_button.invoke()
            done()
            assert "GUI-RETURN-SERIAL" in view.variables["detail"].get()
            assert "Chưa xác định" in view.variables["detail"].get()
        for widget in (view.source_selector, view.location_selector, view.day_entry, view.warranty_button, *view.buttons.values()):
            assert widget.winfo_ismapped()
            assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
            assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        session.logout()
        assert view.doc is None and not view.lines and not view.sources
        wait(root, lambda: session.presenter.pending is None)
    finally:
        if shell:
            shell.close()
            shell.finish()
            assert all(v.variables == {} for v in shell.return_views)
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()
