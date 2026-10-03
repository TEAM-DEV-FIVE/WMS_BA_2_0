"""Export the implemented API schema without connecting to a database."""

import argparse
import json
from pathlib import Path

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    try:
        schema = app.openapi()
    finally:
        app.state.database.dispose()
    path = Path(__file__).resolve().parents[1] / "05_API/openapi_runtime.json"
    if args.check:
        if json.loads(path.read_text(encoding="utf-8")) != schema:
            raise SystemExit("Runtime contract is stale; run scripts/export_runtime_contract.py")
        print("PASS runtime OpenAPI matches implemented routes")
    else:
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Exported {len(schema['paths'])} runtime paths")


if __name__ == "__main__":
    main()
