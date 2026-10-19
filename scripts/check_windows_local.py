"""Native Windows test against a NEW throwaway MySQL datadir, never installed services."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pymysql
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.local_launcher import runtime
from apps.local_launcher.database import SetupError, load_environment
from apps.local_launcher.product import PREFIX, PRODUCT
from apps.local_launcher.provision import provision
from apps.local_launcher.runtime import Supervisor, worker_kinds
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.private_files import private_windows_acl


def wait_for(fn, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.5)
    raise AssertionError("Native readiness timed out")


def test_app(root, password):
    home = root / (PRODUCT + " thử nghiệm")
    app_password = secrets.token_urlsafe(24)
    provision(
        home,
        root_password=password,
        mysql_port=3307,
        api_port=18765,
        database=PRODUCT.lower() + "_mysql",
        username="admin",
        display_name="Quản trị",
        password=app_password,
        timezone=True,
    )
    env = load_environment(home)
    original = (home / "runtime.json").read_bytes()
    assert password.encode() not in original and app_password.encode() not in original
    acl = private_windows_acl(home / "runtime.json")
    assert "OW" in acl and "SY" in acl and ";;;WD" not in acl and "BU" not in acl
    engine = make_engine(Settings(database_url=env[PREFIX + "DATABASE_URL"]))
    supervisor = Supervisor(home)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM wms.product")).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM wms.document")).scalar_one() == 0
        try:
            with engine.begin() as c:
                c.execute(text("CREATE TABLE forbidden (id int)"))
        except DBAPIError:
            pass
        else:
            raise AssertionError("Runtime has DDL privileges")
        supervisor.start()

        def workers_ready():
            with engine.connect() as c:
                rows = c.execute(text("SELECT kind,state FROM wms.worker_status")).all()
            return {r[0] for r in rows if r[1] in {"IDLE", "BUSY"}} == set(worker_kinds())

        wait_for(workers_ready)
        with httpx.Client(base_url="http://127.0.0.1:18765/api/v1", trust_env=False) as client:
            login = client.post(
                "/auth/login", json={"username": "admin", "password": app_password, "device_id": str(uuid4())}
            )
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            assert client.get("/users", headers=headers).status_code == 403
            assert client.post("/auth/logout", headers=headers).status_code == 200
        supervisor.stop()
        supervisor = Supervisor(home)
        supervisor.start()
        supervisor.stop()
        assert (home / "runtime.json").read_bytes() == original
        try:
            provision(
                root / "another",
                root_password=password,
                mysql_port=3307,
                api_port=18765,
                database=PRODUCT.lower() + "_mysql",
                username="admin",
                display_name="Admin",
                password=app_password,
                timezone=True,
            )
        except SetupError:
            pass
        else:
            raise AssertionError("Existing database adopted")
        assert not (root / "another").exists()
    except Exception:
        for log in (home / "logs").glob("*.log"):
            value = log.read_text(encoding="utf-8", errors="replace")[-3000:]
            value = value.replace(password, "[redacted]").replace(app_password, "[redacted]")
            print(log.name, value)
        raise
    finally:
        supervisor.stop()
        engine.dispose()


def main():
    if os.name != "nt":
        raise SystemExit("Native Windows only")
    frozen = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    if frozen:
        assert frozen.is_file()
        runtime.executable = lambda component, home, session: [
            str(frozen),
            "--component",
            component,
            "--home",
            str(home),
            "--session",
            session,
        ]
    requested = os.environ.get(PREFIX + "NATIVE_MYSQL_BIN")
    candidates = (
        [Path(requested)]
        if requested
        else list(Path(r"C:\Program Files\MySQL").glob("MySQL Server 8.0/bin/mysqld.exe"))
    )
    if len(candidates) != 1:
        raise SystemExit("Need native MySQL test server binary")
    binary = candidates[0]
    # Never stop/reconfigure a pre-existing service or use its data directory.
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 3307))
    with tempfile.TemporaryDirectory(prefix=PRODUCT.lower() + "-local-native-") as temporary:
        root = Path(temporary)
        data = root / "data"
        subprocess.run(
            [str(binary), "--no-defaults", "--initialize-insecure", f"--datadir={data}"], check=True
        )
        log = (root / "mysql.log").open("wb")
        process = subprocess.Popen(
            [
                str(binary),
                "--no-defaults",
                f"--datadir={data}",
                "--port=3307",
                "--bind-address=127.0.0.1",
                "--mysqlx=0",
                "--console",
            ],
            stdout=log,
            stderr=log,
        )
        admin = None
        try:

            def connected():
                nonlocal admin
                if process.poll() is not None:
                    raise AssertionError("Test MySQL failed")
                try:
                    admin = pymysql.connect(host="127.0.0.1", port=3307, user="root", autocommit=True)
                    return True
                except pymysql.OperationalError:
                    return False

            wait_for(connected)
            password = secrets.token_hex(32)
            with admin.cursor() as c:
                c.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (password,))
                c.execute("SELECT VERSION()")
                version = c.fetchone()[0]
            test_app(root, password)
            Path(sys.argv[1]).write_text(
                json.dumps(
                    {
                        "result": "PASS",
                        "mysql": version,
                        "scope": "Windows Server 2022 launcher: empty database, runtime grants, NTFS ACL, missing timezone setup, HTTP login, MFA gate, all workers, stop/restart, preserve database",
                        "interactive_uac": "NOT_RUN",
                        "frozen_full_database": "PASS" if frozen else "NOT_RUN",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            if admin:
                try:
                    with admin.cursor() as c:
                        c.execute("SHUTDOWN")
                except pymysql.Error:
                    pass
                admin.close()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                # Only the throwaway CI-owned MySQL process.
                process.kill()
                process.wait()
            log.close()


if __name__ == "__main__":
    main()
