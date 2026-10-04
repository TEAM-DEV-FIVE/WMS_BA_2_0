from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from test_consignments import agreement
from test_count_period import counting  # noqa: F401
from test_move_quality import (
    movement,  # noqa: F401
    reconcile,
)
from test_openings import opening, tracking  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_returns import returning  # noqa: F401
from test_transfers import missing_loss, transfer  # noqa: F401
from test_transfers import reconcile as reconcile_transfer

pytestmark = pytest.mark.integration
# Imported pytest fixtures are intentionally injected as function parameters.
# ruff: noqa: F811


def source_transaction(f, move_id):
    with f.engine.connect() as c:
        return str(c.execute(text("SELECT transaction_id FROM wms.stock_move WHERE id=:id"), {"id": move_id}).scalar_one())


def setup_reversal(f):
    def request(method, path, body=None, who="manager", key=None):
        return f.client.request(method, "/api/v1/" + path, json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())})

    def preview(tx, day="2026-10-02", who="manager"):
        return ok(request("GET", f"transactions/{tx}/reversal-preview?business_date={day}", who=who))

    def create(tx, day="2026-10-02", who="manager"):
        p = preview(tx, day, who)
        return request("POST", "reversals", dict(source_transaction_id=tx, source_version=p["source"]["source_version"],
            business_date=day, reason="Đảo lần ghi sổ nhập sai"), who)

    def approve(tx, day="2026-10-02"):
        doc = ok(create(tx, day), 201)
        return ok(f.decision(ok(f.action(doc, "submit", "manager")), "controller"))

    def post(doc, body=None, key=None, who="controller"):
        return request("POST", f"reversals/{doc['id']}/post", body or dict(expected_version=doc["version"],
            execution_key=str(uuid4()), reason="Ghi sổ đảo đã duyệt"), who, key)

    f.rev_request, f.rev_preview, f.rev_create, f.rev_approve, f.rev_post = request, preview, create, approve, post
    return f


@pytest.fixture
def reversal(receiving):  # noqa: F811
    f = setup_reversal(receiving)
    f.original = ok(f.post(f.receipt_approve()))
    return f


def test_reversal_receipt_preview_approval_net_replay_and_immutable_source(reversal):
    f = reversal
    p = f.rev_preview(f.original["transaction_id"])
    assert p["eligible"] and len(p["plan"]) == 1
    assert p["plan"][0]["source_location_id"] == f.location["id"]
    assert p["effects"][0]["projected_on_hand"] == "0.000000"
    approved = f.rev_approve(f.original["transaction_id"])
    body = dict(expected_version=approved["version"], execution_key=str(uuid4()), reason="Đảo đã duyệt")
    key = uuid4()
    posted = ok(f.rev_post(approved, body, key))
    assert posted == ok(f.rev_post(approved, body, key)) == ok(f.rev_post(approved, body))
    assert posted["status"] == "COMPLETED" and posted["source_transaction_id"] == f.original["transaction_id"]
    assert f.rev_post(approved, {**body, "reason": "Khác"}, key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.rev_post(approved, {**body, "reason": "Khác"}).json()["code"] == "EXECUTION_MISMATCH"
    assert ok(f.rev_request("GET", f"reversals/operations/{key}", who="controller"))["result"] == posted
    assert f.rev_preview(f.original["transaction_id"])["blockers"][0]["code"] == "ALREADY_REVERSED"
    assert f.rev_preview(posted["transaction_id"])["blockers"][0]["code"] == "REVERSAL_OF_REVERSAL"
    assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "100.000000"
    original = f.receipt_read(f.original)
    assert original["status"] == f.original["status"] and original["lines"][0]["posted_base"] == "0.000000"
    view = ok(f.rev_request("GET", f"reversals/{posted['id']}"))
    assert view["transaction_id"] == posted["transaction_id"] and view["lines"][0]["posted_base"] == "40.000000"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE reverses_transaction_id=:id"), {"id": f.original["transaction_id"]}).scalar_one() == 1
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
        for table, field, value in [("audit_event", "action", "reversal.post"), ("outbox_event", "event_type", "reversal.post.v1")]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table} WHERE {field}=:value"), {"value": value}).scalar_one() == 1
    for table in ("inventory_transaction", "stock_move"):
        with pytest.raises(DatabaseError):
            with f.engine.begin() as c:
                c.execute(text(f"DELETE FROM wms.{table}"))
    reconcile(f)


def test_reversal_partial_receipt_only_selected_post_and_closed_order_stays_closed(receiving):
    f = setup_reversal(receiving)
    receipt_body = deepcopy(f.receipt_body)
    receipt_body["lines"][0]["quantity_base"] = "60"
    first = ok(f.post(f.receipt_approve(receipt_body)))
    second = ok(f.post(first, f.post_body(first, "20")))
    closed = ok(f.action(ok(f.read(f.po)), "close", "manager"))
    ok(f.rev_post(f.rev_approve(first["transaction_id"])))
    view = ok(f.read(closed))
    assert view["status"] == "COMPLETED"
    assert (view["lines"][0]["posted_base"], view["lines"][0]["closed_base"], view["lines"][0]["remaining_base"]) == ("20.000000", "40.000000", "40.000000")
    assert f.rev_preview(second["transaction_id"])["eligible"]
    reconcile(f)


@pytest.mark.parametrize("mode", ["NONE", "LOT", "SERIAL"])
def test_reversal_opening_owner_trace_and_cutover_remains_closed(opening, mode):
    f = setup_reversal(opening)
    body = deepcopy(f.opening_body)
    if mode != "NONE":
        _, body = tracking(f, mode, **({"lot_code": "REV-LOT", "expires_on": "2030-01-01"} if mode == "LOT" else {"serial_code": "REV-SERIAL"}))
    original = ok(f.open_post(f.open_approve(body)))
    ok(f.rev_post(f.rev_approve(original["transaction_id"])))
    body["batch_key"] = str(uuid4())
    assert f.open_create(body).json()["code"] == "OPENING_CLOSED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == 0
    reconcile(f)


def test_reversal_move_releases_quality_quantity_but_preserves_decision(movement):
    f = setup_reversal(movement)
    source, original = f.putaway()
    ok(f.rev_post(f.rev_approve(original["transaction_id"])))
    assert {r["result"]: r["remaining_base"] for r in f.quality_history(source)["items"]} == {"ACCEPT": "75.000000", "REJECT": "5.000000"}
    assert f.rev_preview(source_transaction(f, source["id"]))["blockers"][0]["code"] == "DEPENDENT_QUALITY"
    reconcile(f)


@pytest.mark.parametrize("kind", ["SUPPLIER_RETURN", "CUSTOMER_RETURN"])
def test_reversal_return_restores_net_source_capacity_without_changing_order(returning, kind):
    f = setup_reversal(returning)
    if kind == "CUSTOMER_RETURN":
        source, _, order = f.issued_source()
        order_kind, location = "sales-orders", f.quarantine["id"]
    else:
        f.received("10")
        source, order = f.return_sources()["items"][0], f.po
        order_kind, location = "purchase-orders", f.location["id"]
    before = ok(f.read(order, kind=order_kind))
    original = ok(f.return_post(f.return_approve(f.return_body(source, kind=kind, location=location))))
    ok(f.rev_post(f.rev_approve(original["transaction_id"])))
    assert f.return_sources(kind)["items"][0]["returned_base"] == "0.000000"
    assert ok(f.read(order, kind=order_kind)) == before
    reconcile(f)


@pytest.mark.parametrize("serial", [None, "REVERSE-ISSUE-SERIAL"])
def test_reversal_issue_does_not_restore_consumed_reservations(returning, serial):
    f = setup_reversal(returning)
    source, _, so = f.issued_source("1" if serial else "7", serial)
    with f.engine.connect() as c:
        before = c.execute(text("SELECT id,quantity,consumed,released FROM wms.reservation ORDER BY id")).all()
    ok(f.rev_post(f.rev_approve(source_transaction(f, source["id"]))))
    with f.engine.connect() as c:
        assert before == c.execute(text("SELECT id,quantity,consumed,released FROM wms.reservation ORDER BY id")).all()
        assert c.execute(text("SELECT sum(reserved) FROM wms.stock_balance")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == bool(serial)
    assert ok(f.read(so, kind="sales-orders"))["lines"][0]["posted_base"] == "0.000000"
    reconcile(f)


def test_reversal_transfer_arrival_then_dispatch_and_two_warehouse_scope(transfer):
    f = setup_reversal(transfer)
    sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    arrived = ok(f.tr_receive(sent, f.tr_receive_body(sent, "20")))
    assert f.rev_request("GET", f"transactions/{arrived['transaction_id']}/reversal-preview?business_date=2026-10-02", who="buyer").status_code == 404
    assert not f.rev_preview(sent["transaction_id"])["eligible"]
    ok(f.rev_post(f.rev_approve(arrived["transaction_id"])))
    view = ok(f.tr_read(sent))
    assert view["status"] == "COMPLETED" and view["sources"][0]["remaining_base"] == "20.000000"
    assert "receive" in ok(f.tr_read(sent, "receiver"))["allowed_actions"]
    reconcile_transfer(f)
    ok(f.rev_post(f.rev_approve(sent["transaction_id"])))
    assert ok(f.tr_read(sent))["sources"] == []
    reconcile_transfer(f)


def test_reversal_transfer_arrival_allows_explicit_rereceipt(transfer):
    f = setup_reversal(transfer)
    sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    arrived = ok(f.tr_receive(sent, f.tr_receive_body(sent, "20")))
    ok(f.rev_post(f.rev_approve(arrived["transaction_id"])))
    view = ok(f.tr_read(sent))
    assert ok(f.tr_receive(view, f.tr_receive_body(view, "20")))["status"] == "COMPLETED"
    reconcile_transfer(f)


def test_reversal_transfer_loss_restores_transit(transfer):
    f = setup_reversal(transfer)
    arrived = ok(f.tr_receive(ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))))
    _, loss = missing_loss(f, arrived)
    loss = ok(f.decision(ok(f.action(loss, "submit", "manager"))))
    original = ok(f.tr_request("POST", f"transfers/{loss['id']}/loss-post", f.tr_post_body(loss), "controller"))
    ok(f.rev_post(f.rev_approve(original["transaction_id"])))
    assert ok(f.tr_read(arrived))["sources"][0]["remaining_base"] == "2.000000"
    reconcile_transfer(f)


@pytest.mark.parametrize("counted", ["98", "102"])
def test_reversal_count_keeps_observations_snapshot_and_released_locks(counting, counted):
    f = setup_reversal(counting)
    f.count_received()
    original = ok(f.count_action(f.count_approved(counted), "post", "controller", execution_key=str(uuid4())))
    before = f.count_read(original)
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    assert f.rev_request("GET", f"transactions/{original['transaction_id']}/reversal-preview?business_date=2026-10-02", who="buyer").status_code == 404
    ok(f.rev_post(f.rev_approve(original["transaction_id"])))
    assert f.count_read(original) == before
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 100
        assert c.execute(text("SELECT count(*) FROM wms.count_location_lock WHERE released_at IS NULL")).scalar_one() == 0
    reconcile(f)


def test_reversal_permissions_sod_revise_reject_and_revoked_replay(reversal):
    f = reversal
    draft = ok(f.rev_create(f.original["transaction_id"]), 201)
    assert f.rev_post(draft).json()["code"] == "INVALID_STATE"
    f.iam.grant(f.manager, "CONTROLLER", f.warehouse)
    submitted = ok(f.action(draft, "submit", "manager"))
    assert f.decision(submitted, "manager").json()["code"] == "SELF_APPROVAL"
    rejected = ok(f.decision(submitted, decision="REJECT"))
    body = dict(source_transaction_id=f.original["transaction_id"], source_version=f.original["version"],
        expected_version=rejected["version"], business_date="2026-10-02", reason="Lý do đã sửa theo duyệt")
    updated = ok(f.rev_request("PUT", f"reversals/{draft['id']}", body))
    approved = ok(f.decision(ok(f.action(updated, "submit", "manager"))))
    revised = ok(f.action(approved, "revise", "manager"))
    assert f.rev_post(revised).json()["code"] == "INVALID_STATE"
    approved = ok(f.decision(ok(f.action(revised, "submit", "manager"))))
    key = uuid4()
    post_body = dict(expected_version=approved["version"], execution_key=str(uuid4()), reason="Ghi sổ xác nhận")
    ok(f.rev_post(approved, post_body, key))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:user"), {"now": f.iam.now, "user": f.controller})
    assert f.rev_post(approved, post_body, key).status_code in {403, 404}
    assert f.rev_request("GET", f"reversals/operations/{key}", who="controller").status_code in {403, 404}


@pytest.mark.parametrize("guard", ["period", "freeze", "inactive", "reservation", "stale"])
def test_reversal_rechecks_current_guards_after_approval(reversal, guard):
    f = reversal
    approved = f.rev_approve(f.original["transaction_id"])
    with f.engine.begin() as c:
        if guard == "period":
            c.execute(text("UPDATE wms.stock_period SET status='CLOSED'"))
        elif guard == "inactive":
            c.execute(text("UPDATE wms.location SET is_active=false WHERE id=:id"), {"id": f.location["id"]})
        elif guard == "stale":
            c.execute(text("UPDATE wms.document SET version=version+1 WHERE id=:id"), {"id": f.original["id"]})
        elif guard == "reservation":
            c.execute(text("""INSERT INTO wms.reservation(id,line_id,stock_item_id,location_id,quantity,consumed,released,created_by,expires_at)
                SELECT :id,m.line_id,m.stock_item_id,m.destination_location_id,1,0,0,:user,'2020-01-01' FROM wms.stock_move m LIMIT 1"""), {"id": uuid4(), "user": f.buyer})
            c.execute(text("UPDATE wms.stock_balance SET reserved=1"))
        else:
            c.execute(text("""INSERT INTO wms.count_session(id,number,warehouse_id,status,business_date,created_by,version,reason)
                VALUES (:id,'REV-FREEZE',:wh,'DRAFT','2026-10-02',:user,1,'Khóa kiểm thử')"""), {"id": (session := uuid4()), "wh": f.warehouse, "user": f.manager})
            c.execute(text("INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES(:id,:session,:loc,now())"), {"id": uuid4(), "session": session, "loc": f.location["id"]})
    assert f.rev_post(approved).json()["code"] == {"period": "PERIOD_CLOSED", "freeze": "LOCATION_FROZEN", "inactive": "INVALID_LOCATION", "reservation": "RESERVATION_OPEN", "stale": "STALE_SOURCE"}[guard]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='REVERSE'")).scalar_one() == 0


def test_reversal_consignment_fails_closed_without_borrowing_company_owner(opening):
    f = setup_reversal(opening)
    owner, contract = agreement(f)
    body = deepcopy(f.opening_body)
    body["lines"][0].update(owner_id=owner["id"], consignment_id=contract["id"])
    original = ok(f.open_post(f.open_approve(body)))
    assert f.rev_preview(original["transaction_id"])["blockers"][0]["code"] == "OWNER_POLICY_REQUIRED"
    assert f.rev_create(original["transaction_id"]).json()["code"] == "OWNER_POLICY_REQUIRED"
    with f.engine.connect() as c:
        assert str(c.execute(text("SELECT owner_id FROM wms.stock_item")).scalar_one()) == owner["id"]
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction")).scalar_one() == 1


def test_reversal_downstream_move_blocks_then_restores_after_child_inverse(movement):
    f = setup_reversal(movement)
    source, putaway = f.putaway("80", "0")
    moved = ok(f.move_post(f.move_approve(f.move_body(source, qty="10"))))
    assert not f.rev_preview(putaway["transaction_id"])["eligible"]
    ok(f.rev_post(f.rev_approve(moved["transaction_id"])))
    ok(f.rev_post(f.rev_approve(putaway["transaction_id"])))
    reconcile(f)


def test_reversal_expired_lot_cannot_be_restored_to_storage(returning):
    f = setup_reversal(returning)
    # A lot can expire after its original issue; an inverse must recheck today.
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='LOT',expiry_required=true WHERE id=:id"), {"id": f.product["id"]})
    f.receipt_body["lines"][0].update(lot_code="REVERSE-EXPIRY", expires_on="2027-01-01")
    source, _, _ = f.issued_source()
    doc = f.rev_approve(source_transaction(f, source["id"]))
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.lot SET expires_on='2020-01-01'"))
    assert f.rev_post(doc).json()["code"] == "LOT_EXPIRED"


@pytest.mark.parametrize("baseline", [10, 19])
@pytest.mark.parametrize("custom", [False, True])
def test_reversal_upgrade_preserves_history_and_custom_policy(empty_database, monkeypatch, baseline, custom):
    import apps.server.infrastructure.migrations as migration
    sources = migration.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migration, "migration_sources", lambda: sources[:baseline])
        migration.migrate(empty_database)
    warehouse, period, policy = uuid4(), uuid4(), uuid4()
    with empty_database.begin() as c:
        c.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES(:id,'UPGRADE-REV','Existing warehouse',true)"), {"id": warehouse})
        c.execute(text("INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status) VALUES(:id,:wh,'2026-01-01','2026-12-31','CLOSED')"), {"id": period, "wh": warehouse})
        if custom:
            c.execute(text("INSERT INTO wms.approval_policy(id,document_kind,revision,is_active) VALUES(:id,'REVERSAL',77,false)"), {"id": policy})
    assert migration.migrate(empty_database) == [s[0] for s in sources[baseline:]]
    assert migration.migrate(empty_database) == []
    assert migration.is_ready(empty_database)
    with empty_database.connect() as c:
        assert c.execute(text("SELECT status FROM wms.stock_period WHERE id=:id"), {"id": period}).scalar_one() == "CLOSED"
        row = c.execute(text("SELECT revision,is_active FROM wms.approval_policy WHERE document_kind='REVERSAL'")).one()
        assert tuple(row) == ((77, False) if custom else (1, True))
        roles = c.execute(text("""SELECT r.code FROM wms.approval_policy_step s JOIN wms.role r ON r.id=s.role_id
            JOIN wms.approval_policy p ON p.id=s.policy_id WHERE p.document_kind='REVERSAL'""")).scalars().all()
        assert roles == ([] if custom else ["CONTROLLER"])


@pytest.mark.parametrize("fault", ["missing", "quantity", "route", "owner", "line", "foreign_line"])
def test_reversal_database_rejects_incomplete_or_forged_inverse(reversal, fault):
    f = reversal
    doc = f.rev_approve(f.original["transaction_id"])
    other = f.rev_approve(f.original["transaction_id"]) if fault == "foreign_line" else doc
    with pytest.raises(DatabaseError):
        with f.engine.begin() as c:
            tx = uuid4()
            c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by,reverses_transaction_id)
                VALUES(:id,:doc,:id,'REVERSE','2026-10-02',now(),:actor,:original)"""),
                dict(id=tx, doc=doc["id"], actor=f.controller, original=f.original["transaction_id"]))
            if fault != "missing":
                row = c.execute(text("SELECT * FROM wms.stock_move WHERE transaction_id=:id"), {"id": f.original["transaction_id"]}).mappings().one()
                line = c.execute(text("SELECT id FROM wms.document_line WHERE document_id=:id"), {"id": other["id"]}).scalar_one()
                stock = row["stock_item_id"]
                if fault == "owner":
                    from packages.contracts.traceability import UNCLASSIFIED_OWNER
                    stock = uuid4()
                    c.execute(text("INSERT INTO wms.stock_item(id,product_id,owner_id) VALUES(:id,:product,:owner)"), dict(id=stock, product=f.product["id"], owner=UNCLASSIFIED_OWNER))
                c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id,reverses_move_id)
                    VALUES(:id,:tx,:line,:stock,:src,:dst,:qty,:unit,:original)"""), dict(id=uuid4(), tx=tx,
                    line=row["line_id"] if fault == "line" else line, stock=stock,
                    src=row["source_location_id"] if fault == "route" else row["destination_location_id"],
                    dst=row["destination_location_id"] if fault == "route" else row["source_location_id"],
                    qty=1 if fault == "quantity" else row["quantity_base"], unit=row["base_uom_id"], original=row["id"]))
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='REVERSE'")).scalar_one() == 0


def test_reversal_and_real_count_freeze_serialize_on_location(counting):
    f = setup_reversal(counting)
    original = f.count_received("40")
    rev, count = f.rev_approve(original["transaction_id"]), f.count_create()
    barrier = Barrier(2)
    def post():
        barrier.wait(5)
        return f.rev_post(rev)
    def freeze():
        barrier.wait(5)
        return f.count_action(count, "freeze")
    with ThreadPoolExecutor(2) as pool:
        posted, frozen = pool.submit(post), pool.submit(freeze)
        posted, frozen = posted.result(15), frozen.result(15)
    assert frozen.status_code == 200 and posted.status_code in {200, 409}
    if posted.status_code == 409:
        assert posted.json()["code"] == "LOCATION_FROZEN"
    snapshot = sum(float(r["snapshot_quantity"]) for r in f.count_read(frozen.json())["lines"])
    assert snapshot == (0 if posted.status_code == 200 else 40)
    reconcile(f)


def test_reversal_and_real_period_close_reconcile_or_report_pending(counting):
    f = setup_reversal(counting)
    body = deepcopy(f.receipt_body)
    body["lines"][0]["quantity_base"] = "40"
    original = f.count_received("40", body)
    rev = f.rev_approve(original["transaction_id"])
    periods = ok(f.rev_request("GET", f"periods?warehouse_id={f.warehouse}"))["items"]
    period = periods[0]
    barrier = Barrier(2)
    def post():
        barrier.wait(5)
        return f.rev_post(rev)
    def close():
        barrier.wait(5)
        return f.rev_request("POST", f"periods/{period['id']}/close", dict(expected_version=period["version"], reason="Khóa kỳ đối soát"), "controller")
    with ThreadPoolExecutor(2) as pool:
        posted, closed = pool.submit(post), pool.submit(close)
        posted, closed = posted.result(15), closed.result(15)
    assert posted.status_code == 200
    assert closed.status_code in {200, 409}
    if closed.status_code == 409:
        assert closed.json()["code"] == "DOCUMENT_PENDING"
        closed = f.rev_request("POST", f"periods/{period['id']}/close", dict(expected_version=period["version"], reason="Khóa kỳ sau đảo"), "controller")
        assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    reconcile(f)


@pytest.mark.parametrize("relocated", [False, True])
def test_reversal_count_missing_extra_or_relocated_serial(counting, relocated):
    from packages.contracts.traceability import COMPANY_OWNER
    f = setup_reversal(counting)
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.product SET tracking='SERIAL' WHERE id=:id"), {"id": f.product["id"]})
    body = deepcopy(f.receipt_body)
    body["lines"][0].update(quantity_base="1", serial_code="REV-COUNT-ORIGINAL")
    f.count_received("1", body)
    doc = ok(f.count_action(f.count_create([f.location["id"], f.quarantine["id"]] if relocated else None), "freeze"))
    doc = ok(f.count_action(doc, "extra", "buyer", location_id=f.quarantine["id"] if relocated else f.location["id"],
        product_id=f.product["id"], owner_id=str(COMPANY_OWNER), serial_code="REV-COUNT-ORIGINAL" if relocated else "REV-COUNT-EXTRA"))
    for who in ("buyer", "picker"):
        for line in f.count_read(doc, who)["lines"]:
            missing = line["location_id"] == f.location["id"] if relocated else line["serial_code"] == "REV-COUNT-ORIGINAL"
            doc = ok(f.count_observe(doc, "0" if missing else "1", who, line_id=line["id"]))
    doc = ok(f.count_action(doc, "submit"))
    for who in ("controller", "director"):
        doc = ok(f.count_action(doc, "decide", who, decision="APPROVE"))
    posted = ok(f.count_action(doc, "post", "controller", execution_key=str(uuid4())))
    ok(f.rev_post(f.rev_approve(posted["transaction_id"])))
    with f.engine.connect() as c:
        code, location = c.execute(text("SELECT s.code,sp.location_id FROM wms.serial_position sp JOIN wms.serial s ON s.id=sp.serial_id")).one()
        assert code == "REV-COUNT-ORIGINAL" and str(location) == f.location["id"]
    reconcile(f)


def test_reversal_rolls_back_serial_position_balance_and_ack_after_stock_write(returning, monkeypatch):
    from apps.server.application import reversal_stock
    f = setup_reversal(returning)
    source, _, _ = f.issued_source("1", "REV-ROLLBACK-SERIAL")
    doc = f.rev_approve(source_transaction(f, source["id"]))
    original = reversal_stock.write
    def fail(*args):
        original(*args)
        raise RuntimeError("Failure after balance/serial updates")
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Đảo serial")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(reversal_stock, "write", fail)
        assert f.rev_post(doc, body, key).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.serial_position")).scalar_one() == 0
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
    ok(f.rev_post(doc, body, key))
    reconcile(f)


def test_reversal_two_documents_race_only_one_inverse(reversal):
    f = reversal
    docs = [f.rev_approve(f.original["transaction_id"]) for _ in range(2)]
    barrier = Barrier(2)
    def post(doc):
        barrier.wait(5)
        return f.rev_post(doc)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(post, docs))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r.json()["code"] for r in results if r.status_code == 409) == "ALREADY_REVERSED"
    reconcile(f)


def test_reversal_failure_after_ledger_rolls_back_everything(reversal, monkeypatch):
    f = reversal
    doc = f.rev_approve(f.original["transaction_id"])
    original_effects = f.client.app.state.orders.effects
    def fail(*args, **kwargs):
        original_effects(*args, **kwargs)
        raise RuntimeError("test crash after ledger/audit/outbox")
    body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Rollback đảo")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(f.client.app.state.orders, "effects", fail)
        assert f.rev_post(doc, body, key).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='REVERSE'")).scalar_one() == 0
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 40
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        assert c.execute(text("SELECT version FROM wms.document WHERE id=:id"), {"id": f.original["id"]}).scalar_one() == f.original["version"]
    ok(f.rev_post(doc, body, key))
    reconcile(f)
