from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_orders import ok, orders  # noqa: F401

from packages.contracts.traceability import COMPANY_OWNER

pytestmark = pytest.mark.integration


@pytest.fixture
def opening(orders):  # noqa: F811
    f = orders
    f.drafter_grant = f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    f.director, _ = f.iam.user("director")
    f.iam.grant(f.director, "DIRECTOR", f.warehouse)
    f.headers["director"] = f.iam.headers(f.iam.login("director"))
    zone = f.master("locations", code="ZONE", name="Zone", kind="GROUP", warehouse_id=str(f.warehouse))
    rack = f.master(
        "locations",
        code="RACK",
        name="Rack",
        kind="GROUP",
        warehouse_id=str(f.warehouse),
        parent_id=zone["id"],
    )
    f.location = f.master(
        "locations",
        code="BIN",
        name="Kệ",
        kind="STORAGE",
        warehouse_id=str(f.warehouse),
        parent_id=rack["id"],
    )
    f.quarantine = f.master(
        "locations", code="QA", name="Cách ly", kind="QUARANTINE", warehouse_id=str(f.warehouse)
    )
    with f.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status)
            VALUES (:id,:wh,'2026-10-01','2026-10-31','OPEN')"""),
            {"id": uuid4(), "wh": f.warehouse},
        )
    f.opening_body = dict(
        warehouse_id=str(f.warehouse),
        batch_key=str(uuid4()),
        business_date="2026-10-02",
        signed_count_reference="Biên bản kiểm kê đã ký CUTOVER-01",
        reason="Khởi tạo tồn doanh nghiệp",
        lines=[
            dict(
                product_id=f.product["id"],
                quantity_base="10",
                owner_id=str(COMPANY_OWNER),
                destination_location_id=f.location["id"],
            )
        ],
    )

    def create(body=None, key=None, who="buyer"):
        return f.client.post(
            "/api/v1/openings",
            json=body or f.opening_body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
        )

    def approve(body=None, who="director"):
        return ok(f.decision(ok(f.action(ok(create(body), 201), "submit")), who))

    def read(doc, who="buyer"):
        return f.client.get("/api/v1/openings/" + doc["id"], headers=f.headers[who])

    def post_body(doc):
        return dict(
            expected_version=doc["version"], execution_key=str(uuid4()), reason="Ghi tồn đã kiểm kê và ký"
        )

    def post(doc, payload=None, key=None, who="buyer"):
        return f.client.post(
            "/api/v1/openings/" + doc["id"] + "/post",
            json=payload or post_body(doc),
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
        )

    f.open_create, f.open_approve, f.open_read, f.open_post_body, f.open_post = (
        create,
        approve,
        read,
        post_body,
        post,
    )
    return f


def inventory(f):
    with f.engine.connect() as c:
        return tuple(
            c.execute(text(sql)).scalar_one()
            for sql in [
                "SELECT count(*) FROM wms.inventory_transaction",
                "SELECT count(*) FROM wms.stock_move",
                "SELECT coalesce(sum(on_hand),0) FROM wms.stock_balance",
                "SELECT count(*) FROM wms.serial_position",
            ]
        )


def tracking(f, mode, **changes):
    product = f.master(
        "products",
        sku=mode + uuid4().hex[:8],
        name=mode,
        base_uom_id=f.product["base_uom_id"],
        tracking=mode,
        expiry_required=mode == "LOT",
    )
    body = deepcopy(f.opening_body)
    body["batch_key"] = str(uuid4())
    body["lines"][0].update(product_id=product["id"], quantity_base="1", **changes)
    return product, body


def test_opening_lifecycle_replay_ack_and_reconciliation(opening):
    f = opening
    key = uuid4()
    doc = ok(f.open_create(key=key), 201)
    assert ok(f.open_create(key=key), 201) == doc
    listing = ok(
        f.client.get(
            "/api/v1/openings", params={"warehouse_id": str(f.warehouse)}, headers=f.headers["buyer"]
        )
    )
    assert [r["id"] for r in listing["items"]] == [doc["id"]]
    assert ok(f.open_read(doc))["batch_key"] == f.opening_body["batch_key"]
    doc = ok(f.decision(ok(f.action(doc, "submit")), "director"))
    assert "post" in ok(f.open_read(doc))["allowed_actions"]
    assert inventory(f) == (0, 0, 0, 0)
    payload, key = f.open_post_body(doc), uuid4()
    result = ok(f.open_post(doc, payload, key))
    assert result["status"] == "COMPLETED"
    assert ok(f.open_post(doc, payload, key)) == ok(f.open_post(doc, payload)) == result
    assert f.open_post(doc, {**payload, "reason": "Khác"}, key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.open_post(doc, {**payload, "reason": "Khác"}).json()["code"] == "EXECUTION_MISMATCH"
    assert f.open_post(doc, payload, who="controller").json()["code"] == "EXECUTION_MISMATCH"
    assert f.open_post(result).json()["code"] == "INVALID_STATE"
    ack = ok(f.client.get("/api/v1/openings/operations/" + str(key), headers=f.headers["buyer"]))
    assert ack["transaction_id"] == result["transaction_id"] and ack["request_id"] == result["request_id"]
    assert (
        f.client.get("/api/v1/openings/operations/" + str(key), headers=f.headers["controller"]).status_code
        == 404
    )
    assert inventory(f) == (1, 1, 10, 0)
    assert ok(f.open_read(doc))["lines"][0]["posted_base"] == "10.000000"
    with f.engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM wms.stock_balance b JOIN wms.location l ON l.id=b.location_id WHERE l.kind='OPENING'"
                )
            ).scalar_one()
            == 0
        )
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
        assert c.execute(text("SELECT owner_id FROM wms.stock_item")).scalar_one() == COMPANY_OWNER
        for name in ["reconcile.sql", "reconcile_ownership.sql"]:
            with c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[2] / "02_CSDL" / name).read_text())
                while True:
                    if cursor.description:
                        assert cursor.fetchall() == []
                    if not cursor.nextset():
                        break


def test_opening_permissions_scope_sod_and_revoke_on_replay(opening):
    f = opening
    assert f.open_create(who="manager").status_code == 403
    other = f.iam.warehouse("OTHER")
    assert f.open_create({**f.opening_body, "warehouse_id": str(other)}).status_code == 404
    doc = ok(f.open_create(), 201)
    submitted = ok(f.action(doc, "submit"))
    assert f.decision(submitted, "buyer").json()["code"] == "SELF_APPROVAL"
    assert f.decision(submitted, "manager").status_code == 403
    dkey = uuid4()
    approved = ok(f.decision(submitted, "controller", key=dkey))
    assert f.open_post(approved, who="director").status_code == 403
    payload, key = f.open_post_body(approved), uuid4()
    ok(f.open_post(approved, payload, key))
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id IN (:a,:b)"),
            {"a": f.drafter_grant, "b": f.control_grant},
        )
    assert f.open_post(approved, payload, key).status_code == 403
    assert (
        f.client.get("/api/v1/openings/operations/" + str(key), headers=f.headers["buyer"]).status_code == 403
    )
    assert f.decision(submitted, "controller", key=dkey).status_code == 404
    assert f.open_read(approved, "controller").status_code == 404
    assert (
        f.client.get(
            "/api/v1/openings", params={"warehouse_id": str(f.warehouse)}, headers=f.headers["controller"]
        ).status_code
        == 404
    )


def test_opening_two_steps_role_order_policy_snapshot_and_sod(opening):
    f = opening
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.approval_policy_step SET alternative_role_id=NULL WHERE policy_id=(SELECT id FROM wms.approval_policy WHERE document_kind='OPENING')"
            )
        )
        c.execute(
            text("""INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id)
            SELECT :id,p.id,2,r.id FROM wms.approval_policy p,wms.role r WHERE p.document_kind='OPENING' AND r.code='DIRECTOR'"""),
            {"id": uuid4()},
        )
    f.iam.grant(f.controller, "DIRECTOR", f.warehouse)
    submitted = ok(f.action(ok(f.open_create(), 201), "submit"))
    assert f.decision(submitted, "director").status_code == 403
    first = ok(f.decision(submitted))
    assert first["status"] == "SUBMITTED"
    assert f.open_post(first).json()["code"] == "INVALID_STATE"
    assert f.decision(first, "controller").json()["code"] == "SELF_APPROVAL"
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.approval_policy_step SET role_id=(SELECT id FROM wms.role WHERE code='WAREHOUSE_MANAGER') WHERE step_no=2"
            )
        )
    final = ok(f.decision(first, "director"))
    assert final["status"] == "APPROVED"
    ok(f.open_post(final))


def test_opening_edit_reject_revise_cancel_batch_and_stale_version(opening):
    f = opening
    draft = ok(f.open_create(), 201)
    assert f.open_create().json()["code"] == "DUPLICATE_BATCH"
    body = {**deepcopy(f.opening_body), "expected_version": draft["version"]}
    body["lines"][0]["quantity_base"] = "12"

    def update(value):
        return f.client.put(
            "/api/v1/openings/" + draft["id"],
            json=value,
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )

    assert update({**body, "batch_key": str(uuid4())}).status_code == 409
    changed = ok(update(body))
    assert update(body).json()["code"] == "STALE_VERSION"
    submitted = ok(f.action(changed, "submit"))
    rejected = ok(f.decision(submitted, "director", "REJECT"))
    changed = ok(update({**body, "expected_version": rejected["version"]}))
    approved = ok(f.decision(ok(f.action(changed, "submit")), "director"))
    assert update({**body, "expected_version": approved["version"]}).json()["code"] == "INVALID_STATE"
    revised = ok(f.action(approved, "revise"))
    assert ok(f.open_read(revised))["approvals"][-1]["status"] == "INVALIDATED"
    cancelled = ok(f.action(revised, "cancel", "manager"))
    assert ok(f.open_read(cancelled))["status"] == "CANCELLED"
    assert f.open_create().json()["code"] == "DUPLICATE_BATCH"
    assert inventory(f) == (0, 0, 0, 0)


@pytest.mark.parametrize("stage", ["decide", "post"])
def test_opening_snapshot_tampering(opening, stage):
    f = opening
    doc = ok(f.action(ok(f.open_create(), 201), "submit"))
    if stage == "post":
        doc = ok(f.decision(doc, "director"))
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.opening_document SET signed_count_reference='Khác chữ ký' WHERE document_id=:id"
            ),
            {"id": doc["id"]},
        )
    response = f.decision(doc, "director") if stage == "decide" else f.open_post(doc)
    assert response.json()["code"] == "STALE_APPROVAL"
    assert inventory(f) == (0, 0, 0, 0)


@pytest.mark.parametrize("problem", ["period", "frozen", "precision", "inactive", "source", "version"])
def test_opening_post_revalidates_constraints(opening, problem):
    f = opening
    doc = f.open_approve()
    with f.engine.begin() as c:
        if problem == "period":
            c.execute(
                text("UPDATE wms.stock_period SET status='CLOSED',closed_by=:user,closed_at=now()"),
                {"user": f.controller},
            )
        elif problem == "frozen":
            session = uuid4()
            c.execute(
                text(
                    "INSERT INTO wms.count_session(id,number,warehouse_id,status,created_by,version) VALUES (:id,'COUNT',:wh,'DRAFT',:user,1)"
                ),
                {"id": session, "wh": f.warehouse, "user": f.buyer},
            )
            c.execute(
                text("INSERT INTO wms.count_location_lock VALUES (:id,:session,:loc,now(),NULL)"),
                {"id": uuid4(), "session": session, "loc": f.location["id"]},
            )
        elif problem == "inactive":
            c.execute(text("UPDATE wms.location SET is_active=false WHERE id=:id"), {"id": f.location["id"]})
        elif problem == "source":
            c.execute(text("UPDATE wms.location SET kind='EXTERNAL' WHERE code='WMS-OPENING'"))
        elif problem == "version":
            c.execute(text("UPDATE wms.document SET version=version+1 WHERE id=:id"), {"id": doc["id"]})
    if problem == "precision":
        body = deepcopy(f.opening_body)
        body["batch_key"] = str(uuid4())
        body["lines"][0]["quantity_base"] = "0.5"
        response = f.open_create(body)
    else:
        response = f.open_post(doc)
    assert (
        response.json()["code"]
        == {
            "period": "PERIOD_CLOSED",
            "frozen": "LOCATION_FROZEN",
            "precision": "INVALID_REFERENCE",
            "inactive": "INVALID_REFERENCE",
            "source": "SOURCE_MISMATCH",
            "version": "STALE_VERSION",
        }[problem]
    )
    assert inventory(f) == (0, 0, 0, 0)


@pytest.mark.parametrize("point", ["stock_move", "stock_balance", "audit_event", "outbox_event"])
def test_opening_failpoints_rollback_all_and_same_key_retry(opening, point):
    f = opening
    product, body = tracking(f, "SERIAL", serial_code="000SN-A")
    doc = f.open_approve(body)
    payload, key = f.open_post_body(doc), uuid4()
    with f.engine.connect() as c:
        before = {
            t: c.execute(text(f"SELECT count(*) FROM wms.{t}")).scalar_one()
            for t in ["audit_event", "outbox_event", "idempotency_record", "serial", "stock_item"]
        }

    def fail(conn, cursor, statement, parameters, context, executemany):
        prefix = "UPDATE wms." if point == "stock_balance" else "INSERT INTO wms."
        if statement.lstrip().startswith(prefix + point):
            raise RuntimeError("opening failpoint after " + point)

    event.listen(f.engine, "after_cursor_execute", fail)
    try:
        assert f.open_post(doc, payload, key).status_code == 500
    finally:
        event.remove(f.engine, "after_cursor_execute", fail)
    assert inventory(f) == (0, 0, 0, 0)
    assert ok(f.open_read(doc))["version"] == doc["version"]
    with f.engine.connect() as c:
        for table, count in before.items():
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == count
    assert (
        f.client.get("/api/v1/openings/operations/" + str(key), headers=f.headers["buyer"]).status_code == 404
    )
    ok(f.open_post(doc, payload, key))
    assert inventory(f) == (1, 1, 1, 1)


@pytest.mark.parametrize("mode", ["same_key", "same_execution", "different_execution", "different_document"])
def test_opening_concurrent_posts_one_effect(opening, mode):
    f = opening
    docs = [f.open_approve()]
    docs.append(
        f.open_approve({**f.opening_body, "batch_key": str(uuid4())})
        if mode == "different_document"
        else docs[0]
    )
    bodies = [f.open_post_body(docs[0])]
    bodies.append(
        f.open_post_body(docs[1]) if mode in {"different_execution", "different_document"} else bodies[0]
    )
    keys = [uuid4(), uuid4()]
    if mode == "same_key":
        keys[1] = keys[0]
    gate = Barrier(2)

    def run(i):
        gate.wait(timeout=5)
        return f.open_post(docs[i], bodies[i], keys[i])

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, range(2)))
    if mode in {"same_key", "same_execution"}:
        assert [r.status_code for r in responses] == [200, 200]
        assert responses[0].json() == responses[1].json()
    else:
        assert sorted(r.status_code for r in responses) == [200, 409]
    assert inventory(f) == (1, 1, 10, 0)


def test_opening_serial_warranty_has_no_fabricated_supplier_evidence(opening):
    f = opening
    product, body = tracking(f, "SERIAL", serial_code="000sn-X")
    doc = f.open_approve(body)
    ok(f.open_post(doc))
    with f.engine.connect() as c:
        serial = c.execute(
            text("SELECT id FROM wms.serial WHERE product_id=:id"), {"id": product["id"]}
        ).scalar_one()
        assert c.execute(text("SELECT count(*) FROM wms.serial_warranty_record")).scalar_one() == 0
    result = ok(
        f.client.get(
            f"/api/v1/serials/{serial}/warranty",
            params={"warehouse_id": str(f.warehouse)},
            headers=f.headers["buyer"],
        )
    )
    assert (
        result["receipt_id"] is None
        and result["supplier_partner_id"] is None
        and result["status"] == "UNKNOWN"
    )


def test_opening_lot_expiry_and_quarantine(opening):
    f = opening
    _, body = tracking(f, "LOT", lot_code="000LOT-a")
    assert f.open_create(body).json()["code"] == "LOT_EXPIRY_REQUIRED"
    body["lines"][0].update(manufactured_on="2026-01-01", expires_on="2026-10-01")
    body["business_date"] = "2026-10-01"
    doc = f.open_approve(body)
    assert f.open_post(doc).json()["code"] == "LOT_EXPIRED"
    revised = ok(f.action(doc, "revise"))
    body["lines"][0]["destination_location_id"] = f.quarantine["id"]
    changed = ok(
        f.client.put(
            "/api/v1/openings/" + doc["id"],
            json={**body, "expected_version": revised["version"]},
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
    )
    approved = ok(f.decision(ok(f.action(changed, "submit")), "director"))
    ok(f.open_post(approved))
    assert inventory(f) == (1, 1, 1, 0)


def second_warehouse(f, body):
    warehouse = f.iam.warehouse("SECOND")
    f.iam.grant(f.buyer, "CONTROLLER", warehouse)
    f.iam.grant(f.director, "DIRECTOR", warehouse)
    location = f.master(
        "locations", code="SECOND-QA", name="Kho hai", kind="QUARANTINE", warehouse_id=str(warehouse)
    )
    with f.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status)
            VALUES (:id,:wh,'2026-10-01','2026-10-31','OPEN')"""),
            {"id": uuid4(), "wh": warehouse},
        )
    body = deepcopy(body)
    body.update(warehouse_id=str(warehouse))
    for line in body["lines"]:
        line["destination_location_id"] = location["id"]
    return body


@pytest.mark.parametrize("tracking_mode", ["LOT", "SERIAL"])
def test_opening_cross_warehouse_tracking_concurrency(opening, tracking_mode):
    f = opening
    changes = (
        dict(lot_code="same-lot", expires_on="2027-01-01")
        if tracking_mode == "LOT"
        else dict(serial_code="same-serial")
    )
    _, body = tracking(f, tracking_mode, **changes)
    docs = [f.open_approve(body), f.open_approve(second_warehouse(f, body))]
    barrier = Barrier(2)

    def run(doc):
        barrier.wait(timeout=5)
        return f.open_post(doc)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, docs))
    if tracking_mode == "SERIAL":
        assert sorted(r.status_code for r in responses) == [200, 409]
        assert next(r for r in responses if r.status_code == 409).json()["code"] == "SERIAL_ALREADY_PRESENT"
        assert inventory(f) == (1, 1, 1, 1)
    else:
        assert [r.status_code for r in responses] == [200, 200]
        assert inventory(f) == (2, 2, 2, 0)
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.lot")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM wms.stock_item")).scalar_one() == 1


def test_opening_existing_lot_metadata_conflict_rolls_back(opening):
    f = opening
    product, body = tracking(f, "LOT", lot_code="EXISTING", expires_on="2027-01-01")
    with f.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wms.lot(id,product_id,code,expires_on,version) VALUES (:id,:product,'EXISTING','2028-01-01',1)"
            ),
            {"id": uuid4(), "product": product["id"]},
        )
    doc = f.open_approve(body)
    assert f.open_post(doc).json()["code"] == "LOT_METADATA_CONFLICT"
    assert inventory(f) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "problem",
    ["owner", "none_lot", "serial_qty", "duplicate_serial", "group", "cross_location", "scale", "float"],
)
def test_opening_invalid_plan_never_creates_document(opening, problem):
    f = opening
    body = deepcopy(f.opening_body)
    if problem == "owner":
        body["lines"][0]["owner_id"] = str(uuid4())
    elif problem == "none_lot":
        body["lines"][0]["lot_code"] = "LOT"
    elif problem in {"serial_qty", "duplicate_serial"}:
        _, body = tracking(f, "SERIAL", serial_code="001")
        if problem == "serial_qty":
            body["lines"][0]["quantity_base"] = "2"
        else:
            body["lines"] *= 2
    elif problem == "group":
        group = f.master("locations", code="GROUP", name="Zone", kind="GROUP", warehouse_id=str(f.warehouse))
        body["lines"][0]["destination_location_id"] = group["id"]
    elif problem == "cross_location":
        other_body = second_warehouse(f, body)
        body["lines"][0]["destination_location_id"] = other_body["lines"][0]["destination_location_id"]
    elif problem == "scale":
        body["lines"][0]["quantity_base"] = "0.0000001"
    else:
        body["lines"][0]["quantity_base"] = 1.0
    assert f.open_create(body).status_code in {409, 422}
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.opening_document")).scalar_one() == 0
    assert inventory(f) == (0, 0, 0, 0)


def test_opening_and_receipt_race_in_different_periods(opening):
    f = opening
    opening_doc = f.open_approve()
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    po = ok(f.decision(f.submit()))
    source_line = ok(f.read(po))["lines"][0]["id"]
    body = dict(
        source_order_id=po["id"],
        business_date="2026-11-01",
        reason="Nhận sang kỳ khác",
        lines=[
            dict(source_line_id=source_line, quantity_base="1", destination_location_id=f.quarantine["id"])
        ],
    )
    receipt = ok(
        f.client.post(
            "/api/v1/receipts", json=body, headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
        ),
        201,
    )
    receipt = ok(f.decision(ok(f.action(receipt, "submit"))))
    line = ok(f.read(receipt, kind="receipts"))["lines"][0]["id"]
    with f.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status)
            VALUES (:id,:wh,'2026-11-01','2026-11-30','OPEN')"""),
            {"id": uuid4(), "wh": f.warehouse},
        )
    barrier = Barrier(2)

    def run(kind):
        barrier.wait(timeout=5)
        if kind == "opening":
            return f.open_post(opening_doc)
        return f.client.post(
            "/api/v1/receipts/" + receipt["id"] + "/post",
            json=dict(
                expected_version=receipt["version"],
                execution_key=str(uuid4()),
                reason="Nhận thực tế",
                lines=[dict(document_line_id=line, quantity_base="1")],
            ),
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )

    with ThreadPoolExecutor(2) as pool:
        opened, received = list(pool.map(run, ["opening", "receipt"]))
    assert received.status_code == 200, received.text
    if opened.status_code == 200:
        assert inventory(f) == (2, 2, 11, 0)
        with f.engine.connect() as c:
            assert c.execute(
                text("SELECT operation FROM wms.inventory_transaction ORDER BY posted_at")
            ).scalars().all() == ["OPEN", "RECEIVE"]
    else:
        assert opened.status_code == 409 and opened.json()["code"] == "OPENING_CLOSED"
        assert inventory(f) == (1, 1, 1, 0)
    assert f.open_create({**f.opening_body, "batch_key": str(uuid4())}).json()["code"] == "OPENING_CLOSED"


def test_opening_decisions_race_and_revoked_draft_replay(opening):
    f = opening
    ckey, skey = uuid4(), uuid4()
    draft = ok(f.open_create(key=ckey), 201)
    doc = ok(f.action(draft, "submit", key=skey))
    barrier = Barrier(2)

    def run(who):
        barrier.wait(timeout=5)
        return f.decision(doc, who)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, ["controller", "director"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": f.drafter_grant}
        )
    assert f.open_create(key=ckey).status_code == 403
    assert f.action(draft, "submit", key=skey).status_code == 403


@pytest.mark.parametrize("reserved_policy_id", [False, True])
def test_opening_upgrade_from_009_preserves_custom_policy_and_legacy_data(
    empty_database, monkeypatch, reserved_policy_id
):
    import apps.server.infrastructure.migrations as migrations

    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:9])
        migrations.migrate(empty_database)
    ids = {k: uuid4() for k in ["user", "warehouse", "document", "policy", "step"]}
    if reserved_policy_id:
        ids["policy"] = "00000000-0000-4000-8000-000000000104"
    with empty_database.begin() as c:
        for statement in [
            "INSERT INTO wms.app_user VALUES (:user,'legacy','Legacy','fixture-only',true,0,now())",
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'OLD','Legacy',true)",
            "INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes) VALUES (:document,'OLD-OPENING','OPENING','DRAFT',:warehouse,'2026-10-01',:user,now(),3,'{}')",
            "INSERT INTO wms.approval_policy VALUES (:policy,'OPENING',7,false)",
            "INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id) SELECT :step,:policy,1,id FROM wms.role WHERE code='DIRECTOR'",
        ]:
            c.execute(text(statement), ids)
        original = dict(
            c.execute(text("SELECT * FROM wms.document WHERE id=:document"), ids).mappings().one()
        )
    assert migrations.migrate(empty_database) == ["010_opening.sql"]
    assert migrations.migrate(empty_database) == []
    with empty_database.connect() as c:
        assert (
            dict(c.execute(text("SELECT * FROM wms.document WHERE id=:document"), ids).mappings().one())
            == original
        )
        assert tuple(
            c.execute(
                text("SELECT revision,is_active FROM wms.approval_policy WHERE document_kind='OPENING'")
            ).one()
        ) == (7, False)
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.approval_policy_step WHERE policy_id=:policy"), ids
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text("SELECT alternative_role_id FROM wms.approval_policy_step WHERE id=:step"), ids
            ).scalar_one()
            is None
        )
        assert c.execute(text("SELECT count(*) FROM wms.opening_document")).scalar_one() == 0
