"""Native Windows integration smoke. Owns a NEW disposable MySQL instance only."""

import hashlib
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx
import pymysql
import pyotp
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from apps.server.application.identity import IdentityService
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.file_storage import FileStorage, ImportSettings
from apps.server.infrastructure.private_files import private_windows_acl
from apps.server.windows_standalone import KINDS, SetupError, check, load_environment, preflight, setup

TZ_URL = "https://downloads.mysql.com/general/timezone_2026e_posix_sql.zip"
TZ_SHA = "1cdda5f330679b416603739c787bdefd66f3b238fcfd91faaba551550a36ec47"


def wait_for(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError("Readiness timed out")


def test_application(root, password):
    home = root / "WMS thử nghiệm"
    preflight(root_password=password, mysql_port=3307)
    assert not home.exists()
    setup(home, root_password=password, mysql_port=3307, api_port=18000)
    env = load_environment(home)
    check(home)
    original = (home / "runtime.json").read_bytes()
    try:
        setup(home, root_password=password, mysql_port=3307, api_port=18000)
    except SetupError:
        pass
    else:
        raise AssertionError("Existing setup was overwritten")
    assert (home / "runtime.json").read_bytes() == original
    try:
        setup(root / "another", root_password=password, mysql_port=3307, api_port=18000)
    except SetupError:
        pass
    else:
        raise AssertionError("Existing database was adopted")
    assert not (root / "another").exists()
    acl = private_windows_acl(home / "runtime.json")
    assert "OW" in acl and "SY" in acl and "BU" not in acl and ";;;WD" not in acl
    settings = Settings(database_url=env["WMS_DATABASE_URL"], mfa_encryption_key=env["WMS_MFA_ENCRYPTION_KEY"])
    engine = make_engine(settings)
    try:
        try:
            with engine.begin() as c:
                c.execute(text("CREATE TABLE forbidden (id int)"))
        except DBAPIError:
            pass
        else:
            raise AssertionError("Runtime has DDL permissions")
        identity = IdentityService(engine, settings)
        admin_password = secrets.token_urlsafe(24)
        identity.bootstrap("admin.one", "Quản trị một", admin_password)
        identity.bootstrap("admin.two", "Quản trị hai", secrets.token_urlsafe(24))
        data = "sku,name\nTV01,Tiếng Việt\n".encode()
        digest = hashlib.sha256(data).hexdigest()
        for kind in ("import", "export", "print"):
            storage = FileStorage(ImportSettings(storage_root=home / kind))
            key = secrets.token_hex(32)
            storage.put(data, digest, key)
            storage.put(data, digest, key)  # Immutable same-content retry on NTFS.
            assert storage.read(key, digest, len(data)) == data
            assert ";;;OW" in private_windows_acl(storage.path(key))
        launcher_command = [sys.executable, "-I", "-m", "apps.server.windows_standalone", "--home", str(home)]
        with (root / "launcher.log").open("w", encoding="utf-8") as output:
            launcher = subprocess.Popen([*launcher_command, "run"], stdout=output, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                def ready():
                    if launcher.poll() is not None:
                        raise AssertionError("Launcher exited before readiness")
                    try:
                        return httpx.get("http://127.0.0.1:18000/api/v1/ready", trust_env=False).status_code == 200
                    except httpx.HTTPError:
                        return False
                wait_for(ready)

                def workers_ready():
                    with engine.connect() as c:
                        actual = c.execute(text("SELECT kind,state FROM wms.worker_status")).all()
                    return {r[0] for r in actual if r[1] in {"BUSY", "IDLE"}} == set(KINDS)
                wait_for(workers_ready)
                duplicate = subprocess.run([*launcher_command, "run"], capture_output=True, text=True)
                assert duplicate.returncode == 1 and "dang chay" in duplicate.stderr, duplicate.stderr
                with httpx.Client(base_url="http://127.0.0.1:18000/api/v1", trust_env=False) as client:
                    assert client.get("/health").json()["status"] == "ok"
                    login = client.post("/auth/login", json={"username": "admin.one", "password": admin_password,
                                                             "device_id": str(uuid4())})
                    assert login.status_code == 200
                    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                    assert client.get("/users", headers=headers).status_code == 403  # MFA remains required.
                    enrollment = client.post("/auth/mfa/enroll", headers=headers, json={"password": admin_password})
                    assert enrollment.status_code == 200
                    factor = enrollment.json()
                    confirmed = client.post("/auth/mfa/confirm", headers=headers,
                                            json={"factor_id": factor["factor_id"],
                                                  "code": pyotp.TOTP(factor["secret"]).now()})
                    assert confirmed.status_code == 200
                    assert client.get("/users", headers=headers).status_code == 200
                    assert client.get("/warehouses", headers=headers).json() == []
                    assert client.post("/auth/logout", headers=headers).status_code == 200
                subprocess.run([*launcher_command, "stop"], check=True)
                assert launcher.wait(timeout=90) == 0
                with engine.connect() as c:
                    rows = c.execute(text("SELECT kind,state FROM wms.worker_status")).all()
                    assert {r[0] for r in rows} == set(KINDS)
                    assert all(row[1] == "STOPPED" for row in rows)
                    assert c.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one() == 2
                # Restart with the same key/database; second stop must also finish gracefully.
                restarted = subprocess.Popen([*launcher_command, "run"], stdout=output, stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                launcher = restarted
                wait_for(ready)
                subprocess.run([*launcher_command, "stop"], check=True)
                assert launcher.wait(timeout=90) == 0
                assert (home / "runtime.json").read_bytes() == original
            finally:
                if launcher.poll() is None:
                    (home / "stop.request").touch()
                    try:
                        launcher.wait(timeout=90)
                    except subprocess.TimeoutExpired:
                        # Disposable CI process tree only; never used by the production launcher.
                        subprocess.run(["taskkill", "/PID", str(launcher.pid), "/T", "/F"], capture_output=True)
        log = (root / "launcher.log").read_text(encoding="utf-8")
        assert "SERVER_READY" in log and "SERVER_STOPPED" in log
        assert admin_password not in log and password not in log
        print("PASS: fresh schema, refusal to overwrite, private ACL, limited runtime, Unicode NTFS storage, "
              "2 admins, HTTP login/MFA, 6 workers, duplicate launcher refusal, graceful stop and restart")
    finally:
        engine.dispose()


def main():
    if os.name != "nt":
        raise SystemExit("Native Windows only")
    requested = os.environ.get("WMS_NATIVE_MYSQL_BIN")
    candidates = [Path(requested)] if requested else list(Path(r"C:\Program Files\MySQL").glob("MySQL Server 8.0/bin/mysqld.exe"))
    if len(candidates) != 1:
        raise SystemExit("Need native MySQL test server binary")
    binary = candidates[0]
    with tempfile.TemporaryDirectory(prefix="wms-win-server-") as temporary:
        root = Path(temporary)
        data = root / "data"
        subprocess.run([str(binary), "--no-defaults", "--initialize-insecure", f"--datadir={data}"], check=True)
        log = (root / "mysql.log").open("wb")
        process = subprocess.Popen([str(binary), "--no-defaults", f"--datadir={data}", "--port=3307",
                                    "--bind-address=127.0.0.1", "--mysqlx=0", "--console"], stdout=log, stderr=log)
        admin = None
        password = secrets.token_hex(32)
        try:
            def connected():
                nonlocal admin
                if process.poll() is not None:
                    raise AssertionError("MySQL exited before startup")
                try:
                    admin = pymysql.connect(host="127.0.0.1", port=3307, user="root", autocommit=True)
                    return True
                except pymysql.OperationalError:
                    return False
            wait_for(connected)
            # The missing-timezone failure must leave no configuration or database.
            try:
                setup(root / "missing-tz", root_password="", mysql_port=3307, api_port=18000)
            except SetupError:
                assert not (root / "missing-tz").exists()
            else:
                raise AssertionError("Missing timezones accepted")
            payload = urllib.request.urlopen(TZ_URL, timeout=60).read()
            assert hashlib.sha256(payload).hexdigest() == TZ_SHA
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                sql = z.read("timezone_2026e_posix_sql/timezone_posix.sql")
            subprocess.run([str(binary.with_name("mysql.exe")), "--no-defaults", "--host=127.0.0.1",
                            "--port=3307", "--user=root", "mysql"], input=sql, check=True)
            with admin.cursor() as c:
                c.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (password,))
                c.execute("SELECT VERSION()")
                version = c.fetchone()[0]
            test_application(root, password)
            report = {"result": "PASS", "platform": sys.platform, "python": sys.version.split()[0],
                      "mysql": version, "timezone_sha256": TZ_SHA,
                      "scope": "Native Windows Server 2022 disposable MySQL; not device or Win10/11 acceptance"}
            Path("native-windows-server-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            for path in (root / "launcher.log", root / "mysql.log"):
                if path.exists():
                    print(path.name, path.read_text(encoding="utf-8", errors="replace")[-5000:])
            raise
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
                process.kill()
                process.wait()
            log.close()


if __name__ == "__main__":
    main()
