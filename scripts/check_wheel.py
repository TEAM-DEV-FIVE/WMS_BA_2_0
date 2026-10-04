"""Install the wheel in a new prefix and probe it from outside the checkout.

Reuse the caller's locked third-party dependencies, but require every WMS module
to resolve inside the new venv. No editable installation can satisfy this check.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path

from ci_support import ROOT, evidence, logged_run

PROBE = '''
import hashlib
import importlib
import json
import pkgutil
import sys
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

prefix = Path(sys.prefix).resolve()
source = Path(sys.argv[1]).resolve()
for name in ("apps", "packages", "migrations"):
    package = importlib.import_module(name)
    modules = [package] + [importlib.import_module(m.name) for m in pkgutil.walk_packages(package.__path__, name + ".")]
    for module in modules:
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(prefix), (module.__name__, str(path))
        assert not path.is_relative_to(source), str(path)

for entry in distribution("wms-lan").entry_points:
    if entry.group == "console_scripts":
        assert callable(entry.load()), entry.name

expected = json.loads(Path("resources.json").read_text(encoding="utf-8"))
actual = {}
for package in ("migrations", "apps.desktop.local_store"):
    for path in files(package).iterdir():
        if path.name.endswith(".sql"):
            actual[package + "/" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
assert actual == expected, "Wheel SQL resources differ from source"

from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.migrations import expected_revisions
from apps.desktop.local_store.store import LocalStore
from fastapi.testclient import TestClient
assert expected_revisions()
with TestClient(create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))) as client:
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/openapi.json").json()["paths"]
store = LocalStore(Path("local-data"), server_id="https://wheel.invalid/api/v1", user_id=uuid4(), device_id=uuid4())
try:
    draft = store.save_draft("WHEEL_PROBE", {"quantity": "1"})
    assert store.get_draft(draft)
finally:
    store.close()
print("PASS installed WMS modules/entry points, OpenAPI, health, PG SQL checksums and SQLite migrations outside repo")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--report", type=Path, default=ROOT / ".reports/wheel")
    args = parser.parse_args()
    wheels = [args.wheel] if args.wheel else sorted((ROOT / "dist").glob("*.whl"))
    if len(wheels) != 1:
        parser.error("Build exactly one wheel or select it with --wheel")
    wheel = wheels[0].resolve()
    report = args.report.resolve()
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "WMS_DATABASE_URL", "WMS_TEST_DATABASE_URL"):
        environment.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="wms-wheel-") as temporary:
        directory = Path(temporary)
        venv.EnvBuilder(with_pip=True).create(directory / "venv")
        python = directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # A nested venv does not inherit the parent venv's site-packages. Add
        # dependency paths explicitly, without executing the parent's .pth files.
        purelib = Path(subprocess.check_output(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
        ).strip())
        dependencies = sorted({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
        (purelib / "locked_dependencies.pth").write_text("\n".join(dependencies) + "\n", encoding="utf-8")
        status = logged_run([python, "-m", "pip", "install", "--ignore-installed", "--no-deps", "--no-index", wheel],
                            report.with_suffix(".install.log"), cwd=directory, env=environment)
        if status == 0:
            resources = {package + "/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for package in ("migrations", "apps.desktop.local_store")
                         for path in (ROOT / package.replace(".", "/")).glob("*.sql")}
            (directory / "resources.json").write_text(json.dumps(resources), encoding="utf-8")
            status = logged_run([python, "-I", "-c", PROBE, ROOT], report.with_suffix(".log"),
                                cwd=directory, env=environment)
    evidence(report.with_suffix(".environment.json"), wheel=wheel.name,
             wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), result=status,
             dependency_mode="reuse locked third-party packages; WMS installed in fresh prefix")
    return status


if __name__ == "__main__":
    sys.exit(main())
