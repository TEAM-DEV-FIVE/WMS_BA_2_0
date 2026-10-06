"""Closed-loop 15-session load driver; reports measurements, never an invented SLA."""

import math
import os
import platform
import random
import ssl
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import event, text


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def measure(server, admin, actors, *, warmup, duration, seed, think_seconds):
    barrier = threading.Barrier(len(actors) + 1)
    guard = threading.Lock()
    stop = threading.Event()
    events = Counter()
    samples = []
    monitor_errors = []
    pg_pids = set()
    schedule = {}

    def commit(c):
        with guard:
            events["transactions_committed"] += 1

    def rollback(c):
        with guard:
            events["transactions_rolled_back"] += 1

    def checkout(connection, record, proxy):
        with guard:
            pg_pids.add(connection.info.backend_pid)

    def error(context):
        with guard:
            events["sqlstate_" + str(getattr(context.original_exception, "sqlstate", "unknown"))] += 1

    listeners = [("commit", commit), ("rollback", rollback), ("checkout", checkout), ("handle_error", error)]
    for name, handler in listeners:
        event.listen(server["engine"], name, handler)

    def monitor():
        try:
            while not stop.is_set():
                with admin.connect() as c:
                    row = c.execute(
                        text(
                            "SELECT count(*) FILTER(WHERE state='active') AS active, count(*) FILTER(WHERE wait_event_type='Lock') AS locks FROM pg_stat_activity WHERE datname=current_database() AND usename=:role"
                        ),
                        {"role": server["engine"].url.username},
                    ).one()
                    pending = c.execute(
                        text(
                            "SELECT count(*) FROM pg_locks WHERE database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND NOT granted"
                        )
                    ).scalar_one()
                samples.append(
                    dict(t=time.monotonic(), active=row.active, lock_waiters=row.locks, ungranted=pending)
                )
                stop.wait(0.05)
        except Exception as exc:
            monitor_errors.append(type(exc).__name__)

    def actor(index, data):
        randomizer = random.Random(seed + index)
        headers = data["headers"]
        version = data["version"]
        rows = []
        writes = 0
        client_retries = 0
        with httpx.Client(
            base_url=server["url"] + "/",
            verify=ssl.create_default_context(cafile=server["ca"]),
            trust_env=False,
            timeout=15,
        ) as client:
            barrier.wait(30)
            while time.monotonic() < schedule["end"]:
                choice = randomizer.randrange(100)
                if choice < 40:
                    label = "receipt_list"
                    method, path, body = "GET", f"receipts?warehouse_id={data['warehouse']}&limit=50", None
                elif choice < 70:
                    label = "receipt_read"
                    method, path, body = "GET", f"receipts/{data['id']}", None
                else:
                    label = "receipt_post"
                    method, path = "POST", f"receipts/{data['id']}/post"
                    body = dict(
                        expected_version=version,
                        execution_key=str(uuid4()),
                        reason="B24 measured receipt",
                        lines=[dict(document_line_id=data["line"], quantity_base="1")],
                    )
                key = str(uuid4())
                request_headers = {**headers, "Idempotency-Key": key}
                start = time.monotonic()
                response = client.request(method, path, headers=request_headers, json=body)
                if response.status_code == 503 and response.json().get("code") == "DATABASE_BUSY":
                    client_retries += 1
                    response = client.request(method, path, headers=request_headers, json=body)
                elapsed = time.monotonic() - start
                record = dict(
                    operation=label,
                    status=response.status_code,
                    seconds=elapsed,
                    phase="measured" if start >= schedule["measure"] else "warmup",
                )
                if not response.is_success:
                    record["code"] = response.json().get("code", "INVALID_RESPONSE")
                elif label == "receipt_post":
                    version = response.json()["version"]
                    writes += 1
                    # A bounded lost-ACK analogue: repeat exact key/payload, require identical ACK.
                    if writes % 10 == 0:
                        retry_start = time.monotonic()
                        replay = client.post(path, headers=request_headers, json=body)
                        assert replay.status_code == 200 and replay.json() == response.json()
                        rows.append(
                            dict(
                                operation="same_key_replay",
                                status=replay.status_code,
                                seconds=time.monotonic() - retry_start,
                                phase=record["phase"],
                            )
                        )
                rows.append(record)
                time.sleep(think_seconds)
        return dict(rows=rows, writes=writes, client_retries=client_retries)

    with admin.connect() as c:
        before = c.execute(
            text("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()")
        ).scalar_one()
    observer = threading.Thread(target=monitor, daemon=True)
    observer.start()
    start_cpu = time.process_time()
    try:
        with ThreadPoolExecutor(max_workers=len(actors)) as pool:
            futures = [pool.submit(actor, i, d) for i, d in enumerate(actors)]
            start = time.monotonic()
            schedule.update(measure=start + warmup, end=start + warmup + duration)
            barrier.wait(30)
            results = [f.result(timeout=warmup + duration + 60) for f in futures]
        finish = time.monotonic()
    finally:
        stop.set()
        observer.join(10)
        for name, handler in listeners:
            event.remove(server["engine"], name, handler)
    with admin.connect() as c:
        c.exec_driver_sql("SELECT pg_stat_clear_snapshot()")
        after = c.execute(
            text("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()")
        ).scalar_one()
        pg = c.exec_driver_sql("SHOW server_version").scalar_one()
        pg_settings = {
            name: c.exec_driver_sql("SHOW " + name).scalar_one()
            for name in (
                "max_connections",
                "shared_buffers",
                "work_mem",
                "fsync",
                "synchronous_commit",
                "max_wal_size",
            )
        }
    rows = [row for r in results for row in r["rows"] if row["phase"] == "measured"]
    operations = {}
    for name in sorted({r["operation"] for r in rows}):
        group = [r for r in rows if r["operation"] == name]
        values = [r["seconds"] for r in group]
        operations[name] = dict(
            count=len(group),
            p50_seconds=percentile(values, 0.5),
            p95_seconds=percentile(values, 0.95),
            p99_seconds=percentile(values, 0.99),
            max_seconds=max(values),
        )
    observed = [s for s in samples if s["t"] >= schedule["measure"]]
    assert not observer.is_alive() and not monitor_errors and observed, monitor_errors
    assert all(r["writes"] > 0 for r in results), "Every session must perform real posting"
    return dict(
        schema=1,
        kind="synthetic-local-15ccu",
        seed=seed,
        ccu=len(actors),
        session_posts_including_warmup=[r["writes"] for r in results],
        pool_size=3,
        warmup_seconds=warmup,
        configured_duration_seconds=duration,
        observed_duration_seconds=finish - schedule["measure"],
        completed_requests=len(rows),
        throughput_requests_per_second=len(rows) / (finish - schedule["measure"]),
        operations=operations,
        statuses=dict(Counter(str(r["status"]) for r in rows)),
        failures=[r for r in rows if r["status"] >= 400],
        warmup_failures=[
            row for r in results for row in r["rows"] if row["phase"] == "warmup" and row["status"] >= 400
        ],
        successful_posts_including_warmup=sum(r["writes"] for r in results),
        client_database_busy_retries=sum(r["client_retries"] for r in results),
        runtime_db_backend_pids=sorted(pg_pids),
        transactions_and_sqlstates_including_warmup=dict(events),
        database_deadlocks_delta=after - before,
        lock_samples=len(observed),
        samples_with_lock_waiters=sum(s["lock_waiters"] > 0 for s in observed),
        max_lock_waiters=max((s["lock_waiters"] for s in observed), default=0),
        max_ungranted_locks=max((s["ungranted"] for s in observed), default=0),
        process_cpu_seconds=time.process_time() - start_cpu,
        host_cpu_count=os.cpu_count(),
        os=platform.platform(),
        postgres=pg,
        postgres_settings=pg_settings,
        nginx=server["nginx"],
        cpu_model=next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        ),
        python=platform.python_version(),
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        limitations=[
            "closed-loop synthetic mix; not Q05/Q07 business acceptance",
            "API latency is not 15-minute document process time",
            "lock counters are sampled, not every lock wait",
            "CPU covers Python driver/API process, not PostgreSQL or Nginx",
        ],
    )
