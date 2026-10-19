"""Fresh local MySQL setup and foreground supervision on native Windows.

No service installation, database adoption, schema replacement or secret logging.
Run with the installed wheel: python -I -m apps.server.windows_standalone --help.
"""

import json
import os
import re
import secrets
import socket
import subprocess
from pathlib import Path

import pymysql
from cryptography.fernet import Fernet
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready, migrate
from apps.server.infrastructure.private_files import open_private

KINDS = ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")
ENV_KEYS = {
    "WMS_DATABASE_URL",
    "WMS_MFA_ENCRYPTION_KEY",
    "WMS_HOST",
    "WMS_PORT",
    "WMS_BUSINESS_TIMEZONE",
    "WMS_IMPORT_STORAGE_ROOT",
    "WMS_EXPORT_STORAGE_ROOT",
    "WMS_PRINT_STORAGE_ROOT",
}


class SetupError(RuntimeError):
    """A message safe to display without database URLs or passwords."""


def require_mysql_version(version):
    # Invisible columns require 8.0.23; CHECKs and 0900_bin also need newer
    # versions than 8.0.11. Validate before creating any files, users or schema.
    match = re.fullmatch(r"8\.(0|4)\.(\d+)(?:[-+][A-Za-z0-9_.+-]+)?", version)
    if not match or "mariadb" in version.lower() or (match[1] == "0" and int(match[2]) < 23):
        raise SetupError(
            "MySQL ngoai pham vi ho tro: can dong 8.0 (tu 8.0.23) hoac 8.4 LTS. "
            "Khong bat buoc dung dung ban 8.0.46. Khong dung MariaDB. "
            "Chua tao database/user/cau hinh. Giu nguyen ban cu de phuc hoi."
        )


def verify_mysql(cursor):
    """Probe required behavior in a session-local table, before any durable DDL."""
    cursor.execute("SELECT VERSION(), CONVERT_TZ('2026-01-01 00:00:00','UTC','Asia/Ho_Chi_Minh')")
    version, converted = cursor.fetchone()
    require_mysql_version(version)
    if converted is None or str(converted) != "2026-01-01 07:00:00":
        raise SetupError("MySQL thieu mui gio. Nap goi timezone POSIX chinh thuc vao dung cong roi thu lai.")
    table = f"mysql.`_wms_probe_{secrets.token_hex(12)}`"
    created = False
    try:
        cursor.execute(
            f"CREATE TEMPORARY TABLE {table} (qty INT NOT NULL CHECK (qty >= 0), "
            "hidden INT INVISIBLE DEFAULT 0) ENGINE=InnoDB "
            "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin"
        )
        created = True
        cursor.execute(f"INSERT INTO {table} (qty) VALUES (1)")
        cursor.execute(f"SELECT * FROM {table}")
        if cursor.fetchone() != (1,):
            raise SetupError("MySQL khong dap ung cot INVISIBLE. Chua tao database WMS.")
        try:
            cursor.execute(f"INSERT INTO {table} (qty) VALUES (-1)")
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] != 3819:
                raise
        else:
            raise SetupError("MySQL khong thuc thi CHECK. Chua tao database WMS.")
    except pymysql.MySQLError as exc:
        raise SetupError("Kiem tra tinh nang MySQL that bai. " + failure_message(exc)) from None
    finally:
        if created:
            cursor.execute(f"DROP TEMPORARY TABLE {table}")
    return version


def root_connection(password, port):
    return pymysql.connect(
        host="127.0.0.1",
        port=port,
        user="root",
        password=password,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )


def preflight(*, root_password, mysql_port=3306):
    connection = root_connection(root_password, mysql_port)
    try:
        with connection.cursor() as cursor:
            version = verify_mysql(cursor)
    finally:
        connection.close()
    print(
        f"MYSQL_COMPATIBLE: MySQL {version}, cong {mysql_port}; "
        "collation, INVISIBLE, CHECK va mui gio dat. Chua tao database WMS hoac doi ket noi.",
        flush=True,
    )


def failure_message(exc):
    """Expose the numeric driver code, never SQL, parameters or credentials."""
    driver = exc.orig if isinstance(exc, DBAPIError) else exc
    code = driver.args[0] if isinstance(driver, pymysql.Error) and driver.args else None
    detail = f"; MySQL {code}" if type(code) is int and 1000 <= code <= 9999 else ""
    return (
        f"KHONG THANH CONG ({type(exc).__name__}{detail}). "
        "Kiem tra phien ban MySQL, quyen, mui gio va thu muc. "
        "Khong xoa database/cau hinh hien co de thu lai."
    )


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
    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
    )
    match = re.search(r"S-1-5-[0-9-]+", result.stdout)
    if not match:
        raise SetupError("Khong doc duoc SID tai khoan Windows.")
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{match[0]}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
        check=True,
        capture_output=True,
    )


def write_private(path, data):
    with os.fdopen(open_private(path, create=True), "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def setup(
    home, *, root_password, mysql_port=3306, api_port=8000, database="wms_mysql", runtime_user="wms_runtime"
):
    """Fail closed on any existing destination, before making a database change."""
    home = Path(home).absolute()
    database, runtime_user = identifier(database), identifier(runtime_user)
    if home.exists() or home.is_symlink():
        raise SetupError("Thu muc WMS-Server da ton tai. Khong ghi de; dung lenh check/run.")
    connection = root_connection(root_password, mysql_port)
    engine = None
    try:
        with connection.cursor() as cursor:
            verify_mysql(cursor)
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database,)
            )
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
            runtime_url = URL.create(
                "mysql+pymysql",
                username=runtime_user,
                password=password,
                host="127.0.0.1",
                port=mysql_port,
                database=database,
                query={"charset": "utf8mb4"},
            )
            env = {
                "WMS_DATABASE_URL": runtime_url.render_as_string(hide_password=False),
                "WMS_MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "WMS_HOST": "127.0.0.1",
                "WMS_PORT": str(api_port),
                "WMS_BUSINESS_TIMEZONE": "Asia/Ho_Chi_Minh",
                **{
                    f"WMS_{kind.upper()}_STORAGE_ROOT": str(home / kind)
                    for kind in ("import", "export", "print")
                },
            }
            write_private(home / "runtime.json", {"version": 1, "environment": env})
            cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s", (runtime_user, password))
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON `{database}`.* TO %s@'127.0.0.1'",
                (runtime_user,),
            )
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
    settings = Settings(
        **{k.removeprefix("WMS_").lower(): v for k, v in env.items() if "STORAGE_ROOT" not in k}
    )
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername != "mysql+pymysql" or url.host != "127.0.0.1" or settings.host != "127.0.0.1":
        raise SetupError("Launcher doc lap chi ket noi MySQL va API tren 127.0.0.1.")
    for kind in ("import", "export", "print"):
        path = Path(env[f"WMS_{kind.upper()}_STORAGE_ROOT"])
        if path != home / kind or path.is_symlink() or path.is_junction() or not path.is_dir():
            raise SetupError("Thu muc tep khong khop cau hinh hoac khong con ton tai.")
    # Do not inherit unrelated WMS_* secrets/settings from a previous deployment.
    return {
        **{k: v for k, v in os.environ.items() if not k.upper().startswith("WMS_")},
        **env,
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }
