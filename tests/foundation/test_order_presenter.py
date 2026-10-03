import threading

import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.orders import OrderPresenter


class View:
    def __init__(self):
        self.thread = threading.get_ident()
        self.saved, self.errors = [], []

    def orders_busy(self):
        assert threading.get_ident() == self.thread

    def orders_clear(self):
        self.saved.clear()

    def orders_error(self, error):
        assert threading.get_ident() == self.thread
        self.errors.append(error)

    def orders_saved(self, result):
        assert threading.get_ident() == self.thread
        self.saved.append(result)


def test_order_retry_keeps_payload_key_and_is_partitioned_by_user():
    class Api:
        session_generation = 0

        def __init__(self):
            self.calls = []

        def in_session(self, generation, callback):
            return callback()

        def command(self, method, path, body, key):
            self.calls.append((method, path, body.copy(), key))
            if len(self.calls) == 1:
                raise ApiError("TIMEOUT", "Chưa rõ kết quả")
            return {"id": "saved"}

    api, view = Api(), View()
    presenter = OrderPresenter(view, api)
    try:
        presenter.reset("buyer")
        body = {"lines": [{"quantity": "100"}], "execution_key": "fixed-execution-key"}
        presenter.command("POST", "purchase-orders", body)
        body["lines"][0]["quantity"] = "1"
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain
        presenter.reset("other")
        assert presenter.uncertain is None
        presenter.retry()
        assert len(api.calls) == 1
        presenter.reset("buyer")
        presenter.retry()
        presenter.pending.result(timeout=5)
        presenter.drain()
        assert api.calls[0] == api.calls[1]
        assert api.calls[0][2]["lines"][0]["quantity"] == "100"
        assert api.calls[0][2]["execution_key"] == "fixed-execution-key"
        assert presenter.uncertain is None
    finally:
        presenter.close()
        presenter.finish()


def test_order_old_session_response_is_discarded_and_stale_version_is_not_retried():
    started, release = threading.Event(), threading.Event()

    class Api:
        session_generation = 0

        def in_session(self, generation, callback):
            return callback()

        def command(self, *args):
            started.set()
            assert release.wait(timeout=5)
            raise ApiError("STALE_VERSION", "Phiếu đã thay đổi")

    view = View()
    presenter = OrderPresenter(view, Api())
    try:
        presenter.reset("buyer")
        presenter.command("PUT", "purchase-orders/id", {"expected_version": 1})
        assert started.wait(timeout=5)
        release.set()
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain is None and view.errors == ["Phiếu đã thay đổi"]
        release.clear()
        started.clear()
        presenter.command("POST", "purchase-orders", {})
        assert started.wait(timeout=5)
        presenter.reset("other")
        release.set()
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert view.errors == ["Phiếu đã thay đổi"] and view.saved == []
    finally:
        release.set()
        presenter.close()
        presenter.finish()


def test_missing_global_catalogue_grant_does_not_hide_orders():
    class Api:
        session_generation = 0

        def in_session(self, generation, callback):
            return callback()

        def permissions(self, warehouse):
            return ["document.read", "po.draft"]

        def get(self, path):
            if path.startswith("master/"):
                raise ApiError("FORBIDDEN", "Thiếu quyền danh mục")
            return {"items": [{"number": "PO-01"}], "next_after": None}

    view = View()
    loaded = []
    view.orders_loaded = lambda *args: loaded.append(args)
    presenter = OrderPresenter(view, Api())
    try:
        presenter.reset("buyer")
        presenter.load("purchase-orders", "warehouse")
        presenter.pending.result(timeout=5)
        presenter.drain()
        assert loaded[0][0]["items"] == [{"number": "PO-01"}]
        assert loaded[0][1] == {} and not view.errors
    finally:
        presenter.close()
        presenter.finish()
