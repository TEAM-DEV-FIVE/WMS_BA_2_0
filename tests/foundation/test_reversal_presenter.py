from concurrent.futures import Future
from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
from test_count_period_presenter import Api

from apps.desktop.presenters.reversals import ReversalPresenter, run_request


def response(warehouse, target):
    return dict(id=target, kind="REVERSAL", warehouse_id=warehouse, number="REV-TEST", status="COMPLETED", version=4,
        request_id=str(uuid4()), source_transaction_id=str(uuid4()), transaction_id=str(uuid4()))


@pytest.mark.parametrize("lookup", [False, True])
@pytest.mark.parametrize("field,value", [("status", "APPROVED"), ("transaction_id", None), ("version", 3),
    ("warehouse_id", str(uuid4())), ("id", str(uuid4())), ("kind", "RECEIPT")])
def test_reversal_presenter_rejects_mismatched_ack(lookup, field, value):
    warehouse, target, key = [str(uuid4()) for _ in range(3)]
    data = response(warehouse, target)
    body, path = dict(expected_version=3, execution_key=str(uuid4()), reason="Đảo"), f"reversals/{target}/post"
    data[field] = value
    if lookup:
        data = dict(command="reversal.post", result=data)
        body, path = dict(method="POST", path=path, payload=body), "reversals/operations/" + key
    result, _, error, _ = run_request(Api(data), 1, Event(), "GET" if lookup else "POST", path, body, key, warehouse)
    assert result is None and error[0] == "INVALID_RESPONSE"


def test_reversal_presenter_ack_lookup_checks_command_and_source():
    warehouse, target, key = [str(uuid4()) for _ in range(3)]
    data = response(warehouse, target)
    data.update(status="DRAFT", version=1, transaction_id=None)
    payload = dict(source_transaction_id=data["source_transaction_id"], source_version=5, business_date="2026-10-02", reason="Đảo")
    body = dict(method="POST", path="reversals", payload=payload)
    saved = dict(command="reversal.create", result=data)
    assert run_request(Api(saved), 1, Event(), "GET", f"reversals/operations/{key}", body, key, warehouse)[2] is None
    for bad in [{**saved, "command": "reversal.update"}, {**saved, "result": {**data, "source_transaction_id": str(uuid4())}}]:
        assert run_request(Api(bad), 1, Event(), "GET", f"reversals/operations/{key}", body, key, warehouse)[2][0] == "INVALID_RESPONSE"


def test_reversal_presenter_fences_scope_and_retains_immutable_uncertain_request(monkeypatch):
    class View:
        def workflow_clear(self):
            pass
        def workflow_busy(self):
            pass
        def workflow_error(self, message):
            raise AssertionError(message)
        def workflow_loaded(self, *args):
            raise AssertionError("Stale response reached widgets")
        def workflow_saved(self, *args):
            raise AssertionError("Stale ACK reached widgets")
    presenter, future = ReversalPresenter(View(), Api({})), Future()
    try:
        presenter.reset(uuid4(), uuid4())
        scope = presenter.scope
        monkeypatch.setattr(presenter.executor, "submit", lambda *args: future)
        body = dict(source_transaction_id=str(uuid4()), reason="Original")
        expected = deepcopy(body)
        presenter.command("POST", "reversals", body)
        body["reason"] = "Changed"
        assert presenter.uncertain[2] == expected
        future.set_running_or_notify_cancel()
        presenter.reset(uuid4(), uuid4())
        future.set_result(({}, [], None, 1))
        presenter.drain()
        assert presenter.commands[scope][2] == expected and presenter.uncertain is None
    finally:
        presenter.close()
        presenter.finish()
