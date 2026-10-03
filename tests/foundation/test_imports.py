import csv
import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_openings import inventory, opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401

from apps.server.application.import_jobs import ImportExecutor, consumer_factory
from apps.server.application.import_targets import ImportTargets
from apps.server.application.import_templates import TEMPLATES
from apps.server.application.outbox import OutboxProcessor
from apps.server.infrastructure.file_storage import FileStorage, ImportSettings
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = pytest.mark.integration


def csv_bytes(kind, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([x[0] for x in TEMPLATES[kind]])
    writer.writerows([list(r) + ["COMPANY", ""] if kind == "11_opening" and len(r) == 8 else r for r in rows])
    return stream.getvalue().encode("utf-8-sig")


@pytest.fixture
def imports(opening, tmp_path):  # noqa: F811
    f = opening
    f.import_service = f.client.app.state.imports
    f.import_service.storage = FileStorage(ImportSettings(storage_root=tmp_path / "files"))
    f.executor = ImportExecutor(f.import_service)
    f.outbox = OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory())

    def upload(
        kind="01_uom", rows=None, key=None, data=None, filename="data.csv", who="buyer", warehouse=None
    ):
        params = {"kind": kind}
        if kind in {"04_locations", "11_opening", "12_open_orders"}:
            params["warehouse_id"] = str(warehouse or f.warehouse)
        return f.client.post(
            "/api/v1/files",
            params=params,
            content=data if data is not None else csv_bytes(kind, rows or [["NEW", "Mới", 0]]),
            headers={**f.headers[who], "Idempotency-Key": str(key or uuid4()), "X-File-Name": filename},
        )

    def create(file, key=None):
        return f.client.post(
            "/api/v1/imports",
            json={
                "file_id": file["id"],
                "reason": "Nhập dữ liệu kiểm thử",
                "signed_count_reference": "Biên bản đã ký 001",
            },
            headers={**f.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
        )

    def read(job):
        return ok(f.client.get("/api/v1/imports/" + job["id"], headers=f.headers["buyer"]))

    def action(job, action="commit", key=None, **extra):
        body = {"expected_version": job["version"], "reason": "Xác nhận dữ liệu"}
        if action == "commit":
            body.update(commit_token=job["commit_token"], file_hash=job["file_hash"])
        return f.client.post(
            "/api/v1/imports/" + job["id"] + "/" + action,
            json={**body, **extra},
            headers={**f.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
        )

    def prepare(kind="01_uom", rows=None, **kwargs):
        job = ok(create(ok(upload(kind, rows, **kwargs), 201)), 201)
        assert f.outbox.run_batch().processed >= 1
        outcome = f.executor.run_one()
        result = read(job)
        assert outcome in {"VALIDATED", "INVALID"}, (outcome, result)
        return result

    f.upload, f.import_create, f.import_read, f.import_action, f.prepare = (
        upload,
        create,
        read,
        action,
        prepare,
    )
    return f


def test_imports_catalog_commit_rollback_only_preview_dedup_and_ack(imports):
    f = imports
    upload_key = uuid4()
    file = ok(f.upload(key=upload_key), 201)
    assert ok(f.upload(key=upload_key), 201) == file
    assert not any(k in file for k in ["storage_key", "url", "uploaded_by"])
    job = ok(f.import_create(file), 201)
    assert ok(f.import_create(ok(f.upload(), 201)))["id"] == job["id"]
    assert f.outbox.run_batch().processed == 1
    assert f.executor.run_one() == "VALIDATED"
    job = f.import_read(job)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code='NEW'")).scalar_one() == 0
    key = uuid4()
    saved = ok(f.import_action(job, key=key))
    assert ok(f.import_action(job, key=key)) == saved
    assert ok(f.import_action(job)) == saved
    assert f.import_action(job, key=key, reason="Nội dung khác").json()["code"] == "IDEMPOTENCY_MISMATCH"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code='NEW'")).scalar_one() == 1
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM wms.audit_event WHERE action='master.uoms.created' AND after_data->>'code'='NEW'"
                )
            ).scalar_one()
            == 1
        )
    assert inventory(f) == (0, 0, 0, 0)


def test_imports_failed_middle_batch_rolls_back_business_outbox_and_ack(imports, monkeypatch):
    f = imports
    job = f.prepare(rows=[["A", "A unit", 0], ["B", "B unit", 0]])
    original = ImportTargets.master_row

    def fail(self, kind, row):
        result = original(self, kind, row)
        if row["code"] == "B":
            raise RuntimeError("Simulate failure after second business write")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ImportTargets, "master_row", fail)
        assert f.import_action(job).status_code == 500
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code IN ('A','B')")).scalar_one() == 0
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.audit_event WHERE action='import.committed'")
            ).scalar_one()
            == 0
        )
        assert (
            c.execute(text("SELECT count(*) FROM wms.import_row WHERE target_id IS NOT NULL")).scalar_one()
            == 0
        )
    assert f.import_read(job)["status"] == "VALIDATED"
    assert len(ok(f.import_action(job))["targets"]) == 2


@pytest.mark.parametrize(
    "kind,rows",
    [
        ("01_uom", [["DUP", "One", 0], ["dup", "Two", 0]]),
        ("01_uom", [["A", "Okay", 0], ["B", "Bad", 7]]),
        ("05_products", [["NEW", "Missing unit", "", "MISSING", "NONE", "FALSE", "TRUE"]]),
        ("11_opening", [["B", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1]] * 201),
        (
            "11_opening",
            [
                ["B", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1],
                ["C", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1],
            ],
        ),
    ],
)
def test_imports_invalid_rows_have_errors_and_cannot_commit(imports, kind, rows):
    job = imports.prepare(kind, rows)
    assert job["status"] == "INVALID" and job["commit_token"] is None and job["errors"]
    assert all("row_no" in e and "column" in e for e in job["errors"])
    assert imports.import_action(job, commit_token=str(uuid4())).status_code == 409
    assert inventory(imports) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "kind,rows,table",
    [
        ("02_categories", [["ROOT", "Nhóm", ""], ["CHILD", "Nhóm con", "ROOT"]], "product_category"),
        ("03_warehouses", [["NEWWH", "Kho mới", "Địa chỉ", "TRUE"]], "warehouse"),
        ("04_locations", [["NEWQA", "ORDERS", "", "Cách ly", "QUARANTINE", "TRUE"]], "location"),
        ("05_products", [["NEWPROD", "Mặt hàng", "", "EA", "NONE", "FALSE", "TRUE"]], "product"),
        ("06_product_uom", [["ORD-01", "EA", 1, 1, "TRUE"]], "product_uom"),
        ("07_barcodes", [["0000123", "ORD-01", "EA", 1, "TRUE"]], "barcode"),
        ("08_partners", [["PARTNER", "Đối tác", "TRUE", "TRUE", "001234", "Địa chỉ", "TRUE"]], "partner"),
        ("14_prices", [["ORD-01", "2026-10-02", 123, "VND", "Báo giá đã ký"]], "reference_price"),
    ],
)
def test_imports_all_catalog_targets_use_real_services(imports, kind, rows, table):
    f = imports
    # Price write is GLOBAL and intentionally separate from general catalog grants.
    if kind == "14_prices":
        f.iam.grant(f.buyer, "CONTROLLER", scope="GLOBAL")
    job = f.prepare(kind, rows)
    assert job["status"] == "VALIDATED", job
    result = ok(f.import_action(job))
    with f.engine.connect() as c:
        target = (
            c.execute(text(f"SELECT * FROM wms.{table} WHERE id=:id"), {"id": result["targets"][0]["id"]})
            .mappings()
            .one()
        )
        if table == "partner":
            assert target["tax_code"] == "001234" and target["address"] == "Địa chỉ"
        if table == "barcode":
            assert target["code"] == "0000123"
    if table == "partner":
        # An older desktop client must not erase fields it does not yet edit.
        updated = ok(
            f.client.put(
                "/api/v1/master/partners/" + str(target["id"]),
                json=dict(
                    code=target["code"],
                    name="Đối tác đã sửa",
                    is_supplier=True,
                    is_customer=True,
                    expected_version=target["version"],
                    reason="Sửa từ client cũ",
                ),
                headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
            )
        )
        assert updated["tax_code"] == "001234" and updated["address"] == "Địa chỉ"


@pytest.mark.parametrize(
    "tracking,kind,rows",
    [
        ("SERIAL", "10_serials", [["TRACK", "000001"]]),
        ("LOT", "09_lots", [["TRACK", "LOT1", "2026-01-01", "2027-01-01"]]),
    ],
)
def test_imports_tracking_catalog_and_duplicate_serial(imports, tracking, kind, rows):
    f = imports
    f.master("products", sku="TRACK", name="Tracked", base_uom_id=f.conversion["uom_id"], tracking=tracking)
    job = f.prepare(kind, rows)
    assert job["status"] == "VALIDATED", job
    ok(f.import_action(job))
    duplicate = f.prepare(kind, rows, data=csv_bytes(kind, rows) + b"\n")
    assert duplicate["status"] == "INVALID"
    assert duplicate["errors"][0]["code"] == "DUPLICATE_CODE"
    assert inventory(f) == (0, 0, 0, 0)


def test_imports_open_orders_draft_source_dedup_and_permission_per_group(imports):
    f = imports
    rows = [
        ["OLDPO", "PO", "ORDERS", "NCC", "2026-10-02", 1, "ORD-01", "EA", 7, "Ghi chú giữ trong staging"],
        ["OLDSO", "SO", "ORDERS", "NCC", "2026-10-02", 1, "ORD-01", "EA", 3, ""],
    ]
    job = f.prepare("12_open_orders", rows)
    assert job["status"] == "VALIDATED", job
    result = ok(f.import_action(job))
    with f.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.document WHERE kind IN ('PO','SO') AND status='DRAFT'")
            ).scalar_one()
            == 2
        )
        assert c.execute(text("SELECT count(*) FROM wms.approval_request")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.import_document_source")).scalar_one() == 2
    assert len(result["targets"]) == 2 and inventory(f) == (0, 0, 0, 0)
    again = f.prepare("12_open_orders", rows, data=csv_bytes("12_open_orders", rows) + b"\n")
    assert again["status"] == "INVALID" and again["errors"][0]["code"] == "DUPLICATE_SOURCE"


def test_imports_opening_draft_approval_then_single_post(imports):
    f = imports
    job = f.prepare("11_opening", [["CUTOVER", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 12]])
    assert job["status"] == "VALIDATED", job
    saved = ok(f.import_action(job))
    draft = ok(f.open_read(saved["targets"][0]))
    assert draft["status"] == "DRAFT" and inventory(f) == (0, 0, 0, 0)
    assert f.open_post(draft).status_code == 409
    submitted = ok(f.action(draft, "submit"))
    approved = ok(f.decision(submitted, "director"))
    ok(f.open_post(approved))
    assert inventory(f) == (1, 1, 12, 0)
    another = f.prepare("11_opening", [["SECOND", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1]])
    assert another["status"] == "INVALID"


@pytest.mark.parametrize("tamper", ["file", "master", "stage", "token", "expired"])
def test_imports_stale_binding_blocks_commit(imports, tamper):
    f = imports
    job = f.prepare("07_barcodes", [["000999", "ORD-01", "EA", 1, "TRUE"]])
    with f.engine.begin() as c:
        if tamper == "master":
            c.execute(text("UPDATE wms.product SET version=version+1 WHERE id=:id"), {"id": f.product["id"]})
        elif tamper == "stage":
            c.execute(
                text(
                    "UPDATE wms.import_row SET payload=jsonb_set(payload,'{barcode}','\"000888\"') WHERE job_id=:id"
                ),
                {"id": job["id"]},
            )
        elif tamper == "expired":
            c.execute(
                text("UPDATE wms.import_job SET token_expires_at='2026-01-01' WHERE id=:id"),
                {"id": job["id"]},
            )
        elif tamper == "file":
            key = c.execute(
                text("SELECT storage_key FROM wms.stored_file WHERE id=:id"), {"id": job["file_id"]}
            ).scalar_one()
            f.import_service.storage.path(key).write_bytes(b"corrupted")
    response = f.import_action(job, **({"commit_token": str(uuid4())} if tamper == "token" else {}))
    assert response.status_code == 409, response.text
    assert response.json()["code"] in {"STALE_DATA", "STALE_IMPORT", "FILE_HASH_MISMATCH"}


def test_imports_scope_owner_revoke_reads_download_errors_and_commit(imports):
    f = imports
    file = ok(f.upload("11_opening", [["B", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1]]), 201)
    job = ok(f.import_create(file), 201)
    f.outbox.run_batch()
    assert f.executor.run_one() == "VALIDATED"
    job = f.import_read(job)
    paths = [
        "/files/" + file["id"],
        "/files/" + file["id"] + "/download",
        "/imports/" + job["id"],
        "/imports/" + job["id"] + "/errors",
        "/imports/" + job["id"] + "/rows",
    ]
    for path in paths:
        assert f.client.get("/api/v1" + path, headers=f.headers["controller"]).status_code == 404
    other = f.iam.warehouse("OTHER")
    assert f.upload("11_opening", warehouse=other).status_code == 404
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": f.drafter_grant}
        )
    for path in paths:
        assert f.client.get("/api/v1" + path, headers=f.headers["buyer"]).status_code == 403
    assert f.import_action(job).status_code == 403
    assert f.import_action(job, "validate").status_code == 403


def test_imports_cancel_stale_generation_and_revalidate(imports):
    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)
    f.outbox.run_batch()
    task = f.executor.claim()
    cancelled = ok(f.import_action(job, "cancel"))
    assert f.executor.execute(task) == "OBSOLETE"
    assert f.import_read(job)["status"] == "CANCELLED"
    queued = ok(f.import_action(cancelled, "validate"))
    f.outbox.run_batch()
    assert f.executor.run_one() == "VALIDATED"
    fresh = f.import_read(queued)
    assert fresh["generation"] == 2
    ok(f.import_action(fresh))
    assert f.import_action(f.import_read(fresh), "cancel").status_code == 409


def test_imports_crash_enqueue_ack_lease_and_retry_no_duplicate(imports, monkeypatch):
    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)

    def crash(*args):
        raise RuntimeError("Crash before outbox ACK")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresOutboxStore, "_acknowledge", crash)
        assert f.outbox.run_batch().retry == 1
    with f.engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM wms.import_task")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.consumer_receipt")).scalar_one() == 0
        c.execute(text("UPDATE wms.outbox_event SET available_at=now()"))
    assert f.outbox.run_batch().processed == 1
    abandoned = f.executor.claim()
    assert abandoned
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.import_task SET lease_until=now()-interval '1 second'"))
    resumed = f.executor.claim()
    assert resumed["id"] == abandoned["id"] and resumed["lease_token"] != abandoned["lease_token"]
    assert f.executor.execute(abandoned) == "LOST_LEASE"
    assert f.executor.execute(resumed) == "VALIDATED"
    assert f.executor.run_one() is None
    ok(f.import_action(f.import_read(job)))
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.outbox_event SET processed_at=NULL,available_at=now() WHERE event_type='import.validation.requested.v1'"
            )
        )
    assert f.outbox.run_batch().processed == 1
    assert f.executor.run_one() is None


def test_imports_upload_pending_recovery_quota_and_limits(imports, monkeypatch):
    f = imports
    key = uuid4()

    def crash(*args):
        raise OSError("Disk unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(f.import_service.storage, "put", crash)
        assert f.upload(key=key).status_code == 500
    file = ok(f.upload(key=key), 201)
    assert file["ready"]
    assert f.upload(key=key, rows=[["DIFF", "Different", 0]]).json()["code"] == "IDEMPOTENCY_MISMATCH"
    f.import_service.storage.settings.max_user_files = 1
    assert f.upload().json()["code"] == "FILE_QUOTA"
    f.import_service.storage.settings.max_file_bytes = 1024
    assert f.upload(data=b"a" * 1025).status_code == 413
    for name in ["../escape.csv", "C:\\file.csv", "bad.txt"]:
        assert f.upload(filename=name).json()["code"] == "INVALID_FILENAME"
    assert f.upload(filename="mislabeled.xlsx").json()["code"] == "INVALID_FILE"
    response = f.client.get("/api/v1/files/" + file["id"] + "/download", headers=f.headers["buyer"])
    assert response.content == csv_bytes("01_uom", [["NEW", "Mới", 0]])
    assert response.headers["x-content-type-options"] == "nosniff"


def test_imports_concurrent_commit_and_cancel_have_single_linearization(imports):
    f = imports
    job = f.prepare()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda action: f.import_action(job, action), ["commit", "cancel"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    current = f.import_read(job)
    with f.engine.connect() as c:
        count = c.execute(text("SELECT count(*) FROM wms.uom WHERE code='NEW'")).scalar_one()
    assert count == (1 if current["status"] == "COMMITTED" else 0)


def test_imports_validation_crash_before_task_ack_rolls_back_staging(imports, monkeypatch):
    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)
    f.outbox.run_batch()

    def crash(*args):
        raise RuntimeError("Before task ACK")

    with monkeypatch.context() as patch:
        patch.setattr(f.executor, "done", crash)
        assert f.executor.run_one() == "RETRY"
    with f.engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM wms.import_row")).scalar_one() == 0
        c.execute(text("UPDATE wms.import_task SET available_at=now()"))
    assert f.executor.run_one() == "VALIDATED"
    assert f.import_read(job)["status"] == "VALIDATED"


def test_imports_two_commits_concurrent_create_and_same_upload_key(imports):
    f = imports
    key = uuid4()
    with ThreadPoolExecutor(2) as pool:
        files = list(pool.map(lambda _: ok(f.upload(key=key), 201), range(2)))
    assert files[0] == files[1]
    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda _: f.import_create(files[0]), range(2)))
    assert sorted(r.status_code for r in jobs) == [200, 201]
    assert jobs[0].json()["id"] == jobs[1].json()["id"]
    f.outbox.run_batch()
    assert f.executor.run_one() == "VALIDATED"
    job = f.import_read(jobs[0].json())
    with ThreadPoolExecutor(2) as pool:
        saved = list(pool.map(lambda _: ok(f.import_action(job)), range(2)))
    assert saved[0] == saved[1]


def test_imports_worker_rechecks_revoked_identity_before_any_file_io(imports, monkeypatch):
    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)
    f.outbox.run_batch()
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.app_user SET auth_version=auth_version+1 WHERE id=:id"), {"id": f.buyer})

    def no_read(*args):
        pytest.fail("Revoked actor must not reach file I/O")

    monkeypatch.setattr(f.import_service.storage, "read", no_read)
    assert f.executor.run_one() == "FAILED"
    with f.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT errors->0->>'code' FROM wms.import_job WHERE id=:id"), {"id": job["id"]}
            ).scalar_one()
            == "FORBIDDEN"
        )


def test_imports_final_lease_crash_becomes_visible_failure(imports):
    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)
    f.outbox.run_batch()
    f.executor.settings.max_attempts = 1
    assert f.executor.claim()
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.import_task SET lease_until=now()-interval '1 second'"))
    assert f.executor.claim() is None
    state = f.import_read(job)
    assert state["status"] == "FAILED" and state["errors"][0]["code"] == "LEASE_EXHAUSTED"


def test_imports_mixed_order_replay_checks_each_permission(imports):
    f = imports
    job = f.prepare(
        "12_open_orders", [["SO-01", "SO", "ORDERS", "NCC", "2026-10-02", 1, "ORD-01", "EA", 2, ""]]
    )
    key = uuid4()
    ok(f.import_action(job, key=key))
    with f.engine.begin() as c:
        c.execute(
            text(
                "UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id AND role_id=(SELECT id FROM wms.role WHERE code='SELLER')"
            ),
            {"id": f.buyer},
        )
    # BUYER remains valid, but cannot replay or read an import containing SO.
    assert f.import_action(job, key=key).status_code == 403
    assert f.client.get("/api/v1/imports/" + job["id"], headers=f.headers["buyer"]).status_code == 403


def test_imports_serial_received_after_dry_run_rejected_without_changing_receipt(imports):
    f = imports
    product = f.master(
        "products", sku="SERIAL", name="Thiết bị", base_uom_id=f.conversion["uom_id"], tracking="SERIAL"
    )
    conversion = ok(
        f.client.get(
            "/api/v1/master/product-uoms", params={"product_id": product["id"]}, headers=f.headers["buyer"]
        )
    )["items"][0]
    job = f.prepare("11_opening", [["CUT", "2026-10-02", "ORDERS", "BIN", "SERIAL", "", "000001", 1]])
    assert job["status"] == "VALIDATED", job
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    dock = f.master(
        "locations", code="DOCK", name="Cửa nhận", kind="RECEIVING", warehouse_id=str(f.warehouse)
    )
    order = ok(
        f.create(
            body={
                **f.body,
                "lines": [
                    {
                        **f.body["lines"][0],
                        "product_id": product["id"],
                        "product_uom_id": conversion["id"],
                        "quantity": "1",
                    }
                ],
            }
        ),
        201,
    )
    order = ok(f.decision(ok(f.action(order, "submit"))))
    line = ok(f.read(order))["lines"][0]
    receipt = ok(
        f.client.post(
            "/api/v1/receipts",
            json=dict(
                source_order_id=order["id"],
                business_date="2026-10-02",
                reason="Nhận serial trước commit",
                lines=[
                    dict(
                        source_line_id=line["id"],
                        destination_location_id=dock["id"],
                        quantity_base="1",
                        serial_code="000001",
                    )
                ],
            ),
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        ),
        201,
    )
    receipt = ok(f.decision(ok(f.action(receipt, "submit"))))
    view = ok(f.read(receipt, kind="receipts"))
    ok(
        f.client.post(
            "/api/v1/receipts/" + receipt["id"] + "/post",
            json=dict(
                expected_version=receipt["version"],
                execution_key=str(uuid4()),
                reason="Ghi nhận serial",
                lines=[dict(document_line_id=view["lines"][0]["id"], quantity_base="1")],
            ),
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
    )
    before = inventory(f)
    assert before == (1, 1, 1, 1)
    assert f.import_action(job).status_code == 409
    assert inventory(f) == before


def test_imports_worker_clis_enqueue_and_execute_real_job(imports):
    import os
    import subprocess
    import sys

    f = imports
    job = ok(f.import_create(ok(f.upload(), 201)), 201)
    environment = {
        **os.environ,
        "PYTHONPATH": os.getcwd(),
        "WMS_DATABASE_URL": f.engine.url.render_as_string(hide_password=False),
        "WMS_IMPORT_STORAGE_ROOT": str(f.import_service.storage.root),
    }
    for args in [
        [
            "apps.server.worker",
            "--consumer-factory",
            "apps.server.application.import_jobs:consumer_factory",
            "--once",
        ],
        ["apps.server.import_worker", "--once"],
    ]:
        process = subprocess.run(
            [sys.executable, "-m", *args], env=environment, capture_output=True, text=True, timeout=20
        )
        assert process.returncode == 0, process.stderr
    assert f.import_read(job)["status"] == "VALIDATED"


def test_imports_upgrade_from_010_preserves_legacy_staging(empty_database, monkeypatch):
    from apps.server.infrastructure import migrations

    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:10])
        migrations.migrate(empty_database)
    ids = {k: uuid4() for k in ["user", "file", "job", "row", "key"]}
    with empty_database.begin() as c:
        statements = [
            "INSERT INTO wms.app_user VALUES (:user,'legacy-importer','Legacy','fixture-only',true,0,now())",
            "INSERT INTO wms.stored_file VALUES (:file,'legacy-storage','legacy.csv','text/csv',repeat('a',64),4,:user,now())",
            "INSERT INTO wms.import_job VALUES (:job,'01_uom',:file,:user,'VALIDATED',repeat('a',64),'legacy',:key,now())",
            "INSERT INTO wms.import_row VALUES (:row,:job,2,'{\"code\":\"LEGACY\"}','[]',NULL,'VALIDATED')",
        ]
        for statement in statements:
            c.execute(text(statement), ids)
        before = dict(c.execute(text("SELECT * FROM wms.import_job WHERE id=:job"), ids).mappings().one())
        old_row = dict(c.execute(text("SELECT * FROM wms.import_row WHERE id=:row"), ids).mappings().one())
    assert migrations.migrate(empty_database) == [source[0] for source in sources[10:]]
    assert migrations.migrate(empty_database) == []
    with empty_database.connect() as c:
        after = dict(c.execute(text("SELECT * FROM wms.import_job WHERE id=:job"), ids).mappings().one())
        assert {k: after[k] for k in before} == before
        assert after["auth_version"] is None and after["commit_token"] is None
        assert (
            dict(c.execute(text("SELECT * FROM wms.import_row WHERE id=:row"), ids).mappings().one())
            == old_row
        )
