import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from sqlalchemy import text
from test_count_period import counting  # noqa: F401
from test_issues import issuing  # noqa: F401
from test_move_quality import movement  # noqa: F401
from test_openings import inventory, opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_reversals import setup_reversal
from test_transfers import missing_loss, transfer  # noqa: F401

from apps.server.application.export_jobs import ExportExecutor, consumer_factory
from apps.server.application.exports import ExportSettings
from apps.server.application.outbox import OutboxProcessor
from apps.server.infrastructure.file_storage import FileStorage
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = pytest.mark.integration
# ruff: noqa: F811


def snapshot(f, code="R01", who="buyer", key=None, **criteria):
    return f.client.post(
        f"/api/v1/reports/{code}/snapshots",
        json={"warehouse_id": str(f.warehouse), **criteria},
        headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
    )


def page(f, report, who="buyer", **params):
    return f.client.get(f"/api/v1/reports/snapshots/{report['id']}", params=params, headers=f.headers[who])


@pytest.fixture
def reports(opening, tmp_path):  # noqa: F811
    f = opening
    ok(f.open_post(f.open_approve()))
    service = f.client.app.state.exports
    service.storage = FileStorage(ExportSettings(storage_root=tmp_path / "exports"))
    f.exporter = ExportExecutor(service)
    f.export_outbox = OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory())
    return f


@pytest.mark.parametrize("code", [f"R{n:02}" for n in range(1, 9)])
def test_reports_all_queries_real_pg(reports, code):
    f = reports
    report = ok(snapshot(f, code), 201)
    result = ok(page(f, report))
    assert result["snapshot"]["row_count"] == len(result["items"])
    if code in {"R01", "R02", "R03", "R06", "R08"}:
        assert len(result["items"]) == 1
    if code == "R01":
        assert result["items"][0]["physical"] == "10.000000"
        assert result["items"][0]["available"] == "10.000000"
    assert inventory(f) == (1, 1, 10, 0)


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_exports_outbox_separate_executor_download(reports, format):
    f = reports
    report = ok(snapshot(f), 201)
    response = f.client.post(
        "/api/v1/exports",
        json=dict(snapshot_id=report["id"], format=format),
        headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
    )
    job = ok(response, 201)
    assert f.export_outbox.run_batch().processed == 1
    assert f.exporter.run_one() == "READY"
    response = f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"])
    assert response.status_code == 200, response.text
    if format == "csv":
        assert b"10.000000" in response.content
    else:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            assert "10.000000" in list(sheet.itertext())
            assert not sheet.findall(".//{*}f")
    with f.engine.connect() as c:
        file_id = c.execute(
            text("SELECT file_id FROM wms.export_job WHERE id=:id"), {"id": job["id"]}
        ).scalar_one()
    assert f.client.get(f"/api/v1/files/{file_id}/download", headers=f.headers["buyer"]).status_code == 404
    assert inventory(f) == (1, 1, 10, 0)


def rows(f, code="R01", who="buyer", **criteria):
    return ok(page(f, ok(snapshot(f, code, who, **criteria), 201), who))["items"]


def export_job(f, report=None, format="csv", key=None):
    return f.client.post(
        "/api/v1/exports",
        json=dict(snapshot_id=(report or ok(snapshot(f), 201))["id"], format=format),
        headers={**f.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
    )


def job_read(f, job):
    return ok(f.client.get(f"/api/v1/exports/{job['id']}", headers=f.headers["buyer"]))


def job_action(f, job, operation, key=None):
    return f.client.post(
        f"/api/v1/exports/{job['id']}/{operation}",
        json=dict(expected_version=job["version"]),
        headers={**f.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
    )


def test_reports_boundary_internal_moves_inverse_and_stable_paging(movement):
    f = movement
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    source, moved = f.putaway()
    whole = rows(f, "R02")[0]
    assert (whole["inbound"], whole["outbound"], whole["closing"]) == ("80.000000", "0", "80.000000")
    bins = rows(f, "R02", location_ids=[f.bin["id"], f.quarantine["id"]])[0]
    assert Decimal(bins["inbound"]) == 80 and Decimal(bins["outbound"]) == 0
    snapshot_before = ok(snapshot(f, "R03"), 201)
    first = ok(page(f, snapshot_before, limit=1))
    setup_reversal(f)
    ok(f.rev_post(f.rev_approve(moved["transaction_id"])))
    second = ok(page(f, snapshot_before, after=first["next_after"], limit=200))
    assert len(first["items"] + second["items"]) == 3
    assert len({r["id"] for r in first["items"] + second["items"]}) == 3
    reversed_bin = rows(f, "R02", location_ids=[f.bin["id"]])[0]
    assert Decimal(reversed_bin["inbound"]) == Decimal(reversed_bin["outbound"]) == 75
    assert Decimal(reversed_bin["closing"]) == 0
    late = rows(f, "R02", business_from="2026-10-03")[0]
    assert Decimal(late["opening"]) == Decimal(late["closing"]) == 80
    assert Decimal(late["inbound"]) == 0
    assert rows(f, "R03", business_to="2026-10-01") == []
    assert snapshot(f, "R03", sort_by="sku").json()["code"] == "INVALID_FILTER"


def test_reports_reservations_remaining_and_open_demand(issuing):
    f = issuing
    f.seed()
    doc = f.reserve(f.issue_approve(), "7")
    doc = ok(f.issue_post(doc, f.issue_post_body(doc, "3")))
    ok(f.release(doc, "2"))
    r = rows(f, "R04")[0]
    assert Decimal(r["open_demand"]) == 7 and Decimal(r["reserved"]) == 2
    reservation = r["reservations"][0]
    assert [Decimal(reservation[k]) for k in ["quantity", "consumed", "released", "remaining"]] == [
        7,
        3,
        2,
        2,
    ]
    balance = rows(f)[0]
    assert [Decimal(balance[k]) for k in ["physical", "eligible", "reserved", "available"]] == [7, 7, 2, 5]
    assert balance["reservation_reconciled"]


def test_reports_transfer_evidence_transit_two_warehouse_scope(transfer):
    f = transfer
    dispatched = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
    arrived = ok(f.tr_receive(dispatched))
    report = rows(f, "R05", who="controller")[0]
    assert [Decimal(report[k]) for k in ["dispatched", "received_good", "transit"]] == [20, 18, 2]
    assert report["dispatch_evidence"] and report["receipt_evidence"][0]["evidence_ref"]
    assert rows(f, "R05") == []  # buyer has no destination report scope
    stock = rows(f, "R01", who="controller")
    assert sum(Decimal(r["transit"]) for r in stock) == 2
    assert sum(Decimal(r["physical"]) for r in stock) == 0
    assert Decimal(rows(f, "R02", who="controller")[0]["outbound"]) == 20
    assert arrived["status"] == "PARTIAL"
    from test_transfers import missing_loss

    missing_loss(f, arrived)
    missing = rows(f, "R05", who="controller")[0]
    assert Decimal(missing["reported_missing"]) == 2 and Decimal(missing["transit"]) == 2
    assert missing["discrepancy_evidence"][0]["evidence_ref"]


def test_reports_count_snapshot_rounds_approvers_and_blind_counter(counting):
    f = counting
    f.count_received()
    approved = f.count_approved()
    ok(f.count_action(approved, "post", "controller", execution_key=str(uuid4())))
    row = rows(f, "R07", who="controller")[0]
    assert [Decimal(row[k]) for k in ["snapshot_quantity", "approved_quantity", "delta"]] == [100, 98, -2]
    assert len(row["rounds"]) == 2 and len(row["decisions"]) == 2
    assert {d["decided_by"] for d in row["decisions"]} == {str(f.controller), str(f.director)}
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    assert rows(f, "R07") == []


def test_reports_snapshot_concurrent_replay_scope_and_filter_validation(reports):
    f = reports
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: ok(snapshot(f, key=key), 201), range(2)))
    assert result[0] == result[1]
    assert snapshot(f, key=key, descending=True).json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert page(f, result[0], who="controller").status_code == 404
    assert snapshot(f, location_ids=[str(uuid4())]).json()["code"] == "INVALID_SCOPE"
    assert snapshot(f, "R03", posted_from="2026-10-02T00:00:00").status_code == 422
    assert snapshot(f, warehouse_id=str(uuid4())).status_code == 403


def test_exports_prices_effective_date_and_revocation_after_file_io(reports, monkeypatch):
    f = reports
    with f.engine.begin() as c:
        for day, price in [("2026-01-01", "1.2345"), ("2026-10-03", "9.9999")]:
            c.execute(
                text("""INSERT INTO wms.reference_price(id,product_id,effective_on,amount,currency,source,created_by)
                VALUES (:id,:product,:day,:price,'VND','Fixture',:actor)"""),
                dict(id=uuid4(), product=f.product["id"], day=day, price=price, actor=f.buyer),
            )
    report = ok(snapshot(f, "R08", include_price=True, effective_on="2026-10-02"), 201)
    row = ok(page(f, report))["items"][0]
    assert row["reference_price"] == "1.2345" and Decimal(row["inbound_reference_value"]) == Decimal("12.345")
    assert "reference_price" not in rows(f, "R08", who="manager")[0]
    assert snapshot(f, "R08", who="manager", include_price=True).status_code == 403
    job = ok(export_job(f, report), 201)
    f.export_outbox.run_batch()
    assert f.exporter.run_one() == "READY"
    storage = f.exporter.service.storage
    original = storage.read

    def revoke(*args):
        data = original(*args)
        with f.engine.begin() as c:
            c.execute(
                text("""DELETE FROM wms.role_permission WHERE permission_id IN
                (SELECT id FROM wms.permission WHERE code='price.read')""")
            )
        return data

    monkeypatch.setattr(storage, "read", revoke)
    assert (
        f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"]).status_code == 403
    )


def test_exports_cancel_lease_loss_crash_retry_and_deterministic_file(reports, monkeypatch):
    f = reports
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    task = f.exporter.claim()
    cancelled = ok(job_action(f, job_read(f, job), "cancel"))
    assert f.exporter.execute(task) == "OBSOLETE"
    assert job_read(f, job)["status"] == "CANCELLED"
    assert job_action(f, cancelled, "retry").json()["code"] == "INVALID_STATE"
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    task = f.exporter.claim()
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.export_task SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"),
            {"id": task["id"]},
        )
    replacement = f.exporter.claim()
    assert f.exporter.execute(task) == "LOST_LEASE"
    assert f.exporter.execute(replacement) == "READY"
    assert inventory(f) == (1, 1, 10, 0)


def test_exports_final_crash_session_revoke_and_exact_action_replay(reports):
    f = reports
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    task = f.exporter.claim()
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.export_task SET attempts=5,lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": task["id"]},
        )
    assert f.exporter.claim() is None
    failed = job_read(f, job)
    assert failed["status"] == "FAILED" and failed["error_code"] == "LEASE_EXHAUSTED"
    key = uuid4()
    retry = ok(job_action(f, failed, "retry", key))
    assert ok(job_action(f, failed, "retry", key)) == retry
    f.export_outbox.run_batch()
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.auth_session SET revoked_at=:now WHERE user_id=:actor"),
            dict(now=f.iam.now, actor=f.buyer),
        )
    assert f.exporter.run_one() == "FAILED"
    assert (
        f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"]).status_code == 401
    )


def test_exports_retention_fences_publish_removes_expired_and_keeps_tombstone(reports):
    from apps.server.application.export_retention import cleanup, storage_fence
    from apps.server.domain.errors import DomainError

    f = reports
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    assert f.exporter.run_one() == "READY"
    with storage_fence(f.engine, shared=True):
        with pytest.raises(DomainError, match="Storage"):
            cleanup(f.exporter.service)
    assert cleanup(f.exporter.service) == dict(snapshots=0, files=0, orphans=0)
    f.iam.advance(3601)
    assert cleanup(f.exporter.service) == dict(snapshots=1, files=1, orphans=0)
    assert list(f.exporter.service.storage.root.iterdir()) == []
    with f.engine.connect() as c:
        tombstone = c.execute(
            text("SELECT snapshot_id,file_id,status,generation FROM wms.export_job WHERE id=:id"),
            {"id": job["id"]},
        ).one()
        assert tuple(tombstone) == (None, None, "CANCELLED", 2)
        assert c.execute(text("SELECT count(*) FROM wms.report_snapshot_row")).scalar_one() == 0
    assert cleanup(f.exporter.service) == dict(snapshots=0, files=0, orphans=0)
    assert inventory(f) == (1, 1, 10, 0)


@pytest.mark.parametrize("baseline", [10, 20])
def test_reports_upgrade_preserves_legacy_jobs_and_serial_owner(empty_database, monkeypatch, baseline):
    import apps.server.infrastructure.migrations as migration

    sources = migration.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migration, "migration_sources", lambda: sources[:baseline])
        migration.migrate(empty_database)
    actor, job, unit, product, serial, item = [uuid4() for _ in range(6)]
    with empty_database.begin() as c:
        c.execute(
            text(
                """INSERT INTO wms.app_user VALUES (:id,'legacy-report','Legacy','not-a-login',true,0,now())"""
            ),
            {"id": actor},
        )
        c.execute(
            text("""INSERT INTO wms.export_job(id,requested_by,report_code,filters,status,created_at,expires_at)
            VALUES (:id,:actor,'R01',CAST(:filters AS jsonb),'QUEUED',now(),now()+interval '1 hour')"""),
            dict(id=job, actor=actor, filters='{"legacy":true}'),
        )
        c.execute(
            text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES(:id,'EA','Each',0)"), {"id": unit}
        )
        c.execute(
            text("""INSERT INTO wms.product(id,sku,name,base_uom_id,tracking,expiry_required,is_active,version,attributes)
            VALUES(:id,'LEGACY-SERIAL','Device',:uom,'SERIAL',false,true,1,'{}')"""),
            dict(id=product, uom=unit),
        )
        c.execute(
            text("INSERT INTO wms.serial(id,product_id,code) VALUES(:id,:product,'B17-OLD')"),
            dict(id=serial, product=product),
        )
        c.execute(
            text("""INSERT INTO wms.stock_item(id,product_id,serial_id,owner_id)
            VALUES(:id,:product,:serial,'00000000-0000-4000-8000-000000000001')"""),
            dict(id=item, product=product, serial=serial),
        )
    assert migration.migrate(empty_database) == [s[0] for s in sources[baseline:]]
    assert migration.migrate(empty_database) == [] and migration.is_ready(empty_database)
    with empty_database.connect() as c:
        assert c.execute(
            text("SELECT filters FROM wms.export_job WHERE id=:id"), {"id": job}
        ).scalar_one() == dict(legacy=True)
        assert (
            c.execute(text("SELECT snapshot_id FROM wms.export_job WHERE id=:id"), {"id": job}).scalar_one()
            is None
        )
        assert (
            c.execute(text("SELECT serial_id FROM wms.stock_item WHERE id=:id"), {"id": item}).scalar_one()
            == serial
        )


def test_reports_company_consignment_expiry_age_and_serial_dimensions(opening):
    from copy import deepcopy

    from test_consignments import agreement
    from test_openings import tracking

    f = opening
    owner, contract = agreement(f)
    _, lot = tracking(f, "LOT", lot_code="LOT-B17", expires_on="2026-10-02")
    _, serial = tracking(f, "SERIAL", serial_code="=SN-B17")
    body = deepcopy(f.opening_body)
    body["lines"] += [
        dict(body["lines"][0], quantity_base="5", owner_id=owner["id"], consignment_id=contract["id"]),
        lot["lines"][0],
        serial["lines"][0],
    ]
    ok(f.open_post(f.open_approve(body)))
    all_rows = rows(f)
    assert len(all_rows) == 4
    consigned = next(r for r in all_rows if r["owner_kind"] == "CONSIGNOR")
    assert consigned["consignment_id"] == contract["id"] and Decimal(consigned["physical"]) == 5
    assert Decimal(consigned["eligible"]) == 0
    assert rows(f, owner_id=owner["id"])[0]["id"] == consigned["id"]
    ages = rows(f, "R06")
    assert all(r["age_basis"] == "LAST_MOVEMENT_AT_LOCATION" and r["last_move_id"] for r in ages)
    assert next(r for r in ages if r["lot_code"] == "LOT-B17")["days_to_expiry"] == 0
    assert next(r for r in ages if r["serial_code"] == "=SN-B17")["movement_age_days"] == 0
    assert all("warranty_ends_on" not in r for r in ages)  # No invented warranty from movement age.
    # Cross midnight without losing the current session: refresh through a fresh login.
    f.iam.advance(86400)
    f.headers["buyer"] = f.iam.headers(f.iam.login("buyer"))
    assert Decimal(next(r for r in rows(f) if r["lot_code"] == "LOT-B17")["eligible"]) == 0


def test_exports_rollback_crash_after_file_write_and_no_io_transaction(reports, monkeypatch):
    f = reports
    report = ok(snapshot(f), 201)
    service = f.exporter.service
    original_effects = service.effects

    def fail_effects(*args, **kwargs):
        original_effects(*args, **kwargs)
        raise RuntimeError("Injected after effects")

    with monkeypatch.context() as patch:
        patch.setattr(service, "effects", fail_effects)
        assert export_job(f, report).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.export_job")).scalar_one() == 0
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE event_type='export.requested.v1'")
            ).scalar_one()
            == 0
        )
    job = ok(export_job(f, report), 201)
    f.export_outbox.run_batch()
    assert not service.storage.root.exists()
    original_put = service.storage.put

    def crash(*args):
        assert f.engine.pool.checkedout() == 1  # Only the committed session advisory fence is held.
        original_put(*args)
        raise RuntimeError("Crash after durable file write")

    with monkeypatch.context() as patch:
        patch.setattr(service.storage, "put", crash)
        assert f.exporter.run_one() == "RETRY"
    assert job_read(f, job)["status"] == "QUEUED"
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.export_task SET available_at=clock_timestamp() WHERE job_id=:id"),
            {"id": job["id"]},
        )
    assert f.exporter.run_one() == "READY"
    assert len(list(service.storage.root.iterdir())) == 1
    assert inventory(f) == (1, 1, 10, 0)


@pytest.mark.parametrize("permission", ["report.read", "report.export", "ownership.read", "serial.read"])
def test_exports_current_permission_before_download_even_after_ready(reports, permission):
    f = reports
    job = ok(export_job(f), 201)
    f.export_outbox.run_batch()
    assert f.exporter.run_one() == "READY"
    with f.engine.begin() as c:
        c.execute(
            text(
                "DELETE FROM wms.role_permission WHERE permission_id IN (SELECT id FROM wms.permission WHERE code=:code)"
            ),
            {"code": permission},
        )
    assert (
        f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"]).status_code == 403
    )


def test_reports_quota_race_and_snapshot_immutability(reports, monkeypatch):
    from sqlalchemy.exc import ProgrammingError

    f = reports
    monkeypatch.setattr("apps.server.application.reports.MAX_ACTIVE", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: snapshot(f), range(2)))
    assert sorted(r.status_code for r in result) == [201, 409]
    report = next(r.json() for r in result if r.status_code == 201)
    with pytest.raises(ProgrammingError), f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.report_snapshot_row SET payload='{}' WHERE snapshot_id=:id"),
            {"id": report["id"]},
        )
    assert len(ok(page(f, report))["items"]) == 1


def test_reports_empty_count_scope_is_visible_without_inventing_item(counting):
    f = counting
    doc = ok(f.count_action(f.count_create(), "freeze"))
    result = rows(f, "R07", who="controller")
    assert len(result) == 1
    assert result[0]["session_id"] == doc["id"] and result[0]["sku"] is None
    assert Decimal(result[0]["snapshot_quantity"]) == 0
    assert result[0]["rounds"] == result[0]["empty_confirmations"] == []
