import threading
import time
from copy import deepcopy
from uuid import uuid4

import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.openings import OpeningPresenter, validate_lines
from packages.contracts.traceability import COMPANY_OWNER


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.events = []

    def __getattr__(self, name):
        assert name.startswith("opening_")

        def callback(*args, **kwargs):
            assert threading.get_ident() == self.main
            self.events.append((name, args, kwargs))

        return callback


class Client:
    session_generation = 0

    def in_session(self, generation, fn):
        assert threading.current_thread() is not threading.main_thread()
        if generation != self.session_generation:
            raise ApiError("UNAUTHENTICATED", "Phiên cũ")
        return fn()


def drain(presenter):
    deadline = time.monotonic() + 5
    while presenter.pending is not None and time.monotonic() < deadline:
        presenter.drain()
        time.sleep(0.001)
    assert presenter.pending is None


@pytest.fixture
def presenter():
    presenter = OpeningPresenter(View(), Client())
    presenter.reset("buyer", "warehouse")
    try:
        yield presenter
    finally:
        presenter.close()
        presenter.finish()


@pytest.mark.parametrize("post", [False, True])
def test_unknown_requires_lookup_then_exact_explicit_retry(presenter, post):
    calls = []

    def execute(command):
        calls.append(deepcopy(command))
        if len(calls) == 1:
            raise ApiError("TIMEOUT", "Mất phản hồi")
        return {"id": "doc"}

    def lookup(command):
        raise ApiError("NOT_FOUND", "Chưa có ACK")

    presenter.openings.execute, presenter.openings.inspect = execute, lookup
    body = {"execution_key": str(uuid4()), "batch_key": str(uuid4()), "lines": [{"quantity_base": "10"}]}
    original = deepcopy(body)
    presenter.command(
        "POST", "openings/doc/post" if post else "openings", body, "doc" if post else None, post=post
    )
    body["lines"][0]["quantity_base"] = "99"
    drain(presenter)
    assert presenter.uncertain and not presenter.uncertain.checked
    presenter.command("POST", "openings", body)
    presenter.retry()
    assert len(calls) == 1
    presenter.lookup()
    drain(presenter)
    assert presenter.uncertain.checked and len(calls) == 1
    presenter.retry()
    drain(presenter)
    assert len(calls) == 2
    assert calls[0].key == calls[1].key and calls[0].body == calls[1].body == original
    assert presenter.uncertain is None


def test_lookup_committed_marks_saved_without_reposting(presenter):
    def timeout(command):
        raise ApiError("TIMEOUT", "Sau commit")

    presenter.openings.execute = timeout
    presenter.openings.inspect = lambda command: {"id": "doc", "transaction_id": "transaction"}
    presenter.command("POST", "openings/doc/post", {"execution_key": "same"}, "doc", post=True)
    drain(presenter)
    key = presenter.uncertain.key
    presenter.lookup()
    drain(presenter)
    saved = [args for name, args, _ in presenter.view.events if name == "opening_saved"]
    assert saved == [({"id": "doc", "transaction_id": "transaction"}, key, True)]
    assert presenter.uncertain is None


@pytest.mark.parametrize("change", ["user", "warehouse", "generation", "close"])
def test_pending_old_scope_never_updates_view_or_loses_retry_intent(presenter, change):
    started, release = threading.Event(), threading.Event()

    def execute(command):
        started.set()
        assert release.wait(5)
        return {"id": "old-doc"}

    presenter.openings.execute = execute
    presenter.command("POST", "openings", {"batch_key": "fixed"})
    future = presenter.pending
    try:
        assert started.wait(5)
        if change == "user":
            presenter.reset("other", "warehouse")
        elif change == "warehouse":
            presenter.reset("buyer", "other")
        elif change == "generation":
            presenter.api.session_generation += 1
        else:
            presenter.close()
        release.set()
        future.result(5)
        presenter.executor.shutdown(wait=True)
        presenter.drain()
        assert not any(name == "opening_saved" for name, _, _ in presenter.view.events)
        assert presenter.commands[("buyer", "warehouse")].body == {"batch_key": "fixed"}
        if change in {"user", "warehouse"}:
            assert presenter.uncertain is None
            presenter.reset("buyer", "warehouse")
            assert presenter.uncertain and not presenter.uncertain.checked
    finally:
        release.set()


def test_stale_refreshes_version_and_does_not_retry_stale_command(presenter):
    def execute(command):
        raise ApiError("STALE_VERSION", "Phiếu đã đổi")

    presenter.openings.execute = execute
    presenter.openings.read = lambda doc: {"id": doc, "version": 7}
    presenter.command("PUT", "openings/doc", {"expected_version": 1}, "doc")
    drain(presenter)
    assert presenter.uncertain is None
    assert ("opening_read", ({"id": "doc", "version": 7},), {"stale": True}) in presenter.view.events


def test_revoked_permission_during_lookup_preserves_unknown(presenter):
    def failed(command):
        raise ApiError("FORBIDDEN", "Đã thu hồi quyền")

    presenter.openings.execute = presenter.openings.inspect = failed
    presenter.command("POST", "openings/doc/post", {}, "doc", post=True)
    drain(presenter)
    command = presenter.uncertain
    presenter.lookup()
    drain(presenter)
    assert presenter.uncertain is command and not command.checked


@pytest.mark.parametrize(
    "problem", ["201", "duplicate", "serial_qty", "tracking", "precision", "expiry", "owner"]
)
def test_client_validation_rejects_bad_opening_before_http(problem):
    product, unit, location = (str(uuid4()) for _ in range(3))
    products = {product: {"tracking": "SERIAL", "base_uom_id": unit, "expiry_required": False}}
    units = {unit: {"decimal_places": 0}}
    lines = [
        dict(
            product_id=product,
            quantity_base="1",
            owner_id=str(COMPANY_OWNER),
            destination_location_id=location,
            serial_code="000Aa",
        )
    ]
    if problem == "201":
        lines *= 201
    elif problem == "duplicate":
        lines *= 2
    elif problem == "serial_qty":
        lines[0]["quantity_base"] = "2"
    elif problem == "tracking":
        lines[0]["lot_code"] = "forbidden"
    elif problem == "precision":
        products[product]["tracking"] = "NONE"
        lines[0].update(quantity_base="0.1", serial_code=None)
    elif problem == "expiry":
        products[product].update(tracking="LOT", expiry_required=True)
        lines[0].update(serial_code=None, lot_code="Lot01")
    else:
        lines[0]["owner_id"] = str(uuid4())
    with pytest.raises(ValueError):
        validate_lines(lines, products, units)


def test_exact_decimal_and_tracking_codes_survive_validation():
    product, location = str(uuid4()), str(uuid4())
    lines = [
        dict(
            product_id=product,
            quantity_base="0.000001",
            owner_id=str(COMPANY_OWNER),
            destination_location_id=location,
            lot_code="000aa-X",
        )
    ]
    validate_lines(lines)
    assert lines[0]["quantity_base"] == "0.000001" and lines[0]["lot_code"] == "000aa-X"


@pytest.mark.parametrize("problem", ["transaction", "warehouse", "document", "kind", "status"])
def test_invalid_post_ack_stays_unknown(presenter, problem):
    warehouse, doc = str(uuid4()), str(uuid4())
    presenter.reset("buyer", warehouse)
    result = dict(
        id=doc,
        number="OPEN-01",
        kind="OPENING",
        warehouse_id=warehouse,
        status="COMPLETED",
        version=4,
        request_id=str(uuid4()),
        transaction_id=str(uuid4()),
    )
    if problem == "transaction":
        result.pop("transaction_id")
    elif problem == "warehouse":
        result["warehouse_id"] = str(uuid4())
    elif problem == "document":
        result["id"] = str(uuid4())
    elif problem == "kind":
        result["kind"] = "RECEIPT"
    else:
        result["status"] = "APPROVED"
    presenter.api.command = lambda *args: result
    presenter.command("POST", "openings/" + doc + "/post", {"execution_key": str(uuid4())}, doc, post=True)
    drain(presenter)
    assert presenter.uncertain and not presenter.uncertain.checked
    assert not any(name == "opening_saved" for name, _, _ in presenter.view.events)
