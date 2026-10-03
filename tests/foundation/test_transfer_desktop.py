import socket
import threading
import time
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_move_quality_desktop import View, finish_request, wait
from test_openings import opening, orders  # noqa: F401
from test_transfers import transfer  # noqa: F401

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.transfers import TransferPresenter
from apps.desktop.views.shell import DesktopShell
from packages.contracts.identity import SessionTokens


@pytest.mark.parametrize(
    "action,operation", [("dispatch", "DISPATCH"), ("receive", "ARRIVE"), ("loss-post", "ADJUST")]
)
def test_transfer_presenter_preserves_exact_unknown_retry_and_partial_ack(action, operation):
    calls = []

    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["transfer.dispatch", "transfer.receive"])
        if "/operations/" in request.url.path:
            return httpx.Response(
                404, json={"code": "NOT_FOUND", "message": "Chưa có ACK", "request_id": str(uuid4())}
            )
        calls.append((request.content, request.headers["Idempotency-Key"]))
        if len(calls) == 1:
            raise httpx.ReadTimeout("ACK lost")
        return httpx.Response(
            200,
            json=dict(
                id=request.url.path.split("/")[-2],
                number="TRF-TEST",
                kind="ADJUSTMENT" if operation == "ADJUST" else "TRANSFER",
                status="COMPLETED" if operation == "ADJUST" else "PARTIAL",
                warehouse_id=presenter.warehouse_id,
                destination_warehouse_id=str(uuid4()),
                version=7,
                request_id=str(uuid4()),
                transaction_id=str(uuid4()),
                operation=operation,
            ),
        )

    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="test-access", refresh_token="test-refresh", expires_in=900)
    view = View()
    presenter = TransferPresenter(view, api)
    presenter.reset(uuid4(), uuid4())
    try:
        body = dict(
            expected_version=6, execution_key=str(uuid4()), evidence_ref="Biên bản test", reason="Test"
        )
        original = deepcopy(body)
        presenter.command("POST", f"transfers/{uuid4()}/{action}", body)
        body["reason"] = "Đổi trên form"
        finish_request(presenter)
        assert presenter.uncertain[2] == original
        presenter.operation()
        finish_request(presenter)
        assert presenter.uncertain
        presenter.retry()
        finish_request(presenter)
        assert calls[0] == calls[1] and not presenter.uncertain and view.saved[0]["operation"] == operation
    finally:
        presenter.close()
        presenter.finish()
        api.close()


def test_transfer_presenter_discards_old_session_response_and_keeps_unknown_partition():
    started, release = threading.Event(), threading.Event()
    main = threading.get_ident()

    def respond(request):
        assert threading.get_ident() != main
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=[])
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json={"items": [], "next_after": None})

    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="test", refresh_token="test-r", expires_in=900)
    view = View()
    presenter = TransferPresenter(view, api)
    presenter.reset(uuid4(), uuid4())
    try:
        presenter.load()
        assert started.wait(5)
        future = presenter.pending
        presenter.reset(uuid4(), uuid4())
        release.set()
        future.result(5)
        presenter.drain()
        assert not view.loaded
    finally:
        release.set()
        presenter.close()
        presenter.finish()
        api.close()


@pytest.mark.integration
@pytest.mark.gui
def test_transfer_tk_http_draft_approval_partial_missing_loss_and_logout(transfer):  # noqa: F811
    import tkinter as tk

    f = transfer
    f.tr_seed()
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
        shell = DesktopShell(
            root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1")
        )
        session, view = shell.session_view, shell.transfer_view

        def done():
            wait(root, lambda: view.presenter.pending is None and not view.busy)

        def login(name):
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            wait(root, lambda: session.presenter.pending is None)
            view.selector.current(
                next(i for i, w in enumerate(view.warehouses) if str(w.id) == str(f.warehouse))
            )
            view.scope_changed()
            shell.notebook.select(view)

        login("manager")
        view.load_button.invoke()
        done()
        view.new_button.invoke()
        view.destination_selector.current(
            next(i for i, w in enumerate(view.warehouses) if str(w.id) == str(f.destination))
        )
        view.presenter.load("transfers/stock")
        done()
        view.stock_selector.current(0)
        view.variable("quantity").set("20")
        view.add_button.invoke()
        view.variable("day").set("2026-10-02")
        view.variable("reason").set("Chuyển kho từ UI")
        view.buttons["save"].invoke()
        done()
        assert view.doc and view.doc["status"] == "DRAFT", view.variables["status"].get()
        doc_id = view.doc["id"]
        view.variable("reason").set("Gửi duyệt")
        view.buttons["submit"].invoke()
        done()
        assert view.doc["status"] == "SUBMITTED"
        login("controller")
        view.presenter.read(doc_id)
        done()
        view.variable("reason").set("Duyệt độc lập")
        view.buttons["approve"].invoke()
        done()
        assert view.doc["status"] == "APPROVED"
        login("manager")
        view.presenter.read(doc_id)
        done()
        view.variable("reason").set("Xuất chuyển")
        view.variable("evidence").set("Biên bản soạn/giao TRF-UI")
        view.buttons["dispatch"].invoke()
        done()
        assert view.doc["status"] == "PARTIAL", view.variables["status"].get()
        view.tabs.select(view.pages["arrival"])
        view.load_locations()
        done()
        view.source_selector.current(0)
        view.location_selector.current(
            next(i for i, r in enumerate(view.locations) if r["id"] == f.arrival["id"])
        )
        view.condition_selector.current(0)
        view.variable("received").set("18")
        view.variable("receive_day").set("2026-10-02")
        view.variable("reason").set("Nhận thực tế 18")
        view.receive_button.invoke()
        done()
        assert view.doc["sources"][0]["remaining_base"] == "2.000000", view.variables["status"].get()
        view.source_selector.current(0)
        view.variable("missing").set("2")
        view.variable("reason").set("Ghi thiếu 2")
        view.discrepancy_button.invoke()
        done()
        assert len(view.doc["discrepancies"]) == 1, view.variables["status"].get()
        view.tabs.select(view.pages["loss"])
        view.evidence_selector.current(0)
        view.variable("loss_qty").set("2")
        view.variable("loss_day").set("2026-10-02")
        view.variable("reason").set("Đã xác minh mất")
        view.loss_button.invoke()
        done()
        assert view.doc["kind"] == "ADJUSTMENT", view.variables["status"].get()
        loss_id = view.doc["id"]
        view.variable("reason").set("Gửi kiểm soát")
        view.buttons["submit"].invoke()
        done()
        login("controller")
        view.presenter.read(loss_id)
        done()
        view.variable("reason").set("Duyệt mất theo chứng cứ")
        view.buttons["approve"].invoke()
        done()
        view.variable("evidence").set("Quyết định mất đã duyệt")
        view.variable("reason").set("Ghi điều chỉnh mất")
        view.buttons["post"].invoke()
        done()
        assert view.doc["status"] == "COMPLETED", view.variables["status"].get()
        view.parent_button.invoke()
        done()
        assert view.doc["status"] == "COMPLETED" and view.doc["sources"][0]["lost_base"] == "2.000000"
        view.history()
        done()
        assert len(view.history_table.get_children()) == 3
        session.logout()
        assert view.doc is None and not view.stock and not view.lines
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
def test_transfer_layout_900_by_690_and_main_thread_cleanup():
    import tkinter as tk

    from packages.contracts.identity import CurrentUser, WarehouseSummary

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        shell.session_changed(
            CurrentUser(
                id=uuid4(),
                username="fixture",
                display_name="Fixture",
                is_active=True,
                mfa_verified=False,
                global_permissions=[],
            ),
            [WarehouseSummary(id=uuid4(), code="UI", name="Kho fixture")],
        )
        view = shell.transfer_view
        shell.notebook.select(view)
        for page in view.pages.values():
            view.tabs.select(page)
            root.update()
            widgets = [
                view.load_button,
                view.selector,
                view.evidence_entry,
                view.reason_entry,
                view.retry_button,
                *view.buttons.values(),
            ]
            for widget in widgets:
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.close()
        shell.finish()
        assert view.variables == {}
    finally:
        if not shell.closed:
            shell.close()
            shell.finish()
