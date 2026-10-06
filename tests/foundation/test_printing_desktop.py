import threading
import time

import pytest
from test_issues import issuing  # noqa: F401
from test_opening_desktop import opening_ui  # noqa: F401
from test_openings import opening, orders  # noqa: F401

from apps.server.application.outbox import OutboxProcessor
from apps.server.application.print_jobs import PrintExecutor, consumer_factory
from apps.server.application.printing import PrintSettings
from apps.server.infrastructure.file_storage import FileStorage
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = [pytest.mark.integration, pytest.mark.gui]
# ruff: noqa: F811


def test_print_desktop_real_http_preview_save_and_session_fence(opening_ui, tmp_path, monkeypatch):
    f = opening_ui
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    view = f.shell.print_view
    root = f.shell.root
    f.shell.notebook.select(view)

    def wait(predicate=None):
        predicate = predicate or (lambda: view.presenter.pending is None)
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.005)
        assert predicate(), view.variables["status"].get()

    view.template.set("Tem hàng / serial")
    view.template_changed()
    view.variables["search"].set(f.product["sku"])
    view.search()
    wait()
    assert len(view.sources) == 1, view.variables["status"].get()
    service = f.client.app.state.printing
    service.storage = FileStorage(PrintSettings(storage_root=tmp_path / "print"))
    view.create()
    wait()
    assert view.presenter.job, view.variables["status"].get()
    outbox = OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory())
    assert outbox.run_batch().processed == 1
    assert PrintExecutor(service).run_one() == "READY"
    view.presenter.refresh()
    wait()
    view.presenter.preview()
    wait()
    assert view.image
    root.geometry("800x620")
    root.update()
    assert view.canvas.winfo_height() > 100
    from pathlib import Path

    from PIL import ImageGrab

    report = Path(".reports/b18-print-preview.png")
    report.parent.mkdir(exist_ok=True)
    ImageGrab.grab().save(report)
    path = tmp_path / "tem.pdf"
    view.presenter.download(path)
    wait()
    assert path.read_bytes().startswith(b"%PDF-")
    entered, release = threading.Event(), threading.Event()
    original = view.presenter.api.file_request

    def late(*args, **kw):
        result = original(*args, **kw)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(view.presenter.api, "file_request", late)
    path.write_bytes(b"keep")
    view.presenter.download(path)
    wait(entered.is_set)
    view.presenter.reset()
    release.set()
    wait(lambda: not view.presenter.results.empty())
    view.presenter.drain()
    assert path.read_bytes() == b"keep" and view.image is None


def test_print_lost_spool_ack_recovery_never_calls_device(opening_ui, tmp_path, monkeypatch):
    from apps.desktop.api.client import ApiError

    f = opening_ui
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    view = f.shell.print_view

    def wait():
        deadline = time.monotonic() + 15
        while view.presenter.pending and time.monotonic() < deadline:
            f.shell.root.update()
            time.sleep(0.005)
        assert view.presenter.pending is None, view.variables["status"].get()

    view.template.set("Tem hàng / serial")
    view.template_changed()
    view.variables["search"].set(f.product["sku"])
    view.search()
    wait()
    service = f.client.app.state.printing
    service.storage = FileStorage(PrintSettings(storage_root=tmp_path / "print"))
    view.create()
    wait()
    OutboxProcessor(PostgresOutboxStore(f.engine), consumer_factory()).run_batch()
    assert PrintExecutor(service).run_one() == "READY"
    view.presenter.refresh()
    wait()
    original = view.presenter.api.command
    calls = []
    spools = []

    def lost(*args):
        result = original(*args)
        if args[1].endswith("/spool"):
            calls.append(args)
            if len(calls) == 1:
                raise ApiError("TIMEOUT", "Lost ACK")
        return result

    monkeypatch.setattr(view.presenter.api, "command", lost)
    monkeypatch.setattr("apps.desktop.printing.presenter.spool_submit", lambda *a: spools.append(a))
    view.presenter.spool("Q", "CUPS", 1, "Kiểm thử")
    wait()
    assert view.presenter.commands and not spools
    view.presenter.recover()
    wait()
    assert calls[0] == calls[1] and not spools
    assert view.presenter.job["attempt"]["status"] == "UNKNOWN"


def test_issue_hid_widget_real_http_selects_line_without_post(issuing, opening_ui):
    f = issuing
    f.seed()
    doc = f.issue_approve()
    view = f.shell.issue_view
    root = f.shell.root
    f.shell.notebook.select(view)

    def wait(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.005)
        assert predicate(), view.scan_bar.status.get()

    view.presenter.read(doc["id"])
    wait(lambda: view.doc is not None and not view.busy)
    view.scan_bar.quantity.set("2")
    view.scan_bar.scan(f.product["sku"])
    wait(lambda: view.scan_bar.pending is None)
    assert view.variables["qty"].get() == "2"
    assert view.line_table.selection() == ("0",)
    from test_issues import inventory

    assert inventory(f) == (0, 10, 0, 0)
