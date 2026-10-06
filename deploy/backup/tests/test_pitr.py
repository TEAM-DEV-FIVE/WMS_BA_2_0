import json
import os
import shlex
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, text
from test_issues import issuing  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401

from apps.server.api.app import create_app
from apps.server.application.outbox import OutboxProcessor
from apps.server.application.print_jobs import PrintExecutor
from apps.server.application.printing import PrintSettings
from apps.server.consumers.registry import consumer_factory
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.file_storage import FileStorage
from apps.server.infrastructure.outbox import PostgresOutboxStore
from scripts.wms_backup import (
    BackupError,
    Postgres,
    base_backup,
    checkpoint,
    digest,
    reconcile,
    restore_check,
    restore_prepare,
)
from scripts.wms_backup import (
    main as repository_cli,
)

pytestmark = pytest.mark.integration


def test_real_pitr_files_mfa_ledger_pending_jobs_and_no_duplicate(cluster, issuing):  # noqa: F811
    f, pg, repo = issuing, cluster.pg, cluster.repo
    roots = {k: cluster.path / k for k in ("import", "export", "print", "config", "release", "pg_config")}
    for p in roots.values():
        p.mkdir(mode=0o700)
    mfa_key = f.iam.service.settings.mfa_encryption_key.get_secret_value()
    (roots["config"] / "mfa.env").write_text("WMS_MFA_ENCRYPTION_KEY=" + mfa_key + "\n")
    (roots["config"] / "runtime.env").write_text("fixture deployment config\n")
    (roots["pg_config"] / "postgresql.conf").write_text("fixture source config; never executed on DR\n")
    (roots["release"] / "release.json").write_text('{"release":"B22-fixture","pg":24,"sqlite":3}')
    (roots["import"] / "fixture.csv").write_bytes(b"sku,quantity\nfixture,1\n")
    (roots["export"] / "fixture.csv").write_bytes(b"sku,on_hand\nfixture,1\n")
    shutil.copyfile("apps/server/printing_assets/DejaVuSans.ttf", roots["release"] / "DejaVuSans.ttf")
    shutil.copyfile("apps/server/application/import_templates.py", roots["release"] / "import_templates.py")
    f.client.app.state.printing.storage = FileStorage(PrintSettings(storage_root=roots["print"]))
    actor, mfa_secret = f.iam.user("dr-mfa", mfa=True)
    serial = f.master("products", sku="DR-SERIAL", name="DR serial", tracking="SERIAL",
                      base_uom_id=f.product["base_uom_id"])
    batch = {**f.opening_body, "lines": [*f.opening_body["lines"],
             {**f.opening_body["lines"][0], "product_id": serial["id"], "quantity_base": "1", "serial_code": "DR0001"}]}
    f.seed(batch)
    held = f.reserve(f.issue_approve(), "7")
    staging = cluster.path / "staging"
    staging.mkdir(mode=0o700)
    base = base_backup(repo, pg, staging, "B22-fixture")
    # This business transaction exists only in WAL after the base backup.
    key, body = uuid4(), f.issue_post_body(held, "4")
    posted = ok(f.issue_post(held, body, key=key))
    doc = f.issue_read(posted)
    print_body = {"template": "ISSUE", "source_id": doc["id"], "expected_version": doc["version"],
                  "warehouse_id": str(f.warehouse), "paper": "A4"}
    def request_print():
        return ok(f.client.post("/api/v1/printing", json=print_body,
                               headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}), 201)
    first_job = request_print()
    outbox = OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory())
    outbox.run_batch()
    assert PrintExecutor(f.client.app.state.printing).run_one() == "READY"
    pending = request_print()  # Outbox event pending; no task yet at the checkpoint.
    f.engine.dispose()
    with pytest.raises(BackupError, match="RELEASE_MISMATCH"):
        checkpoint(repo, pg, base["id"], roots, "wrong-release")
    point = checkpoint(repo, pg, base["id"], roots, "B22-fixture")
    assert point["fingerprints"]["stock_move"]["count"] >= 3
    assert point["fingerprints"]["serial_position"]["count"] == 1
    assert point["fingerprints"]["reservation"]["count"] > 0
    assert all(v == 0 for v in reconcile(pg).values())
    # Later business activity must NOT be recovered at the selected timestamp.
    ok(f.issue_post(posted, f.issue_post_body(posted, "1")))
    f.engine.dispose()
    failure_at = datetime.now(UTC)
    start = time.monotonic()
    pg.run("pg_ctl", "-D", cluster.data, "-m", "immediate", "-w", "stop")
    cluster.data.rename(cluster.path / "lost-primary")
    # Simulated file loss only inside this test's private /tmp tree.
    roots["print"].rename(cluster.path / "lost-print-files")
    destination = cluster.path / "dr"
    record = restore_prepare(repo, point["id"], destination, pg, target_time=point["target_time"])
    sock = cluster.path / "dr-socket"
    sock.mkdir(mode=0o700)
    dr = Postgres(cluster.binary, sock, 55440, pg.database, pg.user)
    options = shlex.join(["-k", str(sock), "-p", dr.port, "-c", f"config_file={destination}/postgresql.conf"])
    engine = None
    try:
        dr.run("pg_ctl", "-D", destination / "pg", "-l", cluster.path / "dr.log", "-o", options, "-w", "start")
        deadline = time.monotonic() + 30
        while dr.sql("SELECT pg_is_wal_replay_paused()") != "t" and time.monotonic() < deadline:
            time.sleep(0.1)
        checked = restore_check(dr, destination)
        for name, item in record["files"].items():
            assert digest(destination / "files" / name) == item["sha256"]
        rto = time.monotonic() - start
        assert checked["ready_for_review"]
        # Both fail closed before any overwrite or startup: wrong timestamp and existing DR directory.
        with pytest.raises(BackupError):
            restore_prepare(repo, point["id"], destination, pg, target_time=point["target_time"])
        with pytest.raises(BackupError):
            restore_prepare(repo, point["id"], cluster.path / "bad-time", pg, target_time="2000-01-01T00:00:00Z")
        # Explicit test-only promotion follows successful reconciliation, never a CLI side effect.
        dr.sql("SELECT pg_wal_replay_resume()")
        deadline = time.monotonic() + 10
        while dr.sql("SELECT pg_is_in_recovery()") == "t" and time.monotonic() < deadline:
            time.sleep(0.1)
        assert dr.sql("SELECT pg_is_in_recovery()") == "f"
        engine = create_engine(URL.create("postgresql+psycopg", username=pg.user, database=pg.database,
                                         query={"host": str(sock), "port": dr.port}))
        restored_key = (destination / "files/config/mfa.env").read_text().strip().partition("=")[2]
        settings = Settings(database_url=engine.url.render_as_string(hide_password=False),
                            mfa_encryption_key=restored_key)
        app = create_app(settings, engine=engine)
        app.state.printing.storage = FileStorage(PrintSettings(storage_root=destination / "files/print"))
        # Fixture clock only: original IAM fixture dates are fixed, independent from wall-clock PITR.
        app.state.identity.clock = lambda: f.iam.now
        with engine.connect() as c:
            ciphertext = c.execute(text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:id"),
                                   {"id": actor}).scalar_one()
            assert app.state.identity.cipher().decrypt(ciphertext.encode()).decode() == mfa_secret
        with TestClient(app) as client:
            assert client.get("/api/v1/ready").status_code == 200
            assert client.get(f"/api/v1/printing/{first_job['id']}/download",
                              headers=f.headers["buyer"]).content.startswith(b"%PDF-")
            replay = client.post(f"/api/v1/issues/{held['id']}/post", json=body,
                                 headers={**f.headers["buyer"], "Idempotency-Key": str(key)})
            assert ok(replay) == posted
            processor = OutboxProcessor(PostgresOutboxStore(engine), consumer_factory())
            assert processor.run_batch().processed == 1
            assert PrintExecutor(app.state.printing).run_one() == "READY"
            assert processor.run_batch().processed == 0
            assert PrintExecutor(app.state.printing).run_one() is None
            assert client.get(f"/api/v1/printing/{pending['id']}/download",
                              headers=f.headers["buyer"]).content.startswith(b"%PDF-")
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.print_task WHERE job_id=:id"),
                             {"id": pending["id"]}).scalar_one() == 1
            assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 7
            assert c.execute(text("SELECT sum(reserved) FROM wms.stock_balance")).scalar_one() == 3
        service_elapsed = time.monotonic() - start
        # Broken archive/object/base must never be reported as a verified checkpoint.
        wal_name = next(iter(record["wal"]))
        wal_path = repo.wal / wal_name
        saved = wal_path.with_name(wal_name + ".removed")
        wal_path.rename(saved)
        with pytest.raises((OSError, BackupError)):
            restore_prepare(repo, point["id"], cluster.path / "gap", pg, target_time=point["target_time"])
        saved.rename(wal_path)
        object_sha = next(iter(record["files"].values()))["sha256"]
        obj = repo.root / "objects" / object_sha
        original = obj.read_bytes()
        obj.write_bytes(b"corrupt fixture")
        with pytest.raises(BackupError):
            repo.verify_checkpoint(point["id"])
        obj.write_bytes(original)
        base_directory = repo.root / "bases" / base["id"]
        hidden_base = repo.root / "bases" / "missing-base-fixture"
        base_directory.rename(hidden_base)
        with pytest.raises(OSError):
            repo.verify_checkpoint(point["id"])
        hidden_base.rename(base_directory)
        base_file = repo.root / "bases" / base["id"] / "pg/PG_VERSION"
        original_base = base_file.read_bytes()
        base_file.write_bytes(b"99\n")
        with pytest.raises(BackupError):
            restore_prepare(repo, point["id"], cluster.path / "bad-base", pg, target_time=point["target_time"])
        base_file.write_bytes(original_base)
        assert digest(repo.wal_path(wal_name)) == record["wal"][wal_name]
        before_retention = sorted(str(p) for p in repo.root.rglob("*"))
        assert repository_cli(["retention-plan", "--repository", str(repo.root), "--repository-id",
                               (repo.root / ".repository-id").read_text().strip(), "--local"]) == 0
        assert sorted(str(p) for p in repo.root.rglob("*")) == before_retention
        byte_count = sum(p.stat().st_size for p in cluster.path.rglob("*") if p.is_file())
        assert byte_count < 2 * 1024**3
        evidence = {"status": "LOCAL_FIXTURE_VERIFIED; production RPO/RTO NEEDS_ENVIRONMENT",
                    "postgresql": dr.run("postgres", "--version").strip(),
                    "failure_at": failure_at.isoformat(), "recovered_target": record["target_time"],
                    "rpo_seconds": (failure_at - datetime.fromisoformat(record["target_time"])).total_seconds(),
                    "rto_to_reconciled_paused_seconds": round(rto, 3),
                    "elapsed_to_api_and_pending_replay_seconds": round(service_elapsed, 3),
                    "dataset_counts": {k: v["count"] for k, v in record["fingerprints"].items()},
                    "temporary_bytes_at_measurement": byte_count, "cap_bytes": 2 * 1024**3,
                    "off_host": "NEEDS_ENVIRONMENT", "all_invariants_zero": True, "pending_replay_once": True}
        if os.environ.get("WMS_DRILL_REPORT"):
            Path(os.environ["WMS_DRILL_REPORT"]).write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        if engine:
            engine.dispose()
        if (destination / "pg/postmaster.pid").exists():
            dr.run("pg_ctl", "-D", destination / "pg", "-m", "immediate", "-w", "stop")
