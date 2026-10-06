from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_orders import ok, orders  # noqa: F401

pytestmark = pytest.mark.integration


def test_period_bootstrap_is_initial_only_and_audited(iam):
    from datetime import date

    from apps.server.bootstrap_period import provision
    from apps.server.domain.errors import DomainError

    wh = iam.warehouse("FIRST")
    period = provision(iam.engine, "FIRST", date(2026, 10, 1), date(2026, 10, 31), "Thiết lập kho mới")
    with pytest.raises(DomainError, match="Kho đã có kỳ"):
        provision(
            iam.engine,
            "FIRST",
            date(2026, 11, 1),
            date(2026, 11, 30),
            "Không được tạo kỳ tiếp bằng bootstrap",
        )
    with iam.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.stock_period WHERE warehouse_id=:id"), {"id": wh}
            ).scalar_one()
            == 1
        )
        audit = c.execute(
            text("SELECT after_data FROM wms.audit_event WHERE entity_id=:id"), {"id": period}
        ).scalar_one()
        assert audit["database_operator"] and audit["status"] == "OPEN"


@pytest.fixture
def receiving(orders):  # noqa: F811
    f = orders
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    f.location = f.master(
        "locations", code="DOCK", name="Cửa nhận", kind="RECEIVING", warehouse_id=str(f.warehouse)
    )
    f.quarantine = f.master(
        "locations", code="QA", name="Cách ly", kind="QUARANTINE", warehouse_id=str(f.warehouse)
    )
    with f.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status) VALUES (:id,:wh,'2026-10-01','2026-10-31','OPEN')"
            ),
            {"id": uuid4(), "wh": f.warehouse},
        )
    f.po = ok(f.decision(f.submit()))
    f.source_line = ok(f.read(f.po))["lines"][0]["id"]
    f.receipt_body = dict(
        source_order_id=f.po["id"],
        business_date="2026-10-02",
        reason="Nhận PO",
        lines=[
            dict(source_line_id=f.source_line, quantity_base="100", destination_location_id=f.location["id"])
        ],
    )

    def create(body=None):
        return f.client.post(
            "/api/v1/receipts",
            json=body or f.receipt_body,
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )

    def approve(body=None):
        return ok(f.decision(ok(f.action(ok(create(body), 201), "submit"))))

    def read(doc):
        return ok(f.read(doc, kind="receipts"))

    def body(doc, qty="40"):
        return dict(
            expected_version=doc["version"],
            execution_key=str(uuid4()),
            reason="Đếm thực nhận",
            lines=[dict(document_line_id=read(doc)["lines"][0]["id"], quantity_base=qty)],
        )

    def post(doc, payload=None, key=None, who="buyer"):
        return f.client.post(
            "/api/v1/receipts/" + doc["id"] + "/post",
            json=payload or body(doc),
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
        )

    f.receipt_create, f.receipt_approve, f.receipt_read, f.post_body, f.post = (
        create,
        approve,
        read,
        body,
        post,
    )
    return f


def totals(f):
    with f.engine.connect() as c:
        return tuple(
            c.execute(text(sql)).scalar_one()
            for sql in [
                "SELECT count(*) FROM wms.inventory_transaction",
                "SELECT count(*) FROM wms.stock_move",
                "SELECT COALESCE(sum(on_hand),0) FROM wms.stock_balance",
                "SELECT count(*) FROM wms.serial_position",
            ]
        )


def test_receipt_partial_complete_replay_lookup_and_ledger(receiving):
    f = receiving
    doc = f.receipt_approve()
    assert totals(f) == (0, 0, 0, 0)
    key, payload = uuid4(), f.post_body(doc)
    first = ok(f.post(doc, payload, key))
    assert first["status"] == first["source_order_status"] == "PARTIAL"
    assert totals(f) == (1, 1, 40, 0)
    assert ok(f.post(doc, payload, key)) == first
    assert ok(f.post(doc, payload)) == first  # execution-key barrier with a different HTTP key
    assert f.post(doc, {**payload, "reason": "Khác"}).json()["code"] == "EXECUTION_MISMATCH"
    operation = ok(f.client.get("/api/v1/operations/" + str(key), headers=f.headers["buyer"]))
    assert operation["request_id"] == first["request_id"]
    assert operation["transaction_id"] == first["transaction_id"]
    assert f.receipt_read(doc)["lines"][0]["remaining_base"] == "60.000000"
    assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "60.000000"
    finished = ok(f.post(first, f.post_body(first, "60")))
    assert finished["status"] == finished["source_order_status"] == "COMPLETED"
    assert totals(f) == (2, 2, 100, 0)
    assert ok(f.post(doc, payload, key)) == first  # immutable old acknowledgement, current resource completed
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(quantity_base) FROM wms.stock_move")).scalar_one() == 100
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM wms.stock_balance WHERE location_id='00000000-0000-4000-8000-000000000201'"
                )
            ).scalar_one()
            == 0
        )


def test_receipt_visibility_own_assignment_and_replay_revocation(receiving):
    f = receiving
    receiver, _ = f.iam.user("other_receiver")
    grant = f.iam.grant(receiver, "RECEIVER", f.warehouse)
    f.headers["other_receiver"] = f.iam.headers(f.iam.login("other_receiver"))
    assert f.receipt_create().status_code == 201
    denied = f.client.post(
        "/api/v1/receipts",
        json=f.receipt_body,
        headers={**f.headers["other_receiver"], "Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code == 404  # PO not assigned
    doc = f.receipt_approve()
    assert f.post(doc, who="manager").status_code == 403  # manager can read/post but not assigned
    payload, key = f.post_body(doc), uuid4()
    ok(f.post(doc, payload, key))
    with f.engine.begin() as c:
        c.execute(
            text(
                "DELETE FROM wms.user_role_grant WHERE user_id=:id AND role_id=(SELECT id FROM wms.role WHERE code='RECEIVER')"
            ),
            {"id": f.buyer},
        )
    assert f.post(doc, payload, key).status_code == 403
    assert f.client.get("/api/v1/operations/" + str(key), headers=f.headers["buyer"]).status_code == 403
    assert (
        f.client.get("/api/v1/operations/" + str(key), headers=f.headers["other_receiver"]).status_code == 404
    )
    assert grant


def test_receipt_approval_snapshot_stale_version_and_rollback(receiving, monkeypatch):
    f = receiving
    draft = ok(f.receipt_create(), 201)
    assert f.post(draft).json()["code"] == "INVALID_STATE"
    submitted = ok(f.action(draft, "submit"))
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.document SET attributes=jsonb_set(attributes,'{receipt_plan,extra}','true') WHERE id=:id"
            ),
            {"id": draft["id"]},
        )
    assert f.decision(submitted).json()["code"] == "STALE_APPROVAL"
    doc = f.receipt_approve()
    assert f.post(doc, {**f.post_body(doc), "expected_version": 1}).json()["code"] == "STALE_VERSION"
    original = f.iam.client.app.state.orders.effects

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after ledger, balance, document, audit and outbox writes")

    monkeypatch.setattr(f.iam.client.app.state.orders, "effects", fail)
    payload, key = f.post_body(doc), uuid4()
    assert f.post(doc, payload, key).status_code == 500
    assert totals(f) == (0, 0, 0, 0)
    assert f.receipt_read(doc)["version"] == doc["version"]
    assert f.client.get("/api/v1/operations/" + str(key), headers=f.headers["buyer"]).status_code == 404
    monkeypatch.setattr(f.iam.client.app.state.orders, "effects", original)
    ok(f.post(doc, payload, key))


def test_receipt_concurrent_orders_cannot_overreceive(receiving):
    f = receiving
    docs = [f.receipt_approve(), f.receipt_approve()]
    bodies = [f.post_body(doc, "80") for doc in docs]
    barrier = Barrier(2)

    def run(index):
        barrier.wait()
        return f.post(docs[index], bodies[index])

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "SOURCE_EXCEEDED"
    assert totals(f) == (1, 1, 80, 0)
    assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "20.000000"


@pytest.mark.parametrize("closed", [False, True])
def test_receipt_period_and_count_lock(receiving, closed):
    f = receiving
    doc = f.receipt_approve()
    with f.engine.begin() as c:
        if closed:
            c.execute(
                text("UPDATE wms.stock_period SET status='CLOSED',closed_by=:user,closed_at=now()"),
                {"user": f.controller},
            )
        else:
            session = uuid4()
            c.execute(
                text(
                    "INSERT INTO wms.count_session(id,number,warehouse_id,status,created_by,version) VALUES (:id,'COUNT',:wh,'DRAFT',:user,1)"
                ),
                {"id": session, "wh": f.warehouse, "user": f.buyer},
            )
            c.execute(
                text("INSERT INTO wms.count_location_lock VALUES (:id,:session,:location,now(),NULL)"),
                {"id": uuid4(), "session": session, "location": f.location["id"]},
            )
    assert f.post(doc).json()["code"] == ("PERIOD_CLOSED" if closed else "LOCATION_FROZEN")
    assert totals(f) == (0, 0, 0, 0)


def tracking_po(f, tracking):
    product = f.master(
        "products",
        sku=tracking,
        name=tracking,
        base_uom_id=f.product["base_uom_id"],
        tracking=tracking,
        expiry_required=tracking == "LOT",
    )
    conversion = ok(
        f.client.get(
            "/api/v1/master/product-uoms", params={"product_id": product["id"]}, headers=f.headers["buyer"]
        )
    )["items"][0]
    po = ok(
        f.create(
            body={
                **f.body,
                "lines": [
                    {**f.body["lines"][0], "product_id": product["id"], "product_uom_id": conversion["id"]}
                ],
            }
        ),
        201,
    )
    po = ok(f.decision(ok(f.action(po, "submit"))))
    line = ok(f.read(po))["lines"][0]
    return product, dict(
        source_order_id=po["id"],
        business_date="2026-10-02",
        reason="Theo dõi lô/serial",
        lines=[dict(source_line_id=line["id"], quantity_base="1", destination_location_id=f.location["id"])],
    )


def test_receipt_lot_expiry_metadata_and_quarantine(receiving):
    f = receiving
    _, body = tracking_po(f, "LOT")
    body["lines"][0]["lot_code"] = "000Lot-a"
    assert f.receipt_create(body).json()["code"] == "LOT_EXPIRY_REQUIRED"
    body["lines"][0].update(expires_on="2026-10-01", manufactured_on="2026-01-01")
    body["business_date"] = "2026-10-01"  # Backdating must not bypass today's expiry.
    doc = f.receipt_approve(body)
    assert f.post(doc, f.post_body(doc, "1")).json()["code"] == "LOT_EXPIRED"
    body["lines"][0]["destination_location_id"] = f.quarantine["id"]
    doc = f.receipt_approve(body)
    ok(f.post(doc, f.post_body(doc, "1")))
    body["lines"][0]["expires_on"] = "2026-10-31"
    doc = f.receipt_approve(body)
    assert f.post(doc, f.post_body(doc, "1")).json()["code"] == "LOT_METADATA_CONFLICT"
    assert totals(f) == (1, 1, 1, 0)


def test_receipt_serial_identity_and_warranty_source(receiving):
    f = receiving
    product, body = tracking_po(f, "SERIAL")
    body["lines"][0]["serial_code"] = "000sn-X"
    doc = f.receipt_approve(body)
    ok(f.post(doc, f.post_body(doc, "1")))
    other = f.receipt_approve(body)
    assert f.post(other, f.post_body(other, "1")).json()["code"] == "SERIAL_ALREADY_PRESENT"
    assert totals(f) == (1, 1, 1, 1)
    with f.engine.connect() as c:
        row = (
            c.execute(
                text("SELECT s.id,s.code FROM wms.serial s WHERE product_id=:id"), {"id": product["id"]}
            )
            .mappings()
            .one()
        )
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    serial = ok(
        f.client.get(
            "/api/v1/serials/" + str(row["id"]) + "/warranty",
            params={"warehouse_id": str(f.warehouse)},
            headers=f.headers["buyer"],
        )
    )
    assert row["code"] == "000sn-X"
    assert serial["receipt_id"] == doc["id"]
    assert serial["supplier_partner_id"] == f.partner["id"]
    assert serial["status"] == "UNKNOWN"


@pytest.mark.parametrize("failures", [1, 3])
def test_receipt_deadlock_retries_whole_transaction_with_same_key(receiving, monkeypatch, failures):
    f = receiving
    doc, key = f.receipt_approve(), uuid4()
    original = f.iam.client.app.state.orders.effects
    attempts = []

    def fail(c, *args, **kwargs):
        original(c, *args, **kwargs)
        attempts.append(1)
        if len(attempts) <= failures:
            c.exec_driver_sql("DO $$ BEGIN RAISE EXCEPTION 'test deadlock' USING ERRCODE='40P01'; END $$")

    monkeypatch.setattr(f.iam.client.app.state.orders, "effects", fail)
    response = f.post(doc, f.post_body(doc), key)
    if failures == 1:
        ok(response)
        assert len(attempts) == 2 and totals(f) == (1, 1, 40, 0)
    else:
        assert response.status_code == 503 and response.json()["retryable"]
        assert len(attempts) == 3 and totals(f) == (0, 0, 0, 0)


def test_receipt_concurrent_same_execution_and_precision_limits(receiving):
    f = receiving
    doc = f.receipt_approve()
    assert f.post(doc, f.post_body(doc, "0.5")).json()["code"] == "INVALID_REFERENCE"
    assert f.post(doc, f.post_body(doc, "101")).json()["code"] == "RECEIPT_EXCEEDED"
    body = f.post_body(doc)
    duplicate = {**body, "lines": body["lines"] * 2}
    assert f.post(doc, duplicate).status_code == 422
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return ok(f.post(doc, body))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1] and totals(f) == (1, 1, 40, 0)


def test_receipt_edit_revision_cancel_and_source_dependency(receiving):
    f = receiving
    doc = ok(f.receipt_create(), 201)
    assert f.action(f.po, "revise").json()["code"] == "DEPENDENT_DOCUMENT"
    edited = ok(
        f.client.put(
            "/api/v1/receipts/" + doc["id"],
            json={
                **f.receipt_body,
                "expected_version": doc["version"],
                "lines": [{**f.receipt_body["lines"][0], "quantity_base": "80"}],
            },
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
    )
    approved = ok(f.decision(ok(f.action(edited, "submit"))))
    revised = ok(f.action(approved, "revise"))
    assert revised["status"] == "DRAFT"
    assert f.receipt_read(revised)["approvals"][0]["status"] == "INVALIDATED"
    approved = ok(f.decision(ok(f.action(revised, "submit"))))
    completed = ok(f.post(approved, f.post_body(approved, "80")))
    assert completed["status"] == "COMPLETED" and completed["source_order_status"] == "PARTIAL"
    assert f.action(completed, "cancel", "manager").status_code == 409
    po = ok(f.read(f.po))
    closed = ok(f.action(po, "close", "manager"))
    assert closed["status"] == "COMPLETED"
    assert ok(f.read(f.po))["lines"][0]["closed_base"] == "20.000000"
    assert totals(f) == (1, 1, 80, 0)


def test_receipt_creation_and_po_cancel_share_the_source_lock(receiving):
    f = receiving
    barrier = Barrier(2)
    def run(action):
        barrier.wait()
        return f.receipt_create() if action == "create" else f.action(f.po, "cancel", "manager")
    with ThreadPoolExecutor(2) as pool:
        created, cancelled = list(pool.map(run, ["create", "cancel"]))
    assert (created.status_code, cancelled.status_code) in {(201, 409), (409, 200)}
    if created.status_code == 201:
        assert cancelled.json()["code"] == "DEPENDENT_DOCUMENT"
    else:
        assert created.json()["code"] == "INVALID_STATE"
    assert totals(f) == (0, 0, 0, 0)


def test_receipt_batch_serial_rollback_and_reconciliation(receiving, monkeypatch):
    from pathlib import Path

    f = receiving
    product, body = tracking_po(f, "SERIAL")
    body["lines"] = [{**body["lines"][0], "serial_code": code} for code in ["001", "002"]]
    doc = f.receipt_approve(body)
    payload = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Nhận nhiều serial",
                   lines=[dict(document_line_id=line["id"], quantity_base="1") for line in f.receipt_read(doc)["lines"]])
    original = f.iam.client.app.state.orders.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("rollback identities and positions")
    key = uuid4()
    monkeypatch.setattr(f.iam.client.app.state.orders, "effects", fail)
    assert f.post(doc, payload, key).status_code == 500
    assert totals(f) == (0, 0, 0, 0)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial WHERE product_id=:id"), {"id": product["id"]}).scalar_one() == 0
    monkeypatch.setattr(f.iam.client.app.state.orders, "effects", original)
    ok(f.post(doc, payload, key))
    assert totals(f) == (1, 2, 2, 2)
    with f.engine.connect() as c:
        root = Path(__file__).resolve().parents[2]
        for name in ["reconcile.sql", "reconcile_ownership.sql"]:
            with c.connection.driver_connection.cursor() as cursor:
                cursor.execute((root / "02_CSDL" / name).read_text())
                while True:
                    if cursor.description:
                        assert cursor.fetchall() == []
                    if not cursor.nextset():
                        break


@pytest.mark.gui
def test_receipt_desktop_create_approve_and_partial_post(receiving):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    f = receiving
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.iam.client.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    root, shell = tk.Tk(), None
    try:
        shell = DesktopShell(
            root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1")
        )
        session, view = shell.session_view, shell.receipt_view

        def wait(condition):
            deadline = time.monotonic() + 8
            while not condition() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert condition(), view.variables["status"].get()

        def login(name):
            session.username.set(name)
            session.password.set("Test-only-password-2026!")
            session.login()
            wait(lambda: len(view.warehouses) == 1)
            view.load()
            wait(lambda: not view.busy and bool(view.permissions))

        login("buyer")
        view.new()
        view.source.current(0)
        view.source_changed()
        wait(lambda: not view.busy and len(view.source_lines) == 1)
        view.location.current(next(i for i, p in enumerate(view.locations) if p["kind"] == "RECEIVING"))
        view.variables["day"].set("2026-10-02")
        view.variables["qty"].set("80")
        view.add_line()
        view.variables["reason"].set("Tạo kế hoạch nhận trên desktop")
        view.action("save")
        wait(lambda: not view.busy and view.doc is not None)
        doc_id = view.doc["id"]
        view.variables["reason"].set("Gửi duyệt nhận")
        view.action("submit")
        wait(lambda: not view.busy and view.doc["status"] == "SUBMITTED")
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        assert view.doc is None and view.lines == []
        login("controller")
        view.presenter.read("receipts", doc_id)
        wait(lambda: not view.busy and view.doc is not None)
        view.variables["reason"].set("Duyệt kế hoạch nhận")
        view.action("approve")
        wait(lambda: not view.busy and view.doc["status"] == "APPROVED")
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        login("buyer")
        view.presenter.read("receipts", doc_id)
        wait(lambda: not view.busy and view.doc is not None)
        view.line_table.selection_set("0")
        root.update()
        view.variables["qty"].set("40")
        view.variables["reason"].set("Đếm và nhận đợt một")
        view.action("post")
        wait(lambda: not view.busy and view.doc["status"] == "PARTIAL")
        assert view.lines[0]["remaining_base"] == "40.000000" and totals(f) == (1, 1, 40, 0)
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        assert view.lines == []
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.gui
def test_process_dies_after_real_server_commit_desktop_recovers_without_second_post(receiving):
    import json
    import socket
    import sqlite3
    import subprocess
    import sys
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    f = receiving
    doc = f.receipt_approve()
    body = f.post_body(doc, "40")
    key = uuid4()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        settings = DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1")
        # A real process dies AFTER the HTTP server committed, BEFORE the local ACK checkpoint.
        script = """
import json, os, sys
from uuid import UUID
from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.local_store.receipt_recovery import ReceiptPostJournal
d = json.load(sys.stdin)
settings = DesktopSettings(api_url=d['api_url'])
api = IdentityClient(settings)
api.login('buyer', 'Test-only-password-2026!')
user = api.me()
journal = ReceiptPostJournal(settings.local_data_dir, settings.api_url)
journal.open(user.id, api.device_id)
send = api.command
def crash_after_commit(*args):
    send(*args)
    os._exit(17)
api.command = crash_after_commit
journal.send_new(api, key=UUID(d['key']), endpoint=d['endpoint'], body=d['body'], context=d['context'])
"""
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps(dict(api_url=settings.api_url,
            key=str(key), endpoint=f"receipts/{doc['id']}/post", body=body,
            context=dict(document_number=doc["number"], warehouse_id=str(f.warehouse)))),
            capture_output=True, text=True, timeout=20)
        assert result.returncode == 17, result.stderr
        assert totals(f) == (1, 1, 40, 0)
        path = next((settings.local_data_dir / "receipts").glob("*.sqlite3"))
        with sqlite3.connect(path) as c:
            assert c.execute("SELECT state FROM pending_operation").fetchone()[0] == "SENDING"
        root = tk.Tk()
        shell = DesktopShell(root, settings)
        session, view = shell.session_view, shell.receipt_view
        recovery = shell.receipt_recovery_view
        calls = []
        api = session.presenter.api
        original = api.command
        def track(*args):
            calls.append(args)
            return original(*args)
        api.command = track
        def wait(condition):
            deadline = time.monotonic() + 8
            while not condition() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert condition(), recovery.status.get()
        session.username.set("buyer")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: view.presenter.recovery_ready and not view.presenter.recovery_busy)
        assert view.presenter.recovery_records[0]["state"] == "UNKNOWN"
        assert view.presenter.recovery_records[0]["payload"] == body
        assert recovery.table.get_children() == (str(key),)
        assert calls == []
        recovery.table.selection_set(str(key))
        recovery.lookup_button.invoke()
        wait(lambda: view.doc is not None and view.doc["status"] == "PARTIAL")
        assert view.presenter.recovery_records[0]["state"] == "COMMITTED"
        assert calls == [] and totals(f) == (1, 1, 40, 0)
        assert view.doc["lines"][0]["remaining_base"] == "60.000000"
        with sqlite3.connect(path) as c:
            ack = json.loads(c.execute("SELECT response FROM pending_operation").fetchone()[0])
        with f.engine.connect() as c:
            server_ack = c.execute(text("SELECT response FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one()
        assert ack["transaction_id"] == server_ack["transaction_id"]
        assert ack["request_id"] == server_ack["request_id"]
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        assert recovery.table.get_children() == () and view.presenter.recovery_records == []
        session.username.set("controller")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: view.presenter.recovery_ready and not view.presenter.recovery_busy)
        assert recovery.table.get_children() == ()
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
