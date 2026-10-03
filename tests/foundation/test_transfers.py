from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_issues import reconcile as reconcile_inventory
from test_openings import opening, orders  # noqa: F401
from test_orders import ok

pytestmark = pytest.mark.integration


def reconcile(f):
    from pathlib import Path

    reconcile_inventory(f)
    raw = f.engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(
                (Path(__file__).resolve().parents[2] / "02_CSDL/reconcile_transfers.sql").read_text()
            )
            while True:
                if cursor.description:
                    assert cursor.fetchall() == []
                if not cursor.nextset():
                    break
    finally:
        raw.close()


@pytest.fixture
def transfer(opening):  # noqa: F811
    f = opening
    f.destination = f.iam.warehouse("TRANSFER-DEST-FIXTURE")
    for user, role in [(f.manager, "WAREHOUSE_MANAGER"), (f.controller, "CONTROLLER")]:
        f.iam.grant(user, role, f.destination)
    f.sender, _ = f.iam.user("sender")
    f.receiver, _ = f.iam.user("receiver")
    f.receiver2, _ = f.iam.user("receiver2")
    f.iam.grant(f.sender, "PICKER", f.warehouse)
    f.iam.grant(f.receiver, "RECEIVER", f.destination)
    f.iam.grant(f.receiver2, "RECEIVER", f.destination)
    for name in ["sender", "receiver", "receiver2"]:
        f.headers[name] = f.iam.headers(f.iam.login(name))
    f.arrival = f.master(
        "locations",
        code="TRF-RECEIVING",
        name="Nhận chuyển fixture",
        kind="RECEIVING",
        warehouse_id=str(f.destination),
    )
    f.damaged = f.master(
        "locations",
        code="TRF-QUARANTINE",
        name="Cách ly fixture",
        kind="QUARANTINE",
        warehouse_id=str(f.destination),
    )
    with f.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status) VALUES (:id,:wh,'2026-10-01','2026-10-31','OPEN')"
            ),
            {"id": uuid4(), "wh": f.destination},
        )

    def request(method, path, body=None, who="manager", key=None):
        return f.client.request(
            method,
            "/api/v1/" + path,
            json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
        )

    def seed(body=None):
        b = deepcopy(body or f.opening_body)
        if body is None:
            b["lines"][0]["quantity_base"] = "20"
        ok(f.open_post(f.open_approve(b)))
        with f.engine.connect() as c:
            return str(c.execute(text("SELECT id FROM wms.stock_item ORDER BY id LIMIT 1")).scalar_one())

    def create(stock, qty="20", body=None):
        return request(
            "POST",
            "transfers",
            body
            or dict(
                warehouse_id=str(f.warehouse),
                destination_warehouse_id=str(f.destination),
                business_date="2026-10-02",
                reason="Chuyển theo kế hoạch",
                lines=[dict(stock_item_id=stock, source_location_id=f.location["id"], quantity_base=qty)],
            ),
        )

    def approve(stock, qty="20"):
        draft = ok(create(stock, qty), 201)
        assigned = ok(
            f.action(
                draft, "assignments", "manager", user_ids=[str(f.sender), str(f.receiver), str(f.receiver2)]
            )
        )
        return ok(f.decision(ok(f.action(assigned, "submit", "manager"))))

    def dispatch(doc, payload=None, key=None, who="sender"):
        return request("POST", "transfers/" + doc["id"] + "/dispatch", payload or post_body(doc), who, key)

    def post_body(doc):
        return dict(
            expected_version=doc["version"],
            execution_key=str(uuid4()),
            reason="Xác nhận hàng thực tế",
            evidence_ref="Biên bản soạn/giao/nhận đã ký TRF-001",
        )

    def read(doc, who="manager"):
        return request("GET", "transfers/" + doc["id"], who=who)

    def receive_body(doc, qty="18", destination=None, disposition="GOOD"):
        view = ok(read(doc))
        return {
            **post_body(doc),
            "business_date": "2026-10-02",
            "lines": [
                dict(
                    dispatch_move_id=view["sources"][0]["dispatch_move_id"],
                    destination_location_id=destination or f.arrival["id"],
                    quantity_base=qty,
                    disposition=disposition,
                )
            ],
        }

    def receive(doc, payload=None, key=None, who="receiver"):
        return request("POST", "transfers/" + doc["id"] + "/receive", payload or receive_body(doc), who, key)

    f.tr_request, f.tr_seed, f.tr_create, f.tr_approve, f.tr_dispatch = (
        request,
        seed,
        create,
        approve,
        dispatch,
    )
    f.tr_post_body, f.tr_read, f.tr_receive_body, f.tr_receive = post_body, read, receive_body, receive
    return f


def test_transfer_twenty_eighteen_two_scope_replay_history_and_reconcile(transfer):
    f = transfer
    doc = f.tr_approve(f.tr_seed())
    # Source controller can inspect this transfer, but has no destination grant.
    assert f.tr_read(doc, "buyer").status_code == 200
    assert f.tr_dispatch(doc, who="buyer").status_code == 403
    body, key = f.tr_post_body(doc), uuid4()
    sent = ok(f.tr_dispatch(doc, body, key))
    assert ok(f.tr_dispatch(doc, body, key)) == sent == ok(f.tr_dispatch(doc, body))
    assert ok(f.tr_read(sent, "receiver"))["plan"][0]["source_location_id"] is None
    receive, receive_key = f.tr_receive_body(sent), uuid4()
    arrived = ok(f.tr_receive(sent, receive, receive_key))
    assert ok(f.tr_receive(sent, receive, receive_key)) == arrived == ok(f.tr_receive(sent, receive))
    view = ok(f.tr_read(arrived))
    assert view["status"] == "PARTIAL"
    assert view["sources"][0]["remaining_base"] == "2.000000"
    assert ok(f.tr_request("GET", f"transfers/operations/{receive_key}", who="receiver")) == arrived
    assert f.tr_request("GET", f"transfers/operations/{receive_key}", who="sender").status_code == 404
    with f.engine.connect() as c:
        balances = dict(c.execute(text("SELECT location_id,on_hand FROM wms.stock_balance")).all())
        from uuid import UUID

        assert balances[UUID(view["transit_location_id"])] == 2
        assert balances[UUID(f.arrival["id"])] == 18
        assert sum(balances.values()) == 20
    finished = ok(f.tr_receive(arrived, f.tr_receive_body(arrived, "2")))
    assert finished["status"] == "COMPLETED"
    assert ok(f.tr_read(finished))["sources"][0]["remaining_base"] == "0.000000"
    assert len(ok(f.tr_request("GET", f"transfers/{doc['id']}/history"))["items"]) == 3
    reconcile(f)


def test_transfer_reparent_between_discovery_and_locks_rejects_unlocked_path(transfer):
    from sqlalchemy import event

    f = transfer
    doc = f.tr_approve(f.tr_seed())
    zone = f.master(
        "locations", code="NEW-ZONE", name="Zone mới", kind="GROUP", warehouse_id=str(f.warehouse)
    )
    rack = f.master(
        "locations",
        code="NEW-RACK",
        name="Rack mới",
        kind="GROUP",
        warehouse_id=str(f.warehouse),
        parent_id=zone["id"],
    )
    moved = False

    def reparent(conn, cursor, statement, parameters, context, executemany):
        nonlocal moved
        if not moved and "SELECT * FROM wms.location WHERE id=" in statement and "FOR UPDATE" in statement:
            moved = True
            # A second real transaction commits before posting acquires location locks.
            with f.engine.begin() as other:
                other.execute(
                    text("UPDATE wms.location SET parent_id=:rack,version=version+1 WHERE id=:bin"),
                    {"rack": rack["id"], "bin": f.location["id"]},
                )

    body, key = f.tr_post_body(doc), uuid4()
    event.listen(f.engine, "before_cursor_execute", reparent)
    try:
        rejected = f.tr_dispatch(doc, body, key)
    finally:
        event.remove(f.engine, "before_cursor_execute", reparent)
    assert moved and rejected.status_code == 409
    assert rejected.json()["code"] == "INVALID_TREE"
    assert ok(f.tr_read(doc))["sources"] == []
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 20
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='DISPATCH'")
            ).scalar_one()
            == 0
        )
    assert ok(f.tr_dispatch(doc, body, key))["status"] == "PARTIAL"
    reconcile(f)


def missing_loss(f, arrived):
    source = ok(f.tr_read(arrived))["sources"][0]
    evidence = ok(
        f.tr_request(
            "POST",
            f"transfers/{arrived['id']}/discrepancies",
            dict(
                expected_version=arrived["version"],
                reason="Thiếu thực nhận",
                dispatch_move_id=source["dispatch_move_id"],
                kind="MISSING",
                quantity_base="2",
                evidence_ref="Biên bản thiếu hai chiếc, hai kho xác minh",
            ),
            "receiver",
        )
    )
    loss = ok(
        f.tr_request(
            "POST",
            f"transfers/{arrived['id']}/adjustments",
            dict(
                expected_version=evidence["version"],
                reason="Đề nghị xử lý mất sau đối soát",
                discrepancy_id=evidence["discrepancy_id"],
                quantity_base="2",
                business_date="2026-10-02",
            ),
        ),
        201,
    )
    return evidence, loss


def test_transfer_missing_stays_in_transit_until_separate_loss_approved(transfer):
    f = transfer
    sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    arrived = ok(f.tr_receive(sent))
    evidence, loss = missing_loss(f, arrived)
    assert ok(f.tr_read(evidence))["sources"][0]["remaining_base"] == "2.000000"
    assert f.action(evidence, "close", "manager").json()["code"] == "INVALID_STATE"
    assert f.action(evidence, "cancel", "manager").status_code == 409
    assert (
        f.tr_request(
            "POST", f"transfers/{loss['id']}/loss-post", f.tr_post_body(loss), "controller"
        ).status_code
        == 409
    )
    submitted = ok(f.action(loss, "submit", "manager"))
    assert f.decision(submitted, "buyer").status_code == 403  # Controller in source only.
    approved = ok(f.decision(submitted))
    body, key = f.tr_post_body(approved), uuid4()
    posted = ok(f.tr_request("POST", f"transfers/{loss['id']}/loss-post", body, "controller", key))
    assert ok(f.tr_request("POST", f"transfers/{loss['id']}/loss-post", body, "controller", key)) == posted
    assert ok(f.tr_request("POST", f"transfers/{loss['id']}/loss-post", body, "controller")) == posted
    view = ok(f.tr_read(evidence))
    assert view["status"] == "COMPLETED"
    assert (
        view["sources"][0]["received_base"],
        view["sources"][0]["lost_base"],
        view["sources"][0]["remaining_base"],
    ) == ("18.000000", "2.000000", "0.000000")
    assert view["adjustments"][0]["id"] == loss["id"]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 18
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM wms.stock_balance b JOIN wms.location l ON l.id=b.location_id WHERE l.kind='LOSS'"
                )
            ).scalar_one()
            == 0
        )
    reconcile(f)


def test_transfer_concurrent_receivers_cannot_consume_same_remaining(transfer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    f = transfer
    sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    arrived = ok(f.tr_receive(sent))
    barrier = Barrier(2)
    bodies = [f.tr_receive_body(arrived, "2") for _ in range(2)]

    def run(index):
        barrier.wait(5)
        return f.tr_receive(arrived, bodies[index], who=["receiver", "receiver2"][index])

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(run, [0, 1]))
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert ok(f.tr_read(arrived))["sources"][0]["remaining_base"] == "0.000000"
    reconcile(f)


def test_transfer_cancel_races_dispatch_without_orphan_transit(transfer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    f = transfer
    doc = f.tr_approve(f.tr_seed())
    barrier = Barrier(2)

    def run(index):
        barrier.wait(5)
        return f.tr_dispatch(doc) if index else f.action(doc, "cancel", "manager")

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(run, [0, 1]))
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    view = ok(f.tr_read(doc))
    assert view["status"] in {"CANCELLED", "PARTIAL"}
    assert len(view["sources"]) == int(view["status"] == "PARTIAL")
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 20
    reconcile(f)


@pytest.mark.parametrize("side", ["source", "destination"])
def test_transfer_loss_requires_both_periods_open(transfer, side):
    f = transfer
    arrived = ok(f.tr_receive(ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))))
    evidence, loss = missing_loss(f, arrived)
    approved = ok(f.decision(ok(f.action(loss, "submit", "manager"))))
    warehouse = f.warehouse if side == "source" else f.destination
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": warehouse}
        )
    body, key = f.tr_post_body(approved), uuid4()
    reply = f.tr_request("POST", f"transfers/{loss['id']}/loss-post", body, "controller", key)
    assert reply.status_code == 409 and reply.json()["code"] == "PERIOD_CLOSED"
    assert ok(f.tr_read(evidence))["sources"][0]["remaining_base"] == "2.000000"
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.stock_period SET status='OPEN' WHERE warehouse_id=:id"), {"id": warehouse})
    ok(f.tr_request("POST", f"transfers/{loss['id']}/loss-post", body, "controller", key))
    reconcile(f)


def test_transfer_loss_races_arrival_without_double_consumption(transfer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    f = transfer
    arrived = ok(f.tr_receive(ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))))
    evidence, loss = missing_loss(f, arrived)
    approved = ok(f.decision(ok(f.action(loss, "submit", "manager"))))
    barrier = Barrier(2)

    def run(index):
        barrier.wait(5)
        if index:
            return f.tr_receive(evidence, f.tr_receive_body(evidence, "2"))
        return f.tr_request(
            "POST", f"transfers/{loss['id']}/loss-post", f.tr_post_body(approved), "controller"
        )

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(run, [0, 1]))
    assert sorted(r.status_code for r in replies) == [200, 409]
    source = ok(f.tr_read(evidence))["sources"][0]
    from decimal import Decimal

    assert Decimal(source["received_base"]) + Decimal(source["lost_base"]) == 20
    assert source["remaining_base"] == "0.000000"
    reconcile(f)


def test_transfer_opposite_routes_lock_product_without_share_upgrade_deadlock(transfer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    from sqlalchemy import event

    f = transfer
    stock = f.tr_seed()
    first = f.tr_approve(stock)
    for user, role in [(f.buyer, "CONTROLLER"), (f.director, "DIRECTOR"), (f.sender, "PICKER")]:
        f.iam.grant(user, role, f.destination)
    zone = f.master(
        "locations", code="OPPOSITE-Z", name="Zone", kind="GROUP", warehouse_id=str(f.destination)
    )
    rack = f.master(
        "locations",
        code="OPPOSITE-R",
        name="Rack",
        kind="GROUP",
        warehouse_id=str(f.destination),
        parent_id=zone["id"],
    )
    bin_ = f.master(
        "locations",
        code="OPPOSITE-B",
        name="Bin",
        kind="STORAGE",
        warehouse_id=str(f.destination),
        parent_id=rack["id"],
    )
    opening_body = deepcopy(f.opening_body)
    opening_body.update(warehouse_id=str(f.destination), batch_key=str(uuid4()))
    opening_body["lines"][0].update(quantity_base="20", destination_location_id=bin_["id"])
    ok(f.open_post(f.open_approve(opening_body)))
    second = ok(
        f.tr_create(
            stock,
            body=dict(
                warehouse_id=str(f.destination),
                destination_warehouse_id=str(f.warehouse),
                business_date="2026-10-02",
                reason="Luồng ngược độc lập",
                lines=[dict(stock_item_id=stock, source_location_id=bin_["id"], quantity_base="20")],
            ),
        ),
        201,
    )
    second = ok(f.action(second, "assignments", "manager", user_ids=[str(f.sender)]))
    second = ok(f.decision(ok(f.action(second, "submit", "manager"))))
    barrier, guard, seen = Barrier(2), Lock(), set()

    def synchronize(conn, cursor, statement, parameters, context, executemany):
        if "SELECT id FROM wms.product WHERE id=" in statement and "FOR UPDATE" in statement:
            with guard:
                fresh = id(conn) not in seen
                seen.add(id(conn))
            if fresh:
                barrier.wait(10)

    event.listen(f.engine, "before_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(f.tr_dispatch, [first, second]))
    finally:
        event.remove(f.engine, "before_cursor_execute", synchronize)
    assert len(seen) == 2
    assert [ok(reply)["status"] for reply in replies] == ["PARTIAL", "PARTIAL"]
    reconcile(f)


@pytest.mark.parametrize("phase", ["dispatch", "receive", "loss"])
def test_transfer_outbox_failure_rolls_back_stock_serial_audit_and_ack(transfer, phase):
    from sqlalchemy import event

    f = transfer
    doc = f.tr_approve(f.tr_seed())
    if phase != "dispatch":
        doc = ok(f.tr_dispatch(doc))
    if phase == "loss":
        _, loss = missing_loss(f, ok(f.tr_receive(doc)))
        doc = ok(f.decision(ok(f.action(loss, "submit", "manager"))))
    body = f.tr_receive_body(doc) if phase == "receive" else f.tr_post_body(doc)
    key = uuid4()
    tables = [
        "stock_move",
        "inventory_transaction",
        "stock_balance",
        "audit_event",
        "outbox_event",
        "idempotency_record",
        "serial_position",
    ]

    def snapshot():
        with f.engine.connect() as c:
            return [
                c.execute(
                    text(f"SELECT row_to_json(t)::text FROM wms.{table} t ORDER BY row_to_json(t)::text")
                )
                .scalars()
                .all()
                for table in tables
            ]

    before = snapshot()

    def fail(c, cursor, statement, parameters, context, many):
        if "INSERT INTO wms.outbox_event" in statement:
            raise RuntimeError("transfer failpoint")

    def post():
        if phase == "dispatch":
            return f.tr_dispatch(doc, body, key)
        if phase == "receive":
            return f.tr_receive(doc, body, key)
        return f.tr_request("POST", f"transfers/{doc['id']}/loss-post", body, "controller", key)

    event.listen(f.engine, "before_cursor_execute", fail)
    try:
        response = post()
        assert response.status_code == 500, response.text
    finally:
        event.remove(f.engine, "before_cursor_execute", fail)
    assert snapshot() == before
    ok(post())
    reconcile(f)


@pytest.mark.parametrize("phase", ["dispatch", "receive"])
@pytest.mark.parametrize("guard", ["period", "freeze"])
def test_transfer_period_and_freeze_are_atomic(transfer, phase, guard):
    f = transfer
    doc = f.tr_approve(f.tr_seed())
    if phase == "receive":
        doc = ok(f.tr_dispatch(doc))
    warehouse = f.warehouse if phase == "dispatch" else f.destination
    location = f.location["id"] if phase == "dispatch" else f.arrival["id"]
    with f.engine.begin() as c:
        before = c.execute(text("SELECT count(*) FROM wms.stock_move")).scalar_one()
        if guard == "period":
            c.execute(
                text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": warehouse}
            )
        else:
            session = uuid4()
            c.execute(
                text(
                    "INSERT INTO wms.count_session(id,warehouse_id,number,status,frozen_at,created_by,version) VALUES (:id,:wh,:code,'FROZEN',now(),:actor,1)"
                ),
                {"id": session, "wh": warehouse, "code": str(session), "actor": f.manager},
            )
            c.execute(
                text(
                    "INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES (:id,:session,:location,now())"
                ),
                {"id": uuid4(), "session": session, "location": location},
            )
    response = f.tr_dispatch(doc) if phase == "dispatch" else f.tr_receive(doc)
    assert response.json()["code"] == ("PERIOD_CLOSED" if guard == "period" else "LOCATION_FROZEN"), (
        response.text
    )
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.stock_move")).scalar_one() == before


def test_transfer_validates_route_source_excess_permission_and_current_replay(transfer):
    f = transfer
    stock = f.tr_seed()
    assert (
        f.tr_create(
            stock,
            body=dict(
                warehouse_id=str(f.warehouse),
                destination_warehouse_id=str(f.warehouse),
                business_date="2026-10-02",
                reason="Sai kho",
                lines=[dict(stock_item_id=stock, source_location_id=f.location["id"], quantity_base="20")],
            ),
        ).status_code
        == 409
    )
    large = f.tr_approve(stock, "21")
    assert f.tr_dispatch(large).json()["code"] == "INSUFFICIENT_STOCK"
    doc = f.tr_approve(stock)
    assert f.tr_dispatch(doc, who="receiver").status_code == 403
    assert f.decision(doc, "manager").status_code == 409  # Already decided, no bypass.
    sent = ok(f.tr_dispatch(doc))
    wrong = f.tr_receive_body(sent)
    wrong["lines"][0]["dispatch_move_id"] = str(uuid4())
    assert f.tr_receive(sent, wrong).json()["code"] == "SOURCE_MISMATCH"
    assert f.tr_receive(sent, f.tr_receive_body(sent, "21")).json()["code"] == "SOURCE_EXCEEDED"
    assert f.tr_receive(sent, f.tr_receive_body(sent, destination=f.location["id"])).status_code == 409
    assert (
        f.tr_receive(
            sent, f.tr_receive_body(sent, destination=f.arrival["id"], disposition="DAMAGED")
        ).status_code
        == 409
    )
    body, key = f.tr_receive_body(sent), uuid4()
    ok(f.tr_receive(sent, body, key))
    assert f.tr_receive(sent, {**body, "reason": "Đổi payload"}, key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.tr_receive(sent, {**body, "reason": "Đổi payload"}).json()["code"] == "EXECUTION_MISMATCH"
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": f.receiver}
        )
    assert f.tr_receive(sent, body, key).status_code in {403, 404}
    assert f.tr_request("GET", f"transfers/operations/{key}", who="receiver").status_code in {403, 404}
    reconcile(f)


def test_transfer_reserved_company_stock_and_consignment_identity_are_not_borrowed(transfer):
    from test_consignments import agreement

    f = transfer
    owner, contract = agreement(f)
    body = deepcopy(f.opening_body)
    body["lines"][0]["quantity_base"] = "20"
    body["lines"].append(
        {**body["lines"][0], "quantity_base": "5", "owner_id": owner["id"], "consignment_id": contract["id"]}
    )
    f.tr_seed(body)
    with f.engine.connect() as c:
        items = {
            str(r.owner_id): str(r.id) for r in c.execute(text("SELECT id,owner_id FROM wms.stock_item"))
        }
    assert f.tr_create(items[owner["id"]], "5").json()["code"] == "OWNERSHIP_UNSUPPORTED"
    from packages.contracts.traceability import COMPANY_OWNER

    stock = items[str(COMPANY_OWNER)]
    f.iam.grant(f.buyer, "PICKER", f.warehouse)
    so = ok(f.decision(ok(f.action(ok(f.create("sales-orders"), 201), "submit"))))
    line = ok(f.read(so, kind="sales-orders"))["lines"][0]
    issue = ok(
        f.tr_request(
            "POST",
            "issues",
            dict(
                source_order_id=so["id"],
                business_date="2026-10-02",
                reason="Giữ cho khách",
                lines=[dict(source_line_id=line["id"], quantity_base="5")],
            ),
            "buyer",
        ),
        201,
    )
    issue = ok(f.decision(ok(f.action(issue, "submit"))))
    issue_line = ok(f.tr_request("GET", f"issues/{issue['id']}", who="buyer"))["lines"][0]["id"]
    plan = ok(
        f.tr_request(
            "GET",
            f"issues/{issue['id']}/reservation-plan?document_line_id={issue_line}&quantity_base=5",
            who="buyer",
        )
    )
    ok(
        f.tr_request(
            "POST",
            f"issues/{issue['id']}/reservations/reserve",
            dict(
                expected_version=plan["version"],
                reason="Giữ đúng owner",
                lines=[
                    {k: r[k] for k in ["document_line_id", "stock_item_id", "location_id", "quantity_base"]}
                    for r in plan["lines"]
                ],
            ),
            "buyer",
        )
    )
    assert f.tr_dispatch(f.tr_approve(stock, "16")).json()["code"] == "INSUFFICIENT_STOCK"
    ok(f.tr_dispatch(f.tr_approve(stock, "15")))
    with f.engine.begin() as c:
        assert c.execute(text("SELECT sum(reserved) FROM wms.stock_balance")).scalar_one() == 5
    reconcile(f)


@pytest.mark.parametrize("tracking", ["LOT", "SERIAL"])
def test_transfer_preserves_tracking_and_rejects_expiry_or_bad_serial_position(transfer, tracking):
    from test_openings import tracking as tracked_opening

    f = transfer
    product, body = tracked_opening(
        f,
        tracking,
        **(
            {"lot_code": "TRF-LOT", "expires_on": "2026-10-30"}
            if tracking == "LOT"
            else {"serial_code": "000TrfSerial"}
        ),
    )
    stock = f.tr_seed(body)
    doc = f.tr_approve(stock, "1")
    if tracking == "LOT":
        f.iam.advance(31 * 86400)
        # Renew sessions after time travel; expiry is server business date, never payload backdate.
        f.headers["sender"] = f.iam.headers(f.iam.login("sender"))
        assert f.tr_dispatch(doc).json()["code"] == "LOT_EXPIRED"
        f.iam.advance(-31 * 86400)
        f.headers["sender"] = f.iam.headers(f.iam.login("sender"))
    else:
        with f.engine.begin() as c:
            c.execute(
                text("UPDATE wms.serial_position SET location_id=:where"), {"where": f.quarantine["id"]}
            )
        assert f.tr_dispatch(doc).json()["code"] == "SERIAL_POSITION_CONFLICT"
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.serial_position SET location_id=:where"), {"where": f.location["id"]})
    sent = ok(f.tr_dispatch(doc))
    arrived = ok(f.tr_receive(sent, f.tr_receive_body(sent, "1", f.damaged["id"], "DAMAGED")))
    view = ok(f.tr_read(arrived))
    assert view["plan"][0]["stock_item_id"] == stock
    assert (view["plan"][0]["lot_code"] if tracking == "LOT" else view["plan"][0]["serial_code"]) == (
        "TRF-LOT" if tracking == "LOT" else "000TrfSerial"
    )
    assert view["sources"][0]["received_base"] == "1.000000"
    if tracking == "SERIAL":
        with f.engine.connect() as c:
            from uuid import UUID

            assert c.execute(text("SELECT location_id FROM wms.serial_position")).scalar_one() == UUID(
                f.damaged["id"]
            )
            assert c.execute(text("SELECT count(*) FROM wms.serial_warranty_record")).scalar_one() == 0
    reconcile(f)


def test_transfer_arrival_quality_putaway_and_warehouse_boundary_projection(transfer):
    from decimal import Decimal

    f = transfer
    arrived = ok(f.tr_receive(ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))))
    sources = ok(f.tr_request("GET", f"quality/sources?warehouse_id={f.destination}"))["items"]
    assert len(sources) == 1 and sources[0]["source_location_id"] == f.arrival["id"]
    source = sources[0]
    ok(
        f.tr_request(
            "POST",
            f"quality/sources/{source['id']}/decide",
            dict(
                expected_version=source["version"],
                accepted_base="18",
                rejected_base="0",
                reason="Kiểm định hàng nhận chuyển",
            ),
        )
    )
    decision = ok(f.tr_request("GET", f"quality/sources/{source['id']}"))["items"][0]
    zone = f.master(
        "locations", code="TRF-ZONE", name="Zone fixture", kind="GROUP", warehouse_id=str(f.destination)
    )
    rack = f.master(
        "locations",
        code="TRF-RACK",
        name="Rack fixture",
        kind="GROUP",
        warehouse_id=str(f.destination),
        parent_id=zone["id"],
    )
    bin_ = f.master(
        "locations",
        code="TRF-BIN",
        name="Bin fixture",
        kind="STORAGE",
        warehouse_id=str(f.destination),
        parent_id=rack["id"],
    )
    draft = ok(
        f.tr_request(
            "POST",
            "moves",
            dict(
                warehouse_id=str(f.destination),
                business_date="2026-10-02",
                reason="Cất sau nhận chuyển",
                lines=[
                    dict(
                        stock_item_id=source["stock_item_id"],
                        source_location_id=f.arrival["id"],
                        destination_location_id=bin_["id"],
                        quantity_base="18",
                        quality_decision_id=decision["id"],
                    )
                ],
            ),
            who="receiver",
        ),
        201,
    )
    move = ok(f.decision(ok(f.action(draft, "submit", "receiver"))))
    ok(
        f.tr_request(
            "POST",
            f"moves/{move['id']}/post",
            dict(expected_version=move["version"], execution_key=str(uuid4()), reason="Cất hàng đã đạt"),
            who="receiver",
        )
    )
    stock = ok(f.tr_request("GET", f"moves/stock?warehouse_id={f.destination}"))["items"]
    assert sum(Decimal(r["available_base"]) for r in stock) == 18
    assert all(r["source_kind"] != "TRANSIT" for r in stock)
    # R02 boundary: destination arrival is +18; the internal putaway contributes zero.
    with f.engine.connect() as c:
        delta = c.execute(
            text("""SELECT sum((CASE WHEN dst.warehouse_id=:wh THEN m.quantity_base ELSE 0 END)
            -(CASE WHEN src.warehouse_id=:wh THEN m.quantity_base ELSE 0 END)) FROM wms.stock_move m
            JOIN wms.location src ON src.id=m.source_location_id JOIN wms.location dst ON dst.id=m.destination_location_id"""),
            {"wh": f.destination},
        ).scalar_one()
        assert delta == 18
    assert ok(f.tr_read(arrived))["sources"][0]["remaining_base"] == "2.000000"
    reconcile(f)


def test_transfer_edit_invalidation_sod_unassigned_scope_and_stale_snapshot(transfer):
    f = transfer
    stock = f.tr_seed()
    draft = ok(f.tr_create(stock), 201)
    submitted = ok(f.action(draft, "submit", "manager"))
    assert f.decision(submitted, "manager").json()["code"] == "SELF_APPROVAL"
    approved = ok(f.decision(submitted))
    assert f.tr_read(approved, "receiver").status_code == 404  # Not assigned.
    assert f.tr_dispatch(approved, who="sender").status_code == 404
    revised = ok(f.action(approved, "revise", "manager"))
    body = dict(
        warehouse_id=str(f.warehouse),
        destination_warehouse_id=str(f.destination),
        business_date="2026-10-02",
        reason="Đổi lượng trước gửi",
        expected_version=revised["version"],
        lines=[dict(stock_item_id=stock, source_location_id=f.location["id"], quantity_base="19")],
    )
    changed = ok(f.tr_request("PUT", f"transfers/{draft['id']}", body))
    assert ok(f.tr_read(changed))["approvals"][0]["status"] == "INVALIDATED"
    approved = ok(f.decision(ok(f.action(changed, "submit", "manager"))))
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document SET business_date=business_date+1 WHERE id=:id"), {"id": draft["id"]}
        )
    assert f.tr_dispatch(approved, who="manager").json()["code"] == "STALE_APPROVAL"


def test_transfer_rejects_authentic_legacy_item_after_upgrade(empty_database, monkeypatch):
    from conftest import iam as iam_fixture

    from apps.server.infrastructure import migrations
    from packages.contracts.traceability import UNCLASSIFIED_OWNER

    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:5])
        migrations.migrate(empty_database)
    ids = {name: uuid4() for name in ["warehouse", "zone", "rack", "bin", "unit", "product", "item"]}
    with empty_database.begin() as c:
        for sql in [
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'LEGACY-TRF','Legacy transfer fixture',true)",
            "INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:zone,:warehouse,'LEGACY-Z','Zone','GROUP',true)",
            "INSERT INTO wms.location(id,warehouse_id,parent_id,code,name,kind,is_active) VALUES (:rack,:warehouse,:zone,'LEGACY-R','Rack','GROUP',true)",
            "INSERT INTO wms.location(id,warehouse_id,parent_id,code,name,kind,is_active) VALUES (:bin,:warehouse,:rack,'LEGACY-B','Bin','STORAGE',true)",
            "INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:unit,'LEGACY-U','Unit',0)",
            "INSERT INTO wms.product(id,sku,name,base_uom_id,tracking,expiry_required,is_active,version,attributes) VALUES (:product,'LEGACY-TRF-P','Legacy',:unit,'NONE',false,true,1,'{}')",
            "INSERT INTO wms.stock_item VALUES (:item,:product,NULL,NULL)",
        ]:
            c.execute(text(sql), ids)
    migrations.migrate(empty_database)
    with empty_database.connect() as c:
        assert (
            c.execute(text("SELECT owner_id FROM wms.stock_item WHERE id=:item"), ids).scalar_one()
            == UNCLASSIFIED_OWNER
        )
    # Compose the existing real API fixtures on this upgraded DB, without disabling any trigger.
    session = iam_fixture.__wrapped__(empty_database)
    iam = next(session)
    try:
        f = transfer.__wrapped__(opening.__wrapped__(orders.__wrapped__(iam)))
        f.iam.grant(f.manager, "WAREHOUSE_MANAGER", ids["warehouse"])
        response = f.tr_create(
            str(ids["item"]),
            body=dict(
                warehouse_id=str(ids["warehouse"]),
                destination_warehouse_id=str(f.destination),
                business_date="2026-10-02",
                reason="Không tự đổi chủ legacy",
                lines=[
                    dict(
                        stock_item_id=str(ids["item"]), source_location_id=str(ids["bin"]), quantity_base="1"
                    )
                ],
            ),
        )
        assert response.status_code == 409 and response.json()["code"] == "OWNERSHIP_UNSUPPORTED"
        with empty_database.connect() as c:
            assert (
                c.execute(text("SELECT count(*) FROM wms.document WHERE kind='TRANSFER'")).scalar_one() == 0
            )
            assert (
                c.execute(text("SELECT owner_id FROM wms.stock_item WHERE id=:item"), ids).scalar_one()
                == UNCLASSIFIED_OWNER
            )
    finally:
        session.close()


def test_transfer_serial_warranty_source_and_receive_rollback(transfer):
    from sqlalchemy import event

    f = transfer
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    product = f.master(
        "products",
        sku="TRF-WARRANTY",
        name="Serial transfer",
        base_uom_id=f.product["base_uom_id"],
        tracking="SERIAL",
    )
    unit = ok(f.tr_request("GET", f"master/product-uoms?product_id={product['id']}", who="buyer"))["items"][0]
    body = deepcopy(f.body)
    body["lines"][0].update(product_id=product["id"], product_uom_id=unit["id"], quantity="1")
    po = ok(f.decision(ok(f.action(ok(f.create(body=body), 201), "submit"))))
    source = ok(f.read(po))["lines"][0]["id"]
    dock = f.master(
        "locations",
        code="TRF-PO-DOCK",
        name="Nguồn receipt fixture",
        kind="RECEIVING",
        warehouse_id=str(f.warehouse),
    )
    receipt = ok(
        f.tr_request(
            "POST",
            "receipts",
            dict(
                source_order_id=po["id"],
                business_date="2026-10-02",
                reason="Nhận serial có bảo hành",
                lines=[
                    dict(
                        source_line_id=source,
                        quantity_base="1",
                        destination_location_id=dock["id"],
                        serial_code="000TransferWarranty",
                    )
                ],
            ),
            "buyer",
        ),
        201,
    )
    receipt = ok(f.decision(ok(f.action(receipt, "submit"))))
    line = ok(f.tr_request("GET", f"receipts/{receipt['id']}", who="buyer"))["lines"][0]["id"]
    ok(
        f.tr_request(
            "POST",
            f"receipts/{receipt['id']}/post",
            dict(
                expected_version=receipt["version"],
                execution_key=str(uuid4()),
                reason="Nhận serial",
                lines=[dict(document_line_id=line, quantity_base="1")],
            ),
            "buyer",
        )
    )
    source = ok(f.tr_request("GET", f"quality/sources?warehouse_id={f.warehouse}"))["items"][0]
    ok(
        f.tr_request(
            "POST",
            f"quality/sources/{source['id']}/decide",
            dict(
                expected_version=source["version"],
                accepted_base="1",
                rejected_base="0",
                reason="Kiểm định đạt",
            ),
        )
    )
    decision = ok(f.tr_request("GET", f"quality/sources/{source['id']}"))["items"][0]
    move = ok(
        f.tr_request(
            "POST",
            "moves",
            dict(
                warehouse_id=str(f.warehouse),
                business_date="2026-10-02",
                reason="Cất serial",
                lines=[
                    dict(
                        stock_item_id=source["stock_item_id"],
                        source_location_id=dock["id"],
                        destination_location_id=f.location["id"],
                        quantity_base="1",
                        quality_decision_id=decision["id"],
                    )
                ],
            ),
            who="buyer",
        ),
        201,
    )
    move = ok(f.decision(ok(f.action(move, "submit", "buyer"))))
    ok(
        f.tr_request(
            "POST",
            f"moves/{move['id']}/post",
            dict(expected_version=move["version"], execution_key=str(uuid4()), reason="Cất serial đã đạt"),
            who="buyer",
        )
    )
    with f.engine.connect() as c:
        serial = c.execute(text("SELECT id FROM wms.serial")).scalar_one()
    ok(
        f.tr_request(
            "POST",
            f"serials/{serial}/warranty-records",
            dict(
                expected_version=0,
                receipt_move_id=source["id"],
                starts_on="2026-10-02",
                ends_on="2027-10-02",
                evidence_ref="Phiếu bảo hành gốc",
                reason="Lưu chứng cứ gốc",
            ),
        ),
        201,
    )
    before = ok(f.tr_request("GET", f"serials/{serial}/warranty?warehouse_id={f.warehouse}"))
    sent = ok(f.tr_dispatch(f.tr_approve(source["stock_item_id"], "1")))
    payload, key = f.tr_receive_body(sent, "1"), uuid4()

    def fail(c, cursor, statement, parameters, context, many):
        if "INSERT INTO wms.outbox_event" in statement:
            raise RuntimeError("Serial arrival rollback")

    event.listen(f.engine, "before_cursor_execute", fail)
    try:
        assert f.tr_receive(sent, payload, key).status_code == 500
    finally:
        event.remove(f.engine, "before_cursor_execute", fail)
    with f.engine.connect() as c:
        from uuid import UUID

        assert c.execute(text("SELECT location_id FROM wms.serial_position")).scalar_one() == UUID(
            ok(f.tr_read(sent))["transit_location_id"]
        )
    ok(f.tr_receive(sent, payload, key))
    after = ok(f.tr_request("GET", f"serials/{serial}/warranty?warehouse_id={f.destination}"))
    assert after["receipt_move_id"] == before["receipt_move_id"] == source["id"]
    assert after["receipt_id"] == before["receipt_id"] == receipt["id"]
    assert after["warranty_evidence_ref"] == "Phiếu bảo hành gốc"
    reconcile(f)


def test_transfer_paged_evidence_assignees_and_arrival_date(transfer):
    f = transfer
    sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    before = f.tr_receive_body(sent)
    before["business_date"] = "2026-10-01"
    assert f.tr_receive(sent, before).json()["code"] == "INVALID_DATE"
    current = ok(f.tr_receive(sent))
    source = ok(f.tr_read(current))["sources"][0]
    evidence_ids = set()
    for index in range(2):
        current = ok(
            f.tr_request(
                "POST",
                f"transfers/{sent['id']}/discrepancies",
                dict(
                    expected_version=current["version"],
                    reason="Bổ sung chứng cứ",
                    dispatch_move_id=source["dispatch_move_id"],
                    kind="MISSING",
                    quantity_base="2",
                    evidence_ref=f"Biên bản lần {index}",
                ),
                "receiver",
            )
        )
        evidence_ids.add(current["discrepancy_id"])
    first = ok(f.tr_request("GET", f"transfers/{sent['id']}/discrepancies?limit=1", who="receiver"))
    second = ok(
        f.tr_request(
            "GET", f"transfers/{sent['id']}/discrepancies?limit=1&after={first['next_after']}", who="receiver"
        )
    )
    assert {first["items"][0]["id"], second["items"][0]["id"]} == evidence_ids and second[
        "next_after"
    ] is None
    assert ok(f.tr_read(current))["sources"][0]["remaining_base"] == "2.000000"
    users = ok(f.tr_request("GET", f"transfers/{sent['id']}/assignees"))["items"]
    assert {str(f.sender), str(f.receiver)} <= {r["id"] for r in users}
    assert f.tr_request("GET", f"transfers/{sent['id']}/assignees", who="receiver").status_code == 403
    assert f.tr_request("GET", f"transfers/{sent['id']}/adjustments", who="receiver").status_code == 403
    reconcile(f)
