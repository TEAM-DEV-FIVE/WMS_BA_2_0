import threading
import time
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from test_consignments import agreement
from test_imports import csv_bytes, imports  # noqa: F401
from test_opening_desktop import opening_ui  # noqa: F401
from test_openings import inventory, opening, orders  # noqa: F401
from test_orders import ok

from apps.desktop.api.client import ApiError
from apps.server.application.import_templates import TEMPLATES

pytestmark = [pytest.mark.integration, pytest.mark.gui]


@pytest.fixture
def import_ui(imports, opening_ui, tmp_path, monkeypatch):  # noqa: F811
    f, view = imports, opening_ui.shell.import_view
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return f.iam.now
    monkeypatch.setattr("apps.desktop.views.imports.datetime", Clock)
    f.shell.notebook.select(view)

    def wait(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            f.shell.root.update()
            time.sleep(0.005)
        assert predicate(), view.variables["status"].get()

    def idle():
        wait(lambda: view.presenter.pending is None and not view.busy)

    def select(kind):
        view.kind.current(list(TEMPLATES).index(kind))
        view.scope_changed()
        idle()

    def prepare(kind="01_uom", rows=None, *, validate=True):
        select(kind)
        path = tmp_path / "tệp kiểm thử.csv"
        path.write_bytes(csv_bytes(kind, rows or [["B16", "Đơn vị mới", 0]]))
        view.choose(str(path))
        idle()
        assert view.presenter.source, view.variables["status"].get()
        view.presenter.upload()
        idle()
        assert view.presenter.file, view.variables["status"].get()
        view.variables["reason"].set("Kiểm thử B16 qua HTTP thật")
        view.variables["reference"].set("BB-DA-KY-B16")
        view.action("create")
        idle()
        assert view.job, view.variables["status"].get()
        if validate:
            assert f.outbox.run_batch().processed >= 1
            assert f.executor.run_one() in {"VALIDATED", "INVALID", "FAILED"}
            view.refresh()
            idle()
        return path

    idle()
    f.import_view, f.import_idle, f.import_wait, f.import_select, f.import_prepare = view, idle, wait, select, prepare
    try:
        yield f
    finally:
        f.import_view = f.import_idle = f.import_wait = f.import_select = f.import_prepare = None


def commit(f):
    view = f.import_view
    view.variables["reason"].set("Xác nhận dữ liệu đã đối chiếu")
    view.confirm.set(True)
    view.enable()
    view.action("commit")
    f.import_idle()


def test_import_gui_opening_company_consigned_to_approval_and_post(import_ui):
    f, view = import_ui, import_ui.import_view
    owner, contract = agreement(f)
    f.import_prepare("11_opening", [
        ["B16-OPEN", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 10, "COMPANY", ""],
        ["B16-OPEN", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 5, owner["code"], contract["code"]],
    ])
    assert view.job["status"] == "VALIDATED" and inventory(f) == (0, 0, 0, 0)
    assert "200" in view.variables["limits"].get() and "khởi tạo tồn" in view.variables["limits"].get()
    assert view.table.item("3", "values")[2:4] == (owner["code"], contract["code"])
    commit(f)
    assert view.job["status"] == "COMMITTED" and inventory(f) == (0, 0, 0, 0)
    view.table.selection_set("2")
    view.open_target()
    f.idle()
    opening_view = f.shell.opening_view
    assert opening_view.doc["status"] == "DRAFT" and len(opening_view.lines) == 2
    doc_id = opening_view.doc["id"]
    opening_view.variables["reason"].set("Gửi duyệt tồn import")
    opening_view.action("submit")
    f.idle()
    f.login_ui("director")
    opening_view.presenter.read(doc_id)
    f.idle()
    opening_view.variables["reason"].set("Duyệt biên bản nhập ban đầu")
    opening_view.action("approve")
    f.idle()
    assert opening_view.doc["status"] == "APPROVED"
    f.login_ui("buyer")
    opening_view.presenter.read(doc_id)
    f.idle()
    opening_view.variables["reason"].set("Ghi sổ tồn đầu kỳ đã duyệt")
    opening_view.action("post")
    f.idle()
    assert opening_view.ack and inventory(f) == (1, 2, 15, 0)


@pytest.mark.parametrize("lost", ["upload", "create", "commit"])
def test_import_gui_lost_ack_exact_retry_and_commit_lookup(import_ui, monkeypatch, tmp_path, lost):
    f, view = import_ui, import_ui.import_view
    api = view.presenter.api
    original, requests = api.client.send, []
    route = {"upload": "/api/v1/files", "create": "/api/v1/imports", "commit": "/commit"}[lost]

    def send(request, **kwargs):
        response = original(request, **kwargs)
        if request.method == "POST" and (request.url.path == route or lost == "commit" and request.url.path.endswith(route)):
            requests.append((request.headers["Idempotency-Key"], request.content))
            if len(requests) == 1:
                assert response.is_success, response.text
                response.close()
                raise httpx.ReadTimeout("ACK lost after real server commit")
        return response

    monkeypatch.setattr(api.client, "send", send)
    f.import_select("01_uom")
    path = tmp_path / "số không đầu.csv"
    path.write_bytes(csv_bytes("01_uom", [["000B16", "Đơn vị", 0]]))
    view.choose(str(path))
    f.import_idle()
    view.presenter.upload()
    f.import_idle()
    if lost == "upload":
        path.write_bytes(b"changed local file must not replace pending byte snapshot")
    for stage in ("upload", "create", "commit"):
        if stage == lost:
            command = view.presenter.uncertain
            assert command and view.buttons["retry"].instate(["disabled"])
            view.presenter.retry()
            assert len(requests) == 1
            view.presenter.lookup()
            f.import_idle()
            if stage != "commit":
                assert view.presenter.uncertain and view.presenter.checked_key == command.key
                view.variables["reason"].set("Sửa form không được đổi body pending")
                view.presenter.retry()
                f.import_idle()
                assert requests[0] == requests[1]
            else:
                assert len(requests) == 1  # GET stored result is enough, no second commit.
            assert view.presenter.uncertain is None
        if stage == "upload":
            assert view.presenter.file["original_name"] == path.name
            # Restore source for the later *new* commit command, which rechecks it.
            path.write_bytes(view.presenter.source.data)
            view.variables["reason"].set("Nhập theo mẫu đã kiểm tra")
            view.action("create")
            f.import_idle()
        elif stage == "create":
            assert view.job and view.job["status"] == "QUEUED"
            f.outbox.run_batch()
            assert f.executor.run_one() == "VALIDATED"
            view.refresh()
            f.import_idle()
            commit(f)
    assert view.job["status"] == "COMMITTED"
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.import_file")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.import_job")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code='000B16'")).scalar_one() == 1


def test_import_gui_changed_file_token_stale_and_duplicate_resume(import_ui):
    f, view = import_ui, import_ui.import_view
    path = f.import_prepare()
    job_id, original = view.job["id"], path.read_bytes()
    path.write_bytes(original + b"new data")
    commit(f)
    assert "SOURCE_CHANGED" in view.variables["status"].get() and view.presenter.uncertain is None
    assert f.import_read({"id": job_id})["status"] == "VALIDATED"
    path.write_bytes(original)
    view.refresh()
    f.import_idle()
    # Another request invalidates the displayed token; do not silently retry a new version.
    ok(f.import_action(view.job, "validate"))
    commit(f)
    assert "STALE" in view.variables["status"].get()
    assert view.buttons["commit"].instate(["disabled"])
    f.outbox.run_batch()
    assert f.executor.run_one() == "VALIDATED"
    view.refresh()
    f.import_idle()
    commit(f)
    assert view.job["status"] == "COMMITTED"
    # Re-upload same content: backend finds the existing job; no new business target.
    f.import_prepare(validate=False)
    assert view.job["id"] == job_id and view.job["status"] == "COMMITTED"


def test_import_gui_paged_errors_download_revoke_and_cancel(import_ui, tmp_path):
    f, view = import_ui, import_ui.import_view
    f.import_prepare(rows=[[f"BAD{i}", "Sai độ chính xác", 7] for i in range(105)])
    assert view.job["status"] == "INVALID" and len(view.rows) == 50
    assert view.buttons["commit"].instate(["disabled"])
    view.page(1)
    f.import_idle()
    assert view.rows[0]["row_no"] == 52 and len(view.rows) == 50
    view.page(1)
    f.import_idle()
    assert len(view.rows) == 5
    view.page(-1)
    f.import_idle()
    assert view.rows[0]["row_no"] == 52
    destination = tmp_path / "lỗi.csv"
    view.download(True, str(destination))
    f.import_idle()
    assert destination.read_bytes().startswith(b"\xef\xbb\xbfrow_no")
    view.variables["reason"].set("Hủy tệp dữ liệu sai")
    view.action("cancel")
    f.import_idle()
    assert view.job["status"] == "CANCELLED"
    with f.engine.begin() as c:
        c.execute(text("DELETE FROM wms.user_role_grant WHERE user_id=:id"), {"id": f.buyer})
    destination.write_bytes(b"original")
    view.download(True, str(destination))
    f.import_idle()
    assert destination.read_bytes() == b"original" and view.job is None and not view.rows
    assert "FORBIDDEN" in view.variables["status"].get()


def test_import_gui_queued_cancel_and_limits_without_upload(import_ui, tmp_path):
    f, view = import_ui, import_ui.import_view
    f.import_prepare(validate=False)
    job_id = view.job["id"]
    view.variables["reason"].set("Hủy trước worker")
    view.action("cancel")
    f.import_idle()
    f.outbox.run_batch()
    f.executor.run_one()
    assert f.import_read({"id": job_id})["status"] == "CANCELLED"
    f.import_select("11_opening")
    path = tmp_path / "quá hạn mức.csv"
    path.write_bytes(csv_bytes("11_opening", [["B16", "2026-10-02", "ORDERS", "BIN", "ORD-01", "", "", 1]] * 201))
    view.choose(str(path))
    f.import_idle()
    assert "ROW_LIMIT" in view.variables["status"].get() and view.presenter.source is None
    assert view.buttons["upload"].instate(["disabled"])


def test_import_gui_po_handoff_and_late_download_after_scope_change(import_ui, monkeypatch, tmp_path):
    f, view = import_ui, import_ui.import_view
    f.import_prepare("12_open_orders", [["B16-PO", "PO", "ORDERS", f.partner["code"], "2026-10-02", 1,
                                         "ORD-01", "EA", 2, "Ghi chú nguồn B16"]])
    assert view.rows[0]["payload"]["note"] == "Ghi chú nguồn B16"
    commit(f)
    view.table.selection_set(str(view.rows[0]["row_no"]))
    view.open_target()
    f.import_wait(lambda: not f.shell.order_view.busy and f.shell.order_view.presenter.pending is None)
    assert f.shell.order_view.doc["kind"] == "PO" and f.shell.order_view.doc["status"] == "DRAFT"
    gate, started = threading.Event(), threading.Event()
    original = view.presenter.api.client.send

    def slow(request, **kwargs):
        response = original(request, **kwargs)
        if request.url.path.endswith("/download"):
            started.set()
            assert gate.wait(5)
        return response

    monkeypatch.setattr(view.presenter.api.client, "send", slow)
    destination = tmp_path / "do-not-replace.csv"
    destination.write_bytes(b"keep")
    view.download(False, str(destination))
    pending = view.presenter.pending
    assert started.wait(5)
    # Main-thread UI remains responsive; switching scope invalidates the download.
    view.kind.current(0)
    view.scope_changed()
    f.shell.root.update()
    gate.set()
    with pytest.raises(ApiError) as error:
        pending.result(5)
    assert error.value.code == "STALE_SESSION"
    f.import_idle()
    assert destination.read_bytes() == b"keep" and not view.job
    assert view.variables["job_id"].get() == ""


def test_import_template_contract_authorization_and_encoded_filename(import_ui):
    f = import_ui
    assert f.client.get("/api/v1/import-templates").status_code == 401
    data = ok(f.client.get("/api/v1/import-templates", headers=f.headers["buyer"]))
    assert data["mapping_version"] == "b09.v2"
    assert {t["kind"]: t["columns"] for t in data["templates"]} == {k: [c[0] for c in v] for k, v in TEMPLATES.items()}
    response = f.client.post("/api/v1/files?kind=01_uom", content=b"x", headers={
        **f.headers["buyer"], "Idempotency-Key": str(uuid4()),
        "X-File-Name": "%2E%2E%2Fbad.csv", "X-File-Name-Encoding": "percent-utf8"})
    assert response.status_code == 409 and response.json()["code"] == "INVALID_FILENAME"


def test_import_gui_location_combines_global_and_warehouse_permissions(import_ui):
    f, view = import_ui, import_ui.import_view
    f.import_prepare("04_locations", [["B16-BIN", "ORDERS", "RACK", "Ô mới", "STORAGE", "TRUE"]])
    assert {"warehouse.configure", "document.read"}.issubset(view.permissions)
    assert view.job["status"] == "VALIDATED"
    commit(f)
    assert view.job["status"] == "COMMITTED"


def test_import_gui_unknown_job_read_clears_old_actions(import_ui):
    f, view = import_ui, import_ui.import_view
    f.import_prepare()
    assert view.job["status"] == "VALIDATED"
    view.variables["job_id"].set(str(uuid4()))
    view.refresh()
    f.import_idle()
    assert not view.job and not view.rows and view.presenter.job is None
    for action in ("commit", "cancel", "validate", "create", "source", "errors"):
        assert view.buttons[action].instate(["disabled"])


@pytest.mark.parametrize("failure", ["before_send", "bad_ack"])
def test_import_gui_unknown_commit_never_reports_false_success(import_ui, monkeypatch, failure):
    f, view = import_ui, import_ui.import_view
    f.import_prepare()
    api = view.presenter.api
    original, requests = api.client.send, []

    def send(request, **kwargs):
        if request.method == "POST" and request.url.path.endswith("/commit"):
            requests.append((request.headers["Idempotency-Key"], request.content))
            if len(requests) == 1 and failure == "before_send":
                raise httpx.ConnectTimeout("never reached server")
            response = original(request, **kwargs)
            if len(requests) == 1:
                payload = response.json()
                payload["version"] += 1
                response.close()
                return httpx.Response(200, json=payload, request=request)
            return response
        return original(request, **kwargs)

    monkeypatch.setattr(api.client, "send", send)
    commit(f)
    assert view.job["status"] == "VALIDATED" and view.presenter.uncertain
    assert view.buttons["commit"].instate(["disabled"])
    view.presenter.lookup()
    f.import_idle()
    if failure == "before_send":
        assert view.presenter.uncertain and view.presenter.checked_key
        view.presenter.retry()
        f.import_idle()
        assert requests[0] == requests[1]
    else:
        assert len(requests) == 1
    assert view.job["status"] == "COMMITTED" and not view.presenter.uncertain


def test_import_gui_revoked_commit_and_whole_file_failure(import_ui, tmp_path):
    f, view = import_ui, import_ui.import_view
    # Malformed header has file-level errors and no staging rows, still visible.
    f.import_select("01_uom")
    path = tmp_path / "bad.csv"
    path.write_text("wrong,header\na,b\n")
    view.choose(str(path))
    f.import_idle()
    view.presenter.upload()
    f.import_idle()
    view.variables["reason"].set("Kiểm tra lỗi tệp")
    view.action("create")
    f.import_idle()
    f.outbox.run_batch()
    f.executor.run_one()
    view.refresh()
    f.import_idle()
    assert view.job["status"] == "INVALID" and not view.rows
    assert "HEADER" in view.detail.get("1.0", "end")
    f.import_prepare()
    job_id = view.job["id"]
    with f.engine.begin() as c:
        c.execute(text("DELETE FROM wms.user_role_grant WHERE user_id=:id"), {"id": f.buyer})
    commit(f)
    assert view.job is None and view.presenter.uncertain and not view.rows
    assert "FORBIDDEN" in view.variables["status"].get()
    with f.engine.connect() as c:
        assert c.execute(text("SELECT status FROM wms.import_job WHERE id=:id"), {"id": job_id}).scalar_one() == "VALIDATED"
        assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code='B16'")).scalar_one() == 0
