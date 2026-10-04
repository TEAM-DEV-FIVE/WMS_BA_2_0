import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from packages.contracts import Error
from scripts.export_runtime_contract import operations, review_contract

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = json.loads((ROOT / "05_API/openapi_runtime.json").read_text(encoding="utf-8"))


def test_runtime_contract_matches_implementation_and_validates():
    saved = json.loads((Path(__file__).resolve().parents[2] / "05_API/openapi_runtime.json").read_text(encoding="utf-8"))
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    try:
        assert saved == app.openapi()
        validate(saved)
    finally:
        app.state.database.dispose()


def test_contract_inventory_is_current_without_dropping_planned_apis():
    design = json.loads((ROOT / "05_API/openapi_core.json").read_text(encoding="utf-8"))
    saved = json.loads((ROOT / "05_API/contract_inventory.json").read_text(encoding="utf-8"))
    assert saved == review_contract(RUNTIME, design)
    assert len(saved["design_operations"]) == len(operations(design))
    assert any(row["status"] == "PLANNED" for row in saved["design_operations"])
    public = {("GET", "/api/v1/health"), ("GET", "/api/v1/ready"),
              *(("POST", "/api/v1/auth/" + name) for name in ("login", "mfa", "refresh", "password/reset", "mfa/recover"))}
    for key, operation in operations(RUNTIME).items():
        assert bool(operation.get("security")) == (key not in public), key
        if key not in public:
            for status in ("401", "403", "404", "409", "422", "503"):
                error = operation["responses"][status]["content"]["application/json"]["schema"]
                assert error == {"$ref": "#/components/schemas/Error"}, (key, status)
    for row in saved["runtime_operations"]:
        if row["method"] in {"POST", "PUT", "PATCH", "DELETE"} and row["tags"] != ["identity"]:
            assert row["idempotency_key_required"], row
        if row["method"] == "PUT":
            assert row["expected_version_required"], row
        if row["path"].endswith("/post"):
            assert row["execution_key_required"] and row["expected_version_required"], row


@pytest.mark.parametrize("method,path", [key for key, op in operations(RUNTIME).items() if op.get("security")])
def test_every_protected_route_rejects_missing_bearer_before_database(method, path):
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/wms_test_unreachable"))
    concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
    with TestClient(app) as client:
        response = client.request(method, concrete)
    assert response.status_code == 401, (method, path, response.text)
    assert Error.model_validate(response.json()).code == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"
