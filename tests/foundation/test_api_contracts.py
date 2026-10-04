import ast
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from packages.contracts import Error, PositiveQuantity

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def api():
    return create_app(Settings(database_url="postgresql+psycopg://localhost/wms_test_unreachable",
                               database_timeout_seconds=1))


def test_health_does_not_need_database(api):
    with TestClient(api) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        UUID(response.headers["X-Request-ID"])
        assert {"/api/v1/health", "/api/v1/ready", "/api/v1/auth/login"} <= set(client.get("/api/v1/openapi.json").json()["paths"])


def test_errors_conform_to_design_and_never_echo_input(api, caplog):
    class LoginProbe(BaseModel):
        password: SecretStr

    @api.post("/probe")
    def probe(payload: LoginProbe):
        raise RuntimeError("server-secret-password")

    caplog.set_level(logging.INFO, logger="wms.api")
    with TestClient(api) as client:
        response = client.post("/probe", json={"password": {"secret": "client-secret-password"}})
        assert response.status_code == 422
        Error.model_validate(response.json())
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert "client-secret-password" not in response.text
        response = client.post("/probe", json={"password": "valid-but-secret"})
        assert response.status_code == 500
        assert "server-secret-password" not in response.text
        response = client.get("/missing?token=hidden", headers={"X-Request-ID": "injected-value"})
        assert response.status_code == 404
        UUID(response.headers["X-Request-ID"])
    logs = "\n".join(record.message for record in caplog.records if record.name == "wms.api")
    for value in ["client-secret-password", "server-secret-password", "valid-but-secret", "hidden", "injected-value"]:
        assert value not in logs
    design = json.loads((ROOT / "05_API/openapi_core.json").read_text())
    assert set(design["components"]["schemas"]["Error"]["required"]) <= set(response.json())


@pytest.mark.parametrize("value", [80, 1.2, "0", "0.000000", "-1", "1e3", "NaN", "1.0000001", "100000000000000", "01"])
def test_invalid_quantities_are_rejected(value):
    with pytest.raises(ValidationError):
        TypeAdapter(PositiveQuantity).validate_python(value)


@pytest.mark.parametrize("value", ["80", "0.000001", "99999999999999.999999", "10.500000"])
def test_quantities_remain_strings(value):
    assert TypeAdapter(PositiveQuantity).validate_python(value) == value


def test_settings_require_postgres_and_hide_credentials(monkeypatch):
    monkeypatch.delenv("WMS_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError) as error:
        Settings(database_url="sqlite:///super-secret")
    assert "super-secret" not in str(error.value)
    assert "super-secret" not in repr(Settings(database_url="postgresql+psycopg://u:super-secret@localhost/wms"))


def test_domain_and_contracts_have_no_ui_or_persistence_imports():
    for directory in [ROOT / "apps/server/domain", ROOT / "packages/contracts"]:
        for path in directory.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                assert not any(name.startswith(("tkinter", "httpx", "fastapi", "sqlalchemy", "psycopg", "apps")) for name in names)


def test_business_timezone_works_without_os_timezone_database():
    import zoneinfo
    original = zoneinfo.TZPATH
    try:
        zoneinfo.ZoneInfo.clear_cache()
        zoneinfo.reset_tzpath([])
        settings = Settings(database_url="postgresql+psycopg://localhost/unused")
        assert zoneinfo.ZoneInfo(settings.business_timezone).key == "Asia/Ho_Chi_Minh"
        with pytest.raises(ValidationError):
            Settings(database_url="postgresql+psycopg://localhost/unused", business_timezone="Invalid/Fixture")
    finally:
        zoneinfo.reset_tzpath(original)
        zoneinfo.ZoneInfo.clear_cache()


def test_desktop_only_uses_api_and_local_storage():
    forbidden = ("apps.server", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "migrations")
    for path in (ROOT / "apps/desktop").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    package = list(path.relative_to(ROOT).parts[:-1])
                    module = ".".join(package[:len(package) - node.level + 1] + ([module] if module else []))
                names.extend([module, *(module + "." + alias.name for alias in node.names)])
            assert not any(name == blocked or name.startswith(blocked + ".")
                           for name in names for blocked in forbidden), (path, names)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "WMS_DATABASE_URL" not in node.value, path
                assert not node.value.startswith(("postgresql://", "postgresql+psycopg://")), path


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = Error.model_validate(response.json())
    assert body.code == code
    assert str(body.request_id) == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    return body


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["checksum", "unknown", "gap"])
def test_readiness_contract_rejects_incompatible_history(database, damage):
    from sqlalchemy import text

    from apps.server.infrastructure.migrations import MigrationError, migrate

    with database.begin() as connection:
        if damage == "checksum":
            connection.execute(text("UPDATE public.wms_schema_migration SET sha256=:digest WHERE version='001_schema.sql'"),
                               {"digest": "0" * 64})
        elif damage == "unknown":
            connection.execute(text("INSERT INTO public.wms_schema_migration(version,sha256) VALUES ('999_unknown.sql',:digest)"),
                               {"digest": "0" * 64})
        else:
            connection.execute(text("DELETE FROM public.wms_schema_migration WHERE version='001_schema.sql'"))
    api = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"), engine=database)
    with TestClient(api) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert assert_error(client.get("/api/v1/ready"), 503, "DATABASE_NOT_READY").retryable
    with pytest.raises(MigrationError):
        migrate(database)


@pytest.mark.integration
def test_real_api_permission_version_idempotency_and_unknown_operation_contract(iam):
    user, _ = iam.user()
    headers = iam.headers(iam.login())
    path = "/api/v1/master/uoms"
    payload = {"code": "CT", "name": "Contract", "decimal_places": 0, "reason": "Contract probe"}
    key = str(uuid4())
    command_headers = {**headers, "Idempotency-Key": key}
    assert_error(iam.client.post(path, json=payload, headers=command_headers), 403, "FORBIDDEN")
    grant = iam.grant(user, "MASTER_DATA")
    assert_error(iam.client.post(path, json=payload, headers=headers), 422, "VALIDATION_ERROR")
    created = iam.client.post(path, json=payload, headers=command_headers)
    assert created.status_code == 201, created.text
    assert iam.client.post(path, json=payload, headers=command_headers).json() == created.json()
    assert_error(iam.client.post(path, json={**payload, "name": "Other"}, headers=command_headers),
                 409, "IDEMPOTENCY_MISMATCH")
    entity = created.json()
    changed = iam.client.put(path + "/" + entity["id"],
                             json={**payload, "expected_version": entity["version"], "name": "New"},
                             headers={**headers, "Idempotency-Key": str(uuid4())})
    assert changed.status_code == 200, changed.text
    assert_error(iam.client.put(path + "/" + entity["id"],
                               json={**payload, "expected_version": entity["version"]},
                               headers={**headers, "Idempotency-Key": str(uuid4())}), 409, "STALE_VERSION")
    # Lookup is receipt.post-only; a 404 must never authorize retry with a new key.
    for lookup in (key, str(uuid4())):
        assert_error(iam.client.get("/api/v1/operations/" + lookup, headers=headers), 404, "NOT_FOUND")
    from sqlalchemy import text
    with iam.engine.begin() as connection:
        connection.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": grant})
    assert_error(iam.client.post(path, json=payload, headers=command_headers), 403, "FORBIDDEN")
