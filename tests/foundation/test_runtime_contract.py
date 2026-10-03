import json
from pathlib import Path

from openapi_spec_validator import validate

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings


def test_runtime_contract_matches_implementation_and_validates():
    saved = json.loads((Path(__file__).resolve().parents[2] / "05_API/openapi_runtime.json").read_text(encoding="utf-8"))
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    try:
        assert saved == app.openapi()
        validate(saved)
    finally:
        app.state.database.dispose()
