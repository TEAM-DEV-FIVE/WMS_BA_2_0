from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from test_imports import imports  # noqa: F401
from test_issues import issuing, reconcile  # noqa: F401
from test_move_quality import movement  # noqa: F401
from test_openings import inventory, opening, orders  # noqa: F401
from test_orders import ok
from test_receipts import receiving  # noqa: F401

from apps.server.application.commands import payload_hash
from packages.contracts.traceability import COMPANY_OWNER, UNCLASSIFIED_OWNER

pytestmark = pytest.mark.integration


def agreement(f):
    owner = f.master("stock-owners", code="CG-OWNER", name="Chủ ký gửi", partner_id=f.partner["id"])
    contract = f.master(
        "consignment-agreements",
        code="CG-01",
        owner_id=owner["id"],
        warehouse_id=str(f.warehouse),
        valid_from="2026-01-01",
        valid_until="2027-12-31",
        source_ref="Hợp đồng lưu kho CG-01 đã ký",
    )
    return owner, contract


@pytest.fixture
def consignment(opening):  # noqa: F811
    f = opening
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    f.owner, f.agreement = agreement(f)
    f.receiving = f.master(
        "locations", code="CG-IN", name="Nhận ký gửi", kind="RECEIVING", warehouse_id=str(f.warehouse)
    )
    f.consigned_body = dict(
        warehouse_id=str(f.warehouse),
        batch_key=str(uuid4()),
        business_date="2026-10-02",
        delivery_reference="BB-GIAO-NHAN-CG-001",
        reason="Nhận giữ hàng theo hợp đồng",
        lines=[
            dict(
                product_id=f.product["id"],
                quantity_base="5",
                owner_id=f.owner["id"],
                consignment_id=f.agreement["id"],
                destination_location_id=f.receiving["id"],
            )
        ],
    )

    def request(method, path="consignment-receipts", body=None, who="buyer", key=None):
        return f.client.request(
            method,
            "/api/v1/" + path,
            json=body,
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
        )

    def approve(body=None):
        draft = ok(request("POST", body=body or f.consigned_body), 201)
        return ok(f.decision(ok(f.action(draft, "submit")), "manager"))

    def post(doc, payload=None, key=None, who="buyer"):
        return request(
            "POST", f"consignment-receipts/{doc['id']}/post", payload or f.open_post_body(doc), who, key
        )

    f.cg_request, f.cg_approve, f.cg_post = request, approve, post
    return f


def test_consignment_opening_ten_company_five_consigned_snapshot_and_replay(consignment):
    f = consignment
    body = deepcopy(f.opening_body)
    body["lines"].append(
        {
            **body["lines"][0],
            "quantity_base": "5",
            "owner_id": f.owner["id"],
            "consignment_id": f.agreement["id"],
        }
    )
    approved = f.open_approve(body)
    payload, key = f.open_post_body(approved), uuid4()
    posted = ok(f.open_post(approved, payload, key))
    assert ok(f.open_post(approved, payload, key)) == posted == ok(f.open_post(approved, payload))
    assert inventory(f) == (1, 2, 15, 0)
    view = ok(f.open_read(approved))
    assert {line["owner_id"] for line in view["plan"]} == {str(COMPANY_OWNER), f.owner["id"]}
    with f.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT i.id,i.owner_id,b.on_hand FROM wms.stock_item i JOIN wms.stock_balance b ON b.stock_item_id=i.id"
            )
        ).all()
        snapshot = c.execute(
            text("SELECT content_snapshot FROM wms.approval_request WHERE document_id=:id"),
            {"id": approved["id"]},
        ).scalar_one()
        assert snapshot["ownership"]["agreements"][0]["source_ref"] == "Hợp đồng lưu kho CG-01 đã ký"
    assert len(rows) == 2 and {str(r.owner_id): r.on_hand for r in rows} == {
        str(COMPANY_OWNER): 10,
        f.owner["id"]: 5,
    }
    result = ok(
        f.cg_request(
            "GET",
            f"stock-ownership?warehouse_id={f.warehouse}&location_id={f.location['id']}&stock_item_id={rows[0].id}",
        )
    )
    assert (result["physical_base"], result["owned_base"]) == ("15.000000", "10.000000")
    assert result["consigned_by_owner"][0]["quantity_base"] == "5.000000"
    reconcile(f)


def test_consignment_extension_preserves_pre_b09_company_opening_idempotency_hash(opening):  # noqa: F811
    f = opening
    key = uuid4()
    legacy = deepcopy(f.opening_body)
    for line in legacy["lines"]:
        line.update(lot_code=None, serial_code=None, manufactured_on=None, expires_on=None)
    expected = payload_hash("opening.create", UUID(int=0), legacy)
    created = ok(f.open_create(key=key), 201)
    with f.engine.connect() as c:
        stored = c.execute(
            text("SELECT request_hash FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key"),
            {"actor": f.buyer, "key": key},
        ).scalar_one()
    assert stored == expected
    legacy["lines"][0]["consignment_id"] = None
    assert ok(f.open_create(legacy, key), 201) == created


def test_consignment_receipt_lifecycle_evidence_sod_replay_scope_and_warranty(consignment):
    f = consignment
    product = f.master(
        "products",
        sku="CG-SERIAL",
        name="Ký gửi serial",
        base_uom_id=f.product["base_uom_id"],
        tracking="SERIAL",
    )
    body = deepcopy(f.consigned_body)
    body["lines"][0].update(product_id=product["id"], quantity_base="1", serial_code="000Cg-A")
    key = uuid4()
    draft = ok(f.cg_request("POST", body=body, key=key), 201)
    assert ok(f.cg_request("POST", body=body, key=key), 201) == draft
    submitted = ok(f.action(draft, "submit"))
    assert f.decision(submitted, "buyer").json()["code"] == "SELF_APPROVAL"
    approved = ok(f.decision(submitted, "manager"))
    assert f.cg_post(approved, who="manager").status_code == 403  # Current assignment policy applies.
    payload, key = f.open_post_body(approved), uuid4()
    posted = ok(f.cg_post(approved, payload, key))
    assert ok(f.cg_post(approved, payload, key)) == posted == ok(f.cg_post(approved, payload))
    assert f.cg_post(approved, {**payload, "reason": "Thay nội dung"}).json()["code"] == "EXECUTION_MISMATCH"
    assert (
        f.cg_post(approved, {**payload, "reason": "Thay nội dung"}, key).json()["code"]
        == "IDEMPOTENCY_MISMATCH"
    )
    assert (
        ok(f.cg_request("GET", f"consignment-receipts/operations/{key}"))["transaction_id"]
        == posted["transaction_id"]
    )
    assert (
        ok(f.cg_request("GET", f"consignment-receipts/{draft['id']}"))["delivery_reference"]
        == body["delivery_reference"]
    )
    assert ok(f.cg_request("GET", f"receipts?warehouse_id={f.warehouse}"))["items"] == []
    assert len(ok(f.cg_request("GET", f"consignment-receipts?warehouse_id={f.warehouse}"))["items"]) == 1
    with f.engine.connect() as c:
        move, serial = c.execute(
            text(
                "SELECT m.id,i.serial_id FROM wms.stock_move m JOIN wms.stock_item i ON i.id=m.stock_item_id"
            )
        ).one()
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='consignment_receipt.post'")).scalar_one() == 1
        assert c.execute(text("SELECT payload FROM wms.outbox_event WHERE event_type='consignment_receipt.post.v1'")).scalar_one() == posted
        assert c.execute(text("SELECT count(*) FROM wms.outbox_event WHERE event_type='receipt.post.v1'")).scalar_one() == 0
    warranty = ok(f.cg_request("GET", f"serials/{serial}/warranty?warehouse_id={f.warehouse}"))
    assert (
        warranty["receipt_move_id"] == str(move)
        and warranty["receipt_id"] == draft["id"]
        and warranty["status"] == "UNKNOWN"
    )
    outside = f.iam.warehouse("CG-OUTSIDE")
    assert f.cg_request("GET", f"consignment-receipts/owners?warehouse_id={outside}").status_code == 404
    reconcile(f)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"owner_id": str(UNCLASSIFIED_OWNER), "consignment_id": None}, "OWNERSHIP_UNRESOLVED"),
        ({"consignment_id": None}, "INVALID_REFERENCE"),
        ({"owner_id": str(COMPANY_OWNER)}, "INVALID_REFERENCE"),
        ({"owner_id": str(COMPANY_OWNER), "consignment_id": None}, "INVALID_REFERENCE"),
    ],
)
def test_consignment_rejects_unclassified_missing_and_mismatched_owner(consignment, change, code):
    f = consignment
    body = deepcopy(f.consigned_body)
    body["lines"][0].update(change)
    response = f.cg_request("POST", body=body)
    assert response.status_code in {409, 422} and response.json()["code"] == code
    assert inventory(f) == (0, 0, 0, 0)


def test_consignment_revalidates_agreement_snapshot_and_current_rights(consignment):
    f = consignment
    body = {**f.consigned_body, "business_date": "2030-01-01"}
    assert f.cg_request("POST", body=body).json()["code"] == "INVALID_AGREEMENT"
    approved = f.cg_approve()
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.stock_owner SET name='Tên mới',version=version+1 WHERE id=:id"),
            {"id": f.owner["id"]},
        )
    assert f.cg_post(approved).json()["code"] == "STALE_APPROVAL"
    assert inventory(f) == (0, 0, 0, 0)
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.consignment_agreement SET is_active=false WHERE id=:id"),
            {"id": f.agreement["id"]},
        )
    assert (
        f.cg_request("POST", body={**f.consigned_body, "batch_key": str(uuid4())}).json()["code"]
        == "INVALID_REFERENCE"
    )


def test_consignment_replay_and_ack_require_current_warehouse_rights(consignment):
    f = consignment
    doc = f.cg_approve()
    payload, key = f.open_post_body(doc), uuid4()
    ok(f.cg_post(doc, payload, key))
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id AND warehouse_id=:wh"),
            {"id": f.buyer, "wh": f.warehouse},
        )
    assert f.cg_post(doc, payload, key).status_code in {403, 404}
    assert f.cg_request("GET", f"consignment-receipts/operations/{key}").status_code in {403, 404}
    assert inventory(f) == (1, 1, 5, 0)


def test_consignment_post_atomic_rollback_and_parallel_same_execution(consignment):
    f = consignment
    approved = f.cg_approve()
    payload, key = f.open_post_body(approved), uuid4()

    def fail(c, cursor, statement, parameters, context, many):
        if "INSERT INTO wms.outbox_event" in statement:
            raise RuntimeError("consignment failpoint after ledger/balance/audit")

    event.listen(f.engine, "before_cursor_execute", fail)
    try:
        response = f.cg_post(approved, payload, key)
        assert response.status_code == 500 and response.json()["code"] == "INTERNAL_ERROR"
    finally:
        event.remove(f.engine, "before_cursor_execute", fail)
    assert inventory(f) == (0, 0, 0, 0)
    barrier = Barrier(2)

    def post():
        barrier.wait(5)
        return ok(f.cg_post(approved, payload))

    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(lambda _: post(), range(2)))
    assert a == b and inventory(f) == (1, 1, 5, 0)
    reconcile(f)


def test_consignment_import_owner_agreement_dry_run_commit_and_stale_reference(imports):  # noqa: F811
    f = imports
    owner, contract = agreement(f)
    rows = [
        ["CG-CUT", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 10, "COMPANY", ""],
        ["CG-CUT", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 5, owner["code"], contract["code"]],
    ]
    job = f.prepare("11_opening", rows)
    assert job["status"] == "VALIDATED" and inventory(f) == (0, 0, 0, 0)
    result = ok(f.import_action(job))
    assert ok(f.import_action(job)) == result
    with f.engine.connect() as c:
        doc_id = c.execute(text("SELECT document_id FROM wms.import_document_source")).scalar_one()
    draft = ok(f.open_read({"id": str(doc_id)}))
    assert {line["consignment_id"] for line in draft["plan"]} == {None, contract["id"]}
    ok(f.open_post(ok(f.decision(ok(f.action(draft, "submit")), "director"))))
    assert inventory(f) == (1, 2, 15, 0)
    reconcile(f)


def test_consignment_import_revalidates_agreement_after_dry_run(imports):  # noqa: F811
    f = imports
    owner, contract = agreement(f)
    job = f.prepare(
        "11_opening",
        [["CG-STALE", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 5, owner["code"], contract["code"]]],
    )
    assert job["status"] == "VALIDATED"
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.consignment_agreement SET is_active=false,version=version+1 WHERE id=:id"),
            {"id": contract["id"]},
        )
    assert f.import_action(job).status_code == 409
    assert inventory(f) == (0, 0, 0, 0)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.opening_document")).scalar_one() == 0


def test_consignment_reservation_cannot_borrow_other_owner_inventory(issuing):  # noqa: F811
    f = issuing
    owner, contract = agreement(f)
    body = deepcopy(f.opening_body)
    body["lines"].append(
        {**body["lines"][0], "quantity_base": "5", "owner_id": owner["id"], "consignment_id": contract["id"]}
    )
    f.seed(body)
    issue = f.issue_approve()
    plan = f.reserve_body(issue, "10")
    with f.engine.connect() as c:
        item = c.execute(
            text("SELECT id FROM wms.stock_item WHERE owner_id=:owner"), {"owner": owner["id"]}
        ).scalar_one()
    tampered = deepcopy(plan)
    tampered["lines"][0].update(stock_item_id=str(item), quantity_base="5")
    assert f.issue_command(f"issues/{issue['id']}/reservations/reserve", tampered).status_code == 409
    reserved = ok(f.issue_command(f"issues/{issue['id']}/reservations/reserve", plan))
    with f.engine.connect() as c:
        balances = {
            str(r.owner_id): (r.on_hand, r.reserved)
            for r in c.execute(
                text(
                    "SELECT i.owner_id,b.on_hand,b.reserved FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id"
                )
            )
        }
    assert balances == {str(COMPANY_OWNER): (10, 10), owner["id"]: (5, 0)}
    ok(f.issue_post(reserved, f.issue_post_body(reserved, "10")))
    assert inventory(f)[2] == 5
    reconcile(f)


def test_consignment_serial_race_across_two_owners_has_one_physical_position(consignment):
    f = consignment
    partner = f.master("partners", code="CG-NCC2", name="Chủ thứ hai", is_supplier=True)
    owner = f.master("stock-owners", code="CG-OWNER2", name="Ký gửi thứ hai", partner_id=partner["id"])
    contract = f.master(
        "consignment-agreements",
        code="CG-02",
        owner_id=owner["id"],
        warehouse_id=str(f.warehouse),
        valid_from="2026-01-01",
        valid_until="2027-12-31",
        source_ref="Hợp đồng CG-02",
    )
    product = f.master(
        "products",
        sku="CG-RACE",
        name="Serial dùng chung",
        base_uom_id=f.product["base_uom_id"],
        tracking="SERIAL",
    )
    body = deepcopy(f.consigned_body)
    body["lines"][0].update(product_id=product["id"], quantity_base="1", serial_code="001SameSerial")
    first = f.cg_approve(body)
    body["batch_key"] = str(uuid4())
    body["lines"][0].update(owner_id=owner["id"], consignment_id=contract["id"])
    second = f.cg_approve(body)
    barrier = Barrier(2)

    def post(doc):
        barrier.wait(5)
        return f.cg_post(doc)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(post, [first, second]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "SERIAL_ALREADY_PRESENT"
    assert inventory(f) == (1, 1, 1, 1)
    reconcile(f)


@pytest.mark.parametrize("serial", [False, True])
def test_consignment_receipt_quality_putaway_preserves_owner(movement, serial):  # noqa: F811
    f = movement
    owner, contract = agreement(f)
    body = dict(
        warehouse_id=str(f.warehouse),
        batch_key=str(uuid4()),
        business_date="2026-10-02",
        delivery_reference="Giao hàng CG-QC",
        reason="Nhận ký gửi",
        lines=[
            dict(
                product_id=f.product["id"],
                quantity_base="5",
                owner_id=owner["id"],
                consignment_id=contract["id"],
                destination_location_id=f.location["id"],
            )
        ],
    )
    if serial:
        product = f.master(
            "products",
            sku="CG-QC-SERIAL",
            name="Serial ký gửi",
            base_uom_id=f.product["base_uom_id"],
            tracking="SERIAL",
        )
        body["lines"][0].update(product_id=product["id"], quantity_base="1", serial_code="000CgQc")
    draft = ok(f.move_request("POST", "consignment-receipts", body), 201)
    doc = ok(f.decision(ok(f.action(draft, "submit"))))
    ok(
        f.move_request(
            "POST",
            f"consignment-receipts/{doc['id']}/post",
            dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="Ghi sổ ký gửi"),
        )
    )
    source = ok(f.move_request("GET", f"quality/sources?warehouse_id={f.warehouse}"))["items"][0]
    if serial:
        before = ok(
            f.move_request("GET", f"serials/lookup?warehouse_id={f.warehouse}&code=000CgQc", who="manager")
        )[0]
        ok(
            f.move_request(
                "POST",
                f"serials/{before['serial_id']}/warranty-records",
                dict(
                    expected_version=0,
                    receipt_move_id=source["id"],
                    starts_on="2026-10-02",
                    ends_on="2027-10-02",
                    evidence_ref="Phiếu BH đã ký CG-QC",
                    reason="Ghi chứng cứ bảo hành",
                ),
                who="manager",
            ),
            201,
        )
    f.putaway("1" if serial else "5", "0", source)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(DISTINCT stock_item_id) FROM wms.stock_move")).scalar_one() == 1
        assert c.execute(text("SELECT owner_id,consignment_id FROM wms.stock_item")).one() == (
            UUID(owner["id"]),
            UUID(contract["id"]),
        )
    if serial:
        after = ok(
            f.move_request("GET", f"serials/lookup?warehouse_id={f.warehouse}&code=000CgQc", who="manager")
        )[0]
        assert after["receipt_move_id"] == before["receipt_move_id"] == source["id"]
        assert after["receipt_id"] == doc["id"] and after["warranty_evidence_ref"] == "Phiếu BH đã ký CG-QC"
    # A caller may not disguise reversal as a same-warehouse MOVE.
    with pytest.raises(IntegrityError, match="Consignment reversal policy"), f.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,
            source_location_id,destination_location_id,quantity_base,base_uom_id,reverses_move_id)
            SELECT :new_id,m.transaction_id,m.line_id,m.stock_item_id,m.destination_location_id,
            m.source_location_id,m.quantity_base,m.base_uom_id,m.id FROM wms.stock_move m
            JOIN wms.inventory_transaction t ON t.id=m.transaction_id WHERE t.operation='MOVE' LIMIT 1"""),
            {"new_id": uuid4()},
        )
    reconcile(f)
