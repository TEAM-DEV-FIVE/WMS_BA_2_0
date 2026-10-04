"""Exercise pytest as a subprocess so marker/collection failures cannot go green."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect(tmp_path, body, *options):
    suite = tmp_path / "tests" / "future_domain"
    suite.mkdir(parents=True)
    (suite / "test_future.py").write_text(body, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n integration: DB\n gui: Tk\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment.pop("WMS_TEST_SUITE", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["WMS_TEST_COLLECTION_REPORT"] = str(tmp_path / "collection.json")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "scripts.pytest_checks", "tests", "--strict-markers",
         "--collect-only", "-q", *options], cwd=tmp_path, env=environment, capture_output=True, text=True,
    )


def test_new_module_is_collected_with_integration_marker(tmp_path):
    result = collect(tmp_path, "import pytest\n@pytest.mark.integration\ndef test_new(): pass\n", "-m", "integration")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "collection.json").read_text())
    assert report["selected"] == [{"nodeid": "tests/future_domain/test_future.py::test_new", "integration": True, "gui": False}]


def test_db_fixture_cannot_be_misclassified_as_unit_even_when_deselected(tmp_path):
    result = collect(tmp_path, "import pytest\n@pytest.fixture\ndef database(): pass\n"
                     "@pytest.fixture\ndef domain(database): pass\ndef test_new(domain): pass\n", "-m", "integration")
    assert result.returncode != 0
    assert "requires @pytest.mark.integration" in result.stderr


def test_misspelled_marker_is_an_error(tmp_path):
    result = collect(tmp_path, "import pytest\n@pytest.mark.intergration\ndef test_new(): pass\n")
    assert result.returncode != 0
    assert "intergration" in result.stdout
