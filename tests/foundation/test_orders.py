from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from packages.contracts.traceability import COMPANY_OWNER

pytestmark = pytest.mark.integration


@pytest.fixture
def orders(iam):
    buyer, _ = iam.user("buyer")
    manager, _ = iam.user("manager")
    controller, _ = iam.user("controller")
    warehouse = iam.warehouse("ORDERS")
    iam.grant(buyer, "MASTER_DATA")
    iam.grant(buyer, "BUYER", warehouse)
    iam.grant(buyer, "SELLER", warehouse)
    iam.grant(manager, "WAREHOUSE_MANAGER", warehouse)
    control_grant = iam.grant(controller, "CONTROLLER", warehouse)

    class Fixture:
        def __init__(self):
            self.iam, self.client, self.engine = iam, iam.client, iam.engine
            self.buyer, self.manager, self.controller = buyer, manager, controller
            self.warehouse, self.control_grant = warehouse, control_grant
            self.headers = {name: iam.headers(iam.login(name)) for name in ["buyer", "manager", "controller"]}
            unit = self.master("uoms", code="EA", name="Chiếc", decimal_places=0)
            self.product = self.master(
                "products", sku="ORD-01", name="Thiết bị", base_uom_id=unit["id"], tracking="NONE"
            )
            self.partner = self.master(
                "partners", code="NCC", name="Nhà cung cấp / khách hàng", is_supplier=True, is_customer=True
            )
            self.conversion = self.client.get(
                "/api/v1/master/product-uoms",
                params={"product_id": self.product["id"]},
                headers=self.headers["buyer"],
            ).json()["items"][0]
            self.body = dict(
                warehouse_id=str(warehouse),
                partner_id=self.partner["id"],
                business_date="2026-10-02",
                reason="Kiểm thử đơn hàng",
                lines=[
                    dict(
                        product_id=self.product["id"],
                        product_uom_id=self.conversion["id"],
                        quantity="100",
                        owner_id=str(COMPANY_OWNER),
                    )
                ],
            )

        def master(self, resource, **body):
            r = self.client.post(
                "/api/v1/master/" + resource,
                json={"reason": "Fixture danh mục", **body},
                headers={**self.headers["buyer"], "Idempotency-Key": str(uuid4())},
            )
            assert r.status_code == 201, r.text
            return r.json()

        def create(self, kind="purchase-orders", body=None, key=None):
            return self.client.post(
                "/api/v1/" + kind,
                json=body or self.body,
                headers={**self.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
            )

        def read(self, doc, who="buyer", kind="purchase-orders"):
            return self.client.get("/api/v1/" + kind + "/" + doc["id"], headers=self.headers[who])

        def action(self, doc, action, who="buyer", key=None, **extra):
            return self.client.post(
                "/api/v1/documents/" + doc["id"] + "/" + action,
                json={"expected_version": doc["version"], "reason": "Kiểm thử " + action, **extra},
                headers={**self.headers[who], "Idempotency-Key": str(key or uuid4())},
            )

        def decision(self, doc, who="controller", decision="APPROVE", key=None):
            return self.client.post(
                "/api/v1/approval-requests/" + doc["approval_request_id"] + "/decide",
                json={
                    "expected_version": doc["version"],
                    "reason": "Quyết định kiểm thử",
                    "decision": decision,
                },
                headers={**self.headers[who], "Idempotency-Key": str(key or uuid4())},
            )

        def submit(self):
            r = self.create()
            assert r.status_code == 201, r.text
            r = self.action(r.json(), "submit")
            assert r.status_code == 200, r.text
            return r.json()

    return Fixture()


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["purchase-orders", "sales-orders"])
def test_order_lifecycle_snapshot_and_no_inventory_effects(orders, kind):
    doc = ok(orders.create(kind), 201)
    assert doc["status"] == "DRAFT"
    view = ok(orders.read(doc, kind=kind))
    assert view["lines"][0]["remaining_base"] == "100.000000"
    assert view["lines"][0]["owner_id"] == str(COMPANY_OWNER)
    assert "reference_unit_price" not in view["lines"][0]
    submitted = ok(orders.action(doc, "submit"))
    approved = ok(orders.decision(submitted))
    assert approved["status"] == "APPROVED"
    view = ok(orders.read(approved, kind=kind))
    assert view["approvals"][0]["steps"][0]["decider_name"] == "controller"
    revised = ok(orders.action(approved, "revise"))
    assert revised["status"] == "DRAFT"
    assert ok(orders.read(revised, kind=kind))["approvals"][0]["status"] == "INVALIDATED"
    changed = ok(
        orders.client.put(
            "/api/v1/" + kind + "/" + doc["id"],
            json={
                **orders.body,
                "expected_version": revised["version"],
                "lines": [{**orders.body["lines"][0], "quantity": "120"}],
            },
            headers={**orders.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
    )
    assert ok(orders.read(changed, kind=kind))["lines"][0]["base_quantity"] == "120.000000"
    resubmitted = ok(orders.action(changed, "submit"))
    assert resubmitted["approval_request_id"] != submitted["approval_request_id"]
    assert orders.decision(submitted).status_code == 409
    with orders.engine.connect() as c:
        for table in ["stock_move", "stock_balance", "inventory_transaction", "reservation"]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 0
        snapshots = (
            c.execute(text("SELECT content_snapshot FROM wms.approval_request ORDER BY document_version"))
            .scalars()
            .all()
        )
        assert snapshots[0]["lines"][0]["quantity"] == "100.000000"
        assert snapshots[1]["lines"][0]["quantity"] == "120.000000"


def test_self_approval_and_submitter_sod_even_with_manager_role(orders):
    orders.iam.grant(orders.buyer, "WAREHOUSE_MANAGER", orders.warehouse)
    doc = orders.submit()
    assert orders.decision(doc, "buyer").json()["code"] == "SELF_APPROVAL"
    assert "approve" not in ok(orders.read(doc))["allowed_actions"]
    assert ok(orders.decision(doc, "manager"))["status"] == "APPROVED"


def test_assignment_read_filter_and_edit_ownership(orders):
    receiver, _ = orders.iam.user("receiver")
    other_buyer, _ = orders.iam.user("buyer2")
    orders.iam.grant(receiver, "RECEIVER", orders.warehouse)
    orders.iam.grant(other_buyer, "BUYER", orders.warehouse)
    orders.headers["receiver"] = orders.iam.headers(orders.iam.login("receiver"))
    orders.headers["buyer2"] = orders.iam.headers(orders.iam.login("buyer2"))
    doc = ok(orders.create(), 201)
    assert orders.read(doc, "receiver").status_code == 404

    def listing():
        return orders.client.get(
            "/api/v1/purchase-orders",
            params={"warehouse_id": str(orders.warehouse)},
            headers=orders.headers["receiver"],
        )

    assert ok(listing())["items"] == []
    assert orders.action(doc, "submit", "buyer2").status_code == 403
    doc = ok(orders.action(doc, "assignments", "manager", user_ids=[str(receiver), str(other_buyer)]))
    assert ok(orders.read(doc, "receiver"))["id"] == doc["id"]
    assert len(ok(listing())["items"]) == 1
    submitted = ok(orders.action(doc, "submit", "buyer2"))
    orders.iam.grant(other_buyer, "CONTROLLER", orders.warehouse)
    assert orders.decision(submitted, "buyer2").json()["code"] == "SELF_APPROVAL"
    assert orders.action(submitted, "assignments", "manager", user_ids=[]).status_code == 409
    assert orders.decision(submitted, "receiver").status_code == 403


def test_reject_resubmit_and_cancel_history(orders):
    submitted = orders.submit()
    rejected = ok(orders.decision(submitted, decision="REJECT"))
    assert rejected["status"] == "REJECTED"
    submitted2 = ok(orders.action(rejected, "submit"))
    cancelled = ok(orders.action(submitted2, "cancel", "manager"))
    assert cancelled["status"] == "CANCELLED"
    cancelled_line = ok(orders.read(cancelled))["lines"][0]
    assert cancelled_line["remaining_base"] == "0.000000"
    assert cancelled_line["closed_base"] == "100.000000"
    history = ok(orders.read(cancelled))["approvals"]
    assert [r["status"] for r in history] == ["REJECTED", "INVALIDATED"]
    assert orders.action(cancelled, "submit").status_code == 409
    assert orders.decision(submitted2).status_code == 409


def test_two_decisions_or_two_edits_only_one_commits(orders):
    submitted = orders.submit()
    barrier = Barrier(2)

    def decide(who):
        barrier.wait(timeout=5)
        return orders.decision(submitted, who, decision="APPROVE" if who == "manager" else "REJECT")

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(decide, ["manager", "controller"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    doc = ok(orders.create(), 201)

    def edit(qty):
        barrier.wait(timeout=5)
        return orders.client.put(
            "/api/v1/purchase-orders/" + doc["id"],
            json={
                **orders.body,
                "expected_version": doc["version"],
                "lines": [{**orders.body["lines"][0], "quantity": qty}],
            },
            headers={**orders.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, ["50", "60"]))
    assert sorted(r.status_code for r in results) == [200, 409]


def test_idempotency_duplicate_create_decision_and_permission_revocation(orders):
    key = uuid4()
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=5)
        return orders.create(key=key)

    with ThreadPoolExecutor(2) as pool:
        rs = list(pool.map(create, range(2)))
    assert rs[0].status_code == rs[1].status_code == 201
    assert rs[0].json() == rs[1].json()
    assert (
        orders.create(body={**orders.body, "reason": "Khác"}, key=key).json()["code"]
        == "IDEMPOTENCY_MISMATCH"
    )
    submitted = ok(orders.action(rs[0].json(), "submit"))
    key = uuid4()
    saved = ok(orders.decision(submitted, key=key))
    assert ok(orders.decision(submitted, key=key)) == saved
    with orders.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": orders.control_grant}
        )
    assert orders.decision(submitted, key=key).status_code == 404


def test_order_validation_decimal_source_and_warehouse_scopes(orders):
    for quantity in ["1.5", "0", 100, "100000000000000"]:
        r = orders.create(body={**orders.body, "lines": [{**orders.body["lines"][0], "quantity": quantity}]})
        assert r.status_code in [409, 422], r.text
    assert (
        orders.create(
            body={**orders.body, "lines": [{**orders.body["lines"][0], "factor_snapshot": "10"}]}
        ).status_code
        == 422
    )
    other = orders.iam.warehouse("HIDDEN")
    assert orders.create(body={**orders.body, "warehouse_id": str(other)}).status_code == 404
    assert (
        orders.client.get(
            "/api/v1/purchase-orders", params={"warehouse_id": str(other)}, headers=orders.headers["buyer"]
        ).status_code
        == 404
    )
    assert (
        orders.create(
            body={**orders.body, "lines": [{**orders.body["lines"][0], "product_uom_id": str(uuid4())}]}
        ).status_code
        == 409
    )
    assert (
        orders.create(
            body={**orders.body, "lines": [{**orders.body["lines"][0], "owner_id": str(uuid4())}]}
        ).status_code
        == 409
    )


def test_list_keyset_state_filter_and_wrong_kind(orders):
    docs = [ok(orders.create(), 201) for _ in range(3)]
    after = None
    ids = []
    for _ in range(3):
        params = {"warehouse_id": str(orders.warehouse), "status": "DRAFT", "limit": 1}
        if after:
            params["after"] = after
        page = ok(
            orders.client.get("/api/v1/purchase-orders", params=params, headers=orders.headers["buyer"])
        )
        ids += [d["id"] for d in page["items"]]
        after = page["next_after"]
    assert set(ids) == {d["id"] for d in docs} and after is None
    assert orders.read(docs[0], kind="sales-orders").status_code == 404


def test_approval_snapshot_tampering_and_immutable_decision(orders):
    submitted = orders.submit()
    with orders.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document_line SET quantity=101,base_quantity=101 WHERE document_id=:id"),
            {"id": submitted["id"]},
        )
    assert orders.decision(submitted).json()["code"] == "STALE_APPROVAL"
    with pytest.raises(DatabaseError), orders.engine.begin() as c:
        c.execute(text("UPDATE wms.approval_request SET content_snapshot='{}'"))
    with orders.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document_line SET quantity=100,base_quantity=100 WHERE document_id=:id"),
            {"id": submitted["id"]},
        )
    ok(orders.decision(submitted))
    with pytest.raises(DatabaseError), orders.engine.begin() as c:
        c.execute(text("UPDATE wms.approval_step SET comment='Sửa quyết định cũ'"))


def test_transaction_failure_after_outbox_rolls_back_order_and_approval(orders, monkeypatch):
    service = orders.client.app.state.orders
    original = service.effects

    def fail(*args):
        original(*args)
        raise RuntimeError("fixture after outbox")

    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert orders.create().status_code == 500
    with orders.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.document")).scalar_one() == 0
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE event_type LIKE 'order.%'")
            ).scalar_one()
            == 0
        )
    submitted = orders.submit()
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert orders.decision(submitted).status_code == 500
    view = ok(orders.read(submitted))
    assert view["status"] == "SUBMITTED" and view["version"] == submitted["version"]
    assert view["approvals"][0]["steps"][0]["status"] == "PENDING"


def fulfill_fixture(orders, doc, qty=80):
    """SQL-only posted fixture: not evidence for the future receiving/issue posting API."""
    view = ok(orders.read(doc))
    line = view["lines"][0]
    child, child_line, txn, move, item, source, dest = (uuid4() for _ in range(7))
    with orders.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wms.location(id,code,name,kind,is_active) VALUES (:id,:code,'Ngoài kho','EXTERNAL',true)"
            ),
            {"id": source, "code": source.hex},
        )
        c.execute(
            text(
                "INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:id,:wh,:code,'Nhận','RECEIVING',true)"
            ),
            {"id": dest, "wh": orders.warehouse, "code": dest.hex},
        )
        c.execute(
            text("INSERT INTO wms.stock_item(id,product_id,owner_id) VALUES (:id,:product,:owner)"),
            {"id": item, "product": orders.product["id"], "owner": COMPANY_OWNER},
        )
        c.execute(
            text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,partner_id,business_date,created_by,created_at,version,attributes)
            VALUES (:id,:number,'RECEIPT','COMPLETED',:wh,:partner,'2026-10-02',:actor,now(),1,'{}')"""),
            {
                "id": child,
                "number": child.hex,
                "wh": orders.warehouse,
                "partner": orders.partner["id"],
                "actor": orders.buyer,
            },
        )
        c.execute(
            text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,source_line_id)
            VALUES (:id,:doc,1,:product,:uom,:qty,1,:qty,:owner,:source)"""),
            {
                "id": child_line,
                "doc": child,
                "product": orders.product["id"],
                "uom": line["uom_id"],
                "qty": qty,
                "owner": COMPANY_OWNER,
                "source": line["id"],
            },
        )
        c.execute(
            text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by)
            VALUES (:id,:doc,:key,'RECEIVE','2026-10-02',now(),:actor)"""),
            {"id": txn, "doc": child, "key": uuid4(), "actor": orders.buyer},
        )
        c.execute(
            text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
            VALUES (:id,:txn,:line,:item,:source,:dest,:qty,:uom)"""),
            {
                "id": move,
                "txn": txn,
                "line": child_line,
                "item": item,
                "source": source,
                "dest": dest,
                "qty": qty,
                "uom": line["uom_id"],
            },
        )
        c.execute(
            text("UPDATE wms.document SET status='PARTIAL',version=version+1 WHERE id=:id"), {"id": doc["id"]}
        )
    return dict(
        child=child,
        child_line=child_line,
        txn=txn,
        move=move,
        item=item,
        source=source,
        dest=dest,
        qty=qty,
        uom=line["uom_id"],
    )


def test_partial_quantity_close_preserves_posted_history_and_blocks_cancel(orders):
    doc = ok(orders.decision(orders.submit()))
    fulfill_fixture(orders, doc)
    view = ok(orders.read(doc))
    assert view["lines"][0]["posted_base"] == "80.000000"
    assert view["lines"][0]["remaining_base"] == "20.000000"
    assert orders.action(view, "cancel", "manager").status_code == 409
    closed = ok(orders.action(view, "close", "manager"))
    view = ok(orders.read(closed))
    assert view["status"] == "COMPLETED"
    assert view["lines"][0]["closed_base"] == "20.000000"
    assert view["lines"][0]["posted_base"] == "80.000000"
    assert view["lines"][0]["remaining_base"] == "0.000000"
    assert orders.action(closed, "revise").status_code == 409
    with orders.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.stock_move")).scalar_one() == 1


@pytest.mark.parametrize("reservation_on_child", [False, True])
def test_reversal_is_removed_once_from_remaining_and_open_reservation_blocks_close(
    orders, reservation_on_child
):
    doc = ok(orders.decision(orders.submit()))
    f = fulfill_fixture(orders, doc)
    with orders.engine.begin() as c:
        txn = uuid4()
        c.execute(
            text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by,reverses_transaction_id)
            VALUES (:id,:doc,:key,'REVERSE','2026-10-02',now(),:actor,:reversed)"""),
            {"id": txn, "doc": f["child"], "key": uuid4(), "actor": orders.buyer, "reversed": f["txn"]},
        )
        c.execute(
            text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id,reverses_move_id)
            VALUES (:id,:txn,:line,:item,:source,:dest,:qty,:uom,:reversed)"""),
            {
                "id": uuid4(),
                "txn": txn,
                "line": f["child_line"],
                "item": f["item"],
                "source": f["dest"],
                "dest": f["source"],
                "qty": 80,
                "uom": f["uom"],
                "reversed": f["move"],
            },
        )
    view = ok(orders.read(doc))
    assert (
        view["lines"][0]["remaining_base"] == "100.000000" and view["lines"][0]["posted_base"] == "0.000000"
    )
    with orders.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.reservation(id,line_id,stock_item_id,location_id,quantity,consumed,released,created_by)
            VALUES (:id,:line,:item,:location,1,0,0,:actor)"""),
            {
                "id": uuid4(),
                "line": f["child_line"] if reservation_on_child else view["lines"][0]["id"],
                "item": f["item"],
                "location": f["dest"],
                "actor": orders.buyer,
            },
        )
    assert orders.action(view, "close", "manager").json()["code"] == "RESERVATION_OPEN"


def test_two_step_policy_preserves_snapshot_and_enforces_different_approvers(orders):
    with orders.engine.begin() as c:
        policy = c.execute(
            text("SELECT id FROM wms.approval_policy WHERE document_kind='PO' AND is_active")
        ).scalar_one()
        # Test-only policy; no runtime policy-edit API is exposed.
        c.execute(
            text("UPDATE wms.approval_policy_step SET alternative_role_id=NULL WHERE policy_id=:id"),
            {"id": policy},
        )
        c.execute(
            text("""INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id)
            SELECT :id,:policy,2,id FROM wms.role WHERE code='CONTROLLER'"""),
            {"id": uuid4(), "policy": policy},
        )
    submitted = orders.submit()
    assert orders.decision(submitted, "controller").status_code == 403
    pending = ok(orders.decision(submitted, "manager"))
    assert pending["status"] == "SUBMITTED" and pending["version"] == submitted["version"] + 1
    orders.iam.grant(orders.manager, "CONTROLLER", orders.warehouse)
    assert orders.decision(pending, "manager").json()["code"] == "SELF_APPROVAL"
    with orders.engine.begin() as c:
        c.execute(text("UPDATE wms.approval_policy SET is_active=false WHERE id=:id"), {"id": policy})
    assert ok(orders.decision(pending, "controller"))["status"] == "APPROVED"


@pytest.mark.gui
def test_order_desktop_create_stale_form_submit_approve_and_logout(orders):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(orders.client.app, access_log=False, log_level="warning"))
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

        def wait(condition):
            deadline = time.monotonic() + 8
            while not condition() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert condition(), shell.order_view.variables["status"].get()

        session, view = shell.session_view, shell.order_view
        session.username.set("buyer")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: len(view.warehouses) == 1)
        view.load()
        wait(lambda: len(view.products) == 1 and not view.busy)
        view.new()
        view.product.current(0)
        view.product_changed()
        wait(lambda: len(view.conversions) == 1 and not view.busy)
        view.variables["qty"].set("100")
        view.add_line()
        view.variables["reason"].set("Tạo PO qua desktop")
        view.action("save")
        wait(lambda: view.doc is not None and not view.busy)
        doc = view.doc.copy()
        assert doc["status"] == "DRAFT" and doc["lines"][0]["base_quantity"] == "100.000000"
        # A second operator saved the same draft; the old screen must keep its unsaved input on 409.
        ok(
            orders.client.put(
                "/api/v1/purchase-orders/" + doc["id"],
                json={**orders.body, "expected_version": doc["version"]},
                headers={**orders.headers["buyer"], "Idempotency-Key": str(uuid4())},
            )
        )
        view.lines[0]["quantity"] = "70"
        view.variables["reason"].set("Giữ nội dung khi stale")
        view.action("save")
        wait(lambda: not view.busy)
        assert view.lines[0]["quantity"] == "70" and view.doc["version"] == doc["version"]
        assert "Nội dung nhập vẫn được giữ" in view.variables["status"].get()
        view.presenter.read(view.path, doc["id"])
        wait(lambda: not view.busy and view.doc["version"] == 2)
        view.variables["reason"].set("Gửi kiểm tra")
        view.action("submit")
        wait(lambda: not view.busy and view.doc["status"] == "SUBMITTED")
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        assert view.doc is None and view.lines == []
        session.username.set("controller")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: len(view.warehouses) == 1)
        view.load()
        wait(lambda: not view.busy and len(view.table.get_children()) == 1)
        view.presenter.read(view.path, doc["id"])
        wait(lambda: not view.busy and view.doc is not None)
        assert "approve" in view.doc["allowed_actions"]
        view.variables["reason"].set("Duyệt qua desktop")
        view.action("approve")
        wait(lambda: not view.busy and view.doc["status"] == "APPROVED")
        assert "controller" in view.variables["history"].get()
        session.logout()
        assert view.doc is None and view.lines == []
        wait(lambda: session.status.get() == "Đã đăng xuất.")
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_edit_does_not_erase_legacy_price_fields_and_snapshot_covers_attributes(orders):
    doc = ok(orders.create(), 201)
    with orders.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document_line SET reference_unit_price=123 WHERE document_id=:id"),
            {"id": doc["id"]},
        )
    response = orders.client.put(
        "/api/v1/purchase-orders/" + doc["id"],
        json={**orders.body, "expected_version": doc["version"]},
        headers={**orders.headers["buyer"], "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 409 and response.json()["code"] == "UNSUPPORTED_ORDER_FIELDS"
    with orders.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT reference_unit_price FROM wms.document_line WHERE document_id=:id"),
                {"id": doc["id"]},
            ).scalar_one()
            == 123
        )
    submitted = ok(orders.action(doc, "submit"))
    with orders.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document SET attributes=CAST(:value AS jsonb) WHERE id=:id"),
            {"id": doc["id"], "value": '{"fixture":"changed"}'},
        )
    assert orders.decision(submitted).json()["code"] == "STALE_APPROVAL"
