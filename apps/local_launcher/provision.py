"""Fresh database provisioning and bootstrap, never adoption of unrelated data."""

import json
import os
from contextlib import contextmanager
from importlib.resources import files

from sqlalchemy import text

from apps.local_launcher.database import (
    SetupError,
    load_environment,
    require_mysql_version,
    root_connection,
    setup,
)
from apps.local_launcher.product import PREFIX, PRODUCT
from apps.server.application.identity import IdentityService
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready
from packages.contracts.identity import UserCreate


@contextmanager
def server_environment(home):
    env = load_environment(home)
    old = {k: v for k, v in os.environ.items() if k.upper().startswith(("WMS_", "KWS_"))}
    try:
        for key in old:
            del os.environ[key]
        os.environ.update({k: v for k, v in env.items() if k.startswith(PREFIX)})
        yield Settings()
    finally:
        for key in list(os.environ):
            if key.upper().startswith(("WMS_", "KWS_")):
                del os.environ[key]
        os.environ.update(old)


def add_missing_timezones(password, port):
    """Only insert absent named zones from pinned Oracle POSIX data; no TRUNCATE/UPDATE."""
    zones = json.loads(files("apps.local_launcher").joinpath("timezones.json").read_text())["zones"]
    connection = root_connection(password, port)
    locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            require_mysql_version(cursor.fetchone()[0])
            cursor.execute("SELECT GET_LOCK('warehouse:timezone-bootstrap',10)")
            locked = cursor.fetchone()[0] == 1
            if not locked:
                raise SetupError("Một phiên đang bổ sung múi giờ. Hãy thử lại sau.")
            connection.begin()
            for name, zone in zones.items():
                cursor.execute("SELECT Time_zone_id FROM mysql.time_zone_name WHERE Name=%s", (name,))
                if cursor.fetchone():
                    continue
                cursor.execute("INSERT INTO mysql.time_zone (Use_leap_seconds) VALUES ('N')")
                zone_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO mysql.time_zone_name (Name,Time_zone_id) VALUES (%s,%s)", (name, zone_id)
                )
                for stamp, kind in zone["transitions"]:
                    cursor.execute(
                        "INSERT INTO mysql.time_zone_transition (Time_zone_id,Transition_time,Transition_type_id) VALUES (%s,%s,%s)",
                        (zone_id, stamp, kind),
                    )
                for kind, offset, dst, abbreviation in zone["types"]:
                    cursor.execute(
                        "INSERT INTO mysql.time_zone_transition_type (Time_zone_id,Transition_type_id,`Offset`,Is_DST,Abbreviation) VALUES (%s,%s,%s,%s,%s)",
                        (zone_id, kind, offset, dst, abbreviation),
                    )
            connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK('warehouse:timezone-bootstrap')")
        connection.close()


def needs_admin(home):
    with server_environment(home) as settings:
        engine = make_engine(settings)
        try:
            if not is_ready(engine):
                raise SetupError("Database khác phiên bản hoặc chưa hoàn tất. Không tự sửa schema đang có.")
            with engine.connect() as connection:
                return connection.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one() == 0
        finally:
            engine.dispose()


def bootstrap_admin(home, username, display_name, password):
    user = UserCreate(username=username, display_name=display_name, password=password)
    with server_environment(home) as settings:
        engine = make_engine(settings)
        try:
            # UI only offers this for an empty user table; service independently enforces bootstrap limits.
            with engine.connect() as connection:
                if connection.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one() != 0:
                    raise SetupError("Tài khoản đã được tạo. Hãy đăng nhập; không tạo lại quản trị viên.")
            IdentityService(engine, settings).bootstrap(
                user.username, user.display_name, user.password.get_secret_value()
            )
        finally:
            engine.dispose()


def provision(
    home, *, root_password, mysql_port, api_port, database, username, display_name, password, timezone=True
):
    UserCreate(username=username, display_name=display_name, password=password)
    if home.exists():
        raise SetupError("Cấu hình đã tồn tại. Chọn Mở ứng dụng; không tạo lại database.")
    if database != PRODUCT.lower() + "_mysql":
        raise SetupError("Dùng tên database riêng mặc định của ứng dụng để tránh nhầm dữ liệu.")
    if not all(type(v) is int and 1 <= v <= 65535 for v in (mysql_port, api_port)):
        raise SetupError("Cổng phải nằm trong 1–65535.")
    # Refuse existing database BEFORE even adding missing timezone metadata.
    c = root_connection(root_password, mysql_port)
    try:
        with c.cursor() as cursor:
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database,)
            )
            if cursor.fetchone():
                raise SetupError(
                    "Database đã có trên máy. Giữ cấu hình máy chủ cũ; bộ cài không ghi đè hoặc tự nhận dữ liệu cũ."
                )
    finally:
        c.close()
    if timezone:
        add_missing_timezones(root_password, mysql_port)
    setup(
        home,
        root_password=root_password,
        mysql_port=mysql_port,
        api_port=api_port,
        database=database,
        runtime_user=PRODUCT.lower() + "_runtime",
    )
    bootstrap_admin(home, username, display_name, password)
