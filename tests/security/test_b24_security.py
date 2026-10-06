"""Permissions exercised over verified TLS and the deployed runtime SQL grant set."""

import ssl
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_orders import ok

from scripts.b24_harness import reconcile, runtime, tls_server

pytestmark = pytest.mark.integration
ROLES = [
    "SYSADMIN",
    "MASTER_DATA",
    "BUYER",
    "SELLER",
    "RECEIVER",
    "PICKER",
    "WAREHOUSE_MANAGER",
    "CONTROLLER",
    "DIRECTOR",
    "AUDITOR",
]
READERS = {"WAREHOUSE_MANAGER", "CONTROLLER", "DIRECTOR", "AUDITOR"}
PRICES = {"CONTROLLER", "DIRECTOR", "AUDITOR"}


@pytest.mark.parametrize("role", ROLES)
def test_role_warehouse_owner_price_matrix(request, tmp_path, role, caplog):
    f = request.getfixturevalue("reports")
    user, _ = f.iam.user("matrix-" + role.lower())
    f.iam.grant(user, role, f.warehouse)
    headers = f.iam.headers(f.iam.login("matrix-" + role.lower()))
    other = f.iam.warehouse("FORBIDDEN")
    with f.engine.connect() as c:
        stock = str(c.execute(text("SELECT id FROM wms.stock_item LIMIT 1")).scalar_one())
    with (
        tls_server(f.iam, tmp_path / "tls") as s,
        httpx.Client(
            base_url=s["url"] + "/", verify=ssl.create_default_context(cafile=s["ca"]), trust_env=False
        ) as client,
    ):
        for warehouse in [f.warehouse, other]:
            allowed = role in READERS and warehouse == f.warehouse
            response = client.post(
                "reports/R08/snapshots",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"warehouse_id": str(warehouse)},
            )
            assert response.status_code == (201 if allowed else 403), response.text
            if allowed:
                page = client.get("reports/snapshots/" + response.json()["id"], headers=headers)
                assert page.status_code == 200
                assert "reference_price" not in page.text
            priced = client.post(
                "reports/R08/snapshots",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"warehouse_id": str(warehouse), "include_price": True},
            )
            assert priced.status_code == (201 if allowed and role in PRICES else 403), priced.text
            ownership = client.get(
                f"stock-ownership?warehouse_id={warehouse}&location_id={f.location['id']}&stock_item_id={stock}",
                headers=headers,
            )
            assert ownership.status_code == (200 if allowed else 404), ownership.text
        # Authentication failures must not expose database details, credential values or tracebacks.
        denial = client.get("auth/me", headers={"Authorization": "Bearer never-log-b24-token"})
        assert denial.status_code == 401
        assert not any(
            value in denial.text
            for value in ["never-log-b24-token", "Traceback", "postgresql", "password_hash"]
        )
    logs = "\n".join(p.read_text() for p in (tmp_path / "tls").glob("*.log"))
    logs += caplog.text
    assert "never-log-b24-token" not in logs and headers["Authorization"] not in logs
    reconcile(f.engine)


@pytest.mark.parametrize(
    "permission", ["report.read", "report.export", "ownership.read", "serial.read", "price.read"]
)
def test_revoke_after_export_ready_blocks_tls_download(request, tmp_path, permission):
    f = request.getfixturevalue("reports")
    # Export storage/executor use the same runtime role as the TLS API, not owner SQL.
    with tls_server(f.iam, tmp_path / "tls") as s:
        from apps.server.application.export_jobs import ExportExecutor, consumer_factory
        from apps.server.application.outbox import OutboxProcessor
        from apps.server.infrastructure.outbox import PostgresOutboxStore

        service = s["app"].state.exports
        service.storage = f.exporter.service.storage
        with httpx.Client(
            base_url=s["url"] + "/", verify=ssl.create_default_context(cafile=s["ca"]), trust_env=False
        ) as client:
            headers = {**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
            snap = client.post(
                ("reports/R01/snapshots" if permission == "serial.read" else "reports/R08/snapshots"),
                headers=headers,
                json={"warehouse_id": str(f.warehouse), "include_price": permission != "serial.read"},
            )
            assert snap.status_code == 201, snap.text
            job = client.post(
                "exports",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"snapshot_id": snap.json()["id"], "format": "csv"},
            )
            assert job.status_code == 201, job.text
            OutboxProcessor(PostgresOutboxStore(s["engine"]), consumer_factory()).run_batch()
            assert ExportExecutor(service).run_one() == "READY"
            route = f"exports/{job.json()['id']}/download"
            good = client.get(route, headers=f.headers["buyer"])
            assert good.status_code == 200
            with f.engine.begin() as c:
                c.execute(
                    text(
                        "DELETE FROM wms.role_permission WHERE permission_id=(SELECT id FROM wms.permission WHERE code=:code)"
                    ),
                    {"code": permission},
                )
            bad = client.get(route, headers=f.headers["buyer"])
            assert bad.status_code == 403 and not bad.content.startswith(b"PK")
            assert "Content-Disposition" not in bad.headers


def test_runtime_sql_constraints_and_immutable_history(request):
    f = request.getfixturevalue("issuing")
    f.seed()
    held = f.reserve(f.issue_approve())
    ok(f.issue_post(held))
    statements = [
        "UPDATE wms.stock_balance SET on_hand=-1",
        "UPDATE wms.stock_balance SET reserved=on_hand+1",
        "UPDATE wms.reservation SET consumed=quantity+1",
        "UPDATE wms.stock_move SET quantity_base=2",
        "DELETE FROM wms.inventory_transaction",
        "DELETE FROM wms.audit_event",
        "DELETE FROM wms.reservation_consumption",
        "UPDATE wms.reservation_consumption SET quantity=quantity+1",
        "CREATE TABLE wms.b24_forbidden(id int)",
        "TRUNCATE wms.stock_balance",
        "ALTER TABLE wms.stock_move DISABLE TRIGGER ALL",
        "DELETE FROM public.wms_schema_migration",
        "INSERT INTO wms.stock_item(id,product_id,lot_id,serial_id,owner_id,consignment_id) SELECT gen_random_uuid(),product_id,lot_id,serial_id,owner_id,consignment_id FROM wms.stock_item LIMIT 1",
    ]
    with runtime(f.engine) as engine:
        for statement in statements:
            with pytest.raises(DBAPIError), engine.begin() as c:
                c.exec_driver_sql(statement)
    reconcile(f.engine)


def test_reconciliation_detects_software_error_with_zero_tolerance(request):
    f = request.getfixturevalue("reports")
    reconcile(f.engine)
    with f.engine.begin() as c:
        c.exec_driver_sql("UPDATE wms.stock_balance SET on_hand=on_hand+0.000001")
    with pytest.raises(AssertionError):
        reconcile(f.engine)
    with f.engine.begin() as c:
        c.exec_driver_sql("UPDATE wms.stock_balance SET on_hand=on_hand-0.000001")
    reconcile(f.engine)


def test_company_and_consigned_owner_filters_remain_separate_over_tls(request, tmp_path):
    from copy import deepcopy
    from decimal import Decimal

    f = request.getfixturevalue("consignment")
    body = deepcopy(f.opening_body)
    body["lines"].append(
        dict(body["lines"][0], quantity_base="5", owner_id=f.owner["id"], consignment_id=f.agreement["id"])
    )
    ok(f.open_post(f.open_approve(body)))
    with (
        tls_server(f.iam, tmp_path / "tls") as server,
        httpx.Client(
            base_url=server["url"] + "/",
            verify=ssl.create_default_context(cafile=server["ca"]),
            trust_env=False,
        ) as client,
    ):
        for owner, amount in [("00000000-0000-4000-8000-000000000001", 10), (f.owner["id"], 5)]:
            response = client.post(
                "reports/R01/snapshots",
                headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
                json=dict(warehouse_id=str(f.warehouse), owner_id=owner),
            )
            assert response.status_code == 201, response.text
            page = client.get("reports/snapshots/" + response.json()["id"], headers=f.headers["buyer"])
            assert page.status_code == 200, page.text
            rows = page.json()["items"]
            assert len(rows) == 1 and rows[0]["owner_id"] == owner
            assert Decimal(rows[0]["physical"]) == amount
    reconcile(f.engine)
