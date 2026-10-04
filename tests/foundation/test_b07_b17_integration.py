"""Metadata, approval, reversal and immutable export snapshots on the merged runtime."""

from decimal import Decimal

import pytest
from test_custom_fields import custom, field  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_reports_exports import export_job, page, rows, snapshot
from test_reversals import setup_reversal

from apps.server.application.export_jobs import ExportExecutor, consumer_factory
from apps.server.application.exports import ExportSettings
from apps.server.application.outbox import OutboxProcessor
from apps.server.infrastructure.file_storage import FileStorage
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = pytest.mark.integration


def test_metadata_receipt_reversal_preserves_snapshot_and_export_privacy(custom, receiving, tmp_path):  # noqa: F811
    f = setup_reversal(receiving)
    f.iam.grant(f.buyer, "CONTROLLER", f.warehouse)
    f.iam.grant(f.buyer, "CONTROLLER")
    definition = ok(custom.publish([
        field(required=True), field("secret_quote", "DECIMAL", visibility="PRICE"),
    ], kind="RECEIPT"))
    receipt = ok(f.receipt_create(), 201)
    saved = ok(custom.write(receipt, definition, {"note": "kept in approval", "secret_quote": "991234.125"}))
    approved = ok(f.decision(ok(f.action(saved, "submit"))))
    posted = ok(f.post(approved))
    before = ok(snapshot(f, "R03"), 201)
    frozen_rows = ok(page(f, before))["items"]
    assert frozen_rows and "secret_quote" not in str(frozen_rows)
    assert sum(Decimal(r["physical"]) for r in rows(f)) > 0
    service = f.client.app.state.exports
    service.storage = FileStorage(ExportSettings(storage_root=tmp_path / "exports"))
    job = ok(export_job(f, before), 201)

    ok(f.rev_post(f.rev_approve(posted["transaction_id"])))
    assert sum(Decimal(r["physical"]) for r in rows(f)) == 0
    assert ok(page(f, before))["items"] == frozen_rows
    assert ok(custom.read(posted))["values"] == {"note": "kept in approval", "secret_quote": "991234.125"}
    assert OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch().processed == 1
    assert ExportExecutor(service).run_one() == "READY"
    download = f.client.get(f"/api/v1/exports/{job['id']}/download", headers=f.headers["buyer"])
    assert download.status_code == 200, download.text
    assert posted["transaction_id"] in download.text
    assert "secret_quote" not in download.text and "991234.125" not in download.text
