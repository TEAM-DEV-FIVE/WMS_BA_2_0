import socket
import threading
import time
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_fulfillment import fulfillment  # noqa: F401
from test_issues import inventory, issuing  # noqa: F401
from test_move_quality_desktop import View, finish_request, wait
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.fulfillment import FulfillmentPresenter
from apps.desktop.views.shell import DesktopShell
from packages.contracts.identity import SessionTokens


def make_presenter(respond):
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="test-access", refresh_token="test-refresh", expires_in=900)
    view = View()
    presenter = FulfillmentPresenter(view, api)
    presenter.reset(uuid4(), uuid4())
    return presenter, api, view


def ack(doc, warehouse):
    return dict(id=doc, number="ISS-TEST", kind="ISSUE", status="APPROVED", version=4, warehouse_id=warehouse,
                request_id=str(uuid4()), entity_kind="pick", entity_id=str(uuid4()), entity_status="OPEN", entity_version=1)


@pytest.mark.parametrize("response", ["FORBIDDEN", "NOT_FOUND", "wrong_scope", "wrong_document", "wrong_kind", "wrong_version", "wrong_status", "wrong_assignee"])
def test_fulfillment_presenter_keeps_exact_pending_after_timeout_and_unconfirmed_retry(response):
    calls, doc, assignee = [], str(uuid4()), str(uuid4())
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["pick.confirm"])
        calls.append((request.content, request.headers["Idempotency-Key"]))
        if len(calls) == 1:
            raise httpx.ReadTimeout("After possible commit")
        if response in {"FORBIDDEN", "NOT_FOUND"}:
            return httpx.Response(403 if response == "FORBIDDEN" else 404, json=dict(code=response, message="Revoked", request_id=str(uuid4())))
        data = ack(doc, presenter.warehouse_id)
        data["assigned_to"] = assignee
        data.update({"wrong_scope": {"warehouse_id": str(uuid4())}, "wrong_document": {"id": str(uuid4())},
                     "wrong_kind": {"entity_kind": "package"}, "wrong_version": {"version": 20},
                     "wrong_status": {"entity_status": "DONE"}, "wrong_assignee": {"assigned_to": str(uuid4())}}[response])
        return httpx.Response(201, json=data)
    presenter, api, view = make_presenter(respond)
    try:
        body = dict(expected_version=3, reason="Giao soạn", assigned_to=assignee, lines=[{"quantity_base": "5"}])
        original = deepcopy(body)
        presenter.command("POST", f"fulfillment/{doc}/picks", body)
        body["lines"][0]["quantity_base"] = "999"
        finish_request(presenter)
        saved = presenter.uncertain
        assert saved[2] == original
        presenter.retry()
        finish_request(presenter)
        assert calls[0] == calls[1] and presenter.uncertain == saved and not view.saved
    finally:
        presenter.close()
        presenter.finish()
        api.close()


@pytest.mark.parametrize("scope_change", ["user", "warehouse", "session", "close"])
def test_fulfillment_presenter_discards_old_scope_and_keeps_ram_command(scope_change):
    started, release = threading.Event(), threading.Event()
    main, doc = threading.get_ident(), str(uuid4())
    def respond(request):
        assert threading.get_ident() != main
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["pick.confirm"])
        started.set()
        assert release.wait(5)
        return httpx.Response(201, json=ack(doc, original_scope[1]))
    presenter, api, view = make_presenter(respond)
    original_scope = presenter.scope
    try:
        presenter.command("POST", f"fulfillment/{doc}/picks", dict(expected_version=3, reason="Pick"))
        future = presenter.pending
        assert started.wait(5)
        assert not presenter.load() and not presenter.command("POST", "fulfillment", {})
        if scope_change == "close":
            presenter.close()
        elif scope_change == "session":
            # API normally serializes session changes; simulate generation drift
            # in the completed response, without blocking its session lock.
            presenter.generation -= 1
        else:
            presenter.reset(uuid4() if scope_change == "user" else original_scope[0],
                            uuid4() if scope_change == "warehouse" else original_scope[1])
        release.set()
        future.result(timeout=5)
        presenter.drain()
        assert not view.saved and original_scope in presenter.commands
        if scope_change in {"user", "warehouse"}:
            assert not presenter.uncertain
            presenter.reset(*original_scope)
            assert presenter.uncertain
    finally:
        release.set()
        presenter.close()
        presenter.finish()
        api.close()


def test_fulfillment_presenter_operation_validates_original_command():
    doc = str(uuid4())
    def respond(request):
        if request.url.path.endswith("permissions"):
            return httpx.Response(200, json=["pick.confirm"])
        if "/operations/" in request.url.path:
            return httpx.Response(200, json=dict(operation_status="COMMITTED", command="fulfillment.pick.create", result=ack(doc, presenter.warehouse_id)))
        raise httpx.ReadTimeout("Lost ACK")
    presenter, api, view = make_presenter(respond)
    try:
        presenter.command("POST", f"fulfillment/{doc}/picks", dict(expected_version=3, reason="Pick"))
        finish_request(presenter)
        presenter.operation()
        finish_request(presenter)
        assert presenter.uncertain is None and len(view.saved) == 1
    finally:
        presenter.close()
        presenter.finish()
        api.close()


@pytest.mark.integration
@pytest.mark.gui
def test_fulfillment_tk_real_http_scan_pack_lost_ack_and_logout(fulfillment):  # noqa: F811
    import tkinter as tk
    f = fulfillment
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
        view, session = shell.fulfillment_view, shell.session_view
        session.username.set("buyer")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(root, lambda: session.presenter.pending is None)
        shell.notebook.select(view)
        def done():
            wait(root, lambda: view.presenter.pending is None and not view.busy)
        view.load_button.invoke()
        done()
        view.table.selection_set(f.doc["id"])
        view.select_document()
        done()
        view.assignee_button.invoke()
        done()
        view.reservation_selector.current(0)
        view.assignee_selector.current(next(i for i, r in enumerate(view.assignees) if r["id"] == str(f.buyer)))
        view.variables["quantity"].set("5")
        view.variables["reason"].set("Giao soạn qua UI")
        # Drop the ACK only after the real HTTP command committed in PostgreSQL.
        original = view.presenter.api.command
        def lose_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise ApiError("TIMEOUT", "Đã gửi, mất ACK")
        view.presenter.api.command = lose_ack
        view.create_button.invoke()
        done()
        assert view.presenter.uncertain and len(f.fulfill_read()["tasks"]) == 1
        assert view.create_button.instate(["disabled"])
        view.presenter.api.command = original
        view.operation_button.invoke()
        done()
        assert not view.presenter.uncertain and len(view.tasks) == 1
        task_id = next(iter(view.tasks))
        view.task_table.selection_set(task_id)
        root.update()
        view.task_selected()
        res = next(iter(view.reservations.values()))
        assert view.scan("location_code", res["location_code"])
        assert view.scan("item_code", res["sku"])
        view.variables["reason"].set("Quét và xác nhận")
        view.scan_entries["trace_code"].focus_force()
        root.update()
        view.scan_entries["trace_code"].event_generate("<Return>")
        done()
        assert view.tasks[task_id]["status"] == "DONE", view.variables["status"].get()
        view.tabs.select(1)
        view.pack_selector.current(0)
        view.variables["pack_quantity"].set("5")
        view.add_button.invoke()
        view.variables["package_code"].set("UI-BOX")
        view.variables["reason"].set("Đóng kiện đã soạn")
        view.package_create.invoke()
        done()
        package_id = next(iter(view.packages))
        view.package_table.selection_set(package_id)
        root.update()
        view.variables["reason"].set("Chốt kiện giao hàng")
        view.package_buttons["seal"].invoke()
        done()
        assert view.packages[package_id]["status"] == "PACKED", view.variables["status"].get()
        assert inventory(f) == (0, 10, 5, 0)
        posted = ok(f.issue_post(view.doc, f.issue_post_body(view.doc, "3")))
        assert posted["status"] == "PARTIAL" and inventory(f) == (1, 7, 2, 3)
        session.logout()
        assert view.doc is None and not view.tasks and not view.packages
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
def test_fulfillment_layout_900_by_690_and_main_thread_cleanup():
    import tkinter as tk
    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        view = shell.fulfillment_view
        shell.notebook.select(view)
        for page in [0, 1]:
            view.tabs.select(page)
            root.update()
            controls = [view.selector, view.load_button, view.reason_entry, view.retry_button, view.operation_button]
            controls += ([view.reservation_selector, view.quantity_entry, *view.scan_entries.values(), *view.pick_buttons.values()] if page == 0
                         else [view.pack_selector, view.code_entry, view.package_create, *view.package_buttons.values()])
            for widget in controls:
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.close()
        shell.finish()
        assert not view.variables
    finally:
        if not shell.closed:
            shell.close()
            shell.finish()
