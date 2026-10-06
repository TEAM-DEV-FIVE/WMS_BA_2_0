import threading
import time

import pytest
from test_opening_desktop import opening_ui  # noqa: F401
from test_openings import opening, orders  # noqa: F401
from test_reports_exports import reports  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.gui]


def test_reports_gui_real_http_pg_export_and_stale_download(reports, opening_ui, tmp_path, monkeypatch):  # noqa: F811
    f = reports
    view = opening_ui.shell.report_view
    root = f.shell.root
    f.shell.notebook.select(view)

    def wait(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.005)
        assert predicate(), view.status.get()

    view.variables["product"].set(f.product["sku"])
    view.variables["locations"].set(f.location["code"])
    view.create()
    wait(lambda: view.presenter.pending is None)
    assert view.presenter.snapshot, view.status.get()
    assert len(view.tree.get_children()) == 1
    view.presenter.export("xlsx")
    wait(lambda: view.presenter.pending is None)
    assert view.presenter.job["status"] == "QUEUED"
    assert f.export_outbox.run_batch().processed == 1
    assert f.exporter.run_one() == "READY"
    view.presenter.refresh()
    wait(lambda: view.presenter.pending is None)
    # Reopen after losing the current in-memory job, through real API history.
    job_id = view.presenter.job["id"]
    view.presenter.job = None
    view.history.load()
    wait(lambda: view.presenter.pending is None)
    assert job_id in view.history.rows
    view.history.tree.selection_set(job_id)
    view.history.open_selected()
    wait(lambda: view.presenter.pending is None)
    assert view.presenter.job["id"] == job_id
    destination = tmp_path / "report.xlsx"
    view.presenter.download(str(destination))
    wait(lambda: view.presenter.pending is None)
    assert destination.read_bytes().startswith(b"PK")
    entered, release = threading.Event(), threading.Event()
    original = view.presenter.api.file_request

    def late(*args, **kwargs):
        response = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return response

    monkeypatch.setattr(view.presenter.api, "file_request", late)
    destination.write_bytes(b"Keep original")
    view.presenter.download(str(destination))
    wait(entered.is_set)
    view.presenter.reset()
    release.set()
    wait(lambda: bool(view.presenter.results.qsize()))
    view.presenter.drain()
    assert destination.read_bytes() == b"Keep original"
    assert not view.tree.get_children()
    assert view.presenter.snapshot is None
    assert not view.history.rows


def test_reports_gui_unknown_ack_retries_exact_key(reports, opening_ui, monkeypatch):  # noqa: F811
    from apps.desktop.api.client import ApiError

    f = reports
    view = f.shell.report_view

    def wait():
        deadline = time.monotonic() + 15
        while view.presenter.pending and time.monotonic() < deadline:
            f.shell.root.update()
            time.sleep(0.005)
        assert view.presenter.pending is None

    original = view.presenter.api.command
    calls = []

    def lost(*args):
        calls.append(args)
        result = original(*args)
        if len(calls) == 1:
            raise ApiError("TIMEOUT", "Lost ACK")
        return result

    monkeypatch.setattr(view.presenter.api, "command", lost)
    view.create()
    wait()
    assert view.presenter.uncertain
    view.presenter.recover()
    wait()
    assert calls[0] == calls[1]
    assert view.presenter.snapshot and not view.presenter.uncertain
    assert len(view.tree.get_children()) == 1
