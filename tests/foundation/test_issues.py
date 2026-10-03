from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401

from packages.contracts.traceability import COMPANY_OWNER

pytestmark = pytest.mark.integration


@pytest.fixture
def issuing(opening):  # noqa: F811
    f = opening
    f.picker_grant = f.iam.grant(f.buyer, "PICKER", f.warehouse)

    def command(path, body, *, who="buyer", key=None, method="post"):
        return getattr(f.client, method)("/api/v1/" + path, json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())})

    def read(doc, who="buyer"):
        return ok(f.read(doc, who, "issues"))

    def seed(body=None):
        return ok(f.open_post(f.open_approve(body)))

    def sales(body=None):
        body = body or {**f.body, "lines": [{**f.body["lines"][0], "quantity": "10"}]}
        return ok(f.decision(ok(f.action(ok(f.create("sales-orders", body), 201), "submit"))))

    def create(source=None, qty="10", *, body=None):
        source = source or sales()
        line = ok(f.read(source, kind="sales-orders"))["lines"][0]
        payload = body or dict(source_order_id=source["id"], business_date="2026-10-02", reason="Kế hoạch xuất",
                               lines=[dict(source_line_id=line["id"], quantity_base=qty)])
        return command("issues", payload)

    def approve(source=None, qty="10", *, body=None):
        return ok(f.decision(ok(f.action(ok(create(source, qty, body=body), 201), "submit"))))

    def proposal(doc, qty="7", line_id=None, who="buyer"):
        line_id = line_id or read(doc)["lines"][0]["id"]
        return f.client.get(f"/api/v1/issues/{doc['id']}/reservation-plan",
            params={"document_line_id": line_id, "quantity_base": qty}, headers=f.headers[who])

    def reserve_body(doc, qty="7", **extra):
        proposal_body = ok(proposal(doc, qty))
        return dict(expected_version=proposal_body["version"], reason="Xác nhận FEFO",
                    lines=[{k: row[k] for k in ("document_line_id", "stock_item_id", "location_id", "quantity_base")}
                           for row in proposal_body["lines"]], **extra)

    def reserve(doc, qty="7", **extra):
        return ok(command(f"issues/{doc['id']}/reservations/reserve", reserve_body(doc, qty, **extra)))

    def post_body(doc, qty="7"):
        reservations = [r for r in read(doc)["reservations"] if Decimal(r["remaining_base"]) > 0]
        return dict(expected_version=doc["version"], reason="Xuất thực tế", execution_key=str(uuid4()),
                    lines=[dict(reservation_id=reservations[0]["id"], quantity_base=qty)])

    def post(doc, body=None, **kwargs):
        return command(f"issues/{doc['id']}/post", body or post_body(doc), **kwargs)

    def release(doc, qty="7", **kwargs):
        body = post_body(doc, qty)
        body.pop("execution_key")
        return command(f"issues/{doc['id']}/reservations/release", body, **kwargs)

    f.issue_command, f.issue_read, f.seed, f.sales = command, read, seed, sales
    f.issue_create, f.issue_approve, f.proposal = create, approve, proposal
    f.reserve_body, f.reserve, f.issue_post_body, f.issue_post, f.release = reserve_body, reserve, post_body, post, release
    return f


def inventory(f):
    with f.engine.connect() as c:
        return tuple(c.execute(text(sql)).scalar_one() for sql in (
            "SELECT count(*) FROM wms.inventory_transaction WHERE operation='ISSUE'",
            "SELECT coalesce(sum(on_hand),0) FROM wms.stock_balance",
            "SELECT coalesce(sum(reserved),0) FROM wms.stock_balance",
            "SELECT coalesce(sum(quantity),0) FROM wms.reservation_consumption",
        ))


def reconcile(f):
    with f.engine.connect() as c:
        for name in ("reconcile.sql", "reconcile_ownership.sql"):
            with c.connection.driver_connection.cursor() as cursor:
                cursor.execute((Path(__file__).resolve().parents[2] / "02_CSDL" / name).read_text())
                while True:
                    if cursor.description:
                        assert cursor.fetchall() == []
                    if not cursor.nextset():
                        break


def test_issue_partial_complete_replay_execution_and_operation(issuing):
    f = issuing
    f.seed()
    doc = f.issue_approve()
    source_id = f.issue_read(doc)["source_order_id"]
    held = f.reserve(doc)
    assert inventory(f) == (0, 10, 7, 0)
    key, body = uuid4(), f.issue_post_body(held, "4")
    first = ok(f.issue_post(held, body, key=key))
    assert first["status"] == first["source_order_status"] == "PARTIAL"
    assert inventory(f) == (1, 6, 3, 4)
    assert ok(f.issue_post(held, body, key=key)) == first
    assert ok(f.issue_post(held, body)) == first
    assert f.issue_post(held, {**body, "reason": "changed"}, key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.issue_post(held, {**body, "reason": "changed"}).json()["code"] == "EXECUTION_MISMATCH"
    lookup = ok(f.client.get(f"/api/v1/issues/operations/{key}", headers=f.headers["buyer"]))
    assert lookup["result"] == first and lookup["operation_status"] == "COMMITTED"
    assert f.issue_read(doc)["lines"][0]["remaining_base"] == "6.000000"
    second = ok(f.issue_post(first, f.issue_post_body(first, "3")))
    held = f.reserve(second, "3")
    complete = ok(f.issue_post(held, f.issue_post_body(held, "3")))
    assert complete["status"] == complete["source_order_status"] == "COMPLETED"
    assert inventory(f) == (3, 0, 0, 10)
    assert ok(f.read({"id": source_id}, kind="sales-orders"))["lines"][0]["remaining_base"] == "0.000000"
    assert ok(f.issue_post(held, body, key=key)) == first
    reconcile(f)


def test_two_pg_sessions_request_seven_from_ten_only_one_can_reserve_and_post(issuing):
    f = issuing
    f.seed()
    docs = [f.issue_approve(), f.issue_approve()]
    bodies = [f.reserve_body(doc) for doc in docs]
    gate = Barrier(2)

    def run(index):
        gate.wait()
        response = f.issue_command(f"issues/{docs[index]['id']}/reservations/reserve", bodies[index])
        if response.status_code == 200:
            return f.issue_post(response.json())
        return response

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "INSUFFICIENT_STOCK"
    assert inventory(f) == (1, 3, 0, 7)
    reconcile(f)


def test_reserve_replay_source_demand_and_other_documents_hold_are_protected(issuing):
    f = issuing
    f.seed()
    source = f.sales()
    first, second = f.issue_approve(source), f.issue_approve(source)
    body, key = f.reserve_body(first), uuid4()
    held = ok(f.issue_command(f"issues/{first['id']}/reservations/reserve", body, key=key))
    assert ok(f.issue_command(f"issues/{first['id']}/reservations/reserve", body, key=key)) == held
    assert f.issue_command(f"issues/{first['id']}/reservations/reserve", body).json()["code"] == "STALE_VERSION"
    assert f.proposal(second).json()["code"] == "SOURCE_EXCEEDED"
    stolen = {**f.issue_post_body(held), "expected_version": second["version"]}
    assert f.issue_post(second, stolen).json()["code"] == "RESERVATION_MISMATCH"
    assert inventory(f) == (0, 10, 7, 0)
    assert f.proposal(held, "4").json()["code"] == "ISSUE_EXCEEDED"


def test_release_revise_edit_and_close_preserve_history(issuing):
    f = issuing
    f.seed()
    doc = f.reserve(f.issue_approve())
    original_line = f.issue_read(doc)["lines"][0]["id"]
    released = ok(f.release(doc, "2"))
    assert inventory(f) == (0, 10, 5, 0)
    revised = ok(f.action(released, "revise"))
    assert inventory(f) == (0, 10, 0, 0)
    view = f.issue_read(revised)
    assert view["approvals"][0]["status"] == "INVALIDATED"
    changed = ok(f.issue_command(f"issues/{doc['id']}", dict(
        source_order_id=view["source_order_id"], business_date="2026-10-02", expected_version=revised["version"],
        reason="Giảm kế hoạch", lines=[dict(source_line_id=view["source_line_ids"][original_line], quantity_base="8")]), method="put"))
    assert f.issue_read(changed)["lines"][0]["id"] == original_line
    assert f.issue_read(changed)["reservations"][0]["released"] == "7.000000"
    approved = ok(f.decision(ok(f.action(changed, "submit"))))
    held = f.reserve(approved, "8")
    partial = ok(f.issue_post(held, f.issue_post_body(held, "3")))
    closed = ok(f.action(partial, "close", "manager"))
    assert closed["status"] == "COMPLETED"
    assert f.issue_read(closed)["lines"][0]["closed_base"] == "5.000000"
    assert inventory(f) == (1, 7, 0, 3)
    so = ok(f.read({"id": view["source_order_id"]}, kind="sales-orders"))
    assert so["lines"][0]["remaining_base"] == "7.000000"
    ok(f.action(so, "close", "manager"))
    reconcile(f)


def test_cancel_and_post_race_is_atomic(issuing):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve())
    body = f.issue_post_body(held)
    gate = Barrier(2)

    def run(action):
        gate.wait()
        return f.issue_post(held, body) if action == "post" else f.action(held, "cancel", "manager")

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(run, ["post", "cancel"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert inventory(f) in {(1, 3, 0, 7), (0, 10, 0, 0)}
    reconcile(f)


def test_expired_reservation_stays_reserved_until_release_and_release_race(issuing):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve(), expires_at=(f.iam.now + timedelta(seconds=20)).isoformat())
    other = f.issue_approve()
    f.iam.advance(21)
    assert f.issue_post(held).json()["code"] == "RESERVATION_EXPIRED"
    assert f.proposal(other, "4").json()["code"] == "INSUFFICIENT_STOCK"
    assert inventory(f) == (0, 10, 7, 0)
    gate = Barrier(2)
    release_body = f.issue_post_body(held)
    release_body.pop("execution_key")

    def run(action):
        gate.wait()
        body = release_body if action == "release" else dict(expected_version=held["version"], reason="Hết hạn")
        return f.issue_command(f"issues/{held['id']}/reservations/{action}", body)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ["release", "expire"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert inventory(f) == (0, 10, 0, 0)
    assert ok(f.proposal(other))["lines"]
    reconcile(f)


@pytest.mark.parametrize("point", ["inventory_transaction", "stock_move", "stock_balance", "reservation SET consumed",
                                   "reservation_consumption", "audit_event", "outbox_event", "idempotency_record"])
def test_failpoint_rollback_all_effects_then_retry_same_key(issuing, point):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve())
    body, key = f.issue_post_body(held), uuid4()
    before = f.issue_read(held)
    with f.engine.connect() as c:
        counts = {t: c.execute(text(f"SELECT count(*) FROM wms.{t}")).scalar_one()
                  for t in ("audit_event", "outbox_event", "idempotency_record")}

    def fail(c, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith(("INSERT", "UPDATE")) and "wms." + point in statement:
            raise RuntimeError("Test failure after write")

    event.listen(f.engine, "after_cursor_execute", fail)
    try:
        assert f.issue_post(held, body, key=key).status_code == 500
    finally:
        event.remove(f.engine, "after_cursor_execute", fail)
    assert inventory(f) == (0, 10, 7, 0)
    assert f.issue_read(held) == before
    assert f.client.get(f"/api/v1/issues/operations/{key}", headers=f.headers["buyer"]).status_code == 404
    with f.engine.connect() as c:
        assert all(c.execute(text(f"SELECT count(*) FROM wms.{t}")).scalar_one() == n for t, n in counts.items())
    ok(f.issue_post(held, body, key=key))
    reconcile(f)


def test_permissions_assignment_revocation_and_stale_approval(issuing):
    f = issuing
    f.seed()
    doc = f.issue_approve()
    assert f.proposal(doc, who="manager").status_code == 403  # not assigned to this ISSUE
    actor, _ = f.iam.user("unassigned")
    f.iam.grant(actor, "PICKER", f.warehouse)
    f.headers["unassigned"] = f.iam.headers(f.iam.login("unassigned"))
    assert f.read(doc, "unassigned", "issues").status_code == 404
    body, key = f.reserve_body(doc), uuid4()
    held = ok(f.issue_command(f"issues/{doc['id']}/reservations/reserve", body, key=key))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": f.picker_grant})
    assert f.issue_command(f"issues/{doc['id']}/reservations/reserve", body, key=key).status_code == 403
    assert f.issue_post(held).status_code == 403
    assert f.client.get(f"/api/v1/issues/operations/{key}", headers=f.headers["buyer"]).status_code == 403
    assert inventory(f) == (0, 10, 7, 0)


def test_approve_edit_race_and_snapshot_tampering(issuing):
    f = issuing
    doc = ok(f.issue_create(), 201)
    view = f.issue_read(doc)
    body = dict(source_order_id=view["source_order_id"], business_date="2026-10-02", reason="Sửa",
                lines=[dict(source_line_id=next(iter(view["source_line_ids"].values())), quantity_base="8")])
    submitted = ok(f.action(doc, "submit"))
    gate = Barrier(2)

    def run(action):
        gate.wait()
        return f.decision(submitted) if action == "approve" else f.issue_command(
            f"issues/{doc['id']}", {**body, "expected_version": submitted["version"]}, method="put")

    with ThreadPoolExecutor(2) as pool:
        approved, edited = list(pool.map(run, ["approve", "edit"]))
    assert approved.status_code == 200 and edited.status_code == 409
    assert f.issue_read(doc)["lines"][0]["quantity"] == "10.000000"
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.document_line SET quantity=9,base_quantity=9 WHERE document_id=:id"), {"id": doc["id"]})
    assert f.proposal(doc, "1").json()["code"] == "STALE_APPROVAL"


@pytest.mark.parametrize("problem", ["period", "location", "product", "frozen"])
def test_post_rechecks_period_activity_and_count_lock(issuing, problem):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve())
    with f.engine.begin() as c:
        if problem == "period":
            c.execute(text("UPDATE wms.stock_period SET status='CLOSED',closed_by=:actor,closed_at=now()"), {"actor": f.controller})
        elif problem in {"location", "product"}:
            c.execute(text(f"UPDATE wms.{problem} SET is_active=false WHERE id=:id"),
                      {"id": f.location["id"] if problem == "location" else f.product["id"]})
        else:
            count = uuid4()
            c.execute(text("""INSERT INTO wms.count_session(id,number,warehouse_id,status,created_by,version)
                VALUES (:id,'TEST',:wh,'DRAFT',:actor,1)"""), {"id": count, "wh": f.warehouse, "actor": f.buyer})
            c.execute(text("INSERT INTO wms.count_location_lock VALUES (:id,:session,:location,now(),NULL)"),
                      {"id": uuid4(), "session": count, "location": f.location["id"]})
    assert f.issue_post(held).json()["code"] == ("PERIOD_CLOSED" if problem == "period" else "STOCK_INELIGIBLE")
    assert inventory(f) == (0, 10, 7, 0)


def test_fefo_proposal_requires_exact_confirmation_and_revalidates_expiry(issuing):
    f = issuing
    lot_product = f.master("products", sku="LOT", name="Lô", base_uom_id=f.product["base_uom_id"], tracking="LOT", expiry_required=True)
    conversion = ok(f.client.get("/api/v1/master/product-uoms", params={"product_id": lot_product["id"]},
                                 headers=f.headers["buyer"]))["items"][0]
    body = deepcopy(f.opening_body)
    body["lines"] = [{**body["lines"][0], "product_id": lot_product["id"], "lot_code": code,
                      "expires_on": expiry, "quantity_base": qty, "destination_location_id": location}
                     for code, expiry, qty, location in [
                         ("late", "2026-12-01", "5", f.location["id"]),
                         ("early", "2026-10-10", "5", f.location["id"]),
                         ("expired", "2026-10-01", "5", f.quarantine["id"])]]
    f.seed(body)
    source = f.sales({**f.body, "lines": [{**f.body["lines"][0], "product_id": lot_product["id"],
                                         "product_uom_id": conversion["id"]}]})
    doc = f.issue_approve(source)
    proposal = ok(f.proposal(doc))
    assert [(p["lot_code"], p["quantity_base"]) for p in proposal["lines"]] == [("early", "5.000000"), ("late", "2.000000")]
    body = f.reserve_body(doc)
    body["lines"][0]["quantity_base"] = "2"
    body["lines"][1]["quantity_base"] = "5"
    assert f.issue_command(f"issues/{doc['id']}/reservations/reserve", body).json()["code"] == "FEFO_CHANGED"
    held = f.reserve(doc)
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.lot SET expires_on='2026-10-01' WHERE code='early'"))
    assert f.issue_post(held, f.issue_post_body(held, "1")).json()["code"] == "STOCK_INELIGIBLE"
    assert inventory(f) == (0, 15, 7, 0)


def test_serial_allocation_quantity_position_and_consumption(issuing):
    f = issuing
    product = f.master("products", sku="SER", name="Serial", base_uom_id=f.product["base_uom_id"], tracking="SERIAL")
    conversion = ok(f.client.get("/api/v1/master/product-uoms", params={"product_id": product["id"]},
                                 headers=f.headers["buyer"]))["items"][0]
    body = deepcopy(f.opening_body)
    body["lines"] = [{**body["lines"][0], "product_id": product["id"], "serial_code": code, "quantity_base": "1"}
                     for code in ("0001", "0002")]
    f.seed(body)
    source = f.sales({**f.body, "lines": [{**f.body["lines"][0], "product_id": product["id"],
                                         "product_uom_id": conversion["id"], "quantity": "2"}]})
    held = f.reserve(f.issue_approve(source, "2"), "2")
    assert len(f.issue_read(held)["reservations"]) == 2
    assert f.issue_post(held, f.issue_post_body(held, "0.5")).status_code == 409
    assert f.release(held, "0.5").status_code == 409
    post_body = f.issue_post_body(held, "1")
    post_body["lines"] = [dict(reservation_id=r["id"], quantity_base="1") for r in f.issue_read(held)["reservations"]]
    assert ok(f.issue_post(held, post_body))["status"] == "COMPLETED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.reservation_consumption")).scalar_one() == 2
    reconcile(f)


@pytest.mark.parametrize("same_http_key", [False, True])
def test_two_sessions_replay_same_execution_without_second_move(issuing, same_http_key):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve())
    body, key, gate = f.issue_post_body(held), uuid4(), Barrier(2)

    def run(_):
        gate.wait(timeout=5)
        return ok(f.issue_post(held, body, key=key if same_http_key else uuid4()))

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, range(2))
    assert first == second and inventory(f) == (1, 3, 0, 7)
    reconcile(f)


def test_consigned_stock_cannot_satisfy_company_demand(issuing):
    f = issuing
    f.seed()
    ids = {k: uuid4() for k in ("owner", "agreement", "stock", "legacy", "document", "line", "transaction", "move")}
    with f.engine.begin() as c:
        c.execute(text("INSERT INTO wms.stock_owner(id,code,name,kind,partner_id) VALUES (:owner,'CONSIGNOR','Chủ hàng','CONSIGNOR',:partner)"),
                  {**ids, "partner": f.partner["id"]})
        c.execute(text("""INSERT INTO wms.consignment_agreement
            (id,code,owner_id,warehouse_id,valid_from,valid_until,source_ref)
            VALUES (:agreement,'AGR',:owner,:warehouse,'2026-01-01','2026-12-31','Test contract')"""),
            {**ids, "warehouse": f.warehouse})
        params = {**ids, "warehouse": f.warehouse, "user": f.buyer, "product": f.product["id"],
                  "unit": f.product["base_uom_id"], "location": f.location["id"]}
        for sql in [
            "INSERT INTO wms.stock_item(id,product_id,owner_id,consignment_id) VALUES (:stock,:product,:owner,:agreement)",
            "INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes) VALUES (:document,'CONSIGNED-RECEIPT','RECEIPT','COMPLETED',:warehouse,'2026-10-02',:user,now(),1,'{}')",
            "INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,consignment_id) VALUES (:line,:document,1,:product,:unit,5,1,5,:owner,:agreement)",
            "INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by) VALUES (:transaction,:document,:transaction,'RECEIVE','2026-10-02',now(),:user)",
            "INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id) VALUES (:move,:transaction,:line,:stock,'00000000-0000-4000-8000-000000000201',:location,5,:unit)",
            "INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version) VALUES (:move,:stock,:location,5,0,1)",
        ]:
            c.execute(text(sql), params)
    source = f.sales({**f.body, "lines": [{**f.body["lines"][0], "quantity": "15"}]})
    doc = f.issue_approve(source, "15")
    assert f.proposal(doc, "11").json()["code"] == "INSUFFICIENT_STOCK"
    proposed = ok(f.proposal(doc, "10"))
    assert {r["owner_id"] for r in proposed["lines"]} == {str(COMPANY_OWNER)}
    body = f.reserve_body(doc, "10")
    body["lines"][0]["stock_item_id"] = str(ids["stock"])
    assert f.issue_command(f"issues/{doc['id']}/reservations/reserve", body).json()["code"] == "FEFO_CHANGED"
    held = f.reserve(doc, "10")
    ok(f.issue_post(held, f.issue_post_body(held, "10")))
    assert inventory(f) == (1, 5, 0, 10)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT on_hand,reserved FROM wms.stock_balance WHERE stock_item_id=:stock"), ids).one() == (5, 0)
    reconcile(f)


@pytest.mark.parametrize("reserved_policy_id", [False, True])
def test_issue_upgrade_from_010_preserves_legacy_documents_and_policy(empty_database, monkeypatch, reserved_policy_id):
    import apps.server.infrastructure.migrations as migrations

    sources = migrations.migration_sources()
    baseline = [s for s in sources if s[0] <= "010_opening.sql"]
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: baseline)
        migrations.migrate(empty_database)
    ids = {name: uuid4() for name in ("user", "warehouse", "document", "policy", "step")}
    if reserved_policy_id:
        ids["policy"] = "00000000-0000-4000-8000-000000000105"
    with empty_database.begin() as c:
        for sql in [
            "INSERT INTO wms.app_user VALUES (:user,'legacy','Legacy','fixture-only',true,0,now())",
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'OLD','Legacy',true)",
            "INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes) VALUES (:document,'OLD-ISSUE','ISSUE','DRAFT',:warehouse,'2026-10-01',:user,now(),3,'{}')",
            "INSERT INTO wms.approval_policy VALUES (:policy,'ISSUE',7,false)",
            "INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id) SELECT :step,:policy,1,id FROM wms.role WHERE code='DIRECTOR'",
        ]:
            c.execute(text(sql), ids)
        original = c.execute(text("SELECT * FROM wms.document WHERE id=:document"), ids).one()
    assert migrations.migrate(empty_database) == ["012_b02_issue_reservation.sql"]
    assert migrations.migrate(empty_database) == []
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as c:
        assert c.execute(text("SELECT * FROM wms.document WHERE id=:document"), ids).one() == original
        assert c.execute(text("SELECT revision,is_active FROM wms.approval_policy WHERE document_kind='ISSUE'")).one() == (7, False)
        assert c.execute(text("SELECT count(*) FROM wms.approval_policy_step WHERE policy_id=:policy"), ids).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.issue_document")).scalar_one() == 0


def test_issue_self_approval_lifecycle_ack_and_scope(issuing):
    f = issuing
    draft = ok(f.issue_create(), 201)
    key = uuid4()
    submitted = ok(f.action(draft, "submit", key=key))
    assert f.decision(submitted, "buyer").json()["code"] == "SELF_APPROVAL"
    lookup = ok(f.client.get(f"/api/v1/issues/operations/{key}", headers=f.headers["buyer"]))
    assert lookup["result"] == submitted
    assert lookup["command"] == "order.None.submit"
    actor, _ = f.iam.user("wrong_warehouse")
    elsewhere = f.iam.warehouse("ELSEWHERE")
    f.iam.grant(actor, "WAREHOUSE_MANAGER", elsewhere)
    headers = f.iam.headers(f.iam.login("wrong_warehouse"))
    assert f.client.get(f"/api/v1/issues/{draft['id']}", headers=headers).status_code == 404
    assert f.client.get(f"/api/v1/issues/operations/{key}", headers=headers).status_code == 404
    assert f.client.get("/api/v1/issues", params={"warehouse_id": str(f.warehouse)}, headers=headers).status_code == 404
    duplicate = dict(expected_version=submitted["version"], execution_key=str(uuid4()), reason="Invalid",
                     lines=[dict(reservation_id=str(uuid4()), quantity_base="1")])
    duplicate["lines"] *= 2
    assert f.issue_post(submitted, duplicate).status_code == 422


def test_issue_refuses_to_bypass_active_picking_and_releases_only_after_cancel(issuing):
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve())
    reservation_id = f.issue_read(held)["reservations"][0]["id"]
    with f.engine.begin() as c:
        c.execute(text("""INSERT INTO wms.pick_task(id,reservation_id,assigned_to,picked_quantity,status,version)
            VALUES (:id,:reservation,:actor,0,'OPEN',1)"""),
            {"id": uuid4(), "reservation": reservation_id, "actor": f.buyer})
    assert f.issue_post(held).json()["code"] == "FULFILLMENT_ACTIVE"
    assert f.release(held).json()["code"] == "FULFILLMENT_ACTIVE"
    assert f.action(held, "cancel", "manager").json()["code"] == "FULFILLMENT_ACTIVE"
    assert inventory(f) == (0, 10, 7, 0)
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.pick_task SET status='CANCELLED'"))
    ok(f.action(held, "cancel", "manager"))
    assert inventory(f) == (0, 10, 0, 0)


def test_reserve_rechecks_changed_fefo_and_cancel_blocks_new_source_child(issuing):
    f = issuing
    f.seed()
    source = f.sales()
    doc = f.issue_approve(source)
    body = f.reserve_body(doc)
    assert f.action(source, "cancel", "manager").json()["code"] == "DEPENDENT_DOCUMENT"
    other = f.reserve(f.issue_approve(), "4")
    assert f.issue_command(f"issues/{doc['id']}/reservations/reserve", body).json()["code"] == "INSUFFICIENT_STOCK"
    assert inventory(f) == (0, 10, 4, 0)
    ok(f.action(other, "cancel", "manager"))
    held = f.reserve(doc)
    assert inventory(f) == (0, 10, 7, 0)
    cancelled = ok(f.action(held, "cancel", "manager"))
    assert cancelled["status"] == "CANCELLED"
    ok(f.action(source, "cancel", "manager"))
    assert f.issue_create(source).json()["code"] == "INVALID_STATE"


@pytest.mark.gui
def test_issue_gui_real_api_partial_and_lost_ack_lookup(issuing):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import ApiError, DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    f = issuing
    f.seed()
    f.sales()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        session, view = shell.session_view, shell.issue_view
        shell.notebook.select(view)
        main_thread = threading.get_ident()

        def wait(condition):
            until = time.monotonic() + 10
            while not condition() and time.monotonic() < until:
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

        def logout():
            session.logout()
            wait(lambda: session.status.get() == "Đã đăng xuất.")
            assert view.doc is None and view.lines == []

        login("buyer")
        view.new()
        view.source.current(0)
        view.source_changed()
        wait(lambda: not view.busy and view.source_doc is not None)
        view.variables["qty"].set("10")
        view.add_line()
        view.variables["day"].set("2026-10-02")
        view.variables["reason"].set("Tạo phiếu trên desktop")
        view.action("save")
        wait(lambda: not view.busy and view.doc is not None)
        doc_id = view.doc["id"]
        view.action("submit")
        wait(lambda: not view.busy and view.doc["status"] == "SUBMITTED")
        logout()
        login("controller")
        view.presenter.read(doc_id)
        wait(lambda: not view.busy and view.doc is not None)
        view.variables["reason"].set("Duyệt phiếu xuất")
        view.action("approve")
        wait(lambda: not view.busy and view.doc["status"] == "APPROVED")
        logout()
        login("buyer")
        view.presenter.read(doc_id)
        wait(lambda: not view.busy and view.doc is not None)
        view.line_table.selection_set("0")
        root.update()
        view.variables["qty"].set("7")
        view.action("plan")
        wait(lambda: not view.busy and view.proposal is not None)
        view.variables["reason"].set("Giữ FEFO đã xem nguồn")
        view.action("reserve")
        wait(lambda: not view.busy and len(view.doc["reservations"]) == 1)
        assert inventory(f) == (0, 10, 7, 0)
        row = view.doc["reservations"][0]
        view.reservation_table.selection_set(row["id"])
        root.update()
        api = session.presenter.api
        original, calls = api.command, []

        def lose_ack(method, path, body, key):
            assert threading.get_ident() != main_thread
            result = original(method, path, body, key)
            if path.endswith("/post"):
                calls.append((deepcopy(body), key))
                raise ApiError("TIMEOUT", "Test response lost after real COMMIT")
            return result

        api.command = lose_ack
        view.action("post")
        wait(lambda: not view.busy and view.presenter.uncertain is not None)
        assert view.presenter.uncertain["state"] == "UNKNOWN"
        assert view.doc["status"] == "APPROVED"  # no fabricated ACK
        assert "UNKNOWN" in view.variables["pending"].get()
        assert inventory(f) == (1, 3, 0, 7)
        view.variables["qty"].set("999")
        view.presenter.lookup()
        wait(lambda: not view.busy and view.doc["status"] == "PARTIAL")
        assert view.presenter.uncertain is None
        assert view.lines[0]["remaining_base"] == "3.000000"
        assert len(calls) == 1
        assert calls[0][0]["lines"][0]["quantity_base"] == "7.000000"
        api.command = original
        logout()
        reconcile(f)
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
