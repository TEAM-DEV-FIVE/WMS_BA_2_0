from uuid import uuid4

import pytest
from sqlalchemy import text
from test_imports import imports  # noqa: F401
from test_openings import opening, orders  # noqa: F401
from test_orders import ok
from test_reports_exports import export_job, reports, snapshot  # noqa: F401

from apps.server.application.export_retention import cleanup

pytestmark = pytest.mark.integration
# ruff: noqa: F811


def history(f, route="exports", who="buyer", **params):
    if route == "exports":
        params.setdefault("warehouse_id", str(f.warehouse))
    else:
        params.setdefault("kind", "01_uom")
    return f.client.get("/api/v1/" + route, params=params, headers=f.headers[who])


def test_export_history_keyset_filters_actor_and_live_permissions(reports):
    f = reports
    jobs = [ok(export_job(f), 201) for _ in range(3)]
    first = ok(history(f, limit=1))
    second = ok(history(f, after=first["next_after"], limit=1))
    third = ok(history(f, after=second["next_after"], limit=1))
    assert {r["id"] for p in (first, second, third) for r in p["items"]} == {j["id"] for j in jobs}
    assert third["next_after"] is None
    f.iam.grant(f.manager, "CONTROLLER", f.warehouse)
    assert not ok(history(f, who="manager"))["items"]
    assert history(f, who="manager", after=jobs[0]["id"]).json()["code"] == "INVALID_FILTER"
    assert not ok(history(f, code="R08"))["items"]
    assert not ok(history(f, status="READY"))["items"]
    assert not ok(history(f, since="2099-01-01T00:00:00Z"))["items"]
    assert history(f, since="2026-10-07T00:00:00Z", until="2026-10-06T00:00:00Z").json()["code"] == "INVALID_FILTER"
    assert history(f, since="2026-10-07", until="2026-10-06T00:00:00Z").json()["code"] == "INVALID_FILTER"
    assert history(f, limit=101).status_code == 422
    assert history(f, warehouse_id=str(uuid4())).status_code == 403
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": f.buyer})
    assert history(f).status_code == 403


def test_export_history_expiry_cleanup_keeps_only_authorization_metadata(reports):
    f = reports
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    assert f.exporter.run_one() == "READY"
    f.iam.advance(3601)
    # Refresh the login after advancing beyond the access-token lifetime.
    f.headers["buyer"] = f.iam.headers(f.iam.login("buyer"))
    assert ok(history(f))["items"][0]["expired"]
    cleanup(f.exporter.service)
    row = ok(history(f))["items"][0]
    assert row["id"] == job["id"] and row["expired"] and row["error_code"] == "REPORT_EXPIRED"
    assert (
        f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"]).status_code == 404
    )
    with f.engine.connect() as c:
        value = c.execute(
            text("SELECT filters FROM wms.export_job WHERE id=:id"), {"id": job["id"]}
        ).scalar_one()
        assert set(value) == {"history_scope"}
        assert set(value["history_scope"]) == {
            "warehouse_id",
            "include_price",
            "required_warehouses",
            "count_sessions",
        }


def test_export_history_price_revocation_hides_active_and_expired(reports):
    f = reports
    job = ok(export_job(f, ok(snapshot(f, "R08", include_price=True), 201)), 201)
    f.export_outbox.run_batch()
    assert f.exporter.run_one() == "READY"
    # Remove price permission from all roles, retaining report/export permissions.
    with f.engine.begin() as c:
        c.execute(
            text(
                "DELETE FROM wms.role_permission WHERE permission_id=(SELECT id FROM wms.permission WHERE code='price.read')"
            )
        )
    assert ok(history(f))["items"] == []
    f.iam.advance(3601)
    f.headers["buyer"] = f.iam.headers(f.iam.login("buyer"))
    cleanup(f.exporter.service)
    assert ok(history(f))["items"] == []
    assert job["id"]


def test_import_history_scope_paging_errors_and_ownership(imports):
    f = imports
    jobs = [f.prepare(rows=[[f"H{i}", "Lịch sử", 0]]) for i in range(3)]
    first = ok(history(f, "imports", limit=1, status="VALIDATED"))
    rest = ok(history(f, "imports", after=first["next_after"], limit=100))
    assert {r["id"] for p in (first, rest) for r in p["items"]} == {j["id"] for j in jobs}
    assert rest["next_after"] is None
    f.iam.grant(f.manager, "MASTER_DATA")
    assert ok(history(f, "imports", who="manager"))["items"] == []
    assert history(f, "imports", warehouse_id=str(f.warehouse)).json()["code"] == "INVALID_SCOPE"
    assert ok(history(f, "imports", status="INVALID"))["items"] == []
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": f.buyer})
    assert history(f, "imports").status_code == 403
