"""Reuse the same disposable PostgreSQL/API fixtures as the application suite."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("lan_shared_fixtures", ROOT / "tests/conftest.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
empty_database = shared.empty_database
database = shared.database
iam = shared.iam
isolated_desktop_data = shared.isolated_desktop_data
pytest_plugins = ["scripts.pytest_checks"]
