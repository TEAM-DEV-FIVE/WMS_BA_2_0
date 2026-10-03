import json
import os
import select
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import text

from apps.server import worker
from apps.server.application.commands import CommandBus, CommandResult
from apps.server.application.outbox import (
    BatchResult,
    Consumer,
    ConsumerRegistry,
    Delivery,
    DeliveryState,
    HandlerResult,
    OutboxProcessor,
    RetryPolicy,
)
from apps.server.infrastructure.database import PostgresUnitOfWork
from apps.server.infrastructure.outbox import PostgresOutboxStore

EVENT_TYPE = "fixture.created.v1"
SECRET = "password=do-not-store-this-secret"


@pytest.fixture
def outbox(database):
    # Intentionally no UNIQUE constraint on the effects: the worker must dedup.
    with database.begin() as connection:
        connection.execute(text("""CREATE TABLE wms.outbox_test_effect (
            event_id uuid NOT NULL, consumer text NOT NULL, value jsonb NOT NULL)"""))

    class Fixture:
        engine = database

        def insert(self, *, event_type=EVENT_TYPE, delay=0, processed=False, attempts=0, payload=None):
            event_id = uuid4()
            with database.begin() as connection:
                connection.execute(text("""INSERT INTO wms.outbox_event
                    (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts,processed_at)
                    VALUES (:id,:type,:aggregate,CAST(:payload AS jsonb),clock_timestamp(),
                            clock_timestamp() + :delay * interval '1 second',:attempts,:processed)"""),
                    {"id": event_id, "type": event_type, "aggregate": uuid4(),
                     "payload": json.dumps(payload or {"quantity": "2"}), "delay": delay, "attempts": attempts,
                     "processed": datetime.now(UTC) if processed else None})
            return event_id

        def row(self, event_id):
            with database.connect() as connection:
                return dict(connection.execute(text("SELECT * FROM wms.outbox_event WHERE id=:id"),
                                               {"id": event_id}).mappings().one())

        def ready(self, event_id):
            with database.begin() as connection:
                connection.execute(text("UPDATE wms.outbox_event SET available_at=now() WHERE id=:id"),
                                   {"id": event_id})

        def effects(self):
            with database.connect() as connection:
                return connection.execute(text("SELECT event_id,consumer FROM wms.outbox_test_effect")).all()

        def receipts(self):
            with database.connect() as connection:
                return connection.execute(text("SELECT event_id,consumer FROM wms.consumer_receipt")).all()

        def consumer(self, name="projection", event_type=EVENT_TYPE):
            def handle(connection, event):
                connection.execute(text("""INSERT INTO wms.outbox_test_effect VALUES
                    (:event,:consumer,CAST(:payload AS jsonb))"""),
                    {"event": event.id, "consumer": name, "payload": json.dumps(event.payload)})
                return HandlerResult.APPLIED
            return Consumer(name, event_type, handle)

        def processor(self, *consumers, batch_size=100, retry=None, store=None):
            return OutboxProcessor(store or PostgresOutboxStore(database), ConsumerRegistry(consumers),
                                   batch_size=batch_size, retry=retry)

    return Fixture()


def test_registry_requires_explicit_version_unique_subscription_and_callable():
    def handler(connection, event):
        return HandlerResult.APPLIED
    first = Consumer("a", EVENT_TYPE, handler)
    second = Consumer("b", EVENT_TYPE, handler)
    registry = ConsumerRegistry([second, first, Consumer("a", "fixture.updated.v1", handler)])
    assert registry.consumers_for(EVENT_TYPE) == (first, second)
    assert registry.consumers_for("unknown.v1") == ()
    with pytest.raises(ValueError, match="Duplicate"):
        ConsumerRegistry([first, first])
    for name, event_type, handle in [("bad name", EVENT_TYPE, handler), ("a", "unversioned", handler),
                                     ("a", EVENT_TYPE, None), ("a", "x" * 100 + ".v1", handler)]:
        with pytest.raises(ValueError):
            Consumer(name, event_type, handle)


def test_retry_and_batch_bounds():
    policy = RetryPolicy(5, 3, 10)
    assert [policy.delay_seconds(i) for i in range(1, 6)] == [3, 6, 10, 10, 10]
    for args in [(0, 1, 1), (101, 1, 1), (3, 0, 1), (3, 10, 5), (3, 1, 86401)]:
        with pytest.raises(ValueError):
            RetryPolicy(*args)
    with pytest.raises(ValueError):
        policy.delay_seconds(0)
    for size in (0, 1001):
        with pytest.raises(ValueError):
            OutboxProcessor(None, ConsumerRegistry(), batch_size=size)
    assert OutboxProcessor(None, ConsumerRegistry()).run_batch() == BatchResult()


@pytest.mark.parametrize("settings", [
    {"batch_size": 0}, {"batch_size": 1001}, {"max_attempts": 0},
    {"poll_seconds": 0}, {"poll_seconds": float("nan")}, {"poll_seconds": float("inf")},
    {"backoff_base_seconds": 20, "backoff_max_seconds": 10},
])
def test_invalid_worker_settings(settings):
    with pytest.raises(ValidationError):
        worker.WorkerSettings(**settings)


def test_factory_empty_unknown_invalid_and_configuration_logs_are_redacted(monkeypatch, caplog):
    monkeypatch.setattr(worker, "empty_registry", lambda: ConsumerRegistry(), raising=False)
    for path in (None, "not:a:factory", "missing_package:factory", "apps.server.worker:empty_registry"):
        with pytest.raises((ValueError, ModuleNotFoundError)):
            worker.load_registry(path)
    monkeypatch.setenv("WMS_DATABASE_URL", SECRET)
    assert worker.main(["--once"]) == 2
    assert SECRET not in caplog.text
    assert "outbox_configuration_invalid" in caplog.text


def test_batch_excludes_previous_events_and_stops_before_next_claim():
    stop = Event()
    event_id = uuid4()

    class Store:
        def deliver_one(self, registry, retry, exclude):
            if not exclude:
                return Delivery(event_id, DeliveryState.RETRY)
            assert exclude == (event_id,)
            stop.set()
            return Delivery(uuid4(), DeliveryState.PROCESSED)

    registry = ConsumerRegistry([Consumer("a", EVENT_TYPE, lambda c, e: None)])
    processor = OutboxProcessor(Store(), registry)
    assert processor.run_batch(stop.is_set) == BatchResult(attempted=2, retry=1, processed=1)
    assert processor.run_batch(stop.is_set) == BatchResult()


def test_signal_handler_sets_stop_and_restores_previous_handlers():
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    stop = Event()
    with worker.stop_signals(stop):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert stop.is_set()
    assert {s: signal.getsignal(s) for s in before} == before


def test_idle_loop_uses_interruptible_wait():
    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, timeout):
            assert timeout == 60
            self.stopped = True

    class Processor:
        batch_size = 10

        def run_batch(self, should_stop):
            return BatchResult()

    assert worker.run_worker(Processor(), once=False, poll_seconds=60, stop=Stop()) == 0


@pytest.mark.integration
def test_due_processed_unknown_and_exhausted_events_are_not_claimed(outbox):
    unknown = outbox.insert(event_type="unhandled.v1", delay=-60)
    future = outbox.insert(delay=3600)
    processed = outbox.insert(processed=True)
    exhausted = outbox.insert(attempts=5)
    due = outbox.insert()
    unchanged = {i: outbox.row(i) for i in (unknown, future, processed, exhausted)}
    processor = outbox.processor(outbox.consumer())
    assert processor.run_batch() == BatchResult(attempted=1, processed=1)
    assert outbox.effects() == [(due, "projection")]
    assert outbox.receipts() == [(due, "projection")]
    assert outbox.row(due)["attempts"] == 1
    assert outbox.row(due)["processed_at"] is not None
    assert all(outbox.row(i) == row for i, row in unchanged.items())
    assert processor.run_batch() == BatchResult()


@pytest.mark.integration
def test_unknown_event_can_be_processed_after_registering_its_version(outbox):
    event_id = outbox.insert(event_type="new.event.v2")
    assert outbox.processor(outbox.consumer()).run_batch() == BatchResult()
    assert outbox.row(event_id)["attempts"] == 0
    assert outbox.processor(outbox.consumer(event_type="new.event.v2")).run_batch().processed == 1


@pytest.mark.integration
def test_two_workers_skip_locked_row_and_commit_one_effect_each(outbox):
    first = outbox.insert(delay=-20)
    second = outbox.insert(delay=-10)
    entered, release = Event(), Event()
    effect = outbox.consumer()

    def slow(connection, event):
        if event.id == first:
            entered.set()
            assert release.wait(10)
        return effect.handle(connection, event)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(outbox.processor(Consumer("projection", EVENT_TYPE, slow), batch_size=1).run_batch)
        try:
            assert entered.wait(5)
            other = pool.submit(outbox.processor(effect, batch_size=1).run_batch)
            assert other.result(timeout=5).processed == 1
            assert outbox.effects() == [(second, "projection")]
            assert outbox.processor(effect).run_batch() == BatchResult()
        finally:
            release.set()
        assert future.result(timeout=5).processed == 1
    assert sorted(outbox.effects()) == sorted([(first, "projection"), (second, "projection")])
    assert sorted(outbox.receipts()) == sorted(outbox.effects())
    assert outbox.processor(effect).run_batch() == BatchResult()


@pytest.mark.integration
def test_batch_limit_commits_individual_events(outbox):
    for _ in range(5):
        outbox.insert()
    processor = outbox.processor(outbox.consumer(), batch_size=2)
    assert [processor.run_batch().processed for _ in range(4)] == [2, 2, 1, 0]


@pytest.mark.integration
def test_failure_rolls_back_all_consumers_and_preserves_original_audit_outbox(outbox, actor, caplog):
    aggregate, event_id, audit_id = uuid4(), uuid4(), uuid4()
    bus = CommandBus(lambda: PostgresUnitOfWork(outbox.engine))

    def produce(uow):
        uow.connection.execute(text("""INSERT INTO wms.audit_event
            (id,actor_id,action,entity_type,entity_id,request_id,occurred_at)
            VALUES (:id,:actor,'fixture.commit','organization',:entity,:request,now())"""),
            {"id": audit_id, "actor": actor, "entity": aggregate, "request": uuid4()})
        uow.connection.execute(text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,:type,:aggregate,'{"safe":"original"}',now(),now(),0)"""),
            {"id": event_id, "type": EVENT_TYPE, "aggregate": aggregate})
        return CommandResult({"id": str(aggregate)})

    bus.execute(actor_id=actor, key=uuid4(), command="fixture.commit", resource_id=aggregate,
                payload={}, authorize=lambda uow: None, handle=produce)
    original = outbox.row(event_id)
    with outbox.engine.connect() as connection:
        audit = connection.execute(text("SELECT * FROM wms.audit_event")).all()
        commands = connection.execute(text("SELECT * FROM wms.idempotency_record")).all()
    good = outbox.consumer("a")

    def broken(connection, event):
        good.handle(connection, event)
        raise RuntimeError(SECRET)

    result = outbox.processor(good, Consumer("b", EVENT_TYPE, broken)).run_batch()
    assert result == BatchResult(attempted=1, retry=1)
    row = outbox.row(event_id)
    assert row["attempts"] == 1 and row["processed_at"] is None
    assert row["last_error"] == "DELIVERY_FAILED"
    for key in ("id", "event_type", "aggregate_id", "payload", "occurred_at"):
        assert row[key] == original[key]
    assert outbox.effects() == outbox.receipts() == []
    assert SECRET not in caplog.text
    with outbox.engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM wms.audit_event")).all() == audit
        assert connection.execute(text("SELECT * FROM wms.idempotency_record")).all() == commands
    outbox.ready(event_id)
    assert outbox.processor(good, outbox.consumer("b")).run_batch().processed == 1
    assert sorted(outbox.effects()) == [(event_id, "a"), (event_id, "b")]
    assert outbox.row(event_id)["last_error"] is None


@pytest.mark.integration
def test_sql_error_rollback_savepoint_retry_budget_and_capped_backoff(outbox):
    event_id = outbox.insert()

    def invalid_sql(connection, event):
        connection.execute(text("INSERT INTO wms.outbox_test_effect VALUES (NULL,'bad','{}')"))

    processor = outbox.processor(Consumer("failing", EVENT_TYPE, invalid_sql), retry=RetryPolicy(3, 3, 5))
    for attempt, delay in [(1, 3), (2, 5), (3, 5)]:
        before = datetime.now(UTC)
        result = processor.run_batch()
        after = datetime.now(UTC)
        row = outbox.row(event_id)
        assert row["attempts"] == attempt
        assert before + timedelta(seconds=delay) <= row["available_at"] <= after + timedelta(seconds=delay)
        assert row["processed_at"] is None and row["last_error"] == "DELIVERY_FAILED"
        assert (result.retry, result.exhausted) == ((1, 0) if attempt < 3 else (0, 1))
        assert processor.run_batch() == BatchResult()
        outbox.ready(event_id)
    assert processor.run_batch() == BatchResult()  # exhausted even when due
    assert outbox.effects() == outbox.receipts() == []


@pytest.mark.integration
def test_noop_return_does_not_acknowledge_or_keep_effect(outbox):
    event_id = outbox.insert()
    effect = outbox.consumer()

    def forgot_return(connection, event):
        effect.handle(connection, event)

    assert outbox.processor(Consumer("noop", EVENT_TYPE, forgot_return)).run_batch().retry == 1
    assert outbox.effects() == outbox.receipts() == []
    assert outbox.row(event_id)["last_error"] == "HANDLER_NOT_APPLIED"
    assert outbox.row(event_id)["processed_at"] is None


@pytest.mark.integration
@pytest.mark.parametrize("crash_point", ["receipt", "ack", "after_ack"])
def test_crash_between_effect_receipt_and_ack_rolls_back_then_restarts(outbox, crash_point):
    class Crash(BaseException):
        pass

    class CrashingStore(PostgresOutboxStore):
        def _record_receipt(self, connection, event_id, consumer):
            if crash_point == "receipt":
                raise Crash()
            super()._record_receipt(connection, event_id, consumer)

        def _acknowledge(self, connection, event_id, attempt):
            if crash_point == "after_ack":
                super()._acknowledge(connection, event_id, attempt)
            raise Crash()

    event_id = outbox.insert()
    with pytest.raises(Crash):
        outbox.processor(outbox.consumer(), store=CrashingStore(outbox.engine)).run_batch()
    assert outbox.effects() == outbox.receipts() == []
    assert outbox.row(event_id)["attempts"] == 0
    assert outbox.row(event_id)["processed_at"] is None
    assert outbox.processor(outbox.consumer()).run_batch().processed == 1
    assert outbox.effects() == outbox.receipts() == [(event_id, "projection")]


@pytest.mark.integration
def test_lock_survives_handler_savepoint_rollback_until_retry_is_committed(outbox):
    event_id = outbox.insert()
    rolled_back, release = Event(), Event()

    def pause_after_rollback(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("ROLLBACK TO SAVEPOINT"):
            rolled_back.set()
            assert release.wait(10)

    def fail(connection, event):
        outbox.consumer().handle(connection, event)
        raise ValueError(SECRET)

    sqlalchemy_event.listen(outbox.engine, "after_cursor_execute", pause_after_rollback)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(outbox.processor(Consumer("projection", EVENT_TYPE, fail)).run_batch)
            try:
                assert rolled_back.wait(5)
                other = pool.submit(outbox.processor(outbox.consumer()).run_batch)
                assert other.result(timeout=5) == BatchResult()
            finally:
                release.set()
            assert future.result(timeout=5).retry == 1
    finally:
        sqlalchemy_event.remove(outbox.engine, "after_cursor_execute", pause_after_rollback)
    assert outbox.row(event_id)["attempts"] == 1
    assert outbox.effects() == outbox.receipts() == []


@pytest.mark.integration
def test_committed_receipt_skips_existing_effect_but_waits_for_all_consumers(outbox):
    event_id = outbox.insert()
    a, b = outbox.consumer("a"), outbox.consumer("b")
    assert outbox.processor(a).run_batch().processed == 1
    # Explicit operational replay preserves the previous receipt and its effect.
    with outbox.engine.begin() as connection:
        connection.execute(text("UPDATE wms.outbox_event SET processed_at=NULL WHERE id=:id"), {"id": event_id})
    assert outbox.processor(a, b).run_batch().processed == 1
    assert sorted(outbox.effects()) == [(event_id, "a"), (event_id, "b")]
    assert sorted(outbox.receipts()) == sorted(outbox.effects())
    with outbox.engine.begin() as connection:
        connection.execute(text("UPDATE wms.outbox_event SET processed_at=NULL WHERE id=:id"), {"id": event_id})
    assert outbox.processor(a, b).run_batch().processed == 1
    assert len(outbox.effects()) == 2


@pytest.mark.integration
def test_consumers_receive_independent_payloads(outbox):
    event_id = outbox.insert(payload={"items": ["original"]})

    def mutating(connection, event):
        event.payload["items"].append("changed")
        return outbox.consumer("a").handle(connection, event)

    assert outbox.processor(Consumer("a", EVENT_TYPE, mutating), outbox.consumer("b")).run_batch().processed == 1
    with outbox.engine.connect() as connection:
        values = dict(connection.execute(text("SELECT consumer,value FROM wms.outbox_test_effect")).all())
    assert values == {"a": {"items": ["original", "changed"]}, "b": {"items": ["original"]}}
    assert outbox.row(event_id)["payload"] == {"items": ["original"]}


@pytest.fixture
def worker_process(outbox, tmp_path):
    module = tmp_path / "outbox_test_factory.py"
    module.write_text('''from sqlalchemy import text
from apps.server.application.outbox import Consumer, ConsumerRegistry, HandlerResult

def handle(connection, event):
    connection.execute(text("INSERT INTO wms.outbox_test_effect VALUES (:id,'subprocess','{}')"), {"id": event.id})
    if event.payload.get("fail"):
        raise RuntimeError("password=do-not-store-this-secret")
    if event.payload.get("sleep"):
        connection.execute(text("SELECT pg_sleep(2) /* outbox_test_in_handler */"))
    return HandlerResult.APPLIED

def registry():
    return ConsumerRegistry([Consumer("subprocess", "fixture.created.v1", handle)])
''', encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("WMS_")}
    environment.update(
        PYTHONPATH=os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[2])]),
        WMS_DATABASE_URL=outbox.engine.url.render_as_string(hide_password=False),
        WMS_OUTBOX_CONSUMER_FACTORY="outbox_test_factory:registry",
        WMS_OUTBOX_BATCH_SIZE="1", WMS_OUTBOX_POLL_SECONDS="60",
    )
    processes = []

    def launch(*args):
        process = subprocess.Popen([sys.executable, "-m", "apps.server.worker", *args], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(process)
        return process

    yield launch
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def wait_for_handler(outbox, process):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        assert process.poll() is None
        with outbox.engine.connect() as connection:
            count = connection.execute(text("""SELECT count(*) FROM pg_stat_activity
                WHERE datname=current_database() AND pid<>pg_backend_pid()
                  AND state='active' AND query LIKE '%outbox_test_in_handler%'""")).scalar_one()
        if count:
            return
        time.sleep(0.02)
    pytest.fail("Worker never entered DB handler")


@pytest.mark.integration
def test_cli_once_limits_batch_and_reports_failure_without_secrets(outbox, worker_process):
    first, second = outbox.insert(delay=-20), outbox.insert(delay=-10)
    process = worker_process("--once")
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert '"processed": 1' in stderr
    assert outbox.effects() == [(first, "subprocess")]
    assert outbox.row(second)["processed_at"] is None
    process = worker_process("--once")
    process.communicate(timeout=10)
    assert process.returncode == 0
    failed = outbox.insert(payload={"fail": True})
    process = worker_process("--once")
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 1
    assert SECRET not in stdout + stderr
    assert outbox.row(failed)["processed_at"] is None
    assert outbox.row(failed)["last_error"] == "DELIVERY_FAILED"


@pytest.mark.integration
def test_sigterm_finishes_current_transaction_without_claiming_next(outbox, worker_process):
    first = outbox.insert(delay=-20, payload={"sleep": True})
    second = outbox.insert(delay=-10)
    process = worker_process()
    wait_for_handler(outbox, process)
    process.terminate()
    _, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert outbox.effects() == outbox.receipts() == [(first, "subprocess")]
    assert outbox.row(second)["attempts"] == 0


@pytest.mark.integration
def test_sigkill_rolls_back_effect_and_restart_delivers_once(outbox, worker_process):
    event_id = outbox.insert(payload={"sleep": True})
    process = worker_process("--once")
    wait_for_handler(outbox, process)
    process.kill()
    process.communicate(timeout=10)
    assert process.returncode == -signal.SIGKILL
    # PostgreSQL may only notice the dead client after its current query ends.
    deadline = time.monotonic() + 8
    while True:
        with outbox.engine.begin() as connection:
            released = connection.execute(text("""SELECT id FROM wms.outbox_event
                WHERE id=:id FOR UPDATE SKIP LOCKED"""), {"id": event_id}).scalar_one_or_none()
        if released is not None:
            break
        assert time.monotonic() < deadline, "Dead worker's connection did not release its lock"
        time.sleep(0.02)
    assert outbox.effects() == outbox.receipts() == []
    assert outbox.row(event_id)["attempts"] == 0
    restart = worker_process("--once")
    _, stderr = restart.communicate(timeout=15)
    assert restart.returncode == 0, stderr
    assert outbox.effects() == outbox.receipts() == [(event_id, "subprocess")]


@pytest.mark.integration
def test_sigterm_interrupts_idle_poll_wait(outbox, worker_process):
    process = worker_process()
    assert select.select([process.stderr], [], [], 8)[0]
    assert "outbox_batch" in process.stderr.readline()
    started = time.monotonic()
    process.terminate()
    process.communicate(timeout=3)
    assert process.returncode == 0
    assert time.monotonic() - started < 3  # configured poll interval is 60 seconds


def test_database_failure_disposes_engine_and_redacts_logs(monkeypatch, caplog):
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setenv("WMS_DATABASE_URL", "postgresql+psycopg://localhost/unused")
    monkeypatch.setattr(worker, "load_registry", lambda path: ConsumerRegistry())
    monkeypatch.setattr(worker, "make_engine", lambda settings: engine)

    def failure(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(worker, "run_worker", failure)
    assert worker.main(["--once"]) == 1
    assert engine.disposed
    assert SECRET not in caplog.text
    assert "outbox_worker_failed" in caplog.text
