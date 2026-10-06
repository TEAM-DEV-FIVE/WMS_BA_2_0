"""Disposable B24 TLS/process probes. Never accepts a production database."""

import json
import multiprocessing as mp
import os
import secrets
import signal
import socket
import ssl
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from psycopg import sql
from sqlalchemy import create_engine, event, text

from apps.server.api.app import create_app
from deploy.lan.tests.test_proxy import certificate
from scripts.lan_probe import probe

ROOT = Path(__file__).resolve().parents[1]


def reconcile(engine):
    """One read-only repeatable snapshot; SQL derives quantities from immutable ledger."""
    result = {}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        c.exec_driver_sql("SET TRANSACTION READ ONLY")
        for name in (
            "reconcile.sql",
            "reconcile_ownership.sql",
            "reconcile_fulfillment.sql",
            "reconcile_transfers.sql",
            "reconcile_b24.sql",
        ):
            with c.connection.driver_connection.cursor() as cur:
                cur.execute((ROOT / "02_CSDL" / name).read_text())
                index = 0
                while True:
                    if cur.description:
                        rows = cur.fetchall()
                        result[f"{name}:{index}"] = len(rows)
                        index += 1
                    if not cur.nextset():
                        break
    assert not any(result.values()), result
    return result


@contextmanager
def runtime(engine):
    if not engine.url.database.startswith("wms_test_"):
        raise ValueError("Only disposable wms_test_* databases are permitted")
    role = "b24_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    with engine.begin() as c:
        c.connection.driver_connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        c.exec_driver_sql(f'REVOKE CREATE ON DATABASE "{engine.url.database}" FROM PUBLIC')
        c.exec_driver_sql(
            (ROOT / "deploy/lan/postgresql/runtime-grants.sql")
            .read_text()
            .replace("wms_app", role)
            .replace("BEGIN;", "")
            .replace("COMMIT;", "")
        )
    app_engine = create_engine(
        engine.url.set(username=role, password=password),
        pool_size=3,
        max_overflow=0,
        pool_timeout=10,
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=10000"},
    )
    try:
        with app_engine.connect() as c:
            assert c.execute(text("SELECT current_user")).scalar_one() == role
            assert not c.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            ).scalar_one()
        yield app_engine
    finally:
        app_engine.dispose()
        with engine.begin() as c:
            c.exec_driver_sql(f'DROP OWNED BY "{role}"')
            c.exec_driver_sql(f'DROP ROLE "{role}"')


@contextmanager
def tls_server(iam, directory):
    import shutil

    binary = os.environ.get("WMS_TEST_NGINX_BINARY") or shutil.which("nginx")
    assert binary, "B24 requires real nginx; install it or set WMS_TEST_NGINX_BINARY"
    directory.mkdir(parents=True, exist_ok=True)
    ca = certificate(directory, "ca")
    cert = certificate(directory, "server", ca=ca)
    with runtime(iam.engine) as app_engine:
        app = create_app(iam.service.settings, engine=app_engine)
        app.state.identity.clock = lambda: iam.now
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        with socket.socket() as pick:
            pick.bind(("127.0.0.1", 0))
            port = pick.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        template = (ROOT / "deploy/lan/nginx/wms.conf.example").read_text()
        template = (
            template.replace("listen 443 ssl", f"listen 127.0.0.1:{port} ssl")
            .replace("    listen [::]:443 ssl default_server;", "")
            .replace("wms.example.internal", "localhost")
            .replace("/etc/wms/tls/server-chain.pem", str(cert[2]))
            .replace("/etc/wms/tls/server-key.pem", str(cert[3]))
            .replace("/var/log/nginx/wms-access.log", str(directory / "access.log"))
            .replace("127.0.0.1:8000", f"127.0.0.1:{sock.getsockname()[1]}")
            .replace("/etc/wms/maintenance.on", str(directory / "maintenance"))
        )
        config = directory / "nginx.conf"
        config.write_text(
            f"pid {directory}/nginx.pid;\nerror_log {directory}/error.log;\nevents {{}}\nhttp {{ client_body_temp_path {directory}/body; proxy_temp_path {directory}/proxy; fastcgi_temp_path {directory}/fastcgi; uwsgi_temp_path {directory}/uwsgi; scgi_temp_path {directory}/scgi;\n{template}\n}}"
        )
        process = None
        thread.start()
        try:
            with (directory / "process.log").open("w") as log:
                subprocess.run(
                    [binary, "-t", "-p", str(directory), "-c", str(config)],
                    check=True,
                    stdout=log,
                    stderr=log,
                )
                process = subprocess.Popen(
                    [binary, "-p", str(directory), "-c", str(config), "-g", "daemon off;"],
                    stdout=log,
                    stderr=log,
                )
            url = f"https://localhost:{port}/api/v1"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if server.started and probe(url, str(ca[2]))["schema"] == "ready":
                        break
                except Exception:
                    time.sleep(0.05)
            else:
                raise AssertionError("B24 TLS runtime failed to start")
            yield dict(
                url=url,
                ca=str(ca[2]),
                engine=app_engine,
                app=app,
                directory=directory,
                nginx=subprocess.run(
                    [binary, "-v"], capture_output=True, text=True, check=True
                ).stderr.strip(),
            )
        finally:
            if process:
                process.send_signal(signal.SIGQUIT)
                process.wait(timeout=15)
            server.should_exit = True
            thread.join(15)
            sock.close()
            assert not thread.is_alive()


def request_process(url, ca, call, gate, queue):
    """Spawned interpreter: no inherited SQLAlchemy pool or HTTP session."""
    try:
        with httpx.Client(
            verify=ssl.create_default_context(cafile=ca), trust_env=False, timeout=30
        ) as client:
            gate.wait(20)
            start = time.monotonic()
            response = client.request(
                call["method"], url + "/" + call["path"], headers=call["headers"], json=call.get("body")
            )
            queue.put(
                dict(
                    pid=os.getpid(),
                    status=response.status_code,
                    body=response.json(),
                    seconds=time.monotonic() - start,
                )
            )
    except Exception as e:
        queue.put(dict(pid=os.getpid(), error=type(e).__name__))


def race(server, calls):
    context = mp.get_context("spawn")
    gate = context.Barrier(len(calls))
    queue = context.Queue()
    processes = [
        context.Process(target=request_process, args=(server["url"], server["ca"], call, gate, queue))
        for call in calls
    ]
    backend_gate = threading.Barrier(len(calls))
    lock = threading.Lock()
    backends = []
    outcomes = {"commit": 0, "rollback": 0}

    def begin(c):
        with lock:
            if len(backends) >= len(calls):
                return
            # driver information is from this actual API transaction, not a probe connection.
            backends.append(c.connection.driver_connection.info.backend_pid)
        backend_gate.wait(20)

    def committed(c):
        with lock:
            outcomes["commit"] += 1

    def rolled_back(c):
        with lock:
            outcomes["rollback"] += 1

    for name, handler in [("begin", begin), ("commit", committed), ("rollback", rolled_back)]:
        event.listen(server["engine"], name, handler)
    try:
        for p in processes:
            p.start()
        results = [queue.get(timeout=45) for _ in processes]
        for p in processes:
            p.join(15)
            assert p.exitcode == 0
        assert len({r["pid"] for r in results}) == len(calls)
        assert len(set(backends)) == len(calls), backends
        assert all("error" not in r for r in results), results
        return results, dict(client_pids=[r["pid"] for r in results], db_pids=backends, transactions=outcomes)
    finally:
        backend_gate.abort()
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(10)
        queue.close()
        for name, handler in [("begin", begin), ("commit", committed), ("rollback", rolled_back)]:
            event.remove(server["engine"], name, handler)


def command(f, path, body, who="buyer", key=None):
    return dict(
        method="POST",
        path=path,
        body=body,
        headers={**f.headers[who], "Idempotency-Key": str(key or uuid4())},
    )


def save_evidence(name, data):
    folder = ROOT / ".reports/b24"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + ".json")).write_text(json.dumps(data, indent=2, default=str) + "\n")


@contextmanager
def production_workers(server):
    """Six production worker bodies, independent pools; local thread supervision only."""
    from apps.server.application.outbox import OutboxProcessor
    from apps.server.consumers.registry import consumer_factory, fingerprint
    from apps.server.infrastructure.file_storage import FileStorage
    from apps.server.infrastructure.outbox import PostgresOutboxStore
    from apps.server.infrastructure.worker_status import WorkerStatus
    from apps.server.operations_worker import compose

    kinds = ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")
    stop = threading.Event()
    started = threading.Barrier(len(kinds) + 1)
    stats = {kind: dict(cycles=0, failures=0) for kind in kinds}
    engines = []
    threads = []

    def prepare(kind, engine):
        app = create_app(server["app"].state.identity.settings, engine=engine)
        app.state.identity.clock = server["app"].state.identity.clock
        for name in ("imports", "exports", "printing"):
            service = getattr(app.state, name)
            service.storage = FileStorage(
                service.storage.settings.model_copy(update={"storage_root": server["directory"] / name})
            )
        registry = consumer_factory()
        status = WorkerStatus(engine, kind, fingerprint(registry))
        status.update("IDLE")
        if kind == "outbox":
            processor = OutboxProcessor(PostgresOutboxStore(engine), registry)

            def run():
                return processor.run_batch(should_stop=stop.is_set)
        else:
            run = compose(app, kind)
        return status, run

    def work(kind, status, run):
        try:
            started.wait(20)
            while not stop.is_set():
                status.update("BUSY")
                outcome = run()
                stats[kind]["cycles"] += 1
                if kind == "outbox":
                    stats[kind]["processed"] = stats[kind].get("processed", 0) + outcome.processed
                    stats[kind]["failures"] += outcome.retry + outcome.exhausted
                elif isinstance(outcome, str) and outcome in {"FAILED", "RETRY", "LOST_LEASE"}:
                    stats[kind]["failures"] += 1
                status.update("IDLE", completed=True)
                stop.wait(0.25 if kind == "outbox" else 1)
            status.update("STOPPED")
        except Exception as e:
            stats[kind]["failures"] += 1
            stats[kind]["error_type"] = type(e).__name__
            started.abort()

    try:
        for kind in kinds:
            engine = create_engine(
                server["engine"].url,
                pool_size=3,
                max_overflow=0,
                pool_timeout=10,
                hide_parameters=True,
                connect_args={"options": "-c lock_timeout=10000 -c statement_timeout=10000"},
            )
            engines.append(engine)
            status, run = prepare(kind, engine)
            t = threading.Thread(target=work, args=(kind, status, run), daemon=True)
            threads.append(t)
        for t in threads:
            t.start()
        started.wait(20)
        yield stats
    finally:
        stop.set()
        for t in threads:
            t.join(15)
            assert not t.is_alive()
        for engine in engines:
            engine.dispose()
        assert all(v["cycles"] > 0 and v["failures"] == 0 for v in stats.values()), stats
