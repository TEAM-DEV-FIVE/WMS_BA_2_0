import threading

import pytest
from test_order_presenter import View

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.approvals import ApprovalPresenter, decision_explanation
from apps.desktop.presenters.orders import OrderPresenter


@pytest.mark.parametrize("presenter_type", [OrderPresenter, ApprovalPresenter])
def test_old_warehouse_and_session_reads_never_touch_current_view(presenter_type):
    started, release = threading.Event(), threading.Event()
    thread = threading.get_ident()

    class Api:
        session_generation = 0

        def in_session(self, generation, fn):
            assert threading.get_ident() != thread
            return fn()

        def get(self, path):
            if "old" in path:
                started.set()
                assert release.wait(5)
            return {"id": path, "warehouse_id": "new"}

        def permissions(self, warehouse):
            return []

    api, view = Api(), View()
    reads = []
    view.orders_read = lambda doc: reads.append(doc)
    p = presenter_type(view, api)
    try:
        p.reset("buyer")
        p.read("purchase-orders", "old")
        assert started.wait(5)
        p.reset("buyer")  # changing warehouse invalidates the old request
        p.read("purchase-orders", "new")
        release.set()
        p.pending.result(5)
        p.drain()
        assert [r["id"] for r in reads] == ["purchase-orders/new"]
        p.read("purchase-orders", "new")
        p.pending.result(5)
        api.session_generation += 1  # a sibling presenter logged out before this drain
        p.drain()
        assert len(reads) == 1
        assert "Phiên đã thay đổi" in view.errors[-1]
    finally:
        release.set()
        p.close()
        p.finish()


def test_stale_decision_requires_read_and_never_automatically_retries():
    class Api:
        session_generation = 0
        calls = 0

        def in_session(self, generation, fn):
            return fn()

        def command(self, *args):
            self.calls += 1
            raise ApiError("STALE_VERSION", "Phiếu đã đổi")

        def get(self, path):
            return {"warehouse_id": "warehouse", "version": 3}

        def permissions(self, warehouse):
            return []

    api, view = Api(), View()
    view.orders_read = lambda doc: None
    p = ApprovalPresenter(view, api)
    try:
        p.reset("approver")
        p.command("POST", "approval-requests/id/decide", {"expected_version": 2})
        with pytest.raises(ApiError):
            p.pending.result(5)
        p.drain()
        assert p.needs_reload and not p.uncertain
        p.retry()
        p.command("POST", "approval-requests/id/decide", {"expected_version": 2})
        assert api.calls == 1
        p.read("purchase-orders", "id")
        p.pending.result(5)
        p.drain()
        assert not p.needs_reload
    finally:
        p.close()
        p.finish()


def test_approval_explanation_distinguishes_warehouse_grant_and_sod():
    doc = {"created_by": "buyer", "status": "SUBMITTED", "approvals": [
        {"status": "PENDING", "can_decide": False, "requested_by": "sender", "steps": []}]}
    assert "tự duyệt" in decision_explanation(doc, "buyer", ["document.approve"])
    assert "tự duyệt" in decision_explanation(doc, "sender", ["document.approve"])
    assert "kho" in decision_explanation(doc, "buyer", [])
    assert "vai trò" in decision_explanation(doc, "other", ["document.approve"])
