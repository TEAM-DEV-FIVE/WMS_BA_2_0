import ast
import json
import logging
from pathlib import Path
from uuid import UUID

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
