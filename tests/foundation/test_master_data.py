from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog(iam):
    user, _ = iam.user("catalog")
    iam.catalog_user = user
    iam.catalog_grant = iam.grant(user, "MASTER_DATA")
    iam.catalog_headers = iam.headers(iam.login("catalog"))
    return iam


def write(catalog, name, payload, *, key=None, entity=None, headers=None):
    return catalog.client.request("PUT" if entity else "POST", "/api/v1/master/" + name + ("/" + entity if entity else ""),
                                  json=payload, headers={**(headers or catalog.catalog_headers), "Idempotency-Key": str(key or uuid4())})


def create(catalog, entity_name, **values):
    result = write(catalog, entity_name, {"reason": "Dữ liệu kiểm thử", **values})
    assert result.status_code == 201, result.text
    return result.json()


def update_payload(record, **changes):
    return {**{k: v for k, v in record.items() if k not in {"id", "version"}},
            "expected_version": record["version"], "reason": "Cập nhật kiểm thử", **changes}


def product(catalog, **values):
    uom = create(catalog, "uoms", code=uuid4().hex[:20], name="Chiếc", decimal_places=0)
    return create(catalog, "products", sku=uuid4().hex, name="Thiết bị", base_uom_id=uom["id"], tracking="NONE", **values)


def test_master_permissions_are_live_and_global_not_inferred_from_warehouse(iam):
    user, _ = iam.user()
    warehouse = iam.warehouse("WH")
    iam.grant(user, "MASTER_DATA", warehouse)
    headers = iam.headers(iam.login())
    for name in ["products", "uoms", "categories", "partners", "warehouses", "locations", "barcodes"]:
        assert iam.client.get("/api/v1/master/" + name).status_code == 401
        assert iam.client.get("/api/v1/master/" + name, headers=headers).status_code == 403
    iam.grant(user, "RECEIVER")
    assert iam.client.get("/api/v1/master/products", headers=headers).status_code == 200
    assert iam.client.get("/api/v1/master/partners", headers=headers).status_code == 403
    r = iam.client.post("/api/v1/master/uoms", headers={**headers, "Idempotency-Key": str(uuid4())},
                        json={"code": "EA", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử"})
    assert r.status_code == 403


def test_catalog_crud_pagination_search_and_no_stock_effect(catalog):
    rows = [create(catalog, "uoms", code=f"ea{i}", name=f"Đơn vị {i}", decimal_places=i) for i in range(5)]
    found, after = [], None
    while True:
        r = catalog.client.get("/api/v1/master/uoms", params={"limit": 2, **({"after": after} if after else {})}, headers=catalog.catalog_headers)
        assert r.status_code == 200, r.text
        found.extend(row["id"] for row in r.json()["items"])
        after = r.json()["next_after"]
        if not after:
            break
    assert len(found) == len(set(found)) == 5
    assert set(found) == {r["id"] for r in rows}
    assert rows[0]["code"] == "EA0"
    for query, count in [("đơn vị", 5), ("ea2", 1), ("%", 0), ("_", 0), ("' OR true --", 0)]:
        r = catalog.client.get("/api/v1/master/uoms", params={"q": query}, headers=catalog.catalog_headers)
        assert len(r.json()["items"]) == count
    inactive = write(catalog, "uoms", update_payload(rows[0], is_active=False), entity=rows[0]["id"])
    assert inactive.status_code == 200 and inactive.json()["version"] == 2
    assert len(catalog.client.get("/api/v1/master/uoms?active=true", headers=catalog.catalog_headers).json()["items"]) == 4
    assert catalog.client.delete("/api/v1/master/uoms/" + rows[0]["id"], headers=catalog.catalog_headers).status_code == 405
    with catalog.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.stock_move")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.stock_balance")).scalar_one() == 0
        for table in ["outbox_event", "idempotency_record"]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 6
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action LIKE 'master.%'")).scalar_one() == 6


def test_idempotency_stale_version_mismatch_and_revoked_replay(catalog):
    body = {"code": "EA", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử"}
    key = uuid4()
    first = write(catalog, "uoms", body, key=key)
    assert first.status_code == 201
    assert write(catalog, "uoms", body, key=key).json() == first.json()
    assert write(catalog, "uoms", {**body, "name": "Khác"}, key=key).json()["code"] == "IDEMPOTENCY_MISMATCH"
    record = first.json()
    update_key = uuid4()
    changed = write(catalog, "uoms", update_payload(record, name="Cái"), entity=record["id"], key=update_key)
    assert changed.status_code == 200
    assert write(catalog, "uoms", update_payload(record, name="Cái"), entity=record["id"], key=update_key).json() == changed.json()
    assert write(catalog, "uoms", update_payload(record, name="Khác"), entity=record["id"]).json()["code"] == "STALE_VERSION"
    with catalog.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": catalog.catalog_grant})
    assert write(catalog, "uoms", body, key=key).status_code == 403


def test_parallel_same_key_creates_one_row_audit_outbox(catalog):
    key = uuid4()
    body = {"code": "EA", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử"}
    gate = Barrier(2)
    def run():
        gate.wait(timeout=5)
        return write(catalog, "uoms", body, key=key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json() == results[1].json()
    with catalog.engine.connect() as c:
        for table in ["uom", "outbox_event", "idempotency_record"]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 1


def test_duplicate_and_validation_return_safe_field_errors(catalog):
    uom = create(catalog, "uoms", code="EA", name="Chiếc", decimal_places=0)
    assert write(catalog, "uoms", update_payload(uom, is_active=False), entity=uom["id"]).status_code == 200
    r = write(catalog, "uoms", {"code": " ea ", "name": "Trùng", "decimal_places": 0, "reason": "Kiểm thử"})
    assert r.status_code == 409 and r.json()["field_errors"][0]["field"] == "code"
    for values in [{"decimal_places": 7}, {"decimal_places": True}, {"is_active": "false"}, {"unexpected": "secret-fixture"}]:
        r = write(catalog, "uoms", {"code": "NEW", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử", **values})
        assert r.status_code == 422
        assert "secret-fixture" not in r.text
    r = write(catalog, "products", {"sku": "TEST", "name": "Test", "base_uom_id": uom["id"], "tracking": "NONE", "reason": "Kiểm thử"})
    assert r.status_code == 409 and r.json()["field_errors"][0]["field"] == "base_uom_id"


def test_catalog_rollback_includes_audit_outbox_and_replay_record(catalog, monkeypatch):
    service = catalog.client.app.state.master_data
    original = service.effects
    def fail(*args):
        original(*args)
        raise RuntimeError("fixture failure after outbox")
    monkeypatch.setattr(service, "effects", fail)
    r = write(catalog, "uoms", {"code": "EA", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử"})
    assert r.status_code == 500
    with catalog.engine.connect() as c:
        for table in ["uom", "outbox_event", "idempotency_record"]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action LIKE 'master.%'")).scalar_one() == 0


def test_category_cycle_is_rejected_even_under_competing_edits(catalog):
    a = create(catalog, "categories", code="A", name="A")
    b = create(catalog, "categories", code="B", name="B")
    gate = Barrier(2)
    def run(pair):
        current, parent = pair
        gate.wait(timeout=5)
        return write(catalog, "categories", update_payload(current, parent_id=parent["id"]), entity=current["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [(a, b), (b, a)]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r for r in results if r.status_code == 409).json()["code"] == "INVALID_TREE"


def test_location_tree_cross_warehouse_cycles_and_configuration_scope(catalog):
    wh = create(catalog, "warehouses", code="WH", name="Kho")
    other = create(catalog, "warehouses", code="WH2", name="Kho 2")
    zone = create(catalog, "locations", code="Z1", name="Zone", kind="GROUP", warehouse_id=wh["id"])
    rack = create(catalog, "locations", code="R1", name="Rack", kind="GROUP", warehouse_id=wh["id"], parent_id=zone["id"])
    bin_ = create(catalog, "locations", code="B1", name="Bin", kind="STORAGE", warehouse_id=wh["id"], parent_id=rack["id"])
    for changes in [{"warehouse_id": other["id"]}, {"parent_id": None}, {"parent_id": zone["id"]}, {"parent_id": bin_["id"]}]:
        r = write(catalog, "locations", update_payload(bin_, **changes), entity=bin_["id"])
        assert r.status_code == 409, r.text
    r = write(catalog, "locations", update_payload(zone, parent_id=rack["id"]), entity=zone["id"])
    assert r.status_code == 409 and r.json()["code"] == "INVALID_TREE"
    assert write(catalog, "warehouses", update_payload(wh, is_active=False), entity=wh["id"]).status_code == 409
    assert catalog.client.get("/api/v1/warehouses", headers=catalog.catalog_headers).json() == []
    assert len(catalog.client.get("/api/v1/master/locations", params={"warehouse_id": wh["id"]}, headers=catalog.catalog_headers).json()["items"]) == 3
    for location in [bin_, rack, zone]:
        assert write(catalog, "locations", update_payload(location, is_active=False), entity=location["id"]).status_code == 200
    assert write(catalog, "warehouses", update_payload(wh, is_active=False), entity=wh["id"]).status_code == 200


def test_tracking_and_base_uom_lock_after_reference_and_expiry_optional(catalog):
    p = product(catalog)
    other = create(catalog, "uoms", code="BOX", name="Hộp", decimal_places=0)
    with catalog.engine.begin() as c:
        c.execute(text("INSERT INTO wms.stock_item(id,product_id,owner_id) VALUES (:id,:product,'00000000-0000-4000-8000-000000000001')"), {"id": uuid4(), "product": p["id"]})
    for changes in [{"tracking": "LOT"}, {"base_uom_id": other["id"]}]:
        r = write(catalog, "products", update_payload(p, **changes), entity=p["id"])
        assert r.status_code == 409 and r.json()["code"] == "PRODUCT_IN_USE"
    assert write(catalog, "products", update_payload(p, name="Tên mới"), entity=p["id"]).status_code == 200
    lot = create(catalog, "products", sku="LOT-01", name="Linh kiện", base_uom_id=other["id"], tracking="LOT")
    assert lot["expiry_required"] is False
    r = write(catalog, "products", update_payload(lot, tracking="SERIAL", expiry_required=True), entity=lot["id"])
    assert r.status_code == 422


def test_conversion_revisions_preserve_history_and_retire_old_barcodes(catalog):
    p = product(catalog)
    box = create(catalog, "uoms", code="BOX", name="Hộp", decimal_places=0)
    conversion = create(catalog, "product-uoms", product_id=p["id"], uom_id=box["id"], factor="12", expected_product_version=1)
    barcode = create(catalog, "barcodes", code="0000123", product_uom_id=conversion["id"])
    scan = catalog.client.get("/api/v1/master/scan?code=0000123", headers=catalog.catalog_headers)
    assert scan.status_code == 200 and scan.json()["factor"] == "12.00000000"
    revised = create(catalog, "product-uoms", product_id=p["id"], uom_id=box["id"], factor="24", expected_product_version=2)
    assert revised["revision"] == 2
    assert catalog.client.get("/api/v1/master/scan?code=0000123", headers=catalog.catalog_headers).status_code == 404
    assert write(catalog, "barcodes", update_payload(barcode, product_uom_id=revised["id"]), entity=barcode["id"]).status_code == 409
    assert write(catalog, "barcodes", {"code": "0000123", "product_uom_id": revised["id"], "reason": "Kiểm thử"}).json()["code"] == "DUPLICATE_CODE"
    with catalog.engine.connect() as c:
        assert str(c.execute(text("SELECT factor FROM wms.product_uom WHERE id=:id"), {"id": conversion["id"]}).scalar_one()) == "12.00000000"
    with pytest.raises(DatabaseError), catalog.engine.begin() as c:
        c.execute(text("UPDATE wms.product_uom SET factor=99 WHERE id=:id"), {"id": conversion["id"]})


def test_conversion_decimal_contract_and_serial_integer_rules(catalog):
    p = product(catalog)
    box = create(catalog, "uoms", code="BOX", name="Hộp", decimal_places=0)
    serial = create(catalog, "products", sku="SER-01", name="Thiết bị", base_uom_id=p["base_uom_id"], tracking="SERIAL")
    body = {"product_id": serial["id"], "uom_id": box["id"], "factor": "1.5", "expected_product_version": 1, "reason": "Kiểm thử"}
    assert write(catalog, "product-uoms", body).json()["code"] == "INVALID_UOM"
    for factor in [1.5, "0", "-1", "1e2", "NaN", "1.000000001"]:
        assert write(catalog, "product-uoms", {**body, "factor": factor}).status_code == 422
    assert write(catalog, "product-uoms", {**body, "factor": "2", "uom_id": p["base_uom_id"]}).json()["code"] == "INVALID_UOM"


def test_price_append_and_scope_never_leak_through_product_or_replay(catalog):
    p = product(catalog)
    wh = catalog.warehouse("WH")
    other = catalog.warehouse("OTHER")
    user, _ = catalog.user("controller")
    catalog.grant(user, "CONTROLLER")
    headers = catalog.headers(catalog.login("controller"))
    body = {"effective_on": "2026-10-02", "amount": "123456.7800", "currency": "VND", "source": "Bảng giá mẫu 01"}
    endpoint = "products/" + p["id"] + "/prices"
    assert write(catalog, endpoint, body).status_code == 403
    key = uuid4()
    r = write(catalog, endpoint, body, key=key, headers=headers)
    assert r.status_code == 201 and "amount" not in r.json()
    assert write(catalog, endpoint, body, key=key, headers=headers).json() == r.json()
    assert catalog.client.get("/api/v1/master/" + endpoint, params={"warehouse_id": wh}, headers=headers).status_code == 403
    catalog.grant(user, "CONTROLLER", wh)
    read = catalog.client.get("/api/v1/master/" + endpoint, params={"warehouse_id": wh}, headers=headers)
    assert read.status_code == 200 and read.json()["items"][0]["amount"] == "123456.7800"
    assert catalog.client.get("/api/v1/master/" + endpoint, params={"warehouse_id": other}, headers=headers).status_code == 403
    assert "amount" not in catalog.client.get("/api/v1/master/products/" + p["id"], headers=catalog.catalog_headers).text
    assert write(catalog, endpoint, body, headers=headers).json()["code"] == "DUPLICATE_PRICE"
    with pytest.raises(DatabaseError), catalog.engine.begin() as c:
        c.execute(text("DELETE FROM wms.reference_price WHERE id=:id"), {"id": r.json()["id"]})


def test_partner_minimal_dto_and_no_hard_delete(catalog):
    partner = create(catalog, "partners", code="SUP-01", name="NCC kiểm thử", is_supplier=True)
    assert set(partner) == {"id", "code", "name", "is_supplier", "is_customer", "is_active", "version", "tax_code", "address"}
    assert partner["tax_code"] is None and partner["address"] is None
    assert write(catalog, "partners", update_payload(partner, is_active=False), entity=partner["id"]).status_code == 200
    assert write(catalog, "partners", {"code": "NONE", "name": "Sai loại", "reason": "Kiểm thử"}).status_code == 422
    assert catalog.client.delete("/api/v1/master/partners/" + partner["id"], headers=catalog.catalog_headers).status_code == 405
