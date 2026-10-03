import threading
from copy import deepcopy
from uuid import uuid4

import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.issues import IssuePresenter


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.saved, self.errors, self.loaded = [], [], []

    def orders_busy(self):
        assert threading.get_ident() == self.main

    def orders_clear(self):
        assert threading.get_ident() == self.main
        self.saved.clear()
        self.loaded.clear()

    def orders_error(self, error):
        assert threading.get_ident() == self.main
        self.errors.append(error)

    def orders_saved(self, result):
        assert threading.get_ident() == self.main
        self.saved.append(result)

    def orders_read(self, result):
        assert threading.get_ident() == self.main
        self.loaded.append(result)


def ack(doc):
    return dict(id=doc, number="ISS-TEST", kind="ISSUE", status="APPROVED", version=2,
                warehouse_id=str(uuid4()), request_id=str(uuid4()))


def test_issue_retry_preserves_body_key_and_user_partition():
    doc = str(uuid4())

    class Api:
        session_generation = 0
        calls = []

        def in_session(self, generation, callback):
            return callback()

        def command(self, method, path, body, key):
            self.calls.append((method, path, deepcopy(body), key))
            if len(self.calls) == 1:
                raise ApiError("TIMEOUT", "Chưa rõ kết quả")
            if len(self.calls) == 2:
                raise ApiError("FORBIDDEN", "Quyền vừa bị thu hồi")
            return ack(doc)

    api, view = Api(), View()
    presenter = IssuePresenter(view, api)
    try:
        presenter.reset("buyer")
        body = dict(expected_version=1, lines=[dict(quantity_base="7")])
        presenter.command("POST", f"issues/{doc}/reservations/reserve", body)
        body["lines"][0]["quantity_base"] = "999"
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain["state"] == "UNKNOWN"
        presenter.reset("other")
        presenter.retry()
        assert presenter.uncertain is None and len(api.calls) == 1
        presenter.reset("buyer")
        presenter.retry()
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain["state"] == "UNKNOWN"
        presenter.command("POST", "issues", {"replacement": True})
        assert len(api.calls) == 2  # A denial after an unknown attempt never permits a replacement key.
        presenter.retry()
        presenter.pending.result(timeout=5)
        presenter.drain()
        assert api.calls[0] == api.calls[1] == api.calls[2]
        assert api.calls[0][2]["lines"][0]["quantity_base"] == "7"
        assert presenter.uncertain is None and len(view.saved) == 1
    finally:
        presenter.close()
        presenter.finish()


@pytest.mark.parametrize("invalidate", ["user", "warehouse", "generation", "close"])
def test_issue_discards_response_from_old_user_warehouse_or_session(invalidate):
    started, release = threading.Event(), threading.Event()
    doc = str(uuid4())

    class Api:
        session_generation = 0

        def in_session(self, generation, callback):
            return callback()

        def command(self, *args):
            started.set()
            assert release.wait(timeout=5)
            return ack(doc)

    api, view = Api(), View()
    presenter = IssuePresenter(view, api)
    try:
        presenter.reset("buyer")
        presenter.command("PUT", "issues/" + doc, {})
        future = presenter.pending
        assert started.wait(timeout=5)
        if invalidate == "generation":
            api.session_generation += 1
        elif invalidate == "close":
            presenter.close()
        else:
            presenter.reset("other" if invalidate == "user" else "buyer")
        release.set()
        future.result(timeout=5)
        presenter.drain()
        assert view.saved == []
        assert "buyer" in presenter.commands  # ACK not delivered; never create a replacement key.
    finally:
        release.set()
        presenter.close()
        presenter.finish()


def test_issue_lookup_not_found_is_unknown_and_does_not_repost():
    class Api:
        session_generation = 0
        calls = 0

        def in_session(self, generation, callback):
            return callback()

        def command(self, *args):
            self.calls += 1
            raise ApiError("NETWORK_ERROR", "Mất kết nối")

        def get(self, path):
            raise ApiError("NOT_FOUND", "Chưa tìm thấy ACK")

    api, view = Api(), View()
    presenter = IssuePresenter(view, api)
    try:
        presenter.reset("buyer")
        presenter.command("POST", f"issues/{uuid4()}/post", {})
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        key = presenter.uncertain["key"]
        presenter.lookup()
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain["key"] == key
        assert presenter.uncertain["state"] == "UNKNOWN" and api.calls == 1 and not view.saved
    finally:
        presenter.close()
        presenter.finish()


def test_issue_invalid_post_ack_does_not_clear_pending_command():
    doc = str(uuid4())

    class Api:
        session_generation = 0

        def in_session(self, generation, callback):
            return callback()

        def command(self, *args):
            return ack(doc)  # no committed transaction/source acknowledgement

    view = View()
    presenter = IssuePresenter(view, Api())
    try:
        presenter.reset("buyer")
        presenter.command("POST", "issues/" + doc + "/post", {})
        with pytest.raises(ValueError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain["state"] == "UNKNOWN" and not view.saved
    finally:
        presenter.close()
        presenter.finish()
