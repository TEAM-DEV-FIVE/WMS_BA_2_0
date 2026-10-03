from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_consignments import agreement
from test_move_quality import movement, receiving, reconcile  # noqa: F401
from test_orders import ok, orders  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def returning(movement):  # noqa: F811
    f = movement
    f.iam.grant(f.buyer, "PICKER", f.warehouse)
    f.request = f.move_request

    def sources(kind="SUPPLIER_RETURN", **params):
        return ok(f.client.get("/api/v1/returns/sources", params={"warehouse_id": str(f.warehouse), "kind": kind, **params},
                               headers=f.headers["buyer"]))

    def body(source, qty="4", kind="SUPPLIER_RETURN", location=None):
        return dict(kind=kind, source_document_id=source["document_id"], business_date="2026-10-02", reason="Trả hàng có nguồn",
                    lines=[dict(source_move_id=source["id"], location_id=location or f.location["id"], quantity_base=qty)])

    def approve(payload):
        return ok(f.decision(ok(f.action(ok(f.request("POST", "returns", payload), 201), "submit"))))

    def post(doc, payload=None, key=None, who="manager"):
        return f.request("POST", f"returns/{doc['id']}/post", payload or dict(expected_version=doc["version"],
            execution_key=str(uuid4()), reason="Ghi sổ trả hàng"), who=who, key=key)

    def issue(qty="7", serial=None, *, post=True, stock_qty=None):
        receipt = deepcopy(f.receipt_body)
        receipt["lines"][0]["quantity_base"] = stock_qty or qty
        if serial:
            with f.engine.begin() as c:
                c.execute(text("UPDATE wms.product SET tracking='SERIAL' WHERE id=:id"), {"id": f.product["id"]})
            receipt["lines"][0]["serial_code"] = serial
        received = f.received(stock_qty or qty, receipt)
        f.putaway(stock_qty or qty, "0", received)
        so_body = deepcopy(f.body)
        so_body["lines"][0]["quantity"] = qty
        so = ok(f.decision(ok(f.action(ok(f.create("sales-orders", so_body), 201), "submit"))))
        source_line = ok(f.read(so, kind="sales-orders"))["lines"][0]["id"]
        doc = ok(f.request("POST", "issues", dict(source_order_id=so["id"], business_date="2026-10-02", reason="Xuất để trả",
            lines=[dict(source_line_id=source_line, quantity_base=qty)])), 201)
        doc = ok(f.decision(ok(f.action(doc, "submit"))))
        line = ok(f.read(doc, kind="issues"))["lines"][0]
        plan = ok(f.request("GET", f"issues/{doc['id']}/reservation-plan?document_line_id={line['id']}&quantity_base={qty}"))
        held = ok(f.request("POST", f"issues/{doc['id']}/reservations/reserve", dict(expected_version=doc["version"], reason="Giữ để xuất",
            lines=[{k: r[k] for k in ("document_line_id", "stock_item_id", "location_id", "quantity_base")} for r in plan["lines"]])))
        reservation = ok(f.read(held, kind="issues"))["reservations"][0]
        if not post:
            return held, reservation, received, so
        ok(f.request("POST", f"issues/{doc['id']}/post", dict(expected_version=held["version"], execution_key=str(uuid4()), reason="Xuất nguồn",
            lines=[dict(reservation_id=reservation["id"], quantity_base=qty)])))
        return sources("CUSTOMER_RETURN")["items"][0], received, so

    f.return_sources, f.return_body, f.return_approve, f.return_post, f.issued_source = sources, body, approve, post, issue
    return f


def test_returns_supplier_partial_net_replay_and_po_unchanged(returning):
    f = returning
    f.received("10")
    source = f.return_sources()["items"][0]
    before = ok(f.read(f.po))
    doc = f.return_approve(f.return_body(source))
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Trả từng phần")
    key = uuid4()
    result = ok(f.return_post(doc, body, key))
    assert result["status"] == "COMPLETED"
    assert ok(f.return_post(doc, body, key)) == ok(f.return_post(doc, body)) == result
    assert f.return_post(doc, {**body, "reason": "Khác"}, key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.return_post(doc, {**body, "reason": "Khác"}).json()["code"] == "EXECUTION_MISMATCH"
    assert ok(f.request("GET", f"returns/operations/{key}", who="manager"))["transaction_id"] == result["transaction_id"]
    assert f.return_sources()["items"][0]["remaining_base"] == "6.000000"
    ok(f.return_post(f.return_approve(f.return_body(source, "6"))))
    assert f.request("POST", "returns", f.return_body(source, "1")).json()["code"] == "SOURCE_EXCEEDED"
    assert ok(f.read(f.po)) == before
    assert ok(f.read(result, kind="returns"))["lines"][0]["posted_base"] == "4.000000"
    reconcile(f)


def test_returns_customer_quarantine_then_qc_putaway_preserves_so(returning):
    f = returning
    source, _, so = f.issued_source()
    before = ok(f.read(so, kind="sales-orders"))
    for qty in ("3", "4"):
        doc = f.return_approve(f.return_body(source, qty, "CUSTOMER_RETURN", f.quarantine["id"]))
        ok(f.return_post(doc))
        quality = next(r for r in ok(f.request("GET", f"quality/sources?warehouse_id={f.warehouse}"))["items"] if r["receipt_id"] == doc["id"])
        ok(f.quality_decide(quality, qty, "0"))
        move = f.move_approve(f.move_body(quality, f.quality_history(quality)["items"]))
        ok(f.move_post(move))
    assert f.return_sources("CUSTOMER_RETURN")["items"][0]["remaining_base"] == "0.000000"
    assert ok(f.read(so, kind="sales-orders")) == before
    reconcile(f)


def test_returns_concurrent_source_limit_two_four_from_five(returning):
    f = returning
    f.received("5")
    source = f.return_sources()["items"][0]
    docs = [f.return_approve(f.return_body(source)) for _ in range(2)]
    barrier = Barrier(2)
    def post(doc):
        barrier.wait(5)
        return f.return_post(doc)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(post, docs))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r for r in results if r.status_code == 409).json()["code"] == "SOURCE_EXCEEDED"
    assert f.return_sources()["items"][0]["returned_base"] == "4.000000"
    reconcile(f)


def test_returns_atomic_rollback_after_effects_and_retry(returning, monkeypatch):
    f = returning
    f.received("10")
    doc = f.return_approve(f.return_body(f.return_sources()["items"][0]))
    service = f.client.app.state.orders
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("Failure after ledger balance audit outbox")
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Rollback trả")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert f.return_post(doc, body, key).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE document_id=:id"), {"id": doc["id"]}).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='return.post'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='return.post.v1'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 10
    assert ok(f.return_post(doc, body, key))["status"] == "COMPLETED"
    reconcile(f)


def test_returns_serial_race_reuses_identity_and_warranty_source(returning):
    f = returning
    source, received, _ = f.issued_source("1", "RETURN-SERIAL")
    serial = source["serial_id"]
    trace_path = f"serials/{serial}/warranty?warehouse_id={f.warehouse}"
    before = ok(f.request("GET", trace_path))
    docs = [f.return_approve(f.return_body(source, "1", "CUSTOMER_RETURN", f.quarantine["id"])) for _ in range(2)]
    barrier = Barrier(2)
    def post(doc):
        barrier.wait(5)
        return f.return_post(doc)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(post, docs))
    assert sorted(r.status_code for r in results) == [200, 409]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial")).scalar_one() == 1
        assert str(c.execute(text("SELECT serial_id FROM wms.serial_position")).scalar_one()) == serial
        assert c.execute(text("SELECT count(*) FROM wms.serial_warranty_record")).scalar_one() == 0
    after = ok(f.request("GET", trace_path))
    assert {k: v for k, v in after.items() if k != "as_of"} == {k: v for k, v in before.items() if k != "as_of"}
    assert source["stock_item_id"] == received["stock_item_id"]
    reconcile(f)


def test_returns_lifecycle_permissions_stale_source_and_paging(returning):
    f = returning
    f.received("10")
    source = f.return_sources()["items"][0]
    body = f.return_body(source)
    doc = ok(f.request("POST", "returns", body), 201)
    assert f.return_post(doc).json()["code"] == "INVALID_STATE"
    changed = ok(f.request("PUT", "returns/" + doc["id"], {**body, "expected_version": 1, "lines": [{**body["lines"][0], "quantity_base": "2"}]}))
    assert f.action(doc, "submit").json()["code"] == "STALE_VERSION"
    submitted = ok(f.action(changed, "submit"))
    f.iam.grant(f.buyer, "WAREHOUSE_MANAGER", f.warehouse)
    assert f.decision(submitted, "buyer").json()["code"] == "SELF_APPROVAL"
    approved = ok(f.decision(submitted))
    revised = ok(f.action(approved, "revise"))
    assert ok(f.read(revised, kind="returns"))["approvals"][0]["status"] == "INVALIDATED"
    ok(f.action(revised, "cancel", who="manager"))
    ok(f.request("POST", "returns", body), 201)
    first = ok(f.request("GET", f"returns?kind=SUPPLIER_RETURN&warehouse_id={f.warehouse}&limit=1"))
    assert first["next_after"]
    second = ok(f.request("GET", f"returns?kind=SUPPLIER_RETURN&warehouse_id={f.warehouse}&limit=1&after={first['next_after']}"))
    assert first["items"][0]["id"] != second["items"][0]["id"]
    bad = deepcopy(body)
    bad["lines"][0]["source_move_id"] = str(uuid4())
    assert f.request("POST", "returns", bad).json()["code"] == "SOURCE_MISMATCH"


@pytest.mark.parametrize("change,code", [("period", "PERIOD_CLOSED"), ("stock", "INSUFFICIENT_STOCK")])
def test_returns_rechecks_live_period_and_physical_stock(returning, change, code):
    f = returning
    source = f.received("10")
    doc = f.return_approve(f.return_body(f.return_sources()["items"][0]))
    if change == "period":
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": f.warehouse})
    else:
        f.putaway("10", "0", source)
    assert f.return_post(doc).json()["code"] == code
    reconcile(f)


def test_returns_quarantine_policy_and_customer_destination(returning):
    f = returning
    source = f.received("10")
    f.putaway("0", "10", source)
    body = f.return_body(f.return_sources()["items"][0], location=f.quarantine["id"])
    assert f.request("POST", "returns", body).json()["code"] == "QUARANTINE_POLICY_REQUIRED"
    f.client.app.state.returns.identity.settings.supplier_return_quarantine_enabled = True
    doc = f.return_approve(body)
    f.client.app.state.returns.identity.settings.supplier_return_quarantine_enabled = False
    assert f.return_post(doc).json()["code"] == "STALE_APPROVAL"
    f.client.app.state.returns.identity.settings.supplier_return_quarantine_enabled = True
    ok(f.return_post(doc))
    assert Decimal(f.return_sources()["items"][0]["returned_base"]) == 4
    reconcile(f)


def test_returns_supplier_protects_expired_reservation_and_other_location(returning):
    f = returning
    held, reservation, received, _ = f.issued_source(post=False, stock_qty="10")
    source = next(r for r in f.return_sources()["items"] if r["document_id"] == received["receipt_id"])
    doc = f.return_approve(f.return_body(source, "4", location=f.bin["id"]))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.reservation SET expires_at='2026-10-01' WHERE id=:id"), {"id": reservation["id"]})
    assert f.return_post(doc).json()["code"] == "INSUFFICIENT_STOCK"
    ok(f.return_post(f.return_approve(f.return_body(source, "3", location=f.bin["id"])) ))
    with f.engine.connect() as c:
        row = c.execute(text("SELECT on_hand,reserved FROM wms.stock_balance WHERE location_id=:id"), {"id": f.bin["id"]}).one()
        assert tuple(row) == (7, 7)
    assert ok(f.read(held, kind="issues"))["reservations"][0]["remaining_base"] == "7.000000"
    reconcile(f)


def test_returns_owner_policy_rejects_real_consignment_source(returning):
    f = returning
    f.received("10")
    owner, contract = agreement(f)
    body = dict(warehouse_id=str(f.warehouse), batch_key=str(uuid4()), business_date="2026-10-02",
        delivery_reference="Biên bản hàng ký gửi", reason="Nhận ký gửi", lines=[dict(product_id=f.product["id"],
        quantity_base="5", owner_id=owner["id"], consignment_id=contract["id"], destination_location_id=f.location["id"])])
    doc = ok(f.request("POST", "consignment-receipts", body), 201)
    doc = ok(f.decision(ok(f.action(doc, "submit")), "manager"))
    ok(f.request("POST", f"consignment-receipts/{doc['id']}/post", dict(expected_version=doc["version"],
        execution_key=str(uuid4()), reason="Ghi nhập ký gửi")))
    source = next(r for r in f.return_sources()["items"] if r["document_id"] == doc["id"])
    assert not source["returnable"] and source["blocked_reason"]
    assert f.request("POST", "returns", f.return_body(source)).json()["code"] == "OWNER_POLICY_REQUIRED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 15
    reconcile(f)


def test_returns_scope_current_permission_replay_and_source_pagination(returning):
    f = returning
    receipt = deepcopy(f.receipt_body)
    receipt["lines"][0]["quantity_base"] = "10"
    f.received("10", receipt)
    f.received("10", receipt)
    page = f.return_sources(limit=1)
    following = f.return_sources(limit=1, after=page["next_after"])
    assert len(page["items"]) == len(following["items"]) == 1
    assert page["items"][0]["id"] != following["items"][0]["id"]
    doc = f.return_approve(f.return_body(page["items"][0]))
    key = uuid4()
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Quyền hiện tại")
    ok(f.return_post(doc, body, key))
    outsider, _ = f.iam.user("return-outsider")
    other = f.iam.warehouse("RETURN-OTHER")
    f.iam.grant(outsider, "WAREHOUSE_MANAGER", other)
    f.headers["outsider"] = f.iam.headers(f.iam.login("return-outsider"))
    assert f.request("GET", f"returns/{doc['id']}", who="outsider").status_code == 404
    assert f.request("GET", f"returns/sources?kind=SUPPLIER_RETURN&warehouse_id={f.warehouse}", who="outsider").status_code == 404
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:user"), {"now": f.iam.now, "user": f.manager})
    assert f.return_post(doc, body, key).status_code in {403, 404}
    assert f.request("GET", f"returns/operations/{key}", who="manager").status_code in {403, 404}


def test_returns_customer_rejects_eligible_destination_and_duplicate_source_total(returning):
    f = returning
    source, _, _ = f.issued_source()
    bad = f.return_body(source, "1", "CUSTOMER_RETURN", f.bin["id"])
    assert f.request("POST", "returns", bad).json()["code"] == "QUALITY_REQUIRED"
    bad = f.return_body(source, "4", "CUSTOMER_RETURN", f.quarantine["id"])
    bad["lines"] *= 2
    assert f.request("POST", "returns", bad).json()["code"] == "SOURCE_EXCEEDED"
    bad["lines"] = [{**bad["lines"][0], "quantity_base": "1", "stock_item_id": str(uuid4())}]
    assert f.request("POST", "returns", bad).status_code == 422


@pytest.mark.parametrize("lock_kind,code", [("period", "PERIOD_CLOSED"), ("location", "LOCATION_FROZEN")])
def test_returns_waits_for_period_close_or_count_freeze(returning, lock_kind, code):
    f = returning
    f.received("10")
    doc = f.return_approve(f.return_body(f.return_sources()["items"][0]))
    attempted = Event()
    def query(connection, cursor, statement, parameters, context, many):
        table = "stock_period" if lock_kind == "period" else "location"
        if f"FROM wms.{table} " in statement and "FOR UPDATE" in statement:
            if lock_kind == "period" or str(parameters.get("id")) == f.location["id"]:
                attempted.set()
    with ThreadPoolExecutor(1) as pool:
        with f.engine.begin() as c:
            if lock_kind == "period":
                c.execute(text("SELECT id FROM wms.stock_period WHERE warehouse_id=:id FOR UPDATE"), {"id": f.warehouse})
                c.execute(text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": f.warehouse})
            else:
                c.execute(text("SELECT id FROM wms.location WHERE id=:id FOR UPDATE"), {"id": f.location["id"]})
                count = uuid4()
                c.execute(text("""INSERT INTO wms.count_session(id,warehouse_id,number,status,created_by,frozen_at,version)
                    VALUES (:id,:warehouse,'RETURN-FREEZE','FROZEN',:actor,now(),1)"""), {"id": count, "warehouse": f.warehouse, "actor": f.manager})
                c.execute(text("INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES (:id,:session,:location,now())"),
                    {"id": uuid4(), "session": count, "location": f.location["id"]})
            event.listen(f.engine, "before_cursor_execute", query)
            future = pool.submit(f.return_post, doc)
            try:
                assert attempted.wait(5)
            finally:
                event.remove(f.engine, "before_cursor_execute", query)
        assert future.result(timeout=10).json()["code"] == code
    reconcile(f)


def test_returns_parallel_execution_and_no_repost(returning):
    f = returning
    f.received("10")
    doc = f.return_approve(f.return_body(f.return_sources()["items"][0]))
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Race execution")
    barrier = Barrier(2)
    def post(_):
        barrier.wait(5)
        return ok(f.return_post(doc, body))
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(post, range(2)))
    assert results[0] == results[1]
    assert f.return_sources()["items"][0]["returned_base"] == "4.000000"
    reconcile(f)


@pytest.mark.parametrize("prefix", [10, 14])
def test_returns_upgrade_preserves_operator_policy_and_prior_history(empty_database, monkeypatch, prefix):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix])
        migrations.migrate(empty_database)
    policy = uuid4()
    with empty_database.begin() as c:
        c.execute(text("INSERT INTO wms.approval_policy VALUES (:id,'SUPPLIER_RETURN',9,false)"), {"id": policy})
        before = c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()
    assert migrations.migrate(empty_database) == [s[0] for s in sources[prefix:]]
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as c:
        assert c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()[:prefix] == before
        assert tuple(c.execute(text("SELECT id,revision,is_active FROM wms.approval_policy WHERE document_kind='SUPPLIER_RETURN'")).one()) == (policy, 9, False)


def test_returns_expired_lot_to_supplier_uses_physical_free_quantity(returning):
    f = returning
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='LOT' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(quantity_base="10", lot_code="RETURN-EXPIRED", expires_on="2026-10-01", destination_location_id=f.quarantine["id"])
    f.received("10", body)
    source = f.return_sources()["items"][0]
    assert source["lot_code"] == "RETURN-EXPIRED"
    f.client.app.state.returns.identity.settings.supplier_return_quarantine_enabled = True
    doc = f.return_approve(f.return_body(source, "4", location=f.quarantine["id"]))
    ok(f.return_post(doc))
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 6
        assert c.execute(text("SELECT count(DISTINCT stock_item_id) FROM wms.stock_move")).scalar_one() == 1
    reconcile(f)


def test_returns_customer_serial_rollback_keeps_absent_position_and_same_retry(returning, monkeypatch):
    f = returning
    source, _, _ = f.issued_source("1", "ROLLBACK-RETURN")
    doc = f.return_approve(f.return_body(source, "1", "CUSTOMER_RETURN", f.quarantine["id"]))
    service = f.client.app.state.orders
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("Failure after serial position and effects")
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Rollback serial return")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert f.return_post(doc, body, key).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == 0
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
    ok(f.return_post(doc, body, key))
    reconcile(f)


def test_returns_source_lock_rechecks_reversal_committed_by_other_session(returning):
    # B14 is not integrated: this fixture exercises its documented source-lock
    # protocol with a real PG reversal ledger, not a fake B14 API.
    f = returning
    f.received("10")
    source = f.return_sources()["items"][0]
    doc = f.return_approve(f.return_body(source))
    attempted = Event()
    def query(connection, cursor, statement, parameters, context, many):
        if "FROM wms.document " in statement and "FOR UPDATE" in statement and str(parameters.get("id")) == source["document_id"]:
            attempted.set()
    with ThreadPoolExecutor(1) as pool:
        with f.engine.begin() as c:
            c.execute(text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": source["document_id"]})
            event.listen(f.engine, "before_cursor_execute", query)
            future = pool.submit(f.return_post, doc)
            try:
                assert attempted.wait(5)
            finally:
                event.remove(f.engine, "before_cursor_execute", query)
            reversal, line, tx = uuid4(), uuid4(), uuid4()
            c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes)
                VALUES (:id,'RETURN-SOURCE-REVERSE','REVERSAL','COMPLETED',:warehouse,'2026-10-02',:actor,now(),1,'{}')"""),
                {"id": reversal, "warehouse": f.warehouse, "actor": f.manager})
            c.execute(text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,consignment_id)
                SELECT :line,:doc,1,l.product_id,m.base_uom_id,m.quantity_base,1,m.quantity_base,l.owner_id,l.consignment_id
                FROM wms.stock_move m JOIN wms.document_line l ON l.id=m.line_id WHERE m.id=:source"""),
                {"line": line, "doc": reversal, "source": source["id"]})
            c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by,reverses_transaction_id)
                SELECT :id,:doc,:id,'REVERSE','2026-10-02',now(),:actor,transaction_id FROM wms.stock_move WHERE id=:source"""),
                {"id": tx, "doc": reversal, "actor": f.manager, "source": source["id"]})
            c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id,reverses_move_id)
                SELECT :id,:tx,:line,stock_item_id,destination_location_id,source_location_id,quantity_base,base_uom_id,id
                FROM wms.stock_move WHERE id=:source"""), {"id": uuid4(), "tx": tx, "line": line, "source": source["id"]})
            c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand-10,version=version+1 WHERE stock_item_id=:stock AND location_id=:location"),
                      {"stock": source["stock_item_id"], "location": f.location["id"]})
        assert future.result(timeout=10).json()["code"] == "SOURCE_MISMATCH"
    reconcile(f)


def test_returns_allocations_distinguish_two_partial_posts_of_one_receipt_line(returning):
    f = returning
    receipt = f.receipt_approve()
    first = ok(f.post(receipt, f.post_body(receipt, "4")))
    ok(f.post(first, f.post_body(first, "6")))
    sources = f.return_sources()["items"]
    assert len(sources) == 2 and sources[0]["source_line_id"] == sources[1]["source_line_id"]
    small = next(s for s in sources if Decimal(s["posted_base"]) == 4)
    assert f.request("POST", "returns", f.return_body(small, "5")).json()["code"] == "SOURCE_EXCEEDED"
    body = f.return_body(small)
    body["lines"] = [dict(source_move_id=s["id"], location_id=f.location["id"], quantity_base=s["posted_base"]) for s in sources]
    ok(f.return_post(f.return_approve(body)))
    assert all(s["remaining_base"] == "0.000000" for s in f.return_sources()["items"])
    reconcile(f)
