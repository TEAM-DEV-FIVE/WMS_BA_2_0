import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from test_openings import opening  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_reversals import setup_reversal
from test_transfers import missing_loss, transfer  # noqa: F401

from tests.foundation.test_orders import ok, orders  # noqa: F401

pytestmark = pytest.mark.integration


def field(code="note", kind="TEXT", **extra):
    return dict(code=code, label=code, value_type=kind, **extra)


@pytest.fixture
def custom(orders):  # noqa: F811
    iam = orders.iam
    admin, secret = iam.user("schema-admin", mfa=True)
    iam.grant(admin, "SYSADMIN")
    orders.headers["admin"] = iam.headers(iam.login("schema-admin", secret))

    class Fixture:
        def __init__(self):
            self.orders, self.client, self.engine = orders, orders.client, orders.engine

        def publish(self, fields=None, version=0, kind="PO", who="admin", key=None):
            return self.client.put("/api/v1/custom-fields/schemas/"+kind,
                json=dict(fields=fields if fields is not None else [field()], expected_version=version, reason="Định nghĩa thử"),
                headers={**orders.headers[who], "Idempotency-Key": str(key or uuid4())})

        def path(self, doc, target="documents"):
            return f"/api/v1/custom-fields/{target}/{doc['id']}"

        def read(self, doc, who="buyer", target="documents", **params):
            return self.client.get(self.path(doc, target), params=params, headers=orders.headers[who])

        def write(self, doc, schema, values, *, expected=None, target="documents", who="buyer", key=None, **params):
            return self.client.put(self.path(doc, target), params=params,
                json=dict(expected_version=doc["version"], expected_revision_id=expected,
                          revision_id=schema["revision_id"], values=values, reason="Lưu trường thử"),
                headers={**orders.headers[who], "Idempotency-Key": str(key or uuid4())})

        def history(self, doc, who="buyer", target="documents", **params):
            return self.client.get(self.path(doc, target)+"/history", params=params, headers=orders.headers[who])

    return Fixture()


def test_required_snapshot_type_change_and_retirement_preserve_approval(custom):
    o = custom.orders
    first = ok(custom.publish([field(required=True)]))
    doc = ok(o.create(), 201)
    assert o.action(doc, "submit").json()["code"] == "INVALID_CUSTOM_FIELDS"
    saved = ok(custom.write(doc, first, {"note": "old-text"}))
    submitted = ok(o.action(saved, "submit"))
    second = ok(custom.publish([field(kind="INTEGER", required=True)], version=1))
    assert ok(custom.read(doc))["schema"]["revision_id"] == first["revision_id"]
    approved = ok(o.decision(submitted))
    assert custom.write(approved, first, {"note": "changed"}, expected=first["revision_id"]).json()["code"] == "INVALID_STATE"
    revised = ok(o.action(approved, "revise"))
    assert custom.write(revised, second, {}, expected=first["revision_id"]).json()["code"] == "INVALID_CUSTOM_FIELDS"
    changed = ok(custom.write(revised, second, {"note": 7}, expected=first["revision_id"]))
    third = ok(custom.publish([], version=2))
    retired = ok(custom.write(changed, third, {}, expected=second["revision_id"]))
    history = ok(custom.history(retired))["items"]
    assert [r["values"] for r in history] == [{}, {"note": 7}, {"note": "old-text"}]
    assert ok(custom.read(retired))["values"] == {}
    with o.engine.connect() as c:
        snapshot = c.execute(text("SELECT content_snapshot FROM wms.approval_request WHERE id=:id"), {"id": submitted["approval_request_id"]}).scalar_one()
        assert snapshot["custom_fields"]["values"] == {"note": "old-text"}
        assert snapshot["custom_fields"]["schema"]["fields"][0]["value_type"] == "TEXT"


@pytest.mark.parametrize("kind,good,bad,rules", [
    ("TEXT", "abc", 1, {"max_length": 3}), ("INTEGER", 2, True, {"minimum": "1", "maximum": "3"}),
    ("DECIMAL", "1.250000", "1.2500001", {}), ("BOOLEAN", False, "false", {}),
    ("DATE", "2026-10-04", "2026-02-30", {}), ("ENUM", "red", "blue", {"choices": ["red", "green"]}),
])
def test_real_server_types_and_constraints(custom, kind, good, bad, rules):
    definition = ok(custom.publish([field(kind=kind, validation=rules)]))
    doc = ok(custom.orders.create(), 201)
    assert custom.write(doc, definition, {"note": bad}).status_code == 409
    saved = ok(custom.write(doc, definition, {"note": good}))
    assert ok(custom.read(saved))["values"] == {"note": good}


@pytest.mark.parametrize("code", ["quantity", "base_uom_id", "owner_id", "warehouse_id", "price_read", "receipt_plan", "cf_stock_balance", "attributes", "x.y", "PRICE"])
def test_reject_core_and_internal_names(custom, code):
    assert custom.publish([field(code)]).status_code == 422


def test_size_depth_duplicate_and_nested_values_are_rejected(custom):
    definition = ok(custom.publish())
    doc = ok(custom.orders.create(), 201)
    for value in [{"quantity": 99}, ["nested"], 1.5, "x"*2001]:
        assert custom.write(doc, definition, {"note": value}).status_code == 422
    headers = {**custom.orders.headers["buyer"], "Idempotency-Key": str(uuid4()), "Content-Type": "application/json"}
    for raw, status in [(b"["*2000+b"]"*2000, 409), (b'{"values":{},"values":{}}', 409), (b'{"note":NaN}', 409), (b"x"*65537, 413)]:
        response = custom.client.put(custom.path(doc), content=raw, headers=headers)
        assert response.status_code == status, response.text
        assert response.headers["Cache-Control"] == "no-store"
    for value in ["\x00", "\ud800"]:
        body = dict(expected_version=doc["version"], expected_revision_id=None, revision_id=definition["revision_id"],
                    values={"note": value}, reason="Unicode validation")
        assert custom.client.put(custom.path(doc), content=json.dumps(body), headers=headers).status_code == 409


def test_permissions_mfa_assignment_and_replay_revocation(custom):
    o, iam = custom.orders, custom.orders.iam
    assert custom.publish(who="buyer").status_code == 403
    plain, _ = iam.user("plain-admin")
    iam.grant(plain, "SYSADMIN")
    o.headers["plain"] = iam.headers(iam.login("plain-admin"))
    assert custom.publish(who="plain").json()["code"] == "MFA_REQUIRED"
    definition = ok(custom.publish())
    doc = ok(o.create(), 201)
    assert custom.read(doc, "admin").status_code == 404
    receiver, _ = iam.user("receiver")
    iam.grant(receiver, "RECEIVER", o.warehouse)
    o.headers["receiver"] = iam.headers(iam.login("receiver"))
    assert custom.read(doc, "receiver").status_code == 404
    key = uuid4()
    result = ok(custom.write(doc, definition, {"note": "memo"}, key=key))
    assert ok(custom.write(doc, definition, {"note": "memo"}, key=key)) == result
    assert custom.write(doc, definition, {"note": "other"}, key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    with o.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": o.buyer})
    assert custom.write(doc, definition, {"note": "memo"}, key=key).status_code == 404


def test_price_projection_history_no_downgrade_and_hidden_patch(custom):
    o, iam = custom.orders, custom.orders.iam
    definition = ok(custom.publish([field(), field("quote", "DECIMAL", visibility="PRICE")]))
    doc = ok(o.create(), 201)
    assert custom.write(doc, definition, {"quote": "99"}).status_code == 403
    iam.grant(o.buyer, "CONTROLLER", o.warehouse)
    iam.grant(o.buyer, "CONTROLLER")
    saved = ok(custom.write(doc, definition, {"quote": "99", "note": "public"}))
    with o.engine.begin() as c:
        c.execute(text("""DELETE FROM wms.role_permission WHERE permission_id=(SELECT id FROM wms.permission WHERE code='price.read')"""))
    assert "quote" not in json.dumps(ok(custom.read(saved)))
    assert "quote" not in json.dumps(ok(custom.history(saved)))
    changed = ok(custom.write(saved, definition, {"note": "next"}, expected=definition["revision_id"]))
    with o.engine.connect() as c:
        assert c.execute(text("SELECT values->>'quote' FROM wms.custom_field_binding")).scalar_one() == "99"
    assert custom.publish([field("quote")], version=1).status_code == 403
    retired = ok(custom.publish([], version=1))
    assert custom.write(changed, retired, {}, expected=definition["revision_id"]).status_code == 403


def test_product_version_import_preview_scope_and_no_core_mutation(custom):
    o = custom.orders
    definition = ok(custom.publish(kind="PRODUCT"))
    product = o.product
    saved = ok(custom.write(product, definition, {"note": "mô tả"}, target="products"))
    assert custom.write(product, definition, {"note": "stale"}, target="products").json()["code"] == "STALE_VERSION"
    before = ok(custom.read(saved, target="products"))
    body = dict(expected_version=saved["version"], expected_revision_id=definition["revision_id"],
                revision_id=definition["revision_id"], values={"note": "import"}, reason="Preview import")
    preview = custom.client.post(custom.path(saved, "products")+"/preview", json=body, headers={**o.headers["buyer"], "Idempotency-Key": str(uuid4())})
    assert ok(preview)["values"] == {"note": "import"}
    assert ok(custom.read(saved, target="products")) == before
    doc = ok(o.create(), 201)
    assert custom.write(doc, definition, {"note": "wrong kind"}).status_code == 404
    with o.engine.connect() as c:
        actual = c.execute(text("SELECT attributes,base_uom_id,tracking FROM wms.product WHERE id=:id"), {"id": product["id"]}).mappings().one()
        assert actual["attributes"] == {} and actual["tracking"] == "NONE"


def test_two_writes_two_publications_and_duplicate_key_race(custom):
    barrier = Barrier(2)
    def publish(_):
        barrier.wait(timeout=10)
        return custom.publish()
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(publish, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    definition = next(r.json() for r in responses if r.status_code == 200)
    doc = ok(custom.orders.create(), 201)
    def write(value):
        barrier.wait(timeout=10)
        return custom.write(doc, definition, {"note": value})
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(write, ["one", "two"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    doc = ok(custom.orders.create(), 201)
    key = uuid4()
    def replay(_):
        barrier.wait(timeout=10)
        return custom.write(doc, definition, {"note": "same"}, key=key)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(replay, range(2)))
    assert responses[0].status_code == responses[1].status_code == 200
    assert responses[0].json() == responses[1].json()


def test_rollback_atomic_history_outbox_ack_and_immutable_rows(custom, monkeypatch):
    service = custom.client.app.state.custom_fields
    definition = ok(custom.publish())
    doc = ok(custom.orders.create(), 201)
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("after outbox")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert custom.write(doc, definition, {"note": "test"}, key=key).status_code == 500
    with custom.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_binding")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_change")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='custom_field.values.updated.v1'")).scalar_one() == 0
    saved = ok(custom.write(doc, definition, {"note": "test"}, key=key))
    for sql in ["UPDATE wms.custom_field_revision SET reason='tamper'", "DELETE FROM wms.custom_field_definition",
                "UPDATE wms.custom_field_change SET values='{}'", "DELETE FROM wms.custom_field_binding"]:
        with pytest.raises(DatabaseError), custom.engine.begin() as c:
            c.execute(text(sql))
    submitted = ok(custom.orders.action(saved, "submit"))
    with pytest.raises(DatabaseError), custom.engine.begin() as c:
        c.execute(text("UPDATE wms.custom_field_binding SET values='{}'"))
    assert ok(custom.orders.decision(submitted))["status"] == "APPROVED"


def test_optional_auto_pin_and_preexisting_approval_are_stable(custom):
    old = custom.orders.submit()
    first = ok(custom.publish())
    assert ok(custom.orders.decision(old))["status"] == "APPROVED"
    doc = ok(custom.orders.create(), 201)
    submitted = ok(custom.orders.action(doc, "submit"))
    assert ok(custom.read(submitted))["revision_id"] == first["revision_id"]
    ok(custom.publish([field(required=True)], version=1))
    assert ok(custom.orders.decision(submitted))["status"] == "APPROVED"


def test_receipt_and_reversal_real_post_preserve_metadata_and_plan(custom, receiving):  # noqa: F811
    f = setup_reversal(receiving)
    first = ok(custom.publish([field(required=True)], kind="RECEIPT"))
    reverse_schema = ok(custom.publish([field("explanation", required=True)], kind="REVERSAL"))
    doc = ok(f.receipt_create(), 201)
    with f.engine.connect() as c:
        plan = c.execute(text("SELECT attributes FROM wms.document WHERE id=:id"), {"id": doc["id"]}).scalar_one()
    saved = ok(custom.write(doc, first, {"note": "original receipt"}))
    approved = ok(f.decision(ok(f.action(saved, "submit"))))
    ok(custom.publish([], version=1, kind="RECEIPT"))
    # New connections must execute database guards with a safe search_path.
    f.engine.dispose()
    posted = ok(f.post(approved))
    reverse = ok(f.rev_create(posted["transaction_id"]), 201)
    saved_reverse = ok(custom.write(reverse, reverse_schema, {"explanation": "wrong receipt"}, who="manager"))
    approved_reverse = ok(f.decision(ok(f.action(saved_reverse, "submit", "manager")), "controller"))
    reversed_doc = ok(f.rev_post(approved_reverse))
    assert ok(custom.read(posted))["values"] == {"note": "original receipt"}
    assert ok(custom.read(reversed_doc, who="manager"))["values"] == {"explanation": "wrong receipt"}
    assert custom.write(posted, first, {"note": "tamper"}, expected=first["revision_id"]).status_code == 409
    with f.engine.connect() as c:
        assert c.execute(text("SELECT attributes FROM wms.document WHERE id=:id"), {"id": doc["id"]}).scalar_one() == plan
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction")).scalar_one() == 2


@pytest.mark.parametrize("prefix", [10, 20, 21])
def test_custom_upgrade_preserves_legacy_definitions_attributes_and_prefix(empty_database, monkeypatch, prefix):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix])
        migrations.migrate(empty_database)
    uid, uom, product, definition = (uuid4() for _ in range(4))
    with empty_database.begin() as c:
        c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,'LEGACY','Legacy',0)"), {"id": uom})
        c.execute(text("""INSERT INTO wms.product(id,sku,name,base_uom_id,tracking,expiry_required,is_active,version,attributes)
            VALUES (:id,'LEGACY','Legacy',:uom,'NONE',false,true,1,'{"legacy_note":"keep"}')"""), {"id": product, "uom": uom})
        c.execute(text("""INSERT INTO wms.custom_field_definition(id,entity_type,code,value_type,required,validation,is_active)
            VALUES (:id,'PRODUCT','legacy_note','TEXT',false,'{}',true)"""), {"id": definition})
        if prefix >= 21:
            c.execute(text("INSERT INTO wms.app_user VALUES (:id,'upgrade-report','Upgrade','unused',true,0,now())"), {"id": uid})
            c.execute(text("""INSERT INTO wms.report_snapshot
                (id,requested_by,report_code,criteria,required_warehouses,created_at,expires_at,row_count,columns,sha256)
                VALUES (:id,:actor,'R01','{}','{}',now(),now()+interval '1 hour',1,'["physical"]',:hash)"""),
                {"id": definition, "actor": uid, "hash": "a" * 64})
            c.execute(text("INSERT INTO wms.report_snapshot_row VALUES (:id,1,'{\"physical\":\"10.000000\"}')"), {"id": definition})
        history = c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()
    migrations.migrate(empty_database)
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as c:
        assert c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()[:prefix] == history
        assert c.execute(text("SELECT attributes FROM wms.product WHERE id=:id"), {"id": product}).scalar_one() == {"legacy_note": "keep"}
        assert c.execute(text("SELECT revision_id FROM wms.custom_field_definition WHERE id=:id"), {"id": definition}).scalar_one() is None
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_binding")).scalar_one() == 0
        if prefix >= 21:
            assert c.execute(text("SELECT payload FROM wms.report_snapshot_row WHERE snapshot_id=:id"), {"id": definition}).scalar_one() == {"physical": "10.000000"}


def test_legacy_definition_requires_explicit_migration_and_stale_revision_is_blocked(custom):
    with custom.engine.begin() as c:
        c.execute(text("""INSERT INTO wms.custom_field_definition(id,entity_type,code,value_type,required,validation,is_active)
            VALUES (:id,'PRODUCT','old','TEXT',false,'{}',true)"""), {"id": uuid4()})
    assert custom.publish(kind="PRODUCT").json()["code"] == "LEGACY_CUSTOM_FIELDS"
    first = ok(custom.publish())
    doc = ok(custom.orders.create(), 201)
    ok(custom.publish([field("new_note")], version=1))
    assert custom.write(doc, first, {"note": "stale import"}).json()["code"] == "STALE_VERSION"


def test_submit_competes_with_value_edit_on_the_same_document_version(custom):
    definition = ok(custom.publish())
    doc = ok(custom.orders.create(), 201)
    barrier = Barrier(2)
    def run(edit):
        barrier.wait(timeout=10)
        return custom.write(doc, definition, {"note": "concurrent"}) if edit else custom.orders.action(doc, "submit")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [False, True]))
    assert sorted(r.status_code for r in results) == [200, 409]
    with custom.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_change")).scalar_one() == 1


def test_schema_publication_rollback_and_duplicate_key_replay(custom, monkeypatch):
    service = custom.client.app.state.custom_fields
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("schema effect failure")
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail)
        assert custom.publish(key=key).status_code == 500
    with custom.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_schema")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_revision")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.custom_field_definition")).scalar_one() == 0
    result = ok(custom.publish(key=key))
    assert ok(custom.publish(key=key)) == result
    assert custom.publish([field("other")], key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"


@pytest.mark.parametrize("kind", ["ADJUSTMENT", "REVERSAL", "TRANSFER"])
def test_price_scope_inherits_both_transfer_warehouses_for_loss_and_reversal(custom, transfer, kind):  # noqa: F811
    f = setup_reversal(transfer)
    definition = ok(custom.publish([field("quote", "DECIMAL", visibility="PRICE")], kind=kind))
    if kind == "TRANSFER":
        doc = ok(f.tr_create(f.tr_seed()), 201)
    else:
        sent = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
        arrived = ok(f.tr_receive(sent))
        if kind == "ADJUSTMENT":
            _, doc = missing_loss(f, arrived)
        else:
            doc = ok(f.rev_create(arrived["transaction_id"]), 201)
    # Manager can access/edit the object in both warehouses, but price permission
    # is initially granted only in the source warehouse.
    f.iam.grant(f.manager, "CONTROLLER")
    f.iam.grant(f.manager, "CONTROLLER", f.warehouse)
    assert custom.write(doc, definition, {"quote": "97"}, who="manager").status_code == 403
    destination_grant = f.iam.grant(f.manager, "CONTROLLER", f.destination)
    key = uuid4()
    saved = ok(custom.write(doc, definition, {"quote": "97"}, who="manager", key=key))
    assert ok(custom.read(saved, who="manager"))["values"] == {"quote": "97"}
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": destination_grant})
    assert "quote" not in json.dumps(ok(custom.read(saved, who="manager")))
    assert "quote" not in json.dumps(ok(custom.history(saved, who="manager")))
    assert custom.write(doc, definition, {"quote": "97"}, who="manager", key=key).status_code == 403
