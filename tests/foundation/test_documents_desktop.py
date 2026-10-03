import socket
import threading
import time

import pytest
import uvicorn
from sqlalchemy import text
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving, totals  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.views.shell import DesktopShell

pytestmark = [pytest.mark.gui, pytest.mark.integration]


def wait(root, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert predicate()


@pytest.fixture
def desktop(receiving, tmp_path, monkeypatch):  # noqa: F811
    import tkinter as tk

    f = receiving
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(
            api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1", local_data_dir=tmp_path / "device"))
        api = shell.session_view.presenter.api
        request = api._request
        main_thread = threading.get_ident()

        def check_thread(*args, **kwargs):
            assert threading.get_ident() != main_thread
            return request(*args, **kwargs)

        monkeypatch.setattr(api, "_request", check_thread)

        class Harness:
            def __init__(self):
                self.shell, self.root, self.f = shell, root, f

            def login(self, username):
                session = shell.session_view
                session.username.set(username)
                session.password.set("Test-only-password-2026!")
                session.login()
                wait(root, lambda: session.presenter.pending is None)
                assert shell.order_view.presenter.user_id

            def done(self, view):
                wait(root, lambda: view.presenter.pending is None and not view.busy)

            def read(self, view, doc):
                shell.notebook.select(view)
                view.presenter.read(view.path, doc["id"])
                self.done(view)
                assert view.doc, view.variables["status"].get()

        yield Harness()
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def test_tk_assignment_revocation_search_paging_and_snapshot_navigation(desktop):
    h, f = desktop, desktop.f
    view = h.shell.order_view
    doc = ok(f.create(), 201)
    worker, _ = f.iam.user("worker")
    f.iam.grant(worker, "BUYER", f.warehouse)
    h.login("manager")
    view.load()
    h.done(view)
    h.read(view, doc)
    view.details.select(1)
    view.variables["candidate_query"].set("worker")
    view.load_candidates()
    h.done(view)
    view.candidate_table.selection_set(str(worker))
    view.add_assignee()
    view.variables["reason"].set("Giao xử lý")
    view.save_assignments()
    h.done(view)
    assert view.doc["assigned_user_ids"] == [str(worker)]
    assigned = view.doc.copy()
    h.login("worker")
    h.read(view, assigned)
    assert "submit" in view.doc["allowed_actions"]
    unassigned = ok(f.action(assigned, "assignments", "manager", user_ids=[]))
    view.variables["reason"].set("Gửi sau khi bị thu hồi phân công")
    view.action("submit")
    h.done(view)
    assert view.doc is None and not view.presenter.uncertain
    assert "được giao" in view.variables["status"].get()
    h.login("manager")
    h.read(view, unassigned)
    view.variables["candidate_query"].set("worker")
    view.load_candidates()
    h.done(view)
    view.candidate_table.selection_set(str(worker))
    view.add_assignee()
    view.variables["reason"].set("Phân công lại")
    view.save_assignments()
    h.done(view)
    assigned = view.doc.copy()
    # Target loses visibility between lookup and save; no stale candidate list can authorize it.
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": worker})
    view.variables["reason"].set("Giao lại")
    view.save_assignments()
    h.done(view)
    assert view.doc is None and view.presenter.uncertain is None
    assert "quyền" in view.variables["status"].get()
    assert ok(f.read(assigned))["assigned_user_ids"] == [str(worker)]
    h.read(view, assigned)
    view.assignee_table.selection_set(str(worker))
    view.remove_assignee()
    view.variables["reason"].set("Bỏ phân công đã hết quyền")
    view.save_assignments()
    h.done(view)
    assert not view.doc["assigned_user_ids"]
    h.login("worker")  # revoked grant: even a cached document id cannot restore the form
    view.presenter.read(view.path, doc["id"])
    h.done(view)
    assert view.doc is None
    # Actual server keyset pagination (26 results) and literal document-number search.
    h.login("manager")
    for _ in range(24):
        ok(f.create(), 201)
    view.load()
    h.done(view)
    first = set(view.table.get_children())
    assert len(first) == 25 and view.next_after
    view.load(view.next_after)
    h.done(view)
    assert len(view.table.get_children()) == 1 and not (first & set(view.table.get_children()))
    view.previous_page()
    h.done(view)
    assert set(view.table.get_children()) == first
    view.variables["query"].set(doc["number"])
    view.load()
    h.done(view)
    assert view.table.get_children() == (doc["id"],)
    h.read(view, f.po)
    view.details.select(view.review_panel)
    view.load_review()
    h.done(view)
    assert len(view.review_panel.records) == 2
    # A legacy null snapshot must not be substituted with the current document.
    with f.engine.begin() as c:
        c.execute(text("""INSERT INTO wms.approval_request
            (id,document_id,document_version,policy_id,requested_by,status,created_at,content_snapshot)
            SELECT gen_random_uuid(),:doc,1,id,:user,'INVALIDATED',now(),NULL FROM wms.approval_policy
            WHERE document_kind='PO' AND is_active"""), {"doc": f.po["id"], "user": f.buyer})
    view.load_review()
    h.done(view)
    assert len(view.review_panel.records) == 2
    assert "1 lần gửi cũ không có bản lưu" in view.review_panel.message.get()
    view.open_approvals()
    h.done(h.shell.approval_view)
    assert h.shell.notebook.select() == str(h.shell.approval_view)


def test_tk_inbox_sod_warehouse_grant_stale_decision_and_receipt(desktop):
    h, f = desktop, desktop.f
    view = h.shell.approval_view
    f.iam.grant(f.buyer, "WAREHOUSE_MANAGER", f.warehouse)
    doc = f.submit()
    h.login("buyer")
    view.load()
    h.done(view)
    h.read(view, doc)
    assert view.approve_button.instate(["disabled"])
    assert "tự duyệt" in view.variables["status"].get()
    h.login("controller")
    view.load()
    h.done(view)
    h.read(view, doc)
    assert not view.approve_button.instate(["disabled"])
    ok(f.decision(doc, "manager"))  # competing decision while screen retains old version
    view.variables["reason"].set("Duyệt bản cũ")
    view.decide("APPROVE")
    h.done(view)
    assert view.presenter.needs_reload and not view.presenter.uncertain
    assert view.approve_button.instate(["disabled"])
    view.reload()
    h.done(view)
    assert view.doc["status"] == "APPROVED" and not view.presenter.needs_reload
    assert not view.table.exists(doc["id"])
    view.open_document()
    h.done(h.shell.order_view)
    assert h.shell.order_view.doc["id"] == doc["id"]
    # SO uses the same real decision endpoint.
    so = ok(f.action(ok(f.create("sales-orders"), 201), "submit"))
    view.variables["kind"].set("SO")
    view.scope_changed()
    h.read(view, so)
    view.variables["reason"].set("Duyệt bán")
    view.decide("APPROVE")
    h.done(view)
    assert view.doc["status"] == "APPROVED"
    # RECEIPT shows source/tracking and uses the existing receipt service, without changing its form.
    receipt = ok(f.action(ok(f.receipt_create(), 201), "submit"))
    view.variables["kind"].set("RECEIPT")
    view.scope_changed()
    view.load()
    h.done(view)
    h.read(view, receipt)
    assert f.po["id"] in view.content.get("1.0", "end")
    view.load_review()
    h.done(view)
    assert len(view.review_panel.records) == 2
    view.variables["reason"].set("Duyệt kế hoạch nhận")
    view.decide("APPROVE")
    h.done(view)
    assert view.doc["status"] == "APPROVED" and totals(f) == (0, 0, 0, 0)
    # A warehouse read grant never combines with approval granted in another warehouse.
    reader, _ = f.iam.user("reader")
    f.iam.grant(reader, "BUYER", f.warehouse)
    elsewhere = f.iam.warehouse("ELSEWHERE")
    f.iam.grant(reader, "CONTROLLER", elsewhere)
    doc2 = f.submit()
    h.login("reader")
    view.variables["kind"].set("PO")
    view.scope_changed()
    h.read(view, doc2)
    assert view.approve_button.instate(["disabled"])
    assert "Thiếu quyền duyệt tại kho" in view.variables["status"].get()


def test_tk_partial_close_cancel_and_unknown_survive_navigation(desktop, monkeypatch):
    h, f = desktop, desktop.f
    view = h.shell.order_view
    body = {**f.receipt_body, "lines": [{**f.receipt_body["lines"][0], "quantity_base": "40"}]}
    receipt = f.receipt_approve(body)
    ok(f.post(receipt, f.post_body(receipt, "40")))
    assert totals(f) == (1, 1, 40, 0)
    h.login("manager")
    view.load()
    h.done(view)
    h.read(view, f.po)
    assert view.doc["status"] == "PARTIAL" and view.buttons["cancel"].instate(["disabled"])
    view.variables["reason"].set("Đóng lượng còn lại")
    original = view.presenter.api.command
    attempts = []

    def lose_ack(method, path, payload, key):
        attempts.append((method, path, payload.copy(), key))
        result = original(method, path, payload, key)
        if len(attempts) == 1:
            raise ApiError("TIMEOUT", "Mất ACK sau commit")
        return result

    monkeypatch.setattr(view.presenter.api, "command", lose_ack)
    view.action("close")
    h.done(view)
    assert view.presenter.uncertain and "UNKNOWN" in view.variables["uncertainty"].get()
    h.shell.notebook.select(h.shell.approval_view)
    h.root.update()
    h.shell.notebook.select(view)
    h.root.update()
    assert view.presenter.uncertain and view.retry_button.instate(["!disabled"])
    view.presenter.retry()
    h.done(view)
    assert attempts[0] == attempts[1] and not view.presenter.uncertain
    assert view.doc["status"] == "COMPLETED"
    assert "chưa thực hiện đủ" in view.variables["heading"].get()
    assert view.line_table.item("0", "values")[-3:] == ("40.000000", "0.000000", "60.000000")
    assert totals(f) == (1, 1, 40, 0)
    draft = ok(f.create(), 201)
    h.read(view, draft)
    view.variables["reason"].set("Hủy nháp")
    view.action("cancel")
    h.done(view)
    assert view.doc["status"] == "CANCELLED" and "Đã hủy" in view.variables["heading"].get()
    assert view.line_table.item("0", "values")[-3:] == ("0.000000", "0.000000", "100.000000")
    # Every action and status remains reachable at the supported minimum geometry.
    h.root.geometry("800x620")
    h.root.update()
    assert view.retry_button.winfo_ismapped() and view.retry_button.winfo_height() > 10
    assert view.retry_button.winfo_rooty() + view.retry_button.winfo_height() <= view.winfo_rooty() + view.winfo_height()
