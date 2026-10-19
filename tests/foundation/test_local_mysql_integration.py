"""Only the disposable instance created by scripts/check_mysql.py is accepted."""

import json
import os
from pathlib import Path

import pymysql
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from apps.local_launcher import database, provision, runtime
from apps.local_launcher.product import API_PORT, PREFIX, PRODUCT
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def test_fresh_setup_bootstrap_and_preserve_existing(tmp_path, monkeypatch):
    raw = os.environ.get(PREFIX + "TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Run only through scripts/check_mysql.py")
    url = make_url(raw)
    socket = url.query.get("unix_socket", "")
    assert Path(socket).parent.name.startswith(("wms-mysql-test-", "kws-mysql-test-"))
    assert url.database in ("wms_test_application", "kws_test_application")

    def connect(password, port):
        return pymysql.connect(user="root", unix_socket=socket, autocommit=True, charset="utf8mb4")

    monkeypatch.setattr(database, "root_connection", connect)
    monkeypatch.setattr(provision, "root_connection", connect)
    connection = connect("", 0)
    # Remove only the two timezone names in this throwaway server so insert-missing is exercised.
    with connection.cursor() as c:
        c.execute("DELETE FROM mysql.time_zone_name WHERE Name IN ('UTC','Asia/Ho_Chi_Minh')")
    connection.close()
    home = tmp_path / "server"

    # The runtime user created by setup is @127.0.0.1. Unix sockets use @localhost;
    # configure this test's engine to use disposable root (Windows TCP/runtime-account acceptance is a separate test).
    def disposable_engine(settings):
        values = settings.model_dump()
        target = make_url(settings.database_url.get_secret_value()).set(username="root", password="")
        target = target.update_query_dict({"unix_socket": socket})
        values["database_url"] = target.render_as_string(hide_password=False)
        return make_engine(Settings(**values))

    monkeypatch.setattr(database, "make_engine", disposable_engine)
    monkeypatch.setattr(provision, "make_engine", disposable_engine)
    provision.provision(
        home,
        root_password="not-saved",
        mysql_port=3306,
        api_port=API_PORT,
        database=PRODUCT.lower() + "_mysql",
        username="admin",
        display_name="Quản trị",
        password="Setup-admin-2026-test",
        timezone=True,
    )
    assert not (home / "setup-incomplete.json").exists()
    saved = (home / "runtime.json").read_text()
    assert "not-saved" not in saved and "Setup-admin-2026-test" not in saved
    assert provision.needs_admin(home) is False
    values = json.loads(saved)["environment"]
    e = disposable_engine(Settings(database_url=values[PREFIX + "DATABASE_URL"]))
    try:
        with e.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one() == 1
            assert c.execute(text("SELECT count(*) FROM wms.product")).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM wms.document")).scalar_one() == 0
        before = (home / "runtime.json").read_bytes()
        # Real API and all workers on the disposable Unix-socket database.
        # Use ephemeral root only in this test; production runtime.json never uses it.
        payload = json.loads(before)
        target = make_url(payload["environment"][PREFIX + "DATABASE_URL"])
        target = target.set(username="root", password="").update_query_dict({"unix_socket": socket})
        payload["environment"][PREFIX + "DATABASE_URL"] = target.render_as_string(hide_password=False)
        (home / "runtime.json").write_text(json.dumps(payload))
        supervisor = runtime.Supervisor(home)
        try:
            supervisor.start()
            assert not supervisor.failed()
            assert len(supervisor.children) == 1 + len(runtime.worker_kinds())
        finally:
            supervisor.stop()
            (home / "runtime.json").write_bytes(before)

        with pytest.raises(database.SetupError):
            database.setup(home, root_password="not-saved")
        assert (home / "runtime.json").read_bytes() == before
        with pytest.raises(database.SetupError, match="đã có"):
            provision.provision(
                tmp_path / "other",
                root_password="",
                mysql_port=3306,
                api_port=API_PORT,
                database=PRODUCT.lower() + "_mysql",
                username="admin",
                display_name="Admin",
                password="Setup-admin-2026-test",
                timezone=True,
            )
        assert not (tmp_path / "other").exists()
    finally:
        e.dispose()
