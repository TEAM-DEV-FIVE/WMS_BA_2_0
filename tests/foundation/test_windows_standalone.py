import json

import pytest
from cryptography.fernet import Fernet

from apps.server.windows_standalone import SetupError, identifier, load_environment, setup, write_private


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
