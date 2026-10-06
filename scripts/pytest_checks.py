"""Fail closed on misplaced DB tests and record exactly what pytest selected."""

import json
import os
from pathlib import Path

import pytest

DATABASE_FIXTURES = {"empty_database", "database", "actor", "iam"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    # Inspect the transitive fixture closure BEFORE -m deselects anything.
    # Do not auto-mark tests: a missing marker is an error to repair, not hide.
    missing = [item.nodeid for item in items if DATABASE_FIXTURES.intersection(item.fixturenames)
               and not item.get_closest_marker("integration")]
    if missing:
        raise pytest.UsageError("DB fixture requires @pytest.mark.integration: " + ", ".join(missing))


def pytest_collection_finish(session):
    selected = [{"nodeid": item.nodeid, "integration": bool(item.get_closest_marker("integration")),
                 "gui": bool(item.get_closest_marker("gui"))} for item in session.items]
    path = os.environ.get("WMS_TEST_COLLECTION_REPORT")
    if path:
        Path(path).write_text(json.dumps({"selected": selected}, indent=2) + "\n", encoding="utf-8")
    suite = os.environ.get("WMS_TEST_SUITE")
    if suite == "all" and not any(item["integration"] for item in selected):
        raise pytest.UsageError("Full suite selected no integration tests")
    if suite == "gui" and not any(item["gui"] for item in selected):
        raise pytest.UsageError("GUI suite selected no GUI tests")
