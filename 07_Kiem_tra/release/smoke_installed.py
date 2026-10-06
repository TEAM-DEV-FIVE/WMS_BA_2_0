"""Run with the offline prefix Python -I, outside the checkout. No database/service mutation."""

import hashlib
import importlib
import json
import pkgutil
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from uuid import uuid4


def main():
    prefix = Path(sys.prefix).resolve()
    count = 0
    for name in ("apps", "packages", "migrations"):
        root = importlib.import_module(name)
        modules = [root] + [importlib.import_module(m.name) for m in pkgutil.walk_packages(root.__path__, name + ".")]
        for module in modules:
            assert Path(module.__file__).resolve().is_relative_to(prefix), module.__name__
            count += 1
    from fastapi.testclient import TestClient

    from apps.desktop.local_store.store import LocalStore
    from apps.server.api.app import create_app
    from apps.server.application.print_render import render
    from apps.server.infrastructure.config import Settings

    with TestClient(create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))) as client:
        assert client.get("/api/v1/health").status_code == 200
        paths = len(client.get("/api/v1/openapi.json").json()["paths"])
        assert paths == 189
    with tempfile.TemporaryDirectory(prefix="wms-offline-cache-") as folder:
        store = LocalStore(Path(folder), server_id="https://offline-smoke.invalid/api/v1",
                           user_id=uuid4(), device_id=uuid4())
        try:
            draft = store.save_draft("OFFLINE_INSTALL_PROBE", {"quantity": "1"})
            assert store.get_draft(draft)
        finally:
            store.close()
    pdf = render(dict(template="LOCATION_LABEL", paper="80x40",
                      header=dict(number="K01", name="Kho tiếng Việt", barcode="K01", symbology="QR")))
    assert pdf.startswith(b"%PDF-")
    sql = sorted(p.name for p in files("migrations").iterdir() if p.name.endswith(".sql"))
    assert len(sql) == 24
    print(json.dumps({"result": "PASS", "prefix": str(prefix), "modules": count, "runtime_paths": paths,
                      "postgres_migrations": len(sql), "local_cache": "PASS", "pdf": "PASS",
                      "pdf_sha256": hashlib.sha256(pdf).hexdigest(), "runtime_db_contacted": False}))


if __name__ == "__main__":
    main()
