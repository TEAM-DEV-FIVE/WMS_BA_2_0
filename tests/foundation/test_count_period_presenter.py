from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest

from apps.desktop.presenters.counting import CountPresenter, run_request


class Api:
    session_generation = 1

    def __init__(self, data):
        self.data = data

    def in_session(self, generation, action):
        assert generation == self.session_generation
        return action()

    def permissions(self, warehouse):
        return ["count.enter"]

    def command(self, *args):
        return deepcopy(self.data)

    def get(self, path):
        return deepcopy(self.data)


def ack(warehouse, target, execution):
    return dict(id=target, warehouse_id=warehouse, number="COUNT-TEST", status="POSTED", version=4,
                request_id=str(uuid4()), adjustment_document_id=str(uuid4()), transaction_id=str(uuid4()), execution_key=execution)


@pytest.mark.parametrize("field,value", [("status", "SUBMITTED"), ("transaction_id", None), ("version", 3),
                                       ("warehouse_id", str(uuid4())), ("id", str(uuid4())), ("execution_key", str(uuid4()))])
def test_count_presenter_never_accepts_mismatched_post_ack(field, value):
    warehouse, target, execution = [str(uuid4()) for _ in range(3)]
    data = ack(warehouse, target, execution)
    data[field] = value
    result, _, error, _ = run_request(Api(data), 1, Event(), "POST", f"counts/{target}/post",
                                     dict(expected_version=3, execution_key=execution), uuid4(), warehouse)
    assert result is None and error[0] == "INVALID_RESPONSE"


def test_count_presenter_blind_contract_rejects_snapshot_and_old_rounds():
    warehouse, target, location = [str(uuid4()) for _ in range(3)]
    line = dict(id=str(uuid4()), stock_item_id=str(uuid4()), location_id=location, location_code="BIN", sku="SKU",
                tracking="NONE", owner_code="COMPANY", consignment_id=None, lot_code=None, serial_code=None,
                next_round=1, can_count=True)
    data = dict(id=target, warehouse_id=warehouse, number="COUNT", status="FROZEN", version=2, business_date="2026-10-02",
                reason="Đếm mù", mode="BLIND", lines=[line], scope=[dict(location_id=location, user_ids=[str(uuid4()), str(uuid4())])],
                allowed_actions=["observe"])
    assert run_request(Api(data), 1, Event(), "GET", f"counts/{target}", None, None, warehouse)[2] is None
    for field, value in [("snapshot_quantity", "100.000000"), ("observations", [])]:
        bad = deepcopy(data)
        bad["lines"][0][field] = value
        assert run_request(Api(bad), 1, Event(), "GET", f"counts/{target}", None, None, warehouse)[2][0] == "INVALID_RESPONSE"


def test_count_presenter_fences_old_scope_and_keeps_original_payload(monkeypatch):
    from concurrent.futures import Future

    class View:
        def workflow_clear(self):
            pass
        def workflow_busy(self):
            pass
        def workflow_error(self, message):
            raise AssertionError(message)
        def workflow_loaded(self, *args):
            raise AssertionError("Old scope response reached UI")

    api = Api({})
    presenter = CountPresenter(View(), api)
    submitted = Future()
    try:
        presenter.reset(uuid4(), uuid4())
        old_scope = presenter.scope
        monkeypatch.setattr(presenter.executor, "submit", lambda *args: submitted)
        body = {"expected_version": 2, "quantity": "98", "reason": "Đếm"}
        presenter.command("POST", "counts/" + str(uuid4()) + "/observe", body)
        body["quantity"] = "999"
        assert presenter.commands[old_scope][2]["quantity"] == "98"
        submitted.set_running_or_notify_cancel()
        presenter.reset(uuid4(), uuid4())
        submitted.set_result(({}, [], None, api.session_generation))
        presenter.drain()
        assert presenter.pending is None and presenter.commands[old_scope][2]["quantity"] == "98"
        assert presenter.uncertain is None
    finally:
        presenter.close()
        presenter.finish()
