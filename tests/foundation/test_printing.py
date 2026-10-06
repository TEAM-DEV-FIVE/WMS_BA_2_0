from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_count_period import counting  # noqa: F401
from test_fulfillment import fulfillment  # noqa: F401
from test_issues import issuing  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving, totals  # noqa: F401
from test_transfers import transfer  # noqa: F401

from apps.server.application.outbox import OutboxProcessor
from apps.server.application.print_jobs import PrintExecutor, consumer_factory
from apps.server.application.printing import PrintSettings
from apps.server.infrastructure.file_storage import FileStorage
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = pytest.mark.integration
# ruff: noqa: F811


@pytest.fixture
def printing(receiving, tmp_path):
    f = receiving
    f.doc = f.receipt_approve()
    service = f.client.app.state.printing
    service.storage = FileStorage(PrintSettings(storage_root=tmp_path / "prints"))
    f.printer = PrintExecutor(service)
    f.print_outbox = OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory())
    return f


def create(f, key=None, who="buyer", **changes):
    return f.client.post(
        "/api/v1/printing",
        json=dict(
            template="RECEIPT",
            source_id=f.doc["id"],
            expected_version=f.doc["version"],
            warehouse_id=str(f.warehouse),
            paper="A4",
        )
        | changes,
        headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
    )


def read(f, job):
    return ok(f.client.get("/api/v1/printing/" + job["id"], headers=f.headers["buyer"]))


def action(f, job, op, key=None, **data):
    body = dict(expected_version=job["version"], **data)
    if op != "result":
        body.setdefault("reason", "Kiểm thử in")
    return f.client.post(
        f"/api/v1/printing/{job['id']}/{op}",
        json=body,
        headers={**f.headers["buyer"], "Idempotency-Key": str(key or uuid4())},
    )


def ready(f):
    job = ok(create(f), 201)
    assert f.print_outbox.run_batch().processed == 1
    assert f.printer.run_one() == "READY"
    return read(f, job)


def test_print_snapshot_spool_reprint_no_stock_and_same_key(printing):
    f = printing
    key = uuid4()
    job = ok(create(f, key), 201)
    assert ok(create(f, key), 201) == job
    assert create(f, key, paper="A5").json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert f.print_outbox.run_batch().processed == 1
    assert f.print_outbox.run_batch().processed == 0
    assert f.printer.run_one() == "READY"
    job = read(f, job)
    pdf = f.client.get(f"/api/v1/printing/{job['id']}/download", headers=f.headers["buyer"])
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF-")
    attempt = str(uuid4())
    key = uuid4()
    options = dict(attempt_id=attempt, printer="USB test contract", driver="CUPS", copies=1)
    claimed = ok(action(f, job, "spool", key, **options))
    assert claimed["attempt"]["status"] == "UNKNOWN"
    assert ok(action(f, job, "spool", key, **options)) == claimed
    assert action(f, claimed, "spool", **{**options, "attempt_id": str(uuid4())}).status_code == 409
    reported = ok(action(f, claimed, "result", attempt_id=attempt, outcome="SUBMITTED", spool_id="q-123"))
    assert reported["attempt"]["status"] == "SUBMITTED"
    again = ok(action(f, reported, "reprint"))
    assert again["generation"] == 2 and again["attempt"] is None
    assert f.print_outbox.run_batch().processed == 1
    assert f.printer.run_one() == "READY"
    assert read(f, again)["sha256"] == job["sha256"]
    assert totals(f) == (0, 0, 0, 0)
    with f.engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action LIKE 'print.%'")).scalar_one()
            == 4
        )
        file = c.execute(
            text("SELECT file_id FROM wms.print_job WHERE id=:id"), {"id": job["id"]}
        ).scalar_one()
    assert f.client.get(f"/api/v1/files/{file}/download", headers=f.headers["buyer"]).status_code == 404


def test_print_live_revocation_price_expiry_snapshot_immutable(printing):
    f = printing
    job = ready(f)
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": f.buyer})
    assert f.client.get(f"/api/v1/printing/{job['id']}/download", headers=f.headers["buyer"]).status_code in {
        403,
        404,
    }
    assert f.client.get("/api/v1/printing/" + job["id"], headers=f.headers["manager"]).status_code == 404


def test_issuer_is_server_owned_snapshot_survives_configuration_change(printing):
    import pypdfium2 as pdfium

    f = printing
    settings = f.client.app.state.printing.storage.settings
    settings.issuer_name = "InternTechLead"
    settings.issuer_address = "Đông Thạnh, Hóc Môn, TP. Hồ Chí Minh"
    job = ok(create(f), 201)
    with f.engine.connect() as connection:
        snapshot = connection.execute(text("SELECT snapshot FROM wms.print_job WHERE id=:id"),
                                      {"id": job["id"]}).scalar_one()
    assert snapshot["template_version"] == job["template_version"] == 1
    assert snapshot["header"]["issuer"]["name"] == "InternTechLead"
    settings.issuer_name = "Changed after capture"
    assert f.print_outbox.run_batch().processed == 1
    assert f.printer.run_one() == "READY"
    pdf = f.client.get(f"/api/v1/printing/{job['id']}/download", headers=f.headers["buyer"])
    assert pdf.status_code == 200
    with (pdfium.PdfDocument(pdf.content) as document,
          closing(document[0]) as page, closing(page.get_textpage()) as textpage):
        text_content = textpage.get_text_range()
    assert "InternTechLead" in text_content and "Changed after capture" not in text_content
    assert create(f, issuer={"name": "Forged"}).status_code == 422


def test_print_wrong_warehouse_stale_render_failure_retry(printing, monkeypatch):
    f = printing
    payload = dict(
        template="RECEIPT",
        source_id=f.doc["id"],
        expected_version=1,
        warehouse_id=str(f.warehouse),
        paper="A4",
    )
    response = f.client.post(
        "/api/v1/printing", json=payload, headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 409, response.text
    job = ok(create(f), 201)
    f.print_outbox.run_batch()
    from apps.server.domain.errors import DomainError

    def broken(*args):
        raise DomainError("RENDER_FAILED", "test")

    monkeypatch.setattr("apps.server.application.print_jobs.render", broken)
    assert f.printer.run_one() == "FAILED"
    failed = read(f, job)
    assert failed["error_code"] == "RENDER_FAILED"
    retried = ok(action(f, failed, "retry"))
    assert retried["status"] == "QUEUED"
    assert totals(f) == (0, 0, 0, 0)


def test_print_race_claim_one_attempt(printing):
    f = printing
    job = ready(f)

    def claim(_):
        return action(f, job, "spool", attempt_id=str(uuid4()), printer="Q", driver="CUPS", copies=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(claim, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.print_attempt")).scalar_one() == 1
    assert totals(f) == (0, 0, 0, 0)


def test_scanner_exact_quantity_and_stale_no_stock(printing):
    f = printing
    data = dict(
        flow="RECEIPT",
        source_id=f.doc["id"],
        expected_version=f.doc["version"],
        code=f.product["sku"],
        quantity="2",
    )
    response = f.client.post(
        "/api/v1/printing/scan", json=data, headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
    )
    result = ok(response)
    assert len(result["matches"]) == 1 and result["matches"][0]["quantity_base"] == "2"
    for changes in [dict(code="missing"), dict(quantity="101"), dict(expected_version=1), dict(quantity="0")]:
        response = f.client.post(
            "/api/v1/printing/scan",
            json={**data, **changes},
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 409, response.text
    assert totals(f) == (0, 0, 0, 0)


def test_print_price_is_opt_in_revoke_blocks_files_and_replay(printing):
    f = printing
    grant = f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.document_line SET reference_unit_price=987654.321 WHERE document_id=:id"),
            dict(id=f.doc["id"]),
        )
    key = uuid4()
    job = ok(create(f, key, include_price=True), 201)
    f.print_outbox.run_batch()
    assert f.printer.run_one() == "READY"
    masked = ok(create(f), 201)
    with f.engine.connect() as c:
        values = c.execute(text("SELECT id,snapshot FROM wms.print_job")).mappings().all()
        snapshots = {str(r["id"]): r["snapshot"] for r in values}
    assert snapshots[job["id"]]["lines"][0]["reference_unit_price"] == "987654.3210"
    assert "reference_unit_price" not in snapshots[masked["id"]]["lines"][0]
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), dict(id=grant))
    assert create(f, key, include_price=True).status_code == 403
    assert (
        f.client.get(f"/api/v1/printing/{job['id']}/download", headers=f.headers["buyer"]).status_code == 403
    )


def test_print_expiry_retention_and_immutable_snapshot(printing):
    from sqlalchemy.exc import IntegrityError

    from apps.server.application.print_retention import cleanup

    f = printing
    job = ready(f)
    with pytest.raises(IntegrityError):
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.print_job SET snapshot='{}' WHERE id=:id"), dict(id=job["id"]))
    f.iam.advance(3601)
    f.headers["buyer"] = f.iam.headers(f.iam.login("buyer"))
    assert (
        f.client.get("/api/v1/printing/" + job["id"], headers=f.headers["buyer"]).json()["code"]
        == "PRINT_EXPIRED"
    )
    assert cleanup(f.client.app.state.printing)["files"] == 1
    assert cleanup(f.client.app.state.printing)["files"] == 0
    assert not list(f.client.app.state.printing.storage.root.iterdir())


def test_print_atomic_rollback_after_outbox_and_revoke_during_render(printing, monkeypatch):
    f = printing
    service = f.client.app.state.printing
    original = service.effects

    def broken(*a, **kw):
        original(*a, **kw)
        from apps.server.domain.errors import DomainError

        raise DomainError("TEST_ROLLBACK", "rollback")

    monkeypatch.setattr(service, "effects", broken)
    assert create(f).status_code == 409
    with f.engine.connect() as c:
        for table in ["print_job", "print_task"]:
            assert c.execute(text("SELECT count(*) FROM wms." + table)).scalar_one() == 0
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE event_type='print.requested.v1'")
            ).scalar_one()
            == 0
        )
    monkeypatch.setattr(service, "effects", original)
    job = ok(create(f), 201)
    f.print_outbox.run_batch()
    from apps.server.application.print_render import render

    def revoked(*a, **kw):
        result = render(*a, **kw)
        with f.engine.begin() as c:
            c.execute(
                text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), dict(id=f.buyer)
            )
        return result

    monkeypatch.setattr("apps.server.application.print_jobs.render", revoked)
    assert f.printer.run_one() == "FAILED"
    with f.engine.connect() as c:
        assert (
            c.execute(text("SELECT file_id FROM wms.print_job WHERE id=:id"), dict(id=job["id"])).scalar_one()
            is None
        )
    assert totals(f) == (0, 0, 0, 0)


def test_print_duplicate_outbox_and_workers_only_one_publication(printing):
    f = printing
    job = ok(create(f), 201)
    with f.engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            SELECT :id,event_type,aggregate_id,payload,occurred_at,available_at,0 FROM wms.outbox_event
            WHERE event_type='print.requested.v1'"""),
            dict(id=uuid4()),
        )
    assert f.print_outbox.run_batch().processed == 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: f.printer.run_one(), range(2)))
    assert sorted(str(r) for r in results) == ["None", "READY"]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.print_task")).scalar_one() == 1
    assert read(f, job)["status"] == "READY"


def test_count_print_is_always_blind_and_current_assignment(counting, tmp_path):
    f = counting
    f.count_received()
    doc = ok(f.count_action(f.count_create(), "freeze"))
    f.client.app.state.printing.storage = FileStorage(PrintSettings(storage_root=tmp_path / "count"))
    body = dict(
        template="COUNT",
        source_id=doc["id"],
        expected_version=doc["version"],
        warehouse_id=str(f.warehouse),
        paper="A4",
    )
    job = ok(
        f.client.post(
            "/api/v1/printing", json=body, headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
        ),
        201,
    )
    with f.engine.connect() as c:
        snapshot = c.execute(
            text("SELECT snapshot FROM wms.print_job WHERE id=:id"), dict(id=job["id"])
        ).scalar_one()
    assert snapshot["lines"] and not {
        "snapshot_quantity",
        "approved_quantity",
        "observations",
        "delta",
    }.intersection(snapshot["lines"][0])
    with f.engine.begin() as c:
        c.execute(
            text("DELETE FROM wms.count_assignment WHERE session_id=:id AND user_id=:user"),
            dict(id=doc["id"], user=f.buyer),
        )
    assert f.client.get("/api/v1/printing/" + job["id"], headers=f.headers["buyer"]).status_code in {403, 404}


def test_issue_print_and_pick_scanner_current_task(fulfillment, tmp_path):
    f = fulfillment
    f.pick_create()
    doc = f.fulfill_read()
    service = f.client.app.state.printing
    service.storage = FileStorage(PrintSettings(storage_root=tmp_path / "issue-print"))
    payload = dict(
        template="ISSUE",
        source_id=doc["id"],
        expected_version=doc["version"],
        warehouse_id=str(f.warehouse),
        paper="A5",
    )
    job = ok(
        f.client.post(
            "/api/v1/printing", json=payload, headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
        ),
        201,
    )
    OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch()
    assert PrintExecutor(service).run_one() == "READY"
    data = dict(
        flow="PICK", source_id=doc["id"], expected_version=doc["version"], code=f.product["sku"], quantity="1"
    )
    assert (
        len(
            ok(
                f.client.post(
                    "/api/v1/printing/scan",
                    json=data,
                    headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
                )
            )["matches"]
        )
        == 1
    )
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.pick_task SET assigned_to=:user"), dict(user=f.manager))
    assert (
        f.client.post(
            "/api/v1/printing/scan",
            json=data,
            headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())},
        ).json()["code"]
        == "SCAN_NOT_FOUND"
    )
    assert read(f, job)["status"] == "READY"


def test_transfer_print_both_scopes_and_scanner_single_scope(transfer, tmp_path):
    f = transfer
    doc = f.tr_approve(f.tr_seed())
    service = f.client.app.state.printing
    service.storage = FileStorage(PrintSettings(storage_root=tmp_path / "transfer-print"))
    payload = dict(
        template="TRANSFER",
        source_id=doc["id"],
        expected_version=doc["version"],
        warehouse_id=str(f.warehouse),
        paper="A4",
    )
    job = ok(
        f.client.post(
            "/api/v1/printing",
            json=payload,
            headers={**f.headers["manager"], "Idempotency-Key": str(uuid4())},
        ),
        201,
    )
    OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch()
    assert PrintExecutor(service).run_one() == "READY"
    data = dict(
        flow="TRANSFER",
        source_id=doc["id"],
        expected_version=doc["version"],
        code=f.product["sku"],
        quantity="1",
    )
    assert (
        len(
            ok(
                f.client.post(
                    "/api/v1/printing/scan",
                    json=data,
                    headers={**f.headers["sender"], "Idempotency-Key": str(uuid4())},
                )
            )["matches"]
        )
        == 1
    )
    sent = ok(f.tr_dispatch(doc))
    data["expected_version"] = sent["version"]
    assert (
        len(
            ok(
                f.client.post(
                    "/api/v1/printing/scan",
                    json=data,
                    headers={**f.headers["receiver"], "Idempotency-Key": str(uuid4())},
                )
            )["matches"]
        )
        == 1
    )
    with f.engine.begin() as c:
        c.execute(
            text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:user AND warehouse_id=:wh"),
            dict(user=f.manager, wh=f.destination),
        )
    assert f.client.get("/api/v1/printing/" + job["id"], headers=f.headers["manager"]).status_code in {
        403,
        404,
    }


def test_serial_hid_quantity_and_rendered_label_scope(printing):
    from test_receipts import tracking_po

    f = printing
    product, body = tracking_po(f, "SERIAL")
    body["lines"][0]["serial_code"] = "SN-0001"
    doc = f.receipt_approve(body)
    data = dict(
        flow="RECEIPT", source_id=doc["id"], expected_version=doc["version"], code="SN-0001", quantity="1"
    )
    headers = {**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
    assert len(ok(f.client.post("/api/v1/printing/scan", json=data, headers=headers))["matches"]) == 1
    for changes in [dict(quantity="2"), dict(code=product["sku"]), dict(code="sn-0001")]:
        assert (
            f.client.post("/api/v1/printing/scan", json={**data, **changes}, headers=headers).status_code
            == 409
        )
    ok(f.post(doc, f.post_body(doc, "1")))
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    with f.engine.connect() as c:
        serial = c.execute(
            text("SELECT id FROM wms.serial WHERE product_id=:id"), dict(id=product["id"])
        ).scalar_one()
    payload = dict(
        template="PRODUCT_LABEL",
        source_id=product["id"],
        expected_version=product["version"],
        serial_id=str(serial),
        warehouse_id=str(f.warehouse),
        paper="80x40",
    )
    job = ok(f.client.post("/api/v1/printing", json=payload, headers=headers), 201)
    f.print_outbox.run_batch()
    assert f.printer.run_one() == "READY"
    pdf = f.client.get(f"/api/v1/printing/{job['id']}/download", headers=headers).content
    import zxingcpp

    from apps.desktop.printing.pdf import page_image

    image, _ = page_image(pdf, scale=300 / 72)
    assert [x.text for x in zxingcpp.read_barcodes(image)] == ["SN-0001"]


def test_barcode_uom_factor_and_deactivation(printing):
    f = printing
    unit = f.master("uoms", code="PACK", name="Gói", decimal_places=0)
    pu = f.master("product-uoms", product_id=f.product["id"], uom_id=unit["id"], factor="10", expected_product_version=f.product["version"])
    f.master("barcodes", product_uom_id=pu["id"], code="PACK-10")
    headers = {**f.headers["buyer"], "Idempotency-Key": str(uuid4())}
    data = dict(
        flow="RECEIPT", source_id=f.doc["id"], expected_version=f.doc["version"], code="PACK-10", quantity="2"
    )
    result = ok(f.client.post("/api/v1/printing/scan", json=data, headers=headers))
    assert result["matches"][0]["quantity_base"] == "20.00000000"
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.barcode SET is_active=false WHERE code='PACK-10'"))
    assert (
        f.client.post("/api/v1/printing/scan", json=data, headers=headers).json()["code"] == "SCAN_NOT_FOUND"
    )
