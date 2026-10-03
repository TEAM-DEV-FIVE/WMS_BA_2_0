"""Export the implemented API schema without connecting to a database."""

import argparse
import json
import re
from pathlib import Path

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings

ROOT = Path(__file__).resolve().parents[1]
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def operations(schema):
    return {(method.upper(), path): operation for path, item in schema["paths"].items()
            for method, operation in item.items() if method in METHODS}


def route_key(method, path):
    return method, re.sub(r"\{[^}]+\}", "{}", path.removeprefix("/api/v1"))


def review_contract(schema, design):
    """Route presence is not DTO equivalence or business acceptance."""
    runtime = operations(schema)
    index = {route_key(*key): key for key in runtime}
    design_rows = []
    for (method, path), operation in sorted(operations(design).items()):
        match = index.get(route_key(method, path))
        design_rows.append({"method": method, "design_path": path,
                            "status": "IMPLEMENTED_ROUTE_REVIEW_DTO" if match else "PLANNED",
                            "runtime_path": match[1] if match else None})
    runtime_rows = []
    for (method, path), operation in sorted(runtime.items()):
        body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in body:
            body = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]
        required = body.get("required", [])
        headers = [p["name"] for p in operation.get("parameters", []) if p["in"] == "header" and p.get("required")]
        runtime_rows.append({
            "method": method, "path": path, "tags": operation.get("tags", []),
            "bearer_auth": bool(operation.get("security")),
            "idempotency_key_required": "Idempotency-Key" in headers,
            "expected_version_required": "expected_version" in required,
            "execution_key_required": "execution_key" in required,
            "documented_errors": sorted(code for code in operation["responses"] if code[0] in "45"),
            "untyped_success": any(not response.get("content", {}).get("application/json", {}).get("schema")
                                   for code, response in operation["responses"].items() if code.startswith("2")),
        })
    return {"note": "Generated route inventory only; permission policy and DTO differences: CONTRACT_REVIEW.md. "
                    "PLANNED routes remain in openapi_core.json. No acceptance status is inferred.",
            "design_operations": design_rows, "runtime_operations": runtime_rows}


def write_or_check(path, value, check):
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if check:
        if path.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"Stale {path.name}; run scripts/export_runtime_contract.py")
    else:
        path.write_text(rendered, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    try:
        schema = app.openapi()
    finally:
        app.state.database.dispose()
    design = json.loads((ROOT / "05_API/openapi_core.json").read_text(encoding="utf-8"))
    write_or_check(ROOT / "05_API/openapi_runtime.json", schema, args.check)
    write_or_check(ROOT / "05_API/contract_inventory.json", review_contract(schema, design), args.check)
    print(f"PASS {'checked' if args.check else 'exported'} {len(schema['paths'])} runtime paths and contract inventory")


if __name__ == "__main__":
    main()
