"""Fresh local MySQL setup and foreground supervision on native Windows.

No service installation, database adoption, schema replacement or secret logging.
Run with the installed wheel: python -I -m apps.server.windows_standalone --help.
"""

import argparse
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path
from threading import Event

import httpx
import pymysql
from cryptography.fernet import Fernet
from sqlalchemy.engine import URL, make_url

from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready, migrate
from apps.server.infrastructure.private_files import open_private
from apps.server.worker import stop_signals

KINDS = ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")
ENV_KEYS = {
    "WMS_DATABASE_URL", "WMS_MFA_ENCRYPTION_KEY", "WMS_HOST", "WMS_PORT",
    "WMS_BUSINESS_TIMEZONE", "WMS_IMPORT_STORAGE_ROOT", "WMS_EXPORT_STORAGE_ROOT",
    "WMS_PRINT_STORAGE_ROOT",
}


class SetupError(RuntimeError):
    """A message safe to display without database URLs or passwords."""


def default_home():
    return Path(os.environ["LOCALAPPDATA"]) / "WMS-Server"


def identifier(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value):
        raise SetupError("Ten database/user chi gom a-z, 0-9, _, toi da 32 ky tu.")
    return value


def protect_directory(path):
    """Only apply to a newly created application directory, never a user parent."""
    if os.name != "nt":
        path.chmod(0o700)
        return
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, check=True)
    match = re.search(r"S-1-5-[0-9-]+", result.stdout)
    if not match:
        raise SetupError("Khong doc duoc SID tai khoan Windows.")
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                    f"*{match[0]}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                   check=True, capture_output=True)


def write_private(path, data):
    with os.fdopen(open_private(path, create=True), "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def setup(home, *, root_password, mysql_port=3306, api_port=8000,
          database="wms_mysql", runtime_user="wms_runtime"):
    """Fail closed on any existing destination, before making a database change."""
    home = Path(home).absolute()
    database, runtime_user = identifier(database), identifier(runtime_user)
    if home.exists() or home.is_symlink():
        raise SetupError("Thu muc WMS-Server da ton tai. Khong ghi de; dung lenh check/run.")
    connection = pymysql.connect(host="127.0.0.1", port=mysql_port, user="root",
                                 password=root_password, charset="utf8mb4", autocommit=True,
                                 connect_timeout=10, read_timeout=30, write_timeout=30)
    engine = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), CONVERT_TZ('2026-01-01 00:00:00','UTC','Asia/Ho_Chi_Minh')")
            version, converted = cursor.fetchone()
            if not version.startswith("8.0."):
                raise SetupError("Huong dan nay yeu cau MySQL 8.0; khong dung MariaDB/XAMPP.")
            if converted is None or str(converted) != "2026-01-01 07:00:00":
                raise SetupError("MySQL thieu mui gio. Nap goi timezone POSIX chinh thuc roi thu lai.")
            cursor.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database,))
            if cursor.fetchone():
                raise SetupError("Database da ton tai. Cong cu chi tao database moi, khong xoa/ghi de.")
            cursor.execute("SELECT User FROM mysql.user WHERE User=%s", (runtime_user,))
            if cursor.fetchone():
                raise SetupError("Tai khoan runtime da ton tai. Dung ten khac cho cai dat moi.")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", api_port))
            # An incomplete setup retains the marker and generated credentials for recovery.
            # Never retry by deleting an existing database or silently rotating its password.
            home.mkdir(parents=True, exist_ok=False)
            protect_directory(home)
            write_private(home / "setup-incomplete.json", {"database": database, "state": "INCOMPLETE"})
            for kind in ("import", "export", "print", "logs"):
                (home / kind).mkdir(mode=0o700)
            password = secrets.token_hex(32)
            runtime_url = URL.create("mysql+pymysql", username=runtime_user, password=password,
                                     host="127.0.0.1", port=mysql_port, database=database,
                                     query={"charset": "utf8mb4"})
            env = {
                "WMS_DATABASE_URL": runtime_url.render_as_string(hide_password=False),
                "WMS_MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "WMS_HOST": "127.0.0.1", "WMS_PORT": str(api_port),
                "WMS_BUSINESS_TIMEZONE": "Asia/Ho_Chi_Minh",
                **{f"WMS_{kind.upper()}_STORAGE_ROOT": str(home / kind)
                   for kind in ("import", "export", "print")},
            }
            write_private(home / "runtime.json", {"version": 1, "environment": env})
            cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s", (runtime_user, password))
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON `{database}`.* TO %s@'127.0.0.1'",
                           (runtime_user,))
        admin_url = runtime_url.set(username="root", password=root_password)
        engine = make_engine(Settings(database_url=admin_url.render_as_string(hide_password=False)))
        migrate(engine)
        engine.dispose()
        engine = make_engine(Settings(database_url=env["WMS_DATABASE_URL"]))
        if not is_ready(engine):
            raise SetupError("Migration chua hoan tat. Giu nguyen thu muc va database de kiem tra.")
        (home / "setup-incomplete.json").unlink()
    finally:
        connection.close()
        if engine is not None:
            engine.dispose()
    print("SETUP_OK: database moi da san sang; mat khau root khong duoc luu.", flush=True)


def load_environment(home):
    home = Path(home).absolute()
    if home.is_symlink() or home.is_junction():
        raise SetupError("Thu muc may chu khong duoc la lien ket/junction.")
    if (home / "setup-incomplete.json").exists():
        raise SetupError("Cai dat dang do dang. Giu nguyen du lieu; khong chay lai setup de ghi de.")
    with os.fdopen(open_private(home / "runtime.json"), encoding="utf-8") as stream:
        data = json.load(stream)
    env = data.get("environment", {})
    if data.get("version") != 1 or set(env) != ENV_KEYS or not all(isinstance(v, str) for v in env.values()):
        raise SetupError("runtime.json khong dung dinh dang.")
    settings = Settings(**{k.removeprefix("WMS_").lower(): v for k, v in env.items()
                           if "STORAGE_ROOT" not in k})
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername != "mysql+pymysql" or url.host != "127.0.0.1" or settings.host != "127.0.0.1":
        raise SetupError("Launcher doc lap chi ket noi MySQL va API tren 127.0.0.1.")
    for kind in ("import", "export", "print"):
        path = Path(env[f"WMS_{kind.upper()}_STORAGE_ROOT"])
        if path != home / kind or path.is_symlink() or path.is_junction() or not path.is_dir():
            raise SetupError("Thu muc tep khong khop cau hinh hoac khong con ton tai.")
    # Do not inherit unrelated WMS_* secrets/settings from a previous deployment.
    return {**{k: v for k, v in os.environ.items() if not k.upper().startswith("WMS_")},
            **env, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}


def command(component, *extra):
    if component == "api":
        module, args = "apps.server", []
    elif component == "outbox":
        module, args = "apps.server.worker", []
    else:
        module, args = "apps.server.operations_worker", ["--kind", component]
    return [sys.executable, "-I", "-X", "utf8", "-m", module, *args, *extra]


def check(home):
    env = load_environment(home)
    for kind in KINDS:
        subprocess.run(command(kind, "--check"), env=env, check=True, cwd=home)
    print("CHECK_OK: schema va ca 6 worker da san sang.", flush=True)


@contextmanager
def instance_lock(home):
    import msvcrt

    path = Path(home) / "server.lock"
    if path.is_symlink() or path.is_junction():
        raise SetupError("Lock file khong hop le.")
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SetupError("May chu dang chay. Dung cua so dang mo hoac lenh stop.") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def run(home):
    home = Path(home).absolute()
    env = load_environment(home)
    children, streams = [], []
    stop = Event()
    failed = False
    with instance_lock(home), stop_signals(stop):
        stop_path = home / "stop.request"
        stop_path.unlink(missing_ok=True)
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", int(env["WMS_PORT"])))
            check(home)
            for name in (*KINDS, "api"):
                stream = (home / "logs" / f"{name}.log").open("ab")
                streams.append(stream)
                process = subprocess.Popen(command(name), env=env, cwd=home, stdout=stream,
                                           stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                children.append((name, process))
            deadline = time.monotonic() + 90
            ready = False
            while not stop.wait(0.5) and not stop_path.exists():
                dead = [name for name, process in children if process.poll() is not None]
                if dead:
                    raise SetupError("Tien trinh da dung: " + ", ".join(dead) + ". Xem thu muc logs.")
                if not ready:
                    try:
                        response = httpx.get(f"http://127.0.0.1:{env['WMS_PORT']}/api/v1/ready",
                                             timeout=2, trust_env=False)
                        ready = response.status_code == 200
                    except httpx.HTTPError:
                        pass
                    if ready:
                        print("SERVER_READY: mo WMS Desktop. Dung bang Ctrl+C hoac lenh stop; doi SERVER_STOPPED.",
                              flush=True)
                    elif time.monotonic() > deadline:
                        raise SetupError("API chua ready sau 90 giay. Xem logs/api.log.")
        except SetupError as exc:
            print(str(exc), file=sys.stderr)
            failed = True
        finally:
            print("Dang dung API/worker; cho giao dich dang xu ly ket thuc...", flush=True)
            # API first stops accepting new writes; all workers receive graceful break.
            for name, process in reversed(children):
                if process.poll() is None:
                    try:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    except OSError:
                        pass
            last_notice = time.monotonic()
            while any(process.poll() is None for _, process in children):
                time.sleep(0.25)
                if time.monotonic() - last_notice > 30:
                    print("Van cho tien trinh ket thuc an toan; xem logs neu qua lau.", flush=True)
                    last_notice = time.monotonic()
            for stream in streams:
                stream.close()
            stop_path.unlink(missing_ok=True)
            print("SERVER_STOPPED: API va 6 worker da dung.", flush=True)
    return int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=None)
    sub = parser.add_subparsers(dest="action", required=True)
    fresh = sub.add_parser("setup", help="Only initialize a NEW local MySQL 8.0 database")
    fresh.add_argument("--mysql-port", type=int, default=3306)
    fresh.add_argument("--api-port", type=int, default=8000)
    fresh.add_argument("--database", default="wms_mysql")
    fresh.add_argument("--runtime-user", default="wms_runtime")
    for action in ("check", "run", "stop"):
        sub.add_parser(action)
    admin = sub.add_parser("admin", help="Create an initial administrator; hidden password prompt")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", required=True)
    period = sub.add_parser("first-period", help="Create the first stock period for a new warehouse")
    for option in ("warehouse-code", "starts-on", "ends-on", "reason"):
        period.add_argument("--" + option, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("Cong cu nay chi dung tren Windows native.")
    home = (args.home or default_home()).absolute()
    try:
        if args.action == "setup":
            if not all(1 <= port <= 65535 for port in (args.mysql_port, args.api_port)):
                raise SetupError("Cong phai nam trong 1..65535.")
            setup(home, root_password=getpass("Mat khau MySQL root (khong hien ky tu): "),
                  mysql_port=args.mysql_port, api_port=args.api_port,
                  database=args.database, runtime_user=args.runtime_user)
        elif args.action == "run":
            return run(home)
        elif args.action == "check":
            check(home)
        elif args.action == "stop":
            load_environment(home)
            (home / "stop.request").touch()
            print("Da yeu cau dung. Cho SERVER_STOPPED trong cua so may chu truoc khi tat may.")
        else:
            module = "apps.server.bootstrap" if args.action == "admin" else "apps.server.bootstrap_period"
            options = ("username", "display_name") if args.action == "admin" else (
                "warehouse_code", "starts_on", "ends_on", "reason")
            extra = [part for key in options for part in ("--" + key.replace("_", "-"), getattr(args, key))]
            return subprocess.call([sys.executable, "-I", "-X", "utf8", "-m", module, *extra],
                                   env=load_environment(home), cwd=home)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Da huy thao tac.", file=sys.stderr)
        return 1
    except Exception as exc:
        # Never display raw SQL/URL-bearing driver exceptions.
        print(f"KHONG THANH CONG ({type(exc).__name__}). Kiem tra MySQL, quyen, mui gio va thu muc. "
              "Khong xoa database/cau hinh hien co de thu lai.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
