import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_imports import imports  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_printing import create as print_create
from test_printing import printing  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_reports_exports import export_job, reports  # noqa: F401

from apps.server.application.outbox import OutboxProcessor
from apps.server.consumers.registry import consumer_factory, fingerprint
from apps.server.infrastructure.outbox import PostgresOutboxStore
from apps.server.infrastructure.worker_status import WorkerStatus
from apps.server.operations_worker import compose
from apps.server.worker import WorkerSettings, load_registry

pytestmark = pytest.mark.integration


def operator(iam):
    actor, secret = iam.user("operations", mfa=True)
    grant = iam.grant(actor, "SYSADMIN")
    return actor, grant, iam.headers(iam.login("operations", secret))


def insert(engine, *, event_type="export.requested.v1", attempts=5, processed=False):
    event_id = uuid4()
    with engine.begin() as c:
        c.execute(
            text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts,processed_at,last_error)
            VALUES (:id,:type,:aggregate,'{"secret":"never-return-payload"}',clock_timestamp()-interval '5 minutes',
            clock_timestamp(),:attempts,CASE WHEN :processed THEN clock_timestamp() END,'secret-in-old-error')"""),
            dict(id=event_id, type=event_type, aggregate=uuid4(), attempts=attempts, processed=processed),
        )
    return event_id


def replay(iam, headers, event_id, version=1, key=None, **extra):
    return iam.client.post(
        f"/api/v1/operations/outbox/{event_id}/replay",
        json=dict(expected_version=version, reason="Operator fixed the delivery cause") | extra,
        headers={**headers, "Idempotency-Key": str(key or uuid4())},
    )


def test_default_registry_uses_real_versioned_consumers(database):
    registry = load_registry(WorkerSettings().consumer_factory)
    assert registry.event_types == (
        "export.requested.v1",
        "import.validation.requested.v1",
        "print.requested.v1",
    )
    assert fingerprint(registry) == fingerprint(consumer_factory())
    unknown = insert(database, event_type="print.requested.v2", attempts=0)
    assert OutboxProcessor(PostgresOutboxStore(database), registry).run_batch().attempted == 0
    with database.connect() as c:
        assert (
            c.execute(
                text("SELECT attempts FROM wms.outbox_event WHERE id=:id"), dict(id=unknown)
            ).scalar_one()
            == 0
        )


def test_operations_auth_mfa_no_payload_and_paging(iam):
    event_id = insert(iam.engine)
    assert iam.client.get("/api/v1/operations/workers").status_code == 401
    user, _ = iam.user()
    headers = iam.headers(iam.login())
    assert iam.client.get("/api/v1/operations/outbox", headers=headers).status_code == 403
    iam.grant(user, "SYSADMIN")
    assert replay(iam, headers, event_id).json()["code"] == "MFA_REQUIRED"
    _, _, headers = operator(iam)
    unknown = insert(iam.engine, event_type="export.requested.v2")
    response = iam.client.get("/api/v1/operations/outbox", headers=headers, params=dict(limit=1))
    data = ok(response)
    assert len(data["items"]) == 1 and data["next_after"]
    second = ok(
        iam.client.get(
            "/api/v1/operations/outbox", headers=headers, params=dict(limit=1, after=data["next_after"])
        )
    )
    assert {x["id"] for x in data["items"] + second["items"]} == {str(event_id), str(unknown)}
    assert second["next_after"] is None
    assert "never-return-payload" not in response.text and "secret-in-old-error" not in response.text
    assert (
        iam.client.get("/api/v1/operations/outbox", headers=headers, params=dict(limit=201)).status_code
        == 422
    )


def test_replay_idempotency_stale_limits_preserves_receipts_and_current_grants(iam):
    actor, grant, headers = operator(iam)
    event_id = insert(iam.engine)
    with iam.engine.begin() as c:
        c.execute(
            text("INSERT INTO wms.consumer_receipt VALUES (:id,:event,'export.enqueue.v1',now())"),
            dict(id=uuid4(), event=event_id),
        )
    key = uuid4()
    result = ok(replay(iam, headers, event_id, key=key))
    assert result["attempts"] == 0 and result["version"] == 2 and result["replay_count"] == 1
    assert ok(replay(iam, headers, event_id, key=key)) == result
    assert (
        replay(iam, headers, event_id, key=key, reason="Changed reason for same key").json()["code"]
        == "IDEMPOTENCY_MISMATCH"
    )
    assert replay(iam, headers, event_id).status_code == 409
    # The receipt alone prevents re-running its already committed effect.
    assert OutboxProcessor(PostgresOutboxStore(iam.engine), consumer_factory()).run_batch().processed == 1
    assert replay(iam, headers, event_id, version=3).json()["code"] == "INVALID_STATE"
    with iam.engine.begin() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.consumer_receipt WHERE event_id=:id"), dict(id=event_id)
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='outbox.replay'")).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.idempotency_record WHERE command='outbox.replay'")
            ).scalar_one()
            == 1
        )
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), dict(id=grant))
    assert replay(iam, headers, event_id, key=key).status_code == 403


def test_replay_poison_cooldown_cap_unknown_version_and_race(iam):
    _, _, headers = operator(iam)
    unsupported = insert(iam.engine, event_type="export.requested.v2")
    assert replay(iam, headers, unsupported).json()["code"] == "OUTBOX_VERSION_UNSUPPORTED"
    event_id = insert(iam.engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: replay(iam, headers, event_id), range(2)))
    assert sorted(x.status_code for x in results) == [200, 409]
    for count in (1, 2, 3):
        with iam.engine.begin() as c:
            c.execute(text("UPDATE wms.outbox_event SET attempts=5 WHERE id=:id"), dict(id=event_id))
        if count < 3:
            assert (
                replay(iam, headers, event_id, version=count + 1).json()["code"] == "OUTBOX_REPLAY_COOLDOWN"
            )
            with iam.engine.begin() as c:
                c.execute(
                    text("UPDATE wms.outbox_event SET replayed_at=now()-interval '61 seconds' WHERE id=:id"),
                    dict(id=event_id),
                )
            assert ok(replay(iam, headers, event_id, version=count + 1))["replay_count"] == count + 1
        else:
            assert replay(iam, headers, event_id, version=4).json()["code"] == "OUTBOX_REPLAY_LIMIT"


def test_replay_audit_failure_rolls_back_event_and_ack(iam):
    _, _, headers = operator(iam)
    event_id = insert(iam.engine)
    with iam.engine.begin() as c:
        c.execute(
            text("""CREATE FUNCTION wms.reject_replay() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.action='outbox.replay' THEN RAISE EXCEPTION 'fixture'; END IF; RETURN NEW; END $$;
          CREATE TRIGGER reject_replay BEFORE INSERT ON wms.audit_event FOR EACH ROW EXECUTE FUNCTION wms.reject_replay()""")
        )
    assert replay(iam, headers, event_id).status_code == 500
    with iam.engine.connect() as c:
        assert tuple(
            c.execute(
                text("SELECT attempts,version,replay_count FROM wms.outbox_event WHERE id=:id"),
                dict(id=event_id),
            ).one()
        ) == (5, 1, 0)
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.idempotency_record WHERE command='outbox.replay'")
            ).scalar_one()
            == 0
        )


def test_replay_recovery_lookup_ack_and_revoked_grant(iam):
    from packages.contracts.recovery import acknowledgement, request_digest

    _, grant, headers = operator(iam)
    event_id = insert(iam.engine)
    key = uuid4()
    path = f"operations/outbox/{event_id}/replay"
    body = dict(expected_version=1, reason="Operator fixed the delivery cause")
    digest = request_digest("POST", path, body, str(key))
    lookup = {**headers, "X-WMS-Recovery": "lookup-v1"}
    response = replay(iam, lookup, event_id, key=key)
    assert response.json()["code"] == "OPERATION_UNCONFIRMED"
    assert "X-WMS-ACK" not in response.headers
    with iam.engine.connect() as c:
        assert c.execute(text("SELECT replay_count FROM wms.outbox_event WHERE id=:id"),
                         dict(id=event_id)).scalar_one() == 0
    sent = replay(iam, {**headers, "X-WMS-Recovery": "send-v1"}, event_id, key=key)
    result = ok(sent)
    assert sent.headers["X-WMS-ACK"] == acknowledgement(digest, result)
    # Simulate a lost response: lookup recovers the committed ACK without replaying again.
    recovered = replay(iam, lookup, event_id, key=key)
    assert ok(recovered) == result
    assert recovered.headers["X-WMS-ACK"] == sent.headers["X-WMS-ACK"]
    assert ok(replay(iam, {**headers, "X-WMS-Recovery": "send-v1"}, event_id, key=key)) == result
    with iam.engine.begin() as c:
        assert c.execute(text("SELECT replay_count FROM wms.outbox_event WHERE id=:id"),
                         dict(id=event_id)).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='outbox.replay'"))\
            .scalar_one() == 1
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), dict(id=grant))
    denied = replay(iam, lookup, event_id, key=key)
    assert denied.status_code == 403
    assert "X-WMS-ACK" not in denied.headers


def test_metrics_heartbeat_stale_stopped_failed_and_registry_mismatch(iam):
    _, _, headers = operator(iam)
    insert(iam.engine)
    insert(iam.engine, attempts=2)
    insert(iam.engine, event_type="print.requested.v2")
    monitors = []
    for kind in ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup"):
        monitor = WorkerStatus(iam.engine, kind, fingerprint(consumer_factory()))
        monitor.update("IDLE", "OK", completed=True)
        monitors.append(monitor)
    stats = ok(iam.client.get("/api/v1/operations/workers", headers=headers))
    assert stats["ready"] and stats["missing_kinds"] == []
    assert (
        stats["outbox"]["dead_letter"] == 1
        and stats["outbox"]["retry"] == 1
        and stats["outbox"]["unhandled"] == 1
    )
    assert stats["outbox"]["lag_seconds"] >= 300
    monitors[0].update("STOPPED")
    monitors[1].update("FAILED", "WORKER_FAILED")
    with iam.engine.begin() as c:
        c.execute(
            text("UPDATE wms.worker_status SET heartbeat_at=now()-interval '121 seconds' WHERE kind='export'")
        )
        c.execute(
            text("UPDATE wms.worker_status SET registry_hash=:hash WHERE kind='print'"), dict(hash="0" * 64)
        )
    stats = ok(iam.client.get("/api/v1/operations/workers", headers=headers))
    assert not stats["ready"] and set(stats["missing_kinds"]) == {"outbox", "import", "export", "print"}


@pytest.mark.parametrize("kind", ["import", "export", "print"])
def test_default_registry_real_domain_to_result_and_io_retry(request, kind, monkeypatch):
    f = request.getfixturevalue({"import": "imports", "export": "reports", "print": "printing"}[kind])
    app = f.client.app
    if kind == "import":
        job = ok(f.import_create(ok(f.upload(), 201)), 201)
        service = app.state.imports
    elif kind == "export":
        job = ok(export_job(f), 201)
        service = app.state.exports
    else:
        job = ok(print_create(f), 201)
        service = app.state.printing
    registry = consumer_factory()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: OutboxProcessor(PostgresOutboxStore(f.engine), registry).run_batch(), range(2))
        )
    assert sum(x.processed for x in results) == 1
    run = compose(app, kind)
    method = "read" if kind == "import" else "put"
    original = getattr(service.storage, method)

    def failure(*a, **kw):
        raise OSError("secret-do-not-log")

    monkeypatch.setattr(service.storage, method, failure)
    assert run() == "RETRY"
    _, _, headers = operator(f.iam)
    observed = ok(f.client.get("/api/v1/operations/jobs", params=dict(kind=kind), headers=headers))
    observed_job = next(x for x in observed["items"] if x["id"] == job["id"])
    assert observed_job["attempts"] == 1 and observed_job["error_code"] == "EXECUTION_FAILED"
    assert observed_job["task_state"] == "READY"
    monkeypatch.setattr(service.storage, method, original)
    with f.engine.begin() as c:
        c.execute(text(f"UPDATE wms.{kind}_task SET available_at=now()"))
    assert run() == ("VALIDATED" if kind == "import" else "READY")
    assert run() is None
    with f.engine.connect() as c:
        assert c.execute(text(f"SELECT count(*) FROM wms.{kind}_task")).scalar_one() == 1
        status = c.execute(
            text(f"SELECT status FROM wms.{kind}_job WHERE id=:id"), dict(id=job["id"])
        ).scalar_one()
        assert status == ("VALIDATED" if kind == "import" else "READY")
    if kind != "import":
        prefix = "exports" if kind == "export" else "printing"
        response = f.client.get(f"/api/v1/{prefix}/{job['id']}/download", headers=f.headers["buyer"])
        assert response.status_code == 200 and response.content


@pytest.mark.parametrize("kind", ["export", "print"])
def test_bounded_retention_preserves_pending_running_history_and_dedup(request, kind):
    f = request.getfixturevalue("reports" if kind == "export" else "printing")
    job = ok(export_job(f) if kind == "export" else print_create(f), 201)
    executor = f.exporter if kind == "export" else f.printer
    OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch()
    f.iam.advance(3601)
    clean = compose(f.client.app, kind + "-cleanup")
    assert clean()["files"] == 0
    with f.engine.connect() as c:
        assert (
            c.execute(
                text(f"SELECT status FROM wms.{kind}_job WHERE id=:id"), dict(id=job["id"])
            ).scalar_one()
            == "QUEUED"
        )
    task = executor.claim()
    assert clean()["files"] == 0
    # Expired business authorization causes terminal failure; only then clean the derived data.
    assert executor.execute(task) == "FAILED"
    clean()
    with f.engine.connect() as c:
        assert (
            c.execute(
                text(f"SELECT status FROM wms.{kind}_job WHERE id=:id"), dict(id=job["id"])
            ).scalar_one()
            == "CANCELLED"
        )
        assert c.execute(text("SELECT count(*) FROM wms.consumer_receipt")).scalar_one() == 1
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.audit_event WHERE entity_id=:id"), dict(id=job["id"])
            ).scalar_one()
            >= 1
        )
        assert c.execute(text(f"SELECT count(*) FROM wms.{kind}_task")).scalar_one() == 1
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE aggregate_id=:id"), dict(id=job["id"])
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("baseline", [10, 23])
def test_operations_upgrade_backfills_without_changing_delivery_history(
    empty_database, monkeypatch, baseline
):
    from apps.server.infrastructure import migrations

    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:baseline])
        migrations.migrate(empty_database)
    event_id = insert(empty_database, processed=True)
    receipt = uuid4()
    with empty_database.begin() as c:
        c.execute(
            text("INSERT INTO wms.consumer_receipt VALUES (:id,:event,'export.enqueue.v1',now())"),
            dict(id=receipt, event=event_id),
        )
    migrations.migrate(empty_database)
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as c:
        assert tuple(
            c.execute(
                text("SELECT attempts,version,replay_count FROM wms.outbox_event WHERE id=:id"),
                dict(id=event_id),
            ).one()
        ) == (5, 1, 0)
        assert (
            c.execute(
                text("SELECT id FROM wms.consumer_receipt WHERE event_id=:id"), dict(id=event_id)
            ).scalar_one()
            == receipt
        )


def test_cli_default_registry_check_and_graceful_shutdown(database, tmp_path):
    env = {
        **os.environ,
        "WMS_DATABASE_URL": database.url.render_as_string(hide_password=False),
        "PYTHONPATH": os.getcwd(),
    }
    for kind in ("IMPORT", "EXPORT", "PRINT"):
        env[f"WMS_{kind}_STORAGE_ROOT"] = str(tmp_path / kind)
    checked = subprocess.run(
        [sys.executable, "-m", "apps.server.worker", "--check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["ready"]
    for module in ("worker", "import_worker", "export_worker", "print_worker"):
        with (tmp_path / (module + ".log")).open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "apps.server." + module], env=env, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    with database.connect() as c:
                        active = c.execute(
                            text("SELECT count(*) FROM wms.worker_status WHERE state='IDLE'")
                        ).scalar_one()
                    if active:
                        break
                    assert process.poll() is None
                    time.sleep(0.05)
                assert active
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) == 0
                with database.connect() as c:
                    assert (
                        c.execute(
                            text("SELECT count(*) FROM wms.worker_status WHERE state NOT IN ('STOPPED')")
                        ).scalar_one()
                        == 0
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)


@pytest.mark.parametrize("kind", ["export", "print"])
def test_cleanup_batch_bound_and_orphan_reference_protection(request, kind):
    from apps.server.application.export_retention import cleanup as export_cleanup
    from apps.server.application.print_retention import cleanup as print_cleanup

    f = request.getfixturevalue("reports" if kind == "export" else "printing")
    ok(export_job(f) if kind == "export" else print_create(f), 201)
    OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch()
    assert compose(f.client.app, kind)() == "READY"
    service = f.client.app.state.exports if kind == "export" else f.client.app.state.printing
    cleanup = export_cleanup if kind == "export" else print_cleanup
    referenced = set(service.storage.root.iterdir())
    old = time.time() - 90000
    for path in referenced:
        os.utime(path, (old, old))
    for n in range(3):
        path = service.storage.root / (str(n) * 64)
        path.write_bytes(b"orphan")
        os.utime(path, (old, old))
    for remaining in (2, 1, 0):
        result = cleanup(service, batch_size=1)
        assert result["orphans"] == 1 and result["files"] == 0
        assert len(set(service.storage.root.iterdir()) - referenced) == remaining
        assert all(p.exists() for p in referenced)
    assert cleanup(service, batch_size=1)["orphans"] == 0
    with pytest.raises(ValueError):
        cleanup(service, batch_size=0)
