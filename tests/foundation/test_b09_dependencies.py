"""Integration evidence for the reviewed B01/B02/B03/B05/B06 base of B09."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_issues import reconcile
from test_move_quality import movement  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("prefix_length", [10, 11, 12, 13])
def test_b09_dependency_upgrade_preserves_prefix_and_distinct_policies(empty_database, monkeypatch, prefix_length):
    import apps.server.infrastructure.migrations as migrations

    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix_length])
        migrations.migrate(empty_database)
    with empty_database.connect() as c:
        original = set(c.execute(text("SELECT id,document_kind,revision,is_active FROM wms.approval_policy")).all())
    assert migrations.migrate(empty_database) == [source[0] for source in sources[prefix_length:]]
    assert migrations.is_ready(empty_database)
    assert migrations.migrate(empty_database) == []
    with empty_database.connect() as c:
        current = set(c.execute(text("SELECT id,document_kind,revision,is_active FROM wms.approval_policy")).all())
        assert original <= current
        policies = c.execute(text("""SELECT p.document_kind,p.id,s.id,r.code,a.code
            FROM wms.approval_policy p JOIN wms.approval_policy_step s ON s.policy_id=p.id
            JOIN wms.role r ON r.id=s.role_id JOIN wms.role a ON a.id=s.alternative_role_id
            WHERE p.document_kind IN ('ISSUE','INTERNAL_MOVE') AND p.is_active""")).all()
        assert {row[0] for row in policies} == {"ISSUE", "INTERNAL_MOVE"}
        assert len(policies) == len({row[1] for row in policies}) == len({row[2] for row in policies}) == 2
        assert all(row[3:] == ("WAREHOUSE_MANAGER", "CONTROLLER") for row in policies)


def test_b09_dependency_receipt_quality_putaway_reservation_issue_and_move(movement):  # noqa: F811
    f = movement
    f.iam.grant(f.buyer, "PICKER", f.warehouse)
    source, _ = f.putaway()  # 80 received -> 75 STORAGE + 5 QUARANTINE through real APIs.
    transfer = f.move_approve(f.move_body(source, qty="6"))
    sales_body = {**f.body, "lines": [{**f.body["lines"][0], "quantity": "70"}]}
    so = ok(f.decision(ok(f.action(ok(f.create("sales-orders", sales_body), 201), "submit"))))
    parent = ok(f.read(so, kind="sales-orders"))["lines"][0]
    draft = ok(f.move_request("POST", "issues", {
        "source_order_id": so["id"], "business_date": "2026-10-02", "reason": "Xuất sau kiểm định và cất hàng",
        "lines": [{"source_line_id": parent["id"], "quantity_base": "70"}],
    }), 201)
    approved = ok(f.decision(ok(f.action(draft, "submit"))))
    view = ok(f.read(approved, kind="issues"))
    plan = ok(f.client.get(f"/api/v1/issues/{approved['id']}/reservation-plan", params={
        "document_line_id": view["lines"][0]["id"], "quantity_base": "70",
    }, headers=f.headers["buyer"]))
    assert {row["location_id"] for row in plan["lines"]} == {f.bin["id"]}
    reserved = ok(f.move_request("POST", f"issues/{approved['id']}/reservations/reserve", {
        "expected_version": plan["version"], "reason": "Giữ đúng nguồn sau QC",
        "lines": [{key: row[key] for key in ("document_line_id", "stock_item_id", "location_id", "quantity_base")}
                  for row in plan["lines"]],
    }))
    assert f.move_post(transfer).status_code == 409  # Approved MOVE cannot steal a later ISSUE reservation.
    view = ok(f.read(reserved, kind="issues"))
    key = uuid4()
    post_body = {"expected_version": reserved["version"], "execution_key": str(uuid4()), "reason": "Giao đợt đầu",
                 "lines": [{"reservation_id": view["reservations"][0]["id"], "quantity_base": "30"}]}
    posted = ok(f.move_request("POST", f"issues/{reserved['id']}/post", post_body, key=key))
    assert posted["status"] == "PARTIAL"
    assert ok(f.move_request("POST", f"issues/{reserved['id']}/post", post_body, key=key)) == posted
    assert ok(f.read(so, kind="sales-orders"))["lines"][0]["remaining_base"] == "40.000000"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(reserved) FROM wms.stock_balance")).scalar_one() == 40
    ok(f.action(posted, "close", "manager"))
    ok(f.move_post(transfer))  # Close released the unconsumed 40; the original MOVE can now post.
    stock = ok(f.move_request("GET", f"moves/stock?warehouse_id={f.warehouse}"))["items"]
    assert sum(Decimal(row["on_hand"]) for row in stock) == 50
    assert sum(Decimal(row["reserved"]) for row in stock) == 0
    assert sum(Decimal(row["on_hand"]) for row in stock if row["source_kind"] == "QUARANTINE") == 5
    assert ok(f.read(f.po))["lines"][0]["remaining_base"] == "20.000000"
    reconcile(f)
