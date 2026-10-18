import json
from unittest.mock import MagicMock

import pymysql
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import OperationalError

from apps.server.windows_standalone import (
    SetupError,
    failure_message,
    identifier,
    load_environment,
    require_mysql_version,
    setup,
    write_private,
)


@pytest.mark.parametrize("version", ["8.0.11", "8.0.16", "8.0.22", "5.7.44", "8.4.0", "8.0.46-MariaDB", "invalid"])
def test_incompatible_server_refused_without_creating_destination(tmp_path, monkeypatch, version):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (version, "2026-01-01 07:00:00")
    monkeypatch.setattr("pymysql.connect", lambda **kwargs: connection)
    home = tmp_path / "new-home"
    with pytest.raises(SetupError, match="8.0.46"):
        setup(home, root_password="private-root-password")
    assert not home.exists()
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].startswith("SELECT VERSION()")
    connection.close.assert_called_once()


@pytest.mark.parametrize("version", ["8.0.23", "8.0.46", "8.0.46-commercial"])
def test_mysql_schema_feature_version_floor(version):
    require_mysql_version(version)


def test_driver_error_code_is_visible_without_sql_or_secrets():
    error = pymysql.OperationalError(1273, "secret-in-driver-message")
    wrapped = OperationalError("CREATE USER private-user", {"password": "private-password"}, error)
    for exc in (error, wrapped):
        message = failure_message(exc)
        assert "MySQL 1273" in message
        assert "secret" not in message and "private" not in message and "CREATE" not in message
    assert "secret" not in failure_message(RuntimeError("secret"))
    assert "secret" not in failure_message(pymysql.OperationalError("secret-code", "secret-message"))


@pytest.mark.parametrize("name", ["wms_mysql;DROP DATABASE x", "root@localhost", "../data", "", "a" * 33])
def test_database_identifiers_cannot_change_sql(name):
    with pytest.raises(SetupError):
        identifier(name)


def test_existing_home_refused_before_connection(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Must refuse before connecting")
    monkeypatch.setattr("pymysql.connect", forbidden)
    (tmp_path / "important").write_text("keep")
    with pytest.raises(SetupError, match="ton tai"):
        setup(tmp_path, root_password="never-used")
    assert (tmp_path / "important").read_text() == "keep"


def test_config_is_private_and_rejects_incomplete_or_extra_environment(tmp_path, monkeypatch):
    env = {"WMS_DATABASE_URL": "mysql+pymysql://runtime:secret@127.0.0.1/wms_mysql",
           "WMS_MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
           "WMS_HOST": "127.0.0.1", "WMS_PORT": "8000", "WMS_BUSINESS_TIMEZONE": "Asia/Ho_Chi_Minh"}
    for kind in ("import", "export", "print"):
        (tmp_path / kind).mkdir()
        env[f"WMS_{kind.upper()}_STORAGE_ROOT"] = str(tmp_path / kind)
    config = tmp_path / "runtime.json"
    write_private(config, {"version": 1, "environment": env})
    monkeypatch.setenv("WMS_DATABASE_URL", "postgresql+psycopg://never-use/production")
    monkeypatch.setenv("WMS_OUTBOX_CONSUMER_FACTORY", "untrusted:factory")
    actual = load_environment(tmp_path)
    assert actual["WMS_DATABASE_URL"] == env["WMS_DATABASE_URL"]
    assert "WMS_OUTBOX_CONSUMER_FACTORY" not in actual
    (tmp_path / "setup-incomplete.json").write_text("{}")
    with pytest.raises(SetupError, match="do dang"):
        load_environment(tmp_path)
    (tmp_path / "setup-incomplete.json").unlink()
    env["PYTHONPATH"] = "/untrusted"
    config.write_text(json.dumps({"version": 1, "environment": env}))
    with pytest.raises(SetupError, match="dinh dang"):
        load_environment(tmp_path)
