from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from test_move_quality import reconcile
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401

from packages.contracts.traceability import COMPANY_OWNER

pytestmark = pytest.mark.integration


@pytest.fixture
def counting(receiving):  # noqa: F811
    f = receiving
    f.picker, _ = f.iam.user("counter-two")
    f.director, f.director_secret = f.iam.user("director", mfa=True)
    f.iam.grant(f.picker, "PICKER", f.warehouse)
    f.iam.grant(f.director, "DIRECTOR", f.warehouse)
    f.headers["picker"] = f.iam.headers(f.iam.login("counter-two"))
    f.headers["director"] = f.iam.headers(f.iam.login("director", f.director_secret))

    def request(method, path, body=None, who="manager", key=None):
        return f.client.request(method, "/api/v1/" + path, json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())})

    def create(locations=None):
        return ok(request("POST", "counts", dict(warehouse_id=str(f.warehouse), business_date="2026-10-02",
            reason="Kiểm kê định kỳ", scope=[dict(location_id=loc, user_ids=[str(f.buyer), str(f.picker)])
            for loc in locations or [f.location["id"]]])), 201)

    def action(doc, action, who="manager", key=None, **extra):
        return request("POST", "counts/" + doc["id"] + "/" + action,
                       dict(expected_version=doc["version"], reason="Kiểm thử " + action, **extra), who, key)

    def read(doc, who="manager"):
        return ok(request("GET", "counts/" + doc["id"], who=who))

    def observe(doc, quantity="98", who="buyer", line_id=None, key=None, scan=None):
        view = read(doc, who)
        line = next(r for r in view["lines"] if not line_id or r["id"] == line_id)
        return action(view, "observe", who, key, line_id=line["id"], round_no=line["next_round"], quantity=quantity,
                      scan_event_key=str(scan or uuid4()))

    def received(quantity="100", body=None):
        doc = f.receipt_approve(body)
        return ok(f.post(doc, f.post_body(doc, quantity)))

    def approved(quantity="98"):
        doc = ok(action(create(), "freeze"))
        doc = ok(observe(doc, quantity))
        doc = ok(observe(doc, quantity, "picker"))
        doc = ok(action(doc, "submit"))
        doc = ok(action(doc, "decide", "controller", decision="APPROVE"))
        return ok(action(doc, "decide", "director", decision="APPROVE"))

    f.count_request, f.count_create, f.count_action, f.count_read = request, create, action, read
    f.count_observe, f.count_received, f.count_approved = observe, received, approved
    return f


def test_count_t05_blind_rounds_two_approvals_and_exactly_once_adjustment(counting):
    f = counting
    f.count_received()
    doc = ok(f.count_action(f.count_create(), "freeze"))
    blind = f.count_read(doc, "buyer")
    assert blind["mode"] == "BLIND" and len(blind["lines"]) == 1
    assert not {"snapshot_quantity", "approved_quantity", "delta", "observations"}.intersection(blind["lines"][0])
    assert f.count_read(doc)["lines"][0]["snapshot_quantity"] == "100.000000"
    key, scan = uuid4(), uuid4()
    first_body = dict(expected_version=doc["version"], reason="Đếm độc lập", line_id=blind["lines"][0]["id"], round_no=1,
                      quantity="98", scan_event_key=str(scan))
    first = ok(f.count_request("POST", "counts/" + doc["id"] + "/observe", first_body, "buyer", key))
    assert ok(f.count_request("POST", "counts/" + doc["id"] + "/observe", first_body, "buyer", key)) == first
    assert f.count_action(first, "submit").json()["code"] == "RECOUNT_REQUIRED"
    assert f.count_observe(first).json()["code"] == "INDEPENDENT_COUNTER_REQUIRED"
    second = ok(f.count_observe(first, who="picker"))
    submitted = ok(f.count_action(second, "submit"))
    assert f.count_action(submitted, "post", "controller", execution_key=str(uuid4())).json()["code"] == "APPROVAL_REQUIRED"
    f.iam.grant(f.manager, "CONTROLLER", f.warehouse)
    assert f.count_action(submitted, "decide", decision="APPROVE").json()["code"] == "SELF_APPROVAL"
    step1 = ok(f.count_action(submitted, "decide", "controller", decision="APPROVE"))
    assert f.count_action(step1, "post", "controller", execution_key=str(uuid4())).json()["code"] == "APPROVAL_REQUIRED"
    f.iam.grant(f.controller, "DIRECTOR", f.warehouse)
    assert f.count_action(step1, "decide", "controller", decision="APPROVE").json()["code"] == "SELF_APPROVAL"
    approved = ok(f.count_action(step1, "decide", "director", decision="APPROVE"))
    post_key, execution = uuid4(), str(uuid4())
    posted = ok(f.count_action(approved, "post", "controller", post_key, execution_key=execution))
    assert posted["status"] == "POSTED" and posted["transaction_id"]
    assert ok(f.count_action(approved, "post", "controller", post_key, execution_key=execution)) == posted
    assert ok(f.count_action(approved, "post", "controller", execution_key=execution)) == posted
    assert ok(f.count_request("GET", f"counts/operations/{post_key}", who="controller")) == posted
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 98
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='ADJUST'")).scalar_one() == 1
        assert c.execute(text("SELECT quantity_base FROM wms.stock_move WHERE transaction_id=:id"), {"id": posted["transaction_id"]}).scalar_one() == 2
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 0
        for table, field, value in [("audit_event", "action", "count.post"), ("outbox_event", "event_type", "count.post.v1")]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table} WHERE {field}=:value"), {"value": value}).scalar_one() == 1
    reconcile(f)


def test_count_recount_reject_cannot_expose_snapshot_through_added_roles(counting):
    f = counting
    f.count_received()
    doc = ok(f.count_action(f.count_create(), "freeze"))
    doc = ok(f.count_observe(doc, "97"))
    doc = ok(f.count_observe(doc, "98", "picker"))
    assert f.count_action(doc, "submit").json()["code"] == "RECOUNT_REQUIRED"
    doc = ok(f.count_observe(doc, "98"))
    doc = ok(f.count_action(doc, "submit"))
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    assert f.count_read(doc, "buyer")["mode"] == "BLIND"
    assert f.count_action(doc, "decide", "buyer", decision="APPROVE").json()["code"] == "SELF_APPROVAL"
    doc = ok(f.count_action(doc, "decide", "controller", decision="REJECT"))
    assert doc["status"] == "COUNTED"
    doc = ok(f.count_observe(doc, "96", "picker"))
    assert f.count_action(doc, "submit").json()["code"] == "RECOUNT_REQUIRED"
    cancelled = ok(f.count_action(doc, "cancel"))
    assert cancelled["status"] == "CANCELLED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 100
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 0


def test_count_zero_delta_and_rollback_after_effects(counting, monkeypatch):
    f = counting
    f.count_received()
    approved = f.count_approved("100")
    import apps.server.application.counting as module
    original = module.effects
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Fail after audit/outbox")
    key, execution = uuid4(), str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(module, "effects", fail)
        assert f.count_action(approved, "post", "controller", key, execution_key=execution).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='ADJUST'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 1
    posted = ok(f.count_action(approved, "post", "controller", key, execution_key=execution))
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.stock_move WHERE transaction_id=:id"), {"id": posted["transaction_id"]}).scalar_one() == 0
    reconcile(f)


def test_count_post_and_approval_races_and_current_permission_on_replay(counting):
    f = counting
    f.count_received()
    approved = f.count_approved()
    key, execution, barrier = uuid4(), str(uuid4()), Barrier(2)
    def post(_):
        barrier.wait(5)
        return ok(f.count_action(approved, "post", "controller", execution_key=execution))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, range(2)))
    assert results[0] == results[1]
    ok(f.count_action(approved, "post", "controller", key, execution_key=execution))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:id"), {"id": f.controller, "now": f.iam.now})
    assert f.count_action(approved, "post", "controller", key, execution_key=execution).status_code in {403, 404}
    assert f.count_request("GET", f"counts/operations/{key}", who="controller").status_code in {403, 404}
    reconcile(f)


def test_count_extra_serial_missing_serial_and_duplicate_scan(counting):
    f = counting
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='SERIAL' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(quantity_base="1", serial_code="COUNT-MISSING")
    f.count_received("1", body)
    doc = ok(f.count_action(f.count_create(), "freeze"))
    missing = f.count_read(doc, "buyer")["lines"][0]["id"]
    assert f.count_observe(doc, "0.5").json()["code"] == "INVALID_QUANTITY"
    doc = ok(f.count_action(doc, "extra", "buyer", location_id=f.location["id"], product_id=f.product["id"],
                            owner_id=str(COMPANY_OWNER), serial_code="COUNT-EXTRA"))
    extra = next(r["id"] for r in f.count_read(doc, "buyer")["lines"] if r["id"] != missing)
    scan = uuid4()
    doc = ok(f.count_observe(doc, "0", line_id=missing, scan=scan))
    assert f.count_observe(doc, "1", line_id=extra, scan=scan).json()["code"] == "DUPLICATE_SCAN"
    doc = ok(f.count_observe(doc, "1", line_id=extra))
    doc = ok(f.count_observe(doc, "0", "picker", line_id=missing))
    doc = ok(f.count_observe(doc, "1", "picker", line_id=extra))
    doc = ok(f.count_action(doc, "submit"))
    for who in ("controller", "director"):
        doc = ok(f.count_action(doc, "decide", who, decision="APPROVE"))
    ok(f.count_action(doc, "post", "controller", execution_key=str(uuid4())))
    with f.engine.connect() as c:
        assert c.execute(text("SELECT s.code FROM wms.serial_position sp JOIN wms.serial s ON s.id=sp.serial_id")).scalar_one() == "COUNT-EXTRA"
    reconcile(f)


def test_period_create_overlap_close_reopen_mfa_and_audit(counting):
    f = counting
    request = f.count_request
    created = ok(request("POST", "periods", dict(warehouse_id=str(f.warehouse), starts_on="2026-11-01", ends_on="2026-11-30", reason="Mở tháng 11"), "controller"), 201)
    overlap = request("POST", "periods", dict(warehouse_id=str(f.warehouse), starts_on="2026-11-15", ends_on="2026-12-01", reason="Thử kỳ chồng"), "controller")
    assert overlap.json()["code"] == "PERIOD_OVERLAP"
    def action(doc, action, who="controller", **extra):
        return request("POST", "periods/" + doc["id"] + "/" + action,
                       dict(expected_version=doc["version"], reason="Kiểm thử kỳ " + action, **extra), who)
    closed = ok(action(created, "close"))
    assert closed["status"] == "CLOSED"
    assert action(closed, "reopen", "director", confirmation_id=str(uuid4())).json()["code"] == "CONTROLLER_CONFIRMATION_REQUIRED"
    confirmed = ok(action(closed, "confirm-reopen"))
    reopened = ok(action(confirmed, "reopen", "director", confirmation_id=confirmed["confirmation_id"]))
    assert reopened["status"] == "OPEN"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='period.reopen'")).scalar_one() == 1


def test_period_pending_counts_and_reconciliation_block_close(counting):
    f = counting
    f.count_received()
    period = ok(f.count_request("GET", f"periods?warehouse_id={f.warehouse}", who="controller"))["items"][0]
    def close():
        return f.count_request("POST", f"periods/{period['id']}/close", dict(expected_version=period["version"], reason="Khóa tháng"), "controller")
    doc = f.count_create()
    assert close().json()["code"] == "COUNT_PENDING"
    ok(f.count_action(doc, "cancel"))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand+1"))
    assert close().json()["code"] == "RECONCILIATION_FAILED"
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand-1"))
    assert ok(close())["status"] == "CLOSED"
    assert f.count_request("POST", "counts", dict(warehouse_id=str(f.warehouse), business_date="2026-10-02", reason="Backdate bị chặn",
        scope=[dict(location_id=f.location["id"], user_ids=[str(f.buyer), str(f.picker)])])).json()["code"] == "PERIOD_CLOSED"


def test_count_cross_warehouse_and_catalog_permissions(counting):
    f = counting
    doc = f.count_create()
    outsider, _ = f.iam.user("outsider")
    other = f.iam.warehouse("OTHER-COUNT")
    f.iam.grant(outsider, "WAREHOUSE_MANAGER", other)
    f.headers["outsider"] = f.iam.headers(f.iam.login("outsider"))
    assert f.count_request("GET", "counts/" + doc["id"], who="outsider").status_code == 404
    assert f.count_action(doc, "freeze", "outsider").status_code == 404
    users = ok(f.count_request("GET", f"counts/catalog/users?warehouse_id={f.warehouse}"))["items"]
    assert {str(f.buyer), str(f.picker)} <= {u["id"] for u in users}
    assert f.count_request("GET", f"counts/catalog/users?warehouse_id={f.warehouse}", who="buyer").status_code == 403


def test_count_company_and_consigned_lot_remain_separate(counting):
    from test_consignments import agreement

    f = counting
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='LOT' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(lot_code="SHARED-LOT", expires_on="2027-01-01")
    f.count_received("10", body)
    owner, agreement_row = agreement(f)
    body = dict(warehouse_id=str(f.warehouse), batch_key=str(uuid4()), business_date="2026-10-02",
        delivery_reference="CG kiểm kê cùng lô", reason="Nhập cùng lô khác chủ", lines=[dict(product_id=f.product["id"],
            quantity_base="5", owner_id=owner["id"], consignment_id=agreement_row["id"], destination_location_id=f.location["id"],
            lot_code="SHARED-LOT", expires_on="2027-01-01")])
    cg = ok(f.count_request("POST", "consignment-receipts", body, "buyer"), 201)
    cg = ok(f.decision(ok(f.action(cg, "submit")), "manager"))
    ok(f.count_request("POST", "consignment-receipts/" + cg["id"] + "/post",
        dict(expected_version=cg["version"], execution_key=str(uuid4()), reason="Nhập ký gửi"), "buyer"))
    doc = ok(f.count_action(f.count_create(), "freeze"))
    lines = f.count_read(doc)["lines"]
    assert {r["snapshot_quantity"] for r in lines} == {"10.000000", "5.000000"}
    for who in ("buyer", "picker"):
        for line in lines:
            doc = ok(f.count_observe(doc, "4" if line["consignment_id"] else "10", who, line_id=line["id"]))
    doc = ok(f.count_action(doc, "submit"))
    for who in ("controller", "director"):
        doc = ok(f.count_action(doc, "decide", who, decision="APPROVE"))
    posted = ok(f.count_action(doc, "post", "controller", execution_key=str(uuid4())))
    with f.engine.connect() as c:
        quantities = dict(c.execute(text("SELECT i.owner_id,b.on_hand FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id")).all())
        assert quantities[COMPANY_OWNER] == 10 and quantities[next(k for k in quantities if k != COMPANY_OWNER)] == 4
        assert c.execute(text("""SELECT i.consignment_id FROM wms.stock_move m JOIN wms.stock_item i ON i.id=m.stock_item_id
            WHERE m.transaction_id=:id"""), {"id": posted["transaction_id"]}).scalar_one() == UUID(agreement_row["id"])
    reconcile(f)


def test_count_stale_snapshot_double_approval_and_immutable_evidence(counting):
    from sqlalchemy.exc import DatabaseError

    f = counting
    f.count_received()
    doc = ok(f.count_action(f.count_create(), "freeze"))
    assert f.count_action({**doc, "version": doc["version"] - 1}, "cancel").json()["code"] == "STALE_VERSION"
    doc = ok(f.count_observe(doc))
    doc = ok(f.count_observe(doc, who="picker"))
    doc = ok(f.count_action(doc, "submit"))
    barrier = Barrier(2)
    def decide(_):
        barrier.wait(5)
        return f.count_action(doc, "decide", "controller", decision="APPROVE")
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(decide, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    doc = next(r.json() for r in responses if r.status_code == 200)
    doc = ok(f.count_action(doc, "decide", "director", decision="APPROVE"))
    for table in ("count_observation", "count_submission", "count_decision"):
        with pytest.raises(DatabaseError):
            with f.engine.begin() as c:
                c.execute(text(f"DELETE FROM wms.{table}"))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.count_line SET approved_quantity=99 WHERE session_id=:id"), {"id": doc["id"]})
    assert f.count_action(doc, "post", "controller", execution_key=str(uuid4())).json()["code"] == "STALE_APPROVAL"


def test_count_empty_locations_require_two_independent_confirmations(counting):
    f = counting
    doc = ok(f.count_action(f.count_create(), "freeze"))
    assert f.count_action(doc, "submit").json()["code"] == "RECOUNT_REQUIRED"
    for who in ("buyer", "picker"):
        doc = ok(f.count_action(doc, "confirm-empty", who, location_id=f.location["id"]))
    assert f.count_action(doc, "confirm-empty", "buyer", location_id=f.location["id"]).json()["code"] == "DUPLICATE_COUNT"
    doc = ok(f.count_action(doc, "submit"))
    for who in ("controller", "director"):
        doc = ok(f.count_action(doc, "decide", who, decision="APPROVE"))
    posted = ok(f.count_action(doc, "post", "controller", execution_key=str(uuid4())))
    assert posted["status"] == "POSTED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.stock_move")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 0


def test_count_relocated_serial_removes_old_position_before_adding_new(counting):
    f = counting
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='SERIAL' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(quantity_base="1", serial_code="RELOCATED")
    f.count_received("1", body)
    doc = ok(f.count_action(f.count_create([f.location["id"], f.quarantine["id"]]), "freeze"))
    doc = ok(f.count_action(doc, "extra", "buyer", location_id=f.quarantine["id"], product_id=f.product["id"],
                            owner_id=str(COMPANY_OWNER), serial_code="RELOCATED"))
    for who in ("buyer", "picker"):
        for line in f.count_read(doc, who)["lines"]:
            doc = ok(f.count_observe(doc, "0" if line["location_id"] == f.location["id"] else "1", who, line_id=line["id"]))
    doc = ok(f.count_action(doc, "submit"))
    for who in ("controller", "director"):
        doc = ok(f.count_action(doc, "decide", who, decision="APPROVE"))
    ok(f.count_action(doc, "post", "controller", execution_key=str(uuid4())))
    with f.engine.connect() as c:
        assert str(c.execute(text("SELECT location_id FROM wms.serial_position")).scalar_one()) == f.quarantine["id"]
    reconcile(f)


def test_period_reopen_rechecks_mfa_independence_expiry_and_revocation(counting):
    f = counting
    doc = ok(f.count_request("POST", "periods", dict(warehouse_id=str(f.warehouse), starts_on="2026-11-01", ends_on="2026-11-30", reason="Mở kỳ"), "controller"), 201)
    def action(doc, action, who, **extra):
        return f.count_request("POST", f"periods/{doc['id']}/{action}", dict(expected_version=doc["version"], reason="Kiểm thử mở lại", **extra), who)
    doc = ok(action(doc, "close", "controller"))
    doc = ok(action(doc, "confirm-reopen", "controller"))
    f.iam.grant(f.controller, "DIRECTOR", f.warehouse)
    assert action(doc, "reopen", "controller", confirmation_id=doc["confirmation_id"]).json()["code"] == "MFA_REQUIRED"
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:id"), dict(now=f.iam.now, id=f.controller))
    assert action(doc, "reopen", "director", confirmation_id=doc["confirmation_id"]).json()["code"] == "CONTROLLER_CONFIRMATION_REQUIRED"
    f.iam.grant(f.controller, "CONTROLLER", f.warehouse)
    f.iam.advance(25 * 3600)
    f.headers["director"] = f.iam.headers(f.iam.login("director", f.director_secret))
    assert action(doc, "reopen", "director", confirmation_id=doc["confirmation_id"]).json()["code"] == "CONTROLLER_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("baseline", [10, 18])
def test_count_period_upgrade_preserves_existing_period_and_policy(empty_database, monkeypatch, baseline):
    import apps.server.infrastructure.migrations as migration

    sources = migration.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migration, "migration_sources", lambda: sources[:baseline])
        migration.migrate(empty_database)
    warehouse, period = uuid4(), uuid4()
    with empty_database.begin() as c:
        c.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:id,'UPGRADE-B13','Existing',true)"), {"id": warehouse})
        c.execute(text("INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status) VALUES (:id,:warehouse,'2026-01-01','2026-12-31','OPEN')"),
                  dict(id=period, warehouse=warehouse))
        c.execute(text("UPDATE wms.approval_policy SET revision=77 WHERE document_kind='ADJUSTMENT'"))
        c.execute(text("""INSERT INTO wms.approval_policy(id,document_kind,revision,is_active)
            SELECT :id,'ADJUSTMENT',77,false WHERE NOT EXISTS (SELECT 1 FROM wms.approval_policy WHERE document_kind='ADJUSTMENT')"""), {"id": uuid4()})
    assert migration.migrate(empty_database) == [s[0] for s in sources[baseline:]]
    assert migration.is_ready(empty_database)
    with empty_database.connect() as c:
        assert tuple(c.execute(text("SELECT status,version FROM wms.stock_period WHERE id=:id"), {"id": period}).one()) == ("OPEN", 1)
        assert c.execute(text("SELECT revision FROM wms.approval_policy WHERE document_kind='ADJUSTMENT'")).scalar_one() == 77
        permissions = c.execute(text("""SELECT p.code FROM wms.role_permission rp JOIN wms.role r ON r.id=rp.role_id
            JOIN wms.permission p ON p.id=rp.permission_id WHERE r.code='DIRECTOR'""")).scalars().all()
        assert "count.approve" in permissions and "adjustment.approve" not in permissions
