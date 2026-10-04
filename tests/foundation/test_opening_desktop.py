import socket
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from test_openings import inventory, opening, orders, second_warehouse, tracking  # noqa: F401
from test_orders import ok

from apps.desktop.api.client import DesktopSettings

pytestmark = [pytest.mark.integration, pytest.mark.gui]


@pytest.fixture
def opening_ui(opening):  # noqa: F811
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell

    f = opening
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
        view = shell.opening_view
        shell.notebook.select(view)

        def wait(predicate):
            deadline = time.monotonic() + 10
            while not predicate() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.005)
            assert predicate(), view.variables["status"].get()

        def idle():
            wait(lambda: view.presenter.pending is None and not view.busy)

        def login(name):
            session = shell.session_view
            if session.presenter.api._tokens:
                session.logout()
                wait(lambda: session.status.get() == "Đã đăng xuất.")
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            wait(lambda: bool(view.warehouses))
            view.load()
            idle()

        def fill(product_id=None, serial=None):
            view.new()
            view.variables["day"].set("2026-10-02")
            view.variables["reference"].set("BB-KIEM-KE-DA-KY-01")
            view.variables["reason"].set("Nhập tồn đầu kỳ từ desktop")
            index = next(
                i
                for i, p in enumerate(view.catalogs["products"])
                if p["id"] == (product_id or f.product["id"])
            )
            view.product.current(index)
            view.product_changed()
            idle()
            index = next(i for i, p in enumerate(view.catalogs["locations"]) if p["id"] == f.location["id"])
            view.location.current(index)
            view.variables["qty"].set("1" if serial else "10")
            view.variables["serial"].set(serial or "")
            view.add_line()
            assert len(view.lines) == 1

        f.shell, f.view, f.wait, f.idle, f.login_ui, f.fill_ui = shell, view, wait, idle, login, fill
        login("buyer")
        yield f
    finally:
        if shell:
            shell.close()
            shell.finish()
        # The backend fixture contains self-referencing helper closures. Never
        # leave Tk objects in that cycle for a later HTTP worker's GC to free.
        f.shell = f.view = f.wait = f.idle = f.login_ui = f.fill_ui = None
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def action(f, name):
    f.view.variables["reason"].set("Kiểm thử thao tác " + name)
    f.view.action(name)
    f.idle()


def test_opening_gui_lifecycle_stale_sod_timeout_ack_and_reconciliation(opening_ui, monkeypatch):
    f, view = opening_ui, opening_ui.view
    f.fill_ui()
    batch = view.variables["batch"].get()
    action(f, "save")
    assert view.doc["status"] == "DRAFT" and view.doc["batch_key"] == batch
    assert view.variables["status"].get().startswith("SYNCED")
    doc_id = view.doc["id"]
    # Another session updates the same draft before the desktop saves.
    body = {**f.opening_body, "batch_key": batch, "expected_version": view.doc["version"]}
    body["lines"] = [dict(body["lines"][0], quantity_base="12")]
    changed = ok(
        f.client.put(
            "/api/v1/openings/" + doc_id,
            json=body,
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
    )
    action(f, "save")
    assert view.doc["version"] == changed["version"] and "STALE" in view.variables["status"].get()
    assert view.lines[0]["quantity_base"] == "12.000000"
    # Edit a selected line, then save through the real UI and API.
    view.line_table.selection_set("0")
    view.edit_line()
    f.idle()
    view.variables["qty"].set("13")
    view.add_line(replace=True)
    action(f, "save")
    assert view.lines[0]["quantity_base"] == "13.000000"
    action(f, "submit")
    assert "approve" not in view.doc["allowed_actions"] and view.buttons["approve"].instate(["disabled"])
    pending = view.doc["approvals"][-1]
    view.presenter.command(
        "POST",
        "approval-requests/" + pending["id"] + "/decide",
        {"expected_version": view.doc["version"], "reason": "Thử tự duyệt", "decision": "APPROVE"},
        doc_id,
    )
    f.idle()
    assert "SELF_APPROVAL" in view.variables["status"].get()
    f.login_ui("director")
    view.presenter.read(doc_id)
    f.idle()
    assert not view.catalog_ready and not view.buttons["approve"].instate(["disabled"])
    action(f, "approve")
    assert view.doc["status"] == "APPROVED" and "director" in view.variables["history"].get()
    f.login_ui("buyer")
    view.presenter.read(doc_id)
    f.idle()
    api = view.presenter.api
    send, requests = api.client.send, []

    def lose_ack(request, **kwargs):
        response = send(request, **kwargs)  # Real server commit happens first.
        if request.url.path.endswith("/post"):
            assert response.status_code == 200
            requests.append((request.headers["Idempotency-Key"], request.content))
            response.close()
            raise httpx.ReadTimeout("deliberately lost ACK")
        return response

    monkeypatch.setattr(api.client, "send", lose_ack)
    action(f, "post")
    assert inventory(f) == (1, 1, 13, 0)
    assert view.ack is None and view.variables["status"].get().startswith("UNKNOWN")
    command = view.presenter.uncertain
    assert command and command.body["execution_key"]
    assert view.retry_button.instate(["disabled"]) and view.buttons["post"].instate(["disabled"])
    view.presenter.retry()
    assert len(requests) == 1
    view.lookup()
    f.idle()
    assert view.variables["status"].get().startswith("POSTED")
    assert view.doc["status"] == "COMPLETED" and view.doc["batch_key"] == batch
    assert view.presenter.uncertain is None and view.ack["transaction_id"]
    assert "đã ghi đủ" in view.variables["reconciliation"].get() and len(requests) == 1
    with f.engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='opening.post'")).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE event_type='opening.post.v1'")
            ).scalar_one()
            == 1
        )
        for name in ("reconcile.sql", "reconcile_ownership.sql"):
            with c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[2] / "02_CSDL" / name).read_text())
                while True:
                    if cursor.description:
                        assert cursor.fetchall() == []
                    if not cursor.nextset():
                        break
    # A new batch cannot add more stock to an active warehouse.
    f.fill_ui()
    action(f, "save")
    assert "OPENING_CLOSED" in view.variables["status"].get() and inventory(f) == (1, 1, 13, 0)


def test_opening_gui_limits_duplicate_batch_and_serial_scope(opening_ui):
    f, view = opening_ui, opening_ui.view
    # Changing the search text before Next must start the new search at page 1.
    view.cursors["products"] = f.product["id"]
    view.variables["product_query"].set(f.product["sku"])
    view.search("products", "product", more=True)
    f.idle()
    assert [p["id"] for p in view.catalogs["products"]] == [f.product["id"]]
    f.fill_ui()
    line = deepcopy(view.lines[0])
    view.lines = [deepcopy(line) for _ in range(201)]
    action(f, "save")
    assert "1–200" in view.variables["status"].get() and view.presenter.uncertain is None
    assert inventory(f) == (0, 0, 0, 0)
    view.lines = [line]
    action(f, "save")
    batch = view.doc["batch_key"]
    f.fill_ui()
    view.variables["batch"].set(batch)
    action(f, "save")
    assert "DUPLICATE_BATCH" in view.variables["status"].get()
    assert view.variables["batch"].get() == batch and view.lines[0]["quantity_base"] == "10"
    # Serial already posted in another warehouse is rejected by the real server.
    product, body = tracking(f, "SERIAL", serial_code="000Aa-X")
    other_body = second_warehouse(f, body)
    ok(f.open_post(f.open_approve(other_body)))
    view.load()
    f.idle()
    f.fill_ui(product["id"], "000Aa-X")
    view.add_line()
    assert "serial lặp" in view.variables["status"].get() and len(view.lines) == 1
    action(f, "save")
    draft = view.doc
    approved = ok(f.decision(ok(f.action(draft, "submit")), "director"))
    view.presenter.read(approved["id"])
    f.idle()
    action(f, "post")
    assert "SERIAL_ALREADY_PRESENT" in view.variables["status"].get()
    assert view.ack is None and inventory(f) == (1, 1, 1, 1)
    # A warehouse outside the actor's grants cannot be listed or edited.
    outside = f.iam.warehouse("NO-GRANT")
    view.presenter.reset(f.buyer, outside)
    view.presenter.load()
    f.idle()
    assert not view.doc and not view.lines and not view.permissions
    assert not view.table.get_children()


def test_opening_gui_lost_create_response_lookup_and_retry_same_batch(opening_ui, monkeypatch):
    f, view = opening_ui, opening_ui.view
    f.fill_ui()
    api = view.presenter.api
    send, requests = api.client.send, []

    def lose_once(request, **kwargs):
        response = send(request, **kwargs)
        if request.method == "POST" and request.url.path == "/api/v1/openings":
            requests.append((request.headers["Idempotency-Key"], request.content))
            if len(requests) == 1:
                assert response.status_code == 201
                response.close()
                raise httpx.ReadTimeout("lost draft result")
        return response

    monkeypatch.setattr(api.client, "send", lose_once)
    batch = view.variables["batch"].get()
    action(f, "save")
    assert view.presenter.uncertain and "UNKNOWN" in view.variables["status"].get()
    view.new()
    assert view.variables["batch"].get() == batch
    view.lookup()
    f.idle()
    assert "Máy chủ:" in view.variables["status"].get() and view.presenter.uncertain.checked
    view.presenter.retry()
    f.idle()
    assert requests[0] == requests[1] and view.doc["batch_key"] == batch
    assert view.presenter.uncertain is None
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.opening_document")).scalar_one() == 1
    f.shell.session_view.logout()
    assert not view.doc and not view.lines and not view.permissions
    f.wait(lambda: f.shell.session_view.status.get() == "Đã đăng xuất.")


def test_opening_gui_lot_and_uncommitted_post_lookup_then_exact_retry(opening_ui, monkeypatch):
    f, view = opening_ui, opening_ui.view
    product, _ = tracking(f, "LOT", lot_code="000Lot-X", expires_on="2027-01-01")
    view.load()
    f.idle()
    f.fill_ui()
    view.lines = []
    index = next(i for i, p in enumerate(view.catalogs["products"]) if p["id"] == product["id"])
    view.product.current(index)
    view.product_changed()
    f.idle()
    view.variables["lot"].set("000Lot-X")
    view.variables["manufactured"].set("2026-01-01")
    view.variables["expiry"].set("2027-01-01")
    view.add_line()
    action(f, "save")
    doc = view.doc
    assert doc["plan"][0]["lot_code"] == "000Lot-X"
    assert doc["plan"][0]["manufactured_on"] == "2026-01-01"
    approved = ok(f.decision(ok(f.action(doc, "submit")), "director"))
    view.presenter.read(approved["id"])
    f.idle()
    send, requests = view.presenter.api.client.send, []

    def lose_before_send(request, **kwargs):
        if request.url.path.endswith("/post"):
            requests.append((request.headers["Idempotency-Key"], request.content))
            if len(requests) == 1:
                raise httpx.ConnectTimeout("request never reached server")
        return send(request, **kwargs)

    monkeypatch.setattr(view.presenter.api.client, "send", lose_before_send)
    action(f, "post")
    assert view.presenter.uncertain and inventory(f) == (0, 0, 0, 0)
    view.lookup()
    f.idle()
    assert view.presenter.uncertain.checked and view.ack is None
    assert "UNKNOWN" in view.variables["status"].get()
    view.presenter.retry()
    f.idle()
    assert requests[0] == requests[1] and len(requests) == 2
    assert view.variables["status"].get().startswith("POSTED") and inventory(f) == (1, 1, 10, 0)
