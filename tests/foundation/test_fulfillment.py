from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_issues import inventory, issuing, reconcile  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def fulfillment(issuing):  # noqa: F811
    f = issuing
    f.seed()
    f.doc = f.reserve(f.issue_approve(), "5")

    def read(doc=None, who="buyer"):
        return ok(f.client.get(f"/api/v1/fulfillment/{(doc or f.doc)['id']}", headers=f.headers[who]))

    def command(kind, action, entity=None, *, doc=None, who="buyer", key=None, body=None, **extra):
        doc = doc or read()
        path = f"fulfillment/{doc['id']}/" + ("picks" if kind == "pick" else "packages")
        payload = dict(expected_version=doc["version"], reason="Soạn đóng kiện thực tế", **extra)
        if entity:
            path += f"/{entity['id']}/{action}"
            payload["entity_version"] = entity["version"]
        return f.issue_command(path, body or payload, who=who, key=key)

    def create(qty="5", **extra):
        return ok(command("pick", "create", reservation_id=read()["reservations"][0]["id"],
                          assigned_to=str(f.buyer), quantity_base=qty, **extra), 201)

    def confirm(qty="5", task=None, **extra):
        view = read()
        task = task or view["tasks"][0]
        res = next(r for r in view["reservations"] if r["id"] == task["reservation_id"])
        return command("pick", "confirm", task, quantity_base=qty, **{
            "location_code": res["location_code"], "item_code": res["sku"],
            "trace_code": res["lot_code"] or res["serial_code"], **extra})

    def pack(qty="5", task=None, code=None):
        task = task or read()["tasks"][0]
        return command("package", "create", code=code or str(uuid4()), lines=[dict(pick_task_id=task["id"], quantity_base=qty)])

    def ready(qty="5"):
        create(qty)
        ok(confirm(qty))
        ack = ok(pack(qty), 201)
        package = next(p for p in read()["packages"] if p["id"] == ack["entity_id"])
        return ok(command("package", "seal", package))

    f.fulfill_read, f.fulfill, f.pick_create, f.pick_confirm, f.pack, f.ready = read, command, create, confirm, pack, ready
    return f


def consumption(f):
    with f.engine.connect() as c:
        return tuple(c.execute(text(sql)).scalar_one() for sql in (
            "SELECT coalesce(sum(consumed_quantity),0) FROM wms.pick_task",
            "SELECT coalesce(sum(consumed_quantity),0) FROM wms.package_line",
            "SELECT coalesce(sum(quantity),0) FROM wms.fulfillment_consumption"))


def test_fulfillment_t15_pick_pack_unchanged_partial_issue_once(fulfillment):
    f = fulfillment
    before = inventory(f)
    ready = f.ready()
    assert inventory(f) == before == (0, 10, 5, 0)
    assert consumption(f) == (0, 0, 0)
    key, body = uuid4(), f.issue_post_body(ready, "3")
    posted = ok(f.issue_post(ready, body, key=key))
    assert inventory(f) == (1, 7, 2, 3)
    assert consumption(f) == (3, 3, 3)
    assert ok(f.issue_post(ready, body, key=key)) == posted
    assert ok(f.issue_post(ready, body)) == posted  # execution key replay
    assert consumption(f) == (3, 3, 3)
    view = f.fulfill_read()
    assert view["tasks"][0]["consumed_quantity"] == "3.000000"
    assert view["packages"][0]["lines"][0]["consumed_quantity"] == "3.000000"
    ok(f.issue_post(posted, f.issue_post_body(posted, "2")))
    assert consumption(f) == (5, 5, 5)
    reconcile(f)
    reconcile_fulfillment(f)


def reconcile_fulfillment(f):
    with f.engine.connect() as c:
        with c.connection.driver_connection.cursor() as cursor:
            cursor.execute((Path(__file__).resolve().parents[2] / "02_CSDL/reconcile_fulfillment.sql").read_text())
            while True:
                if cursor.description:
                    assert cursor.fetchall() == []
                if not cursor.nextset():
                    break


def test_fulfillment_partial_shortage_reject_and_reallocate(fulfillment):
    f = fulfillment
    f.pick_create()
    ok(f.pick_confirm("3"))
    f.pick_create("2")
    new = next(t for t in f.fulfill_read()["tasks"] if t["status"] == "OPEN")
    ok(f.fulfill("pick", "reject", new))
    f.pick_create("2")
    assert sorted(t["status"] for t in f.fulfill_read()["tasks"]) == ["CANCELLED", "DONE", "OPEN"]
    assert inventory(f) == (0, 10, 5, 0)


def test_fulfillment_overallocation_scan_mismatch_and_unsealed_issue(fulfillment):
    f = fulfillment
    f.pick_create()
    response = f.fulfill("pick", "create", reservation_id=f.fulfill_read()["reservations"][0]["id"],
                         assigned_to=str(f.buyer), quantity_base="1")
    assert response.json()["code"] == "PICK_EXCEEDED"
    assert f.pick_confirm("6").json()["code"] == "RESERVATION_MISMATCH"
    assert f.pick_confirm(item_code="wrong").json()["code"] == "SCAN_MISMATCH"
    assert f.pick_confirm(location_code="wrong").json()["code"] == "SCAN_MISMATCH"
    assert f.pick_confirm(trace_code="unexpected-lot").json()["code"] == "SCAN_MISMATCH"
    assert f.pack().json()["code"] == "PICK_INCOMPLETE"
    ok(f.pick_confirm())
    ok(f.pack("3"), 201)
    assert f.pack("3").json()["code"] == "PACK_EXCEEDED"
    doc = f.fulfill_read()
    assert f.issue_post(doc, f.issue_post_body(doc, "1")).json()["code"] == "FULFILLMENT_INCOMPLETE"
    assert inventory(f) == (0, 10, 5, 0)


def test_fulfillment_cancel_packages_then_tasks_release_and_revise(fulfillment):
    f = fulfillment
    doc = f.ready()
    assert f.release(doc, "5").json()["code"] == "FULFILLMENT_ACTIVE"
    assert f.action(doc, "revise").json()["code"] == "FULFILLMENT_ACTIVE"
    view = f.fulfill_read()
    assert f.fulfill("pick", "cancel", view["tasks"][0]).json()["code"] == "PACKAGE_ACTIVE"
    ok(f.fulfill("package", "cancel", view["packages"][0]))
    doc = ok(f.fulfill("pick", "cancel", f.fulfill_read()["tasks"][0]))
    revised = ok(f.action(doc, "revise"))
    assert revised["status"] == "DRAFT"
    assert inventory(f) == (0, 10, 0, 0)
    assert f.fulfill_read()["packages"][0]["lines"][0]["quantity"] == "5.000000"
    assert f.fulfill_read()["tasks"][0]["picked_quantity"] == "5.000000"


def test_fulfillment_cancel_remainder_after_partial_post_preserves_trace(fulfillment):
    f = fulfillment
    ready = f.ready()
    ok(f.issue_post(ready, f.issue_post_body(ready, "3")))
    ok(f.fulfill("package", "cancel", f.fulfill_read()["packages"][0]))
    doc = ok(f.fulfill("pick", "cancel", f.fulfill_read()["tasks"][0]))
    ok(f.release(doc, "2"))
    assert inventory(f) == (1, 7, 0, 3)
    assert consumption(f) == (3, 3, 3)
    reconcile(f)
    reconcile_fulfillment(f)


def test_fulfillment_multi_package_partial_post_allocates_and_reconciles(fulfillment):
    f = fulfillment
    f.pick_create("3")
    ok(f.pick_confirm("3"))
    first_task = f.fulfill_read()["tasks"][0]
    f.pick_create("2")
    second_task = next(t for t in f.fulfill_read()["tasks"] if t["status"] == "OPEN")
    ok(f.pick_confirm("2", second_task))
    for qty, task in [("1", first_task), ("2", first_task), ("2", second_task)]:
        created = ok(f.pack(qty, task), 201)
        package = next(p for p in f.fulfill_read()["packages"] if p["id"] == created["entity_id"])
        ok(f.fulfill("package", "seal", package))
    doc = f.fulfill_read()
    posted = ok(f.issue_post(doc, f.issue_post_body(doc, "4")))
    assert consumption(f) == (4, 4, 4)
    reconcile_fulfillment(f)
    ok(f.issue_post(posted, f.issue_post_body(posted, "1")))
    assert consumption(f) == (5, 5, 5)
    reconcile(f)
    reconcile_fulfillment(f)


def test_fulfillment_replay_stale_current_authorization_and_operation(fulfillment):
    f = fulfillment
    doc, key = f.fulfill_read(), uuid4()
    body = dict(expected_version=doc["version"], reason="Giao soạn", reservation_id=doc["reservations"][0]["id"],
                assigned_to=str(f.buyer), quantity_base="5")
    first = ok(f.fulfill("pick", "create", body=body, key=key), 201)
    assert ok(f.fulfill("pick", "create", body=body, key=key), 201) == first
    assert f.fulfill("pick", "create", body=body).json()["code"] == "STALE_VERSION"
    assert f.fulfill("pick", "create", body={**body, "quantity_base": "4"}, key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    path = f"/api/v1/fulfillment/operations/{key}"
    assert ok(f.client.get(path, headers=f.headers["buyer"]))["result"] == first
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE id=:id"), {"now": f.iam.now, "id": f.picker_grant})
    assert f.fulfill("pick", "create", body=body, key=key).status_code == 403
    assert f.client.get(path, headers=f.headers["buyer"]).status_code == 403
    assert len(f.fulfill_read()["tasks"]) == 1


@pytest.mark.parametrize("failure", ["fulfillment", "issue"])
def test_fulfillment_outbox_failure_rolls_back_all_effects(fulfillment, failure):
    f = fulfillment
    if failure == "issue":
        f.ready()
    doc = f.fulfill_read()
    before = inventory(f), consumption(f)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO wms.outbox_event" in statement:
            raise RuntimeError("injected outbox failure")

    event.listen(f.engine, "before_cursor_execute", fail)
    try:
        response = (f.issue_post(doc, f.issue_post_body(doc, "3")) if failure == "issue" else
                    f.fulfill("pick", "create", reservation_id=doc["reservations"][0]["id"], assigned_to=str(f.buyer), quantity_base="5"))
        assert response.status_code == 500
    finally:
        event.remove(f.engine, "before_cursor_execute", fail)
    assert (inventory(f), consumption(f)) == before
    assert f.fulfill_read()["version"] == doc["version"]
    if failure == "fulfillment":
        assert not f.fulfill_read()["tasks"]


@pytest.mark.parametrize("race", ["release", "cancel", "post", "pick"])
def test_fulfillment_pg_race_create_against_other_command(fulfillment, race):
    f = fulfillment
    doc = f.fulfill_read()
    barrier = Barrier(2)
    def run(index):
        barrier.wait(timeout=5)
        if index == 0 or race == "pick":
            return f.fulfill("pick", "create", doc=doc, reservation_id=doc["reservations"][0]["id"], assigned_to=str(f.buyer), quantity_base="5")
        if race == "release":
            return f.release(doc, "5")
        if race == "cancel":
            return f.action(doc, "cancel", who="manager")
        return f.issue_post(doc, f.issue_post_body(doc, "5"))
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sum(r.status_code in {200, 201} for r in results) == 1
    assert next(r for r in results if r.status_code == 409).json()["code"] == "STALE_VERSION"
    assert inventory(f)[1] >= inventory(f)[2] >= 0
    reconcile(f)


def test_fulfillment_assignment_scope_and_only_assigned_picker_can_confirm(fulfillment):
    f = fulfillment
    f.pick_create()
    task = f.fulfill_read()["tasks"][0]
    assert f.pick_confirm(who="manager").status_code == 403
    assigned = ok(f.fulfill("pick", "assign", task, who="manager", assigned_to=str(f.manager)))
    assert assigned["entity_version"] == task["version"] + 1
    assert f.pick_confirm().status_code == 403
    ok(f.pick_confirm(who="manager"))
    assert f.fulfill("pick", "create", reservation_id=f.fulfill_read()["reservations"][0]["id"],
                     assigned_to=str(f.controller), quantity_base="1", who="manager").json()["code"] == "ASSIGNEE_INELIGIBLE"
    people = ok(f.client.get(f"/api/v1/fulfillment/{f.doc['id']}/assignees", headers=f.headers["manager"]))
    assert str(f.controller) not in [p["id"] for p in people["items"]]


def test_fulfillment_assignment_audit_and_lookup_keep_original_permission(fulfillment):
    f = fulfillment
    key = uuid4()
    created = ok(f.fulfill("pick", "create", who="manager", key=key, assigned_to=str(f.buyer),
                          reservation_id=f.fulfill_read()["reservations"][0]["id"], quantity_base="5"), 201)
    assert created["assigned_to"] == str(f.buyer)
    changed = ok(f.fulfill("pick", "assign", f.fulfill_read()["tasks"][0], who="manager", assigned_to=str(f.manager)))
    assert changed["assigned_to"] == str(f.manager)
    f.iam.grant(f.manager, "PICKER", f.warehouse)
    f.iam.grant(f.manager, "SELLER", f.warehouse)
    with f.engine.begin() as c:
        c.execute(text("""UPDATE wms.user_role_grant g SET revoked_at=:now FROM wms.role r
            WHERE g.role_id=r.id AND r.code='WAREHOUSE_MANAGER' AND g.user_id=:user"""), {"now": f.iam.now, "user": f.manager})
        recipient = c.execute(text("""SELECT after_data->>'assigned_to' FROM wms.audit_event
            WHERE action='fulfillment.pick.create' AND entity_id=:id"""), {"id": created["id"]}).scalar_one()
        assert recipient == str(f.buyer)
    # Still allowed to work on the current assigned task, but not reconcile a
    # create-for-someone-else command after document.assign was revoked.
    ok(f.pick_confirm(who="manager"))
    assert f.client.get(f"/api/v1/fulfillment/operations/{key}", headers=f.headers["manager"]).status_code == 403


def test_fulfillment_foreign_task_and_reservation_are_hidden(fulfillment):
    f = fulfillment
    f.pick_create()
    task = f.fulfill_read()["tasks"][0]
    other = f.issue_approve()
    response = f.fulfill("package", "create", doc=other, code="FOREIGN", lines=[dict(pick_task_id=task["id"], quantity_base="1")])
    assert response.status_code == 404
    assert f.fulfill("pick", "create", doc=other, reservation_id=task["reservation_id"], assigned_to=str(f.buyer), quantity_base="1").json()["code"] == "RESERVATION_MISMATCH"
    hidden, _ = f.iam.user("hidden-picker")
    f.iam.grant(hidden, "PICKER", f.iam.warehouse("OTHER-PICK"))
    headers = f.iam.headers(f.iam.login("hidden-picker"))
    assert f.client.get(f"/api/v1/fulfillment/{f.doc['id']}", headers=headers).status_code == 404


def test_fulfillment_expired_hold_blocks_pick_but_allows_cleanup(fulfillment):
    f = fulfillment
    f.pick_create()
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.reservation SET expires_at=:expiry"), {"expiry": f.iam.now - timedelta(seconds=1)})
    assert f.pick_confirm().json()["code"] == "RESERVATION_EXPIRED"
    doc = ok(f.fulfill("pick", "cancel", f.fulfill_read()["tasks"][0]))
    ok(f.release(doc, "5"))
    assert inventory(f) == (0, 10, 0, 0)


def test_fulfillment_serial_sources_cannot_be_picked_or_packed_twice(issuing):  # noqa: F811
    f = issuing
    # Use the standard opening API with a serial product, then real SO/ISSUE.
    product = f.master("products", sku="SERIAL-PICK", name="Serial pick", base_uom_id=f.product["base_uom_id"], tracking="SERIAL", expiry_required=False)
    body = {**f.opening_body, "lines": [dict(f.opening_body["lines"][0])]}
    body["lines"] = [{**body["lines"][0], "product_id": product["id"], "quantity_base": "1", "serial_code": "PICK-S01"}]
    f.seed(body)
    conversion = ok(f.client.get("/api/v1/master/product-uoms", params={"product_id": product["id"]}, headers=f.headers["buyer"]))["items"][0]
    source_body = {**f.body, "lines": [{**f.body["lines"][0], "product_id": product["id"], "product_uom_id": conversion["id"], "quantity": "1"}]}
    source = f.sales(source_body)
    doc = f.reserve(f.issue_approve(source, "1"), "1")
    res = f.issue_read(doc)["reservations"][0]
    body = dict(expected_version=doc["version"], reason="Soạn serial", reservation_id=res["id"], assigned_to=str(f.buyer), quantity_base="1")
    created = ok(f.issue_command(f"fulfillment/{doc['id']}/picks", body), 201)
    confirm = dict(expected_version=created["version"], entity_version=1, reason="Quét serial", quantity_base="1", location_code=res["location_code"], item_code=res["sku"], trace_code="WRONG")
    path = f"fulfillment/{doc['id']}/picks/{created['entity_id']}/confirm"
    assert f.issue_command(path, confirm).json()["code"] == "SCAN_MISMATCH"
    confirmed = ok(f.issue_command(path, {**confirm, "trace_code": "PICK-S01"}))
    package = dict(expected_version=confirmed["version"], reason="Đóng serial", code="SERIAL-BOX", lines=[dict(pick_task_id=created["entity_id"], quantity_base="1")])
    packed = ok(f.issue_command(f"fulfillment/{doc['id']}/packages", package), 201)
    assert f.issue_command(f"fulfillment/{doc['id']}/packages", {**package, "expected_version": packed["version"], "code": "DUP"}).json()["code"] == "PACK_EXCEEDED"
    assert inventory(f) == (0, 1, 1, 0)


@pytest.mark.parametrize("change", ["warehouse", "ancestor", "product", "freeze", "owner"])
def test_fulfillment_rechecks_source_after_pick_and_before_post(fulfillment, change):
    from sqlalchemy.exc import IntegrityError
    f = fulfillment
    doc = f.ready()
    if change == "owner":
        # B09 prevents changing the identity once it is reserved, even before
        # B10 or ISSUE could inspect the changed source.
        with pytest.raises(IntegrityError, match="ownership is immutable"):
            with f.engine.begin() as c:
                c.execute(text("UPDATE wms.document_line SET owner_id='00000000-0000-4000-8000-000000000002' WHERE document_id=:id"), {"id": doc["id"]})
        assert inventory(f) == (0, 10, 5, 0) and consumption(f) == (0, 0, 0)
        return
    with f.engine.begin() as c:
        if change == "warehouse":
            c.execute(text("UPDATE wms.warehouse SET is_active=false WHERE id=:id"), {"id": f.warehouse})
        elif change == "ancestor":
            c.execute(text("UPDATE wms.location SET is_active=false WHERE code='RACK'"))
        elif change == "product":
            c.execute(text("UPDATE wms.product SET is_active=false WHERE id=:id"), {"id": f.product["id"]})
        else:
            session = uuid4()
            c.execute(text("""INSERT INTO wms.count_session(id,warehouse_id,number,status,created_by,frozen_at,version)
                VALUES (:id,:warehouse,'PICK-COUNT','FROZEN',:actor,now(),1)"""), {"id": session, "warehouse": f.warehouse, "actor": f.manager})
            c.execute(text("""INSERT INTO wms.count_location_lock(id,location_id,session_id,locked_at)
                VALUES (:id,:loc,:session,now())"""), {"id": uuid4(), "loc": f.location["id"], "session": session})
    response = f.issue_post(doc, f.issue_post_body(doc, "3"))
    assert response.status_code == 409, response.text
    assert inventory(f) == (0, 10, 5, 0) and consumption(f) == (0, 0, 0)
    # Cancelling logical work must not be trapped by inactive/frozen inventory.
    ok(f.fulfill("package", "cancel", f.fulfill_read()["packages"][0]))
    ok(f.fulfill("pick", "cancel", f.fulfill_read()["tasks"][0]))


@pytest.mark.parametrize("race", ["seal", "cancel", "post"])
def test_fulfillment_pg_race_package_against_issue(fulfillment, race):
    f = fulfillment
    f.ready()
    view = f.fulfill_read()
    package = view["packages"][0]
    if race == "seal":
        # Build a second package to test double seal on a DRAFT independently.
        ok(f.fulfill("package", "cancel", package))
        ok(f.pack(), 201)
        view = f.fulfill_read()
        package = next(p for p in view["packages"] if p["status"] == "DRAFT")
    barrier = Barrier(2)
    def run(index):
        barrier.wait(timeout=5)
        if race == "seal" or index == 0 and race == "cancel":
            return f.fulfill("package", "seal" if race == "seal" else "cancel", package, doc=view)
        return f.issue_post(view, f.issue_post_body(view, "3"))
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sum(r.status_code == 200 for r in results) == 1
    assert next(r for r in results if r.status_code == 409).json()["code"] == "STALE_VERSION"
    assert consumption(f)[0] in {0, 3}
    assert len(set(consumption(f))) == 1
    reconcile(f)


def test_fulfillment_reconcile_consumption_is_append_only_and_failure_atomic(fulfillment):
    from sqlalchemy.exc import DatabaseError
    f = fulfillment
    ready = f.ready()
    ok(f.issue_post(ready, f.issue_post_body(ready, "3")))
    for sql in ["DELETE FROM wms.fulfillment_consumption", "UPDATE wms.fulfillment_consumption SET quantity=1"]:
        with pytest.raises(DatabaseError):
            with f.engine.begin() as c:
                c.execute(text(sql))
    with f.engine.connect() as c:
        rows = c.execute(text("""SELECT fc.quantity,rc.quantity,m.quantity_base,r.stock_item_id,l.stock_item_id,
            r.line_id,l.document_line_id,t.reservation_id,rc.reservation_id FROM wms.fulfillment_consumption fc
            JOIN wms.package_line l ON l.id=fc.package_line_id JOIN wms.pick_task t ON t.id=l.pick_task_id
            JOIN wms.reservation_consumption rc ON rc.id=fc.reservation_consumption_id
            JOIN wms.reservation r ON r.id=rc.reservation_id JOIN wms.stock_move m ON m.id=rc.move_id""")).one()
        assert rows[0] == rows[1] == rows[2] == 3
        assert rows[3] == rows[4] and rows[5] == rows[6] and rows[7] == rows[8]


@pytest.mark.parametrize("prefix", [10, 16])
def test_fulfillment_upgrade_preserves_legacy_rows_without_inventing_sources(empty_database, monkeypatch, prefix):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix])
        migrations.migrate(empty_database)
    ids = {k: uuid4() for k in ("user", "warehouse", "location", "uom", "product", "stock", "doc", "line", "res", "task", "package", "packline")}
    with empty_database.begin() as c:
        statements = [
            "INSERT INTO wms.app_user VALUES (:user,'legacy','Legacy','fixture',true,0,now())",
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'OLD','Old',true)",
            "INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:location,:warehouse,'BIN','Bin','STORAGE',true)",
            "INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:uom,'EA','Unit',0)",
            "INSERT INTO wms.product(id,sku,name,base_uom_id,tracking,expiry_required,is_active,version,attributes) VALUES (:product,'LEGACY','Legacy',:uom,'NONE',false,true,1,'{}')",
            "INSERT INTO wms.stock_item(id,product_id,owner_id) VALUES (:stock,:product,'00000000-0000-4000-8000-000000000001')",
            "INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes) VALUES (:doc,'LEGACY','ISSUE','APPROVED',:warehouse,current_date,:user,now(),7,'{}')",
            "INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id) VALUES (:line,:doc,1,:product,:uom,2,1,2,'00000000-0000-4000-8000-000000000001')",
            "INSERT INTO wms.reservation(id,line_id,stock_item_id,location_id,quantity,consumed,released,created_by) VALUES (:res,:line,:stock,:location,2,0,0,:user)",
            "INSERT INTO wms.pick_task(id,reservation_id,assigned_to,picked_quantity,status,version) VALUES (:task,:res,:user,1,'DONE',4)",
            "INSERT INTO wms.package(id,document_id,code) VALUES (:package,:doc,'LEGACY-PACK')",
            "INSERT INTO wms.package_line(id,package_id,document_line_id,stock_item_id,quantity) VALUES (:packline,:package,:line,:stock,1)",
        ]
        for statement in statements:
            c.execute(text(statement), ids)
        before = {table: dict(c.execute(text(f"SELECT * FROM wms.{table}")).mappings().one()) for table in ("pick_task", "package", "package_line", "reservation", "document")}
        history = c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()
    assert migrations.migrate(empty_database) == [s[0] for s in sources[prefix:]]
    with empty_database.connect() as c:
        for table, old in before.items():
            new = dict(c.execute(text(f"SELECT * FROM wms.{table}")).mappings().one())
            assert {k: new[k] for k in old} == old
        assert c.execute(text("SELECT target_quantity FROM wms.pick_task")).scalar_one() is None
        assert c.execute(text("SELECT status FROM wms.package")).scalar_one() is None
        assert c.execute(text("SELECT pick_task_id FROM wms.package_line")).scalar_one() is None
        assert c.execute(text("SELECT count(*) FROM wms.fulfillment_consumption")).scalar_one() == 0
        assert c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()[:prefix] == history
