import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.migrations import is_ready, migrate, migration_sources
from scripts import lan_probe, lan_runtime, lan_stage

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def profile(tmp_path):
    config = tmp_path / "runtime.env"
    raw = (ROOT / "deploy/lan/runtime.env.example").read_text()
    for kind in ("import", "export", "print"):
        root = tmp_path / kind
        root.mkdir(mode=0o700)
        raw = raw.replace("/srv/wms/" + kind, str(root))
    config.write_text(raw)
    config.chmod(0o644)
    credential = tmp_path / "mfa.env"
    credential.write_text("WMS_MFA_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
    credential.chmod(0o600)
    return config, credential


def test_profile_overrides_inherited_config_without_shell(profile, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setenv("WMS_OUTBOX_CONSUMER_FACTORY", "evil:factory")
    lan_runtime.configure(*profile)
    settings, worker, roots = lan_runtime.validate_config()
    assert settings.host == "127.0.0.1" and settings.pool_size == 3
    assert worker.consumer_factory == lan_runtime.FACTORY and len(roots) == 3


@pytest.mark.parametrize("change", ["tcp", "owner", "public_api", "symlink", "nested", "permissions", "mfa", "typo"])
def test_profile_rejects_unsafe_configuration(profile, monkeypatch, tmp_path, change):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    lan_runtime.configure(*profile)
    if change == "tcp":
        monkeypatch.setenv("WMS_DATABASE_URL", "postgresql+psycopg://wms_app@localhost/wms")
    elif change == "owner":
        monkeypatch.setenv("WMS_DATABASE_URL", "postgresql+psycopg://wms_owner@/wms?host=/var/run/postgresql")
    elif change == "public_api":
        monkeypatch.setenv("WMS_HOST", "0.0.0.0")
    elif change == "symlink":
        (tmp_path / "alias").symlink_to(tmp_path / "import")
        monkeypatch.setenv("WMS_IMPORT_STORAGE_ROOT", str(tmp_path / "alias"))
    elif change == "nested":
        (tmp_path / "import/child").mkdir(mode=0o700)
        monkeypatch.setenv("WMS_EXPORT_STORAGE_ROOT", str(tmp_path / "import/child"))
    elif change == "permissions":
        (tmp_path / "import").chmod(0o755)
    elif change == "mfa":
        monkeypatch.delenv("WMS_MFA_ENCRYPTION_KEY")
    else:
        monkeypatch.setenv("WMS_OUTBOX_MAX_ATTEMPT", "1")
    with pytest.raises(ValueError):
        lan_runtime.validate_config()


@pytest.mark.parametrize("mode,text_value", [(0o644, "WMS_SECRET=abc\n"), (0o600, "export WMS_SECRET=x\n"),
                                            (0o600, "WMS_SECRET=x\nWMS_SECRET=y\n")])
def test_credential_parser_fails_closed(tmp_path, mode, text_value):
    f = tmp_path / "secret"
    f.write_text(text_value)
    f.chmod(mode)
    with pytest.raises(ValueError):
        lan_runtime.read_config(f, secret=True)


def test_failure_output_never_contains_secret(profile, capsys, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    profile[1].write_text("WMS_MFA_ENCRYPTION_KEY=do-not-log-this-secret\n")
    assert lan_runtime.main(["check", "--config", str(profile[0]), "--credential", str(profile[1])]) == 1
    output = capsys.readouterr()
    assert "do-not-log" not in output.err + output.out
    assert "CHECK_CONFIG_DB_STORAGE" in output.err


def bundle_at(path):
    path.mkdir()
    (path / "wheels").mkdir()
    for name, data in {"wms_lan-0.1.0-py3-none-any.whl": b"fixture bytes for manifest tests only",
                       "wheels/example-1-py3-none-any.whl": b"dependency fixture",
                       "requirements-app-lock.txt": b"example==1\n", "lan_runtime.py": b"# fixture\n"}.items():
        (path / name).write_bytes(data)
    entries = {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in path.rglob("*") if p.is_file()}
    (path / "manifest.json").write_text(json.dumps(entries))
    return hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("tamper", ["digest", "extra", "symlink", "traversal", "pip_option"])
def test_bundle_verification_rejects_tamper(tmp_path, tamper):
    bundle = tmp_path / "bundle"
    digest = bundle_at(bundle)
    assert lan_stage.verify_bundle(bundle, digest).startswith("wms_lan-")
    if tamper == "digest":
        (bundle / "lan_runtime.py").write_text("changed")
    elif tamper == "extra":
        (bundle / "wheels/injected.whl").write_text("extra")
    elif tamper == "symlink":
        (bundle / "lan_runtime.py").unlink()
        (bundle / "lan_runtime.py").symlink_to(tmp_path / "other")
    else:
        entries = json.loads((bundle / "manifest.json").read_text())
        if tamper == "traversal":
            entries["../evil"] = "0" * 64
        else:
            (bundle / "requirements-app-lock.txt").write_text("--extra-index-url https://invalid\n")
            entries["requirements-app-lock.txt"] = hashlib.sha256(
                (bundle / "requirements-app-lock.txt").read_bytes()).hexdigest()
        (bundle / "manifest.json").write_text(json.dumps(entries))
        digest = hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        lan_stage.verify_bundle(bundle, digest)
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("url", ["http://host/api/v1", "https://user:pass@host/api/v1", "https://host/api/v1?token=x"])
def test_probe_refuses_insecure_or_secret_url(url):
    with pytest.raises(ValueError):
        lan_probe.probe(url, None)


@pytest.mark.integration
def test_runtime_role_works_without_ddl_or_history_write(database, iam):
    user, _ = iam.user("runtime-account")
    iam.grant(user, "MASTER_DATA")
    role = "lan_" + uuid4().hex
    with database.begin() as c:
        c.exec_driver_sql(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        c.exec_driver_sql(f'REVOKE CREATE ON DATABASE "{database.url.database}" FROM PUBLIC')
        c.exec_driver_sql((ROOT / "deploy/lan/postgresql/runtime-grants.sql").read_text()
                         .replace("wms_app", role).replace("BEGIN;", "").replace("COMMIT;", ""))
    engine = create_engine(database.url.set(username=role))
    try:
        lan_runtime.database_check(engine)
        with engine.begin() as c:
            c.execute(text("INSERT INTO wms.worker_status(id,kind,registry_hash,state) VALUES (:id,'outbox',:h,'IDLE')"),
                      {"id": uuid4(), "h": "a" * 64})
        with TestClient(create_app(Settings(database_url=engine.url.render_as_string(hide_password=False)),
                                   engine=engine)) as client:
            assert client.get("/api/v1/ready").status_code == 200
            assert client.get("/api/v1/operations/workers").status_code == 401
            login = client.post("/api/v1/auth/login", json={"username": "runtime-account",
                                "password": "Test-only-password-2026!", "device_id": str(uuid4())})
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"],
                       "Idempotency-Key": str(uuid4()), "X-WMS-Recovery": "send-v1"}
            body = {"code": "RUNTIME", "name": "Unit", "decimal_places": 0, "reason": "Privilege check"}
            first = client.post("/api/v1/master/uoms", json=body, headers=headers)
            assert first.status_code == 201, first.text
            assert first.headers.get("X-WMS-ACK")
            assert client.post("/api/v1/master/uoms", json=body, headers=headers).json() == first.json()
        for sql in ("CREATE TABLE wms.intrusion(id int)", "CREATE TABLE public.intrusion(id int)",
                    "DELETE FROM public.wms_schema_migration", "TRUNCATE wms.worker_status",
                    "ALTER TABLE wms.stock_move DISABLE TRIGGER ALL"):
            with pytest.raises(DBAPIError), engine.begin() as c:
                c.exec_driver_sql(sql)
    finally:
        engine.dispose()
        with database.begin() as c:
            c.exec_driver_sql(f'DROP OWNED BY "{role}"')
            c.exec_driver_sql(f'DROP ROLE "{role}"')


@pytest.mark.integration
def test_failed_candidate_migration_preserves_previous_release_and_data(database, monkeypatch):
    from apps.server.infrastructure import migrations

    with database.begin() as c:
        c.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:id,'B21','B21',true)"),
                  {"id": uuid4()})
    sources = migration_sources()
    bad = "CREATE TABLE wms.must_rollback(id int); SELECT 1/0;"
    with monkeypatch.context() as m:
        m.setattr(migrations, "migration_sources", lambda: sources + [
            ("025_test_failure.sql", hashlib.sha256(bad.encode()).hexdigest(), bad)])
        with pytest.raises(DBAPIError):
            migrate(database)
        assert not is_ready(database)
        app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"), engine=database)
        with TestClient(app) as client:
            assert client.get("/api/v1/ready").status_code == 503
    assert is_ready(database)
    with database.connect() as c:
        assert c.execute(text("SELECT to_regclass('wms.must_rollback')")).scalar_one() is None
        assert c.execute(text("SELECT count(*) FROM wms.warehouse WHERE code='B21'")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM public.wms_schema_migration")).scalar_one() == 24


@pytest.mark.integration
def test_unprivileged_owner_can_upgrade_023_with_data(empty_database, monkeypatch):
    from apps.server.infrastructure import migrations

    role = "owner_" + uuid4().hex
    with empty_database.begin() as c:
        c.exec_driver_sql(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        c.exec_driver_sql(f'ALTER DATABASE "{empty_database.url.database}" OWNER TO "{role}"')
    engine = create_engine(empty_database.url.set(username=role))
    try:
        lan_runtime.database_check(engine, migration=True)
        sources = migration_sources()
        with monkeypatch.context() as m:
            m.setattr(migrations, "migration_sources", lambda: sources[:-1])
            assert len(migrate(engine)) == 23
        with engine.begin() as c:
            c.execute(text("INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:id,'UPGRADE','Keep',true)"),
                      {"id": uuid4()})
        assert migrate(engine) == ["024_b20_outbox_operations.sql"]
        assert is_ready(engine)
        with engine.connect() as c:
            assert c.execute(text("SELECT name FROM wms.warehouse WHERE code='UPGRADE'")).scalar_one() == "Keep"
    finally:
        engine.dispose()
        with empty_database.begin() as c:
            c.exec_driver_sql(f'ALTER DATABASE "{empty_database.url.database}" OWNER TO CURRENT_USER')
            c.exec_driver_sql(f'DROP OWNED BY "{role}" CASCADE')
            c.exec_driver_sql(f'DROP ROLE "{role}"')


@pytest.mark.integration
def test_monitor_requires_all_six_kinds_and_rejects_wrong_registry(database):
    fingerprint = "a" * 64
    assert not lan_runtime.workers_ready(database, fingerprint)
    ids = []
    with database.begin() as c:
        for kind in lan_runtime.KINDS:
            ids.append(uuid4())
            c.execute(text("INSERT INTO wms.worker_status(id,kind,registry_hash,state) VALUES (:id,:k,:h,'IDLE')"),
                      {"id": ids[-1], "k": kind, "h": fingerprint})
    assert lan_runtime.workers_ready(database, fingerprint)
    with database.begin() as c:
        c.execute(text("UPDATE wms.worker_status SET heartbeat_at=now()-interval '121 seconds' WHERE id=:id"),
                  {"id": ids[0]})
    assert not lan_runtime.workers_ready(database, fingerprint)
    with database.begin() as c:
        c.execute(text("UPDATE wms.worker_status SET heartbeat_at=now(), registry_hash=:h WHERE id=:id"),
                  {"id": ids[0], "h": "b" * 64})
    assert not lan_runtime.workers_ready(database, fingerprint)


def test_cli_errors_are_redacted():
    result = subprocess.run([sys.executable, "scripts/lan_runtime.py", "check", "--config", "/nonexistent",
                             "--credential", "/nonexistent"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1 and "Traceback" not in result.stderr
