from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401

from packages.contracts.traceability import UNCLASSIFIED_OWNER

pytestmark = pytest.mark.integration


@pytest.fixture
def movement(receiving):  # noqa: F811
    f = receiving
    zone = f.master("locations", code="ZONE-MOVE", name="Zone", kind="GROUP", warehouse_id=str(f.warehouse))
    rack = f.master("locations", code="RACK-MOVE", name="Rack", kind="GROUP", warehouse_id=str(f.warehouse), parent_id=zone["id"])
    f.bin = f.master("locations", code="BIN-MOVE", name="Bin", kind="STORAGE", warehouse_id=str(f.warehouse), parent_id=rack["id"])
    f.bin2 = f.master("locations", code="BIN-MOVE-2", name="Bin 2", kind="STORAGE", warehouse_id=str(f.warehouse), parent_id=rack["id"])
    f.quality_zone, f.quality_rack = zone, rack

    def request(method, path, body=None, who="buyer", key=None):
        return f.client.request(method, "/api/v1/" + path, json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())})

    def received(qty="80", body=None):
        doc = f.receipt_approve(body)
        ok(f.post(doc, f.post_body(doc, qty)))
        rows = ok(request("GET", f"quality/sources?warehouse_id={f.warehouse}"))["items"]
        return next(r for r in rows if r["receipt_id"] == doc["id"])

    def history(source):
        return ok(request("GET", "quality/sources/" + source["id"]))

    def decide(source, accepted="75", rejected="5", who="manager", key=None):
        return request("POST", "quality/sources/" + source["id"] + "/decide",
                       {"expected_version": source["version"], "accepted_base": accepted,
                        "rejected_base": rejected, "reason": "Kiểm định hàng đã nhận"}, who, key)

    def draft(source, decisions=None, qty="75", destination=None):
        lines = []
        for q in decisions or []:
            lines.append(dict(stock_item_id=source["stock_item_id"], source_location_id=source["source_location_id"],
                destination_location_id=f.bin["id"] if q["result"] == "ACCEPT" else f.quarantine["id"],
                quantity_base=q["quantity"], quality_decision_id=q["id"]))
        if not lines:
            lines = [dict(stock_item_id=source["stock_item_id"], source_location_id=f.bin["id"],
                          destination_location_id=destination or f.bin2["id"], quantity_base=qty)]
        return dict(warehouse_id=str(f.warehouse), business_date="2026-10-02", reason="Cất/chuyển theo quyết định", lines=lines)

    def approve(body):
        doc = ok(request("POST", "moves", body), 201)
        return ok(f.decision(ok(f.action(doc, "submit"))))

    def post(doc, body=None, key=None, who="buyer"):
        return request("POST", "moves/" + doc["id"] + "/post", body or {
            "expected_version": doc["version"], "execution_key": str(uuid4()), "reason": "Ghi sổ cất/chuyển"}, who, key)

    def putaway(accepted="75", rejected="5", source=None):
        source = source or received()
        ok(decide(source, accepted, rejected))
        doc = approve(draft(source, history(source)["items"]))
        return source, ok(post(doc))

    f.move_request, f.received, f.quality_history, f.quality_decide = request, received, history, decide
    f.move_body, f.move_approve, f.move_post, f.putaway = draft, approve, post, putaway
    return f


def reconcile(f):
    raw = f.engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute((Path(__file__).resolve().parents[2] / "02_CSDL/reconcile.sql").read_text())
            while True:
                if cursor.description:
                    assert cursor.fetchall() == []
                if not cursor.nextset():
                    break
    finally:
        raw.close()


def test_move_quality_t01_receipt_80_accept_75_reject_5_conserves_stock_and_po(movement):
    f = movement
    source = f.received()
    key = uuid4()
    result = ok(f.quality_decide(source, key=key))
    assert ok(f.quality_decide(source, key=key)) == result
    assert f.quality_decide(source, "74", "6", key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    decisions = f.quality_history(source)["items"]
    assert len(decisions) == 2
    doc = f.move_approve(f.move_body(source, decisions))
    body = {"expected_version": doc["version"], "execution_key": str(uuid4()), "reason": "Thực hiện cất hàng"}
    key = uuid4()
    posted = ok(f.move_post(doc, body, key))
    assert ok(f.move_post(doc, body, key)) == posted
    assert ok(f.move_post(doc, body)) == posted
    assert f.move_post(doc, {**body, "reason": "Nội dung khác"}).json()["code"] == "EXECUTION_MISMATCH"
    assert ok(f.move_request("GET", f"moves/operations/{key}"))["transaction_id"] == posted["transaction_id"]
    assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "20.000000"
    current = ok(f.move_request("GET", "moves/" + doc["id"]))
    assert current["status"] == "COMPLETED" and all(r["remaining_base"] == "0.000000" for r in current["lines"])
    stock = ok(f.move_request("GET", f"moves/stock?warehouse_id={f.warehouse}"))["items"]
    assert sum(Decimal(r["on_hand"]) for r in stock) == 80
    assert sum(Decimal(r["eligible_base"]) for r in stock) == 75
    assert sum(Decimal(r["available_base"]) for r in stock) == 75
    assert {r["source_kind"]: r["on_hand"] for r in stock} == {"STORAGE": "75.000000", "QUARANTINE": "5.000000"}
    assert all(r["remaining_base"] == "0.000000" and r["followup_document_id"] == doc["id"] for r in f.quality_history(source)["items"])
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='MOVE'")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='move.post'")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='move.post.v1'")).scalar_one() == 1
    reconcile(f)


def test_move_quality_source_limits_stale_sod_and_missing_evidence(movement):
    f = movement
    source = f.received()
    assert f.quality_decide(source, "81", "0").json()["code"] == "SOURCE_EXCEEDED"
    assert f.quality_decide(source, who="buyer").status_code == 403
    ok(f.quality_decide(source, "75", "0"))
    assert f.quality_decide(source, "1", "0").json()["code"] == "STALE_VERSION"
    remaining = f.quality_history(source)["source"]
    assert remaining["remaining_base"] == "5.000000"
    assert f.quality_decide(remaining, "6", "0").json()["code"] == "SOURCE_EXCEEDED"
    body = f.move_body(source, f.quality_history(source)["items"])
    missing = deepcopy(body)
    missing["lines"][0]["quality_decision_id"] = None
    assert f.move_request("POST", "moves", missing).json()["code"] == "QUALITY_REQUIRED"
    doc = ok(f.move_request("POST", "moves", body), 201)
    assert f.move_post(doc).json()["code"] == "INVALID_STATE"
    f.iam.grant(f.buyer, "WAREHOUSE_MANAGER", f.warehouse)
    submitted = ok(f.action(doc, "submit"))
    assert f.decision(submitted, "buyer").json()["code"] == "SELF_APPROVAL"
    approved = ok(f.decision(submitted))
    stale = {"expected_version": approved["version"] - 1, "execution_key": str(uuid4()), "reason": "Thử stale"}
    assert f.move_post(approved, stale).json()["code"] == "STALE_VERSION"
    with f.engine.begin() as c:
        c.execute(text("""UPDATE wms.move_line SET destination_location_id=:id WHERE document_line_id IN
            (SELECT id FROM wms.document_line WHERE document_id=:doc)"""), {"id": f.bin2["id"], "doc": doc["id"]})
    assert f.move_post(approved).json()["code"] == "STALE_APPROVAL"


def test_move_quality_reserved_stock_stays_at_source_and_owner_is_immutable(movement):
    f = movement
    source, _ = f.putaway()
    sale = ok(f.create("sales-orders"), 201)
    with f.engine.begin() as c:
        line = c.execute(text("SELECT id FROM wms.document_line WHERE document_id=:id"), {"id": sale["id"]}).scalar_one()
        c.execute(text("""INSERT INTO wms.reservation(id,line_id,stock_item_id,location_id,quantity,consumed,released,expires_at,created_by)
            VALUES (:id,:line,:stock,:location,10,0,0,'2020-01-01',:actor)"""),
                  {"id": uuid4(), "line": line, "stock": source["stock_item_id"], "location": f.bin["id"], "actor": f.buyer})
        c.execute(text("UPDATE wms.stock_balance SET reserved=10 WHERE stock_item_id=:stock AND location_id=:location"),
                  {"stock": source["stock_item_id"], "location": f.bin["id"]})
    too_much = f.move_approve(f.move_body(source, qty="66"))
    assert f.move_post(too_much).json()["code"] == "INSUFFICIENT_STOCK"
    stock = ok(f.move_request("GET", f"moves/stock?warehouse_id={f.warehouse}"))["items"]
    available = next(r for r in stock if r["source_location_id"] == f.bin["id"])
    assert (available["eligible_base"], available["available_base"], available["movable_base"]) == ("75.000000", "65.000000", "65.000000")
    doc = f.move_approve(f.move_body(source, qty="65"))
    ok(f.move_post(doc))
    with f.engine.connect() as c:
        assert tuple(c.execute(text("SELECT on_hand,reserved FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:location"),
                               {"stock": source["stock_item_id"], "location": f.bin["id"]}).one()) == (10, 10)
        assert c.execute(text("SELECT count(DISTINCT stock_item_id) FROM wms.stock_move")).scalar_one() == 1
    changed = f.move_body(source, qty="1")
    changed["lines"][0]["owner_id"] = str(uuid4())
    assert f.move_request("POST", "moves", changed).status_code == 422
    reconcile(f)


@pytest.mark.parametrize("change,code", [("period", "PERIOD_CLOSED"), ("freeze", "LOCATION_FROZEN"),
                                       ("inactive", "INVALID_LOCATION"), ("cycle", "INVALID_TREE"),
                                       ("wrong_warehouse", "INVALID_LOCATION")])
def test_move_quality_rechecks_period_freeze_location_tree_at_post(movement, change, code):
    f = movement
    source = f.received()
    ok(f.quality_decide(source, "80", "0"))
    doc = f.move_approve(f.move_body(source, f.quality_history(source)["items"]))
    with f.engine.begin() as c:
        if change == "period":
            c.execute(text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": f.warehouse})
        elif change == "freeze":
            count = uuid4()
            c.execute(text("""INSERT INTO wms.count_session(id,warehouse_id,number,status,created_by,frozen_at,version)
                VALUES (:id,:warehouse,'MOVE-COUNT','FROZEN',:actor,now(),1)"""), {"id": count, "warehouse": f.warehouse, "actor": f.manager})
            c.execute(text("INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES (:id,:session,:location,now())"),
                      {"id": uuid4(), "session": count, "location": f.bin["id"]})
        elif change == "inactive":
            c.execute(text("UPDATE wms.location SET is_active=false WHERE id=:id"), {"id": f.quality_zone["id"]})
        elif change == "cycle":
            c.execute(text("UPDATE wms.location SET parent_id=:rack WHERE id=:id"), {"id": f.quality_zone["id"], "rack": f.quality_rack["id"]})
        else:
            other = f.iam.warehouse("OTHER-MOVE")
            c.execute(text("UPDATE wms.location SET warehouse_id=:warehouse WHERE id=:id"), {"warehouse": other, "id": f.bin["id"]})
    assert f.move_post(doc).json()["code"] == code
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='MOVE'")).scalar_one() == 0


def test_move_quality_atomic_rollback_after_ledger_audit_outbox(movement, monkeypatch):
    f = movement
    source = f.received()
    ok(f.quality_decide(source))
    doc = f.move_approve(f.move_body(source, f.quality_history(source)["items"]))
    service = f.client.app.state.orders
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("Injected failure after effects")
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        key = uuid4()
        body = {"expected_version": doc["version"], "execution_key": str(uuid4()), "reason": "Rollback thử nghiệm"}
        assert f.move_post(doc, body, key).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='MOVE'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='move.post'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='move.post.v1'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.quality_decision WHERE followup_document_id IS NOT NULL")).scalar_one() == 0
    ok(f.move_post(doc, body, key))
    reconcile(f)


def test_move_quality_concurrent_decisions_and_putaway_cannot_overallocate(movement):
    f = movement
    source = f.received()
    barrier = Barrier(2)
    def decide(_):
        barrier.wait(5)
        return f.quality_decide(source, "80", "0")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    body = f.move_body(source, f.quality_history(source)["items"])
    docs = [f.move_approve(body), f.move_approve(body)]
    barrier = Barrier(2)
    def post(index):
        barrier.wait(5)
        return f.move_post(docs[index])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r.json()["code"] for r in results if r.status_code != 200) == "SOURCE_EXCEEDED"
    reconcile(f)


def test_move_quality_same_execution_race_replay_rechecks_permission(movement):
    f = movement
    source = f.received()
    ok(f.quality_decide(source))
    doc = f.move_approve(f.move_body(source, f.quality_history(source)["items"]))
    body = {"expected_version": doc["version"], "execution_key": str(uuid4()), "reason": "Race execution"}
    barrier = Barrier(2)
    def post(_):
        barrier.wait(5)
        return f.move_post(doc, body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [ok(r) for r in pool.map(post, range(2))]
    assert results[0] == results[1]
    key = uuid4()
    ok(f.move_post(doc, body, key))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:user AND role_id IN (SELECT id FROM wms.role WHERE code='RECEIVER')"),
                  {"now": f.iam.now, "user": f.buyer})
    assert f.move_post(doc, body, key).status_code == 403
    assert f.move_request("GET", f"moves/operations/{key}").status_code == 403


def test_move_quality_lot_expiry_and_serial_race(movement):
    f = movement
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='SERIAL' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(quantity_base="1", serial_code="MOVE-SERIAL-1")
    source = f.received("1", body)
    assert f.quality_decide(source, "0.5", "0.5").status_code == 409
    source, _ = f.putaway("1", "0", source)
    docs = [f.move_approve(f.move_body(source, qty="1")), f.move_approve(f.move_body(source, qty="1", destination=f.quarantine["id"]))]
    barrier = Barrier(2)
    def post(index):
        barrier.wait(5)
        return f.move_post(docs[index])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == 1
        assert c.execute(text("SELECT SUM(on_hand) FROM wms.stock_balance")).scalar_one() == 1
    reconcile(f)


def test_move_quality_expiry_uses_today_not_backdated_document(movement):
    f = movement
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='LOT' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(lot_code="LOT-MOVE", expires_on="2026-10-03")
    source = f.received("80", body)
    ok(f.quality_decide(source, "80", "0"))
    doc = f.move_approve(f.move_body(source, f.quality_history(source)["items"]))
    f.iam.advance(3 * 24 * 3600)
    f.headers["buyer"] = f.iam.headers(f.iam.login("buyer"))
    assert f.move_post(doc).json()["code"] == "LOT_EXPIRED"


def test_move_quality_decisions_immutable_and_scope_hidden(movement):
    f = movement
    source = f.received()
    ok(f.quality_decide(source))
    qid = f.quality_history(source)["items"][0]["id"]
    with pytest.raises(IntegrityError):
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.quality_decision SET quantity=999 WHERE id=:id"), {"id": qid})
    outsider, _ = f.iam.user("move-outsider")
    other = f.iam.warehouse("MOVE-OTHER")
    f.iam.grant(outsider, "WAREHOUSE_MANAGER", other)
    f.headers["outsider"] = f.iam.headers(f.iam.login("move-outsider"))
    assert f.move_request("GET", "quality/sources/" + source["id"], who="outsider").status_code == 404
    assert f.move_request("GET", f"moves/stock?warehouse_id={f.warehouse}", who="outsider").status_code == 404


def test_move_quality_upgrade_from_010_preserves_data_and_custom_policy(empty_database, monkeypatch):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:10])
        migrations.migrate(empty_database)
    policy = uuid4()
    with empty_database.begin() as c:
        c.execute(text("INSERT INTO wms.approval_policy VALUES (:id,'INTERNAL_MOVE',9,false)"), {"id": policy})
        c.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:id,'UPGRADE-MOVE','Existing',true)"), {"id": uuid4()})
    assert migrations.migrate(empty_database) == [source[0] for source in sources[10:]]
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as c:
        assert tuple(c.execute(text("SELECT id,revision,is_active FROM wms.approval_policy WHERE document_kind='INTERNAL_MOVE'")).one()) == (policy, 9, False)
        assert c.execute(text("SELECT name FROM wms.warehouse WHERE code='UPGRADE-MOVE'")).scalar_one() == "Existing"


def test_move_quality_decision_rollback_and_current_permission_on_replay(movement, monkeypatch):
    f = movement
    source, key = f.received(), uuid4()
    service = f.client.app.state.orders
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("Injected failure after quality evidence and effects")
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert f.quality_decide(source, key=key).status_code == 500
    assert f.quality_history(source)["source"]["version"] == source["version"]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.quality_decision")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='quality.decide'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='quality.decide.v1'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
    result = ok(f.quality_decide(source, key=key))
    assert ok(f.quality_decide(source, key=key)) == result
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:user"), {"now": f.iam.now, "user": f.manager})
    assert f.quality_decide(source, key=key).status_code in {403, 404}
    reconcile(f)


def test_move_quality_edit_reapprove_cancel_and_paginated_queries(movement):
    f = movement
    source = f.received()
    ok(f.quality_decide(source))
    qpage = ok(f.move_request("GET", "quality/sources/" + source["id"] + "?limit=1"))
    qnext = ok(f.move_request("GET", "quality/sources/" + source["id"] + "?limit=1&after=" + qpage["next_after"]))
    assert len(qpage["items"]) == len(qnext["items"]) == 1 and qnext["next_after"] is None
    assert qpage["items"][0]["id"] != qnext["items"][0]["id"]
    body = f.move_body(source, f.quality_history(source)["items"])
    doc = ok(f.move_request("POST", "moves", body), 201)
    body["lines"][0]["quantity_base"] = "1"
    doc = ok(f.move_request("PUT", "moves/" + doc["id"], {**body, "expected_version": doc["version"]}))
    submitted = ok(f.action(doc, "submit"))
    rejected = ok(f.decision(submitted, decision="REJECT"))
    edited = ok(f.move_request("PUT", "moves/" + doc["id"], {**body, "expected_version": rejected["version"]}))
    approved = ok(f.decision(ok(f.action(edited, "submit"))))
    revised = ok(f.action(approved, "revise"))
    assert revised["status"] == "DRAFT"
    approved = ok(f.decision(ok(f.action(revised, "submit"))))
    assert f.action(approved, "cancel").status_code == 403
    cancelled = ok(f.action(approved, "cancel", who="manager"))
    assert cancelled["status"] == "CANCELLED" and f.move_post(cancelled).status_code == 409
    other = ok(f.move_request("POST", "moves", body), 201)
    page = ok(f.move_request("GET", f"moves?warehouse_id={f.warehouse}&limit=1"))
    following = ok(f.move_request("GET", f"moves?warehouse_id={f.warehouse}&limit=1&after={page['next_after']}"))
    assert {r["id"] for r in page["items"] + following["items"]} == {doc["id"], other["id"]}
    locations = ok(f.move_request("GET", f"moves/locations?warehouse_id={f.warehouse}&limit=1"))
    assert len(locations["items"]) == 1 and locations["next_after"]
    assert f.quality_history(source)["source"]["remaining_base"] == "0.000000"
    assert sum(Decimal(r["moved_base"]) for r in f.quality_history(source)["items"]) == 0
    reconcile(f)


def test_move_quality_preserves_consigned_owner_and_blocks_new_unclassified_stock(movement):
    f = movement
    owner = f.master("stock-owners", code="MOVE-OWNER", name="Chủ hàng ký gửi", partner_id=f.partner["id"])
    agreement = f.master("consignment-agreements", code="MOVE-AGREEMENT", owner_id=owner["id"],
        warehouse_id=str(f.warehouse), valid_from="2026-01-01", valid_until="2026-12-31", source_ref="Hợp đồng kiểm thử")
    source = f.received()
    with f.engine.begin() as c:
        consigned, unclassified = uuid4(), uuid4()
        c.execute(text("INSERT INTO wms.stock_item(id,product_id,owner_id,consignment_id) VALUES (:id,:product,:owner,:agreement)"),
                  {"id": consigned, "product": f.product["id"], "owner": owner["id"], "agreement": agreement["id"]})
    with pytest.raises(IntegrityError, match="Select an explicit owner"):
        with f.engine.begin() as c:
            c.execute(text("INSERT INTO wms.stock_item(id,product_id,owner_id) VALUES (:id,:product,:owner)"),
                      {"id": unclassified, "product": f.product["id"], "owner": UNCLASSIFIED_OWNER})
    # B09 permits same-owner internal moves, but an empty consigned identity
    # cannot borrow the 80 COMPANY units stored at exactly the same source.
    f.putaway("80", "0", source)
    doc = f.move_approve(f.move_body({**source, "stock_item_id": str(consigned)}))
    line = ok(f.read(doc, kind="moves"))["lines"][0]
    assert (line["owner_id"], line["consignment_id"]) == (owner["id"], agreement["id"])
    assert f.move_post(doc).json()["code"] == "INSUFFICIENT_STOCK"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 80
    reconcile(f)


@pytest.mark.parametrize("lock_kind,code", [("period", "PERIOD_CLOSED"), ("location", "LOCATION_FROZEN")])
def test_move_quality_waits_for_period_or_freeze_transaction(movement, lock_kind, code):
    f = movement
    source = f.received()
    ok(f.quality_decide(source, "80", "0"))
    doc = f.move_approve(f.move_body(source, f.quality_history(source)["items"]))
    attempted = Event()
    def on_query(connection, cursor, statement, parameters, context, executemany):
        if f"FROM wms.{lock_kind if lock_kind == 'location' else 'stock_period'} " in statement and "FOR UPDATE" in statement:
            if lock_kind == "period" or str(parameters.get("id")) == f.bin["id"]:
                attempted.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with f.engine.begin() as c:
            if lock_kind == "period":
                c.execute(text("SELECT id FROM wms.stock_period WHERE warehouse_id=:id FOR UPDATE"), {"id": f.warehouse})
                c.execute(text("UPDATE wms.stock_period SET status='CLOSED' WHERE warehouse_id=:id"), {"id": f.warehouse})
            else:
                c.execute(text("SELECT id FROM wms.location WHERE id=:id FOR UPDATE"), {"id": f.bin["id"]})
                count = uuid4()
                c.execute(text("""INSERT INTO wms.count_session(id,warehouse_id,number,status,created_by,frozen_at,version)
                    VALUES (:id,:warehouse,'RACE-MOVE-COUNT','FROZEN',:actor,now(),1)"""), {"id": count, "warehouse": f.warehouse, "actor": f.manager})
                c.execute(text("INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES (:id,:session,:location,now())"),
                          {"id": uuid4(), "session": count, "location": f.bin["id"]})
            event.listen(f.engine, "before_cursor_execute", on_query)
            future = pool.submit(f.move_post, doc)
            try:
                assert attempted.wait(5)
            finally:
                event.remove(f.engine, "before_cursor_execute", on_query)
        assert future.result(timeout=10).json()["code"] == code
    reconcile(f)
