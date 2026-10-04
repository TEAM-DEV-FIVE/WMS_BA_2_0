"""Two real PostgreSQL transactions exercise the count/period barrier in every engine."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_issues import issuing  # noqa: F401
from test_move_quality import movement, reconcile  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401
from test_returns import returning  # noqa: F401
from test_transfers import transfer  # noqa: F401

pytestmark = pytest.mark.integration


def create_count(f, location, warehouse=None):
    warehouse = warehouse or f.warehouse
    users = [f.iam.user("freeze-counter-" + str(i))[0] for i in (1, 2)]
    for user in users:
        f.iam.grant(user, "PICKER", warehouse)
    response = f.client.post("/api/v1/counts", json=dict(warehouse_id=str(warehouse), business_date="2026-10-02",
        reason="Kiểm thử khóa cạnh tranh", scope=[dict(location_id=location, user_ids=[str(u) for u in users])]),
        headers={**f.headers["manager"], "Idempotency-Key": str(uuid4())})
    return ok(response, 201)


def freeze(f, doc):
    return f.client.post(f"/api/v1/counts/{doc['id']}/freeze", json=dict(expected_version=doc["version"], reason="Khóa cạnh tranh"),
        headers={**f.headers["manager"], "Idempotency-Key": str(uuid4())})


def race(f, count, posting, *, first, monkeypatch, blocked_code="LOCATION_FROZEN"):
    import apps.server.application.counting as module
    ready, release, attempted = Event(), Event(), Event()
    target = module if first == "freeze" else f.client.app.state.orders
    original = target.effects
    def held_effects(*args, **kwargs):
        original(*args, **kwargs)
        ready.set()
        assert release.wait(10), "Race coordinator did not release transaction"
    def queried(connection, cursor, statement, parameters, context, executemany):
        if ("wms.stock_period" in statement or "wms.warehouse" in statement) and ("FOR UPDATE" in statement or "FOR SHARE" in statement):
            attempted.set()
    with monkeypatch.context() as patch, ThreadPoolExecutor(2) as pool:
        patch.setattr(target, "effects", held_effects)
        first_call = pool.submit(freeze, f, count) if first == "freeze" else pool.submit(posting)
        try:
            assert ready.wait(10)
            event.listen(f.engine, "before_cursor_execute", queried)
            second_call = pool.submit(posting) if first == "freeze" else pool.submit(freeze, f, count)
            assert attempted.wait(10)
            assert not second_call.done()
        finally:
            event.remove(f.engine, "before_cursor_execute", queried) if event.contains(f.engine, "before_cursor_execute", queried) else None
            release.set()
        first_response, second_response = first_call.result(10), second_call.result(10)
    ok(first_response)
    if first == "freeze":
        assert second_response.status_code == 409, second_response.text
        assert second_response.json()["code"] == blocked_code
    else:
        ok(second_response)
    return ok(f.client.get(f"/api/v1/counts/{count['id']}", headers=f.headers["manager"]))


@pytest.mark.parametrize("first", ["freeze", "post"])
@pytest.mark.parametrize("flow", ["receipt", "move", "supplier-return", "customer-return", "opening", "transfer-dispatch", "transfer-arrive"])
def test_freeze_serializes_every_inventory_engine(request, flow, first, monkeypatch):
    fixture = {"receipt": "receiving", "move": "movement", "supplier-return": "returning", "customer-return": "returning",
               "opening": "opening", "transfer-dispatch": "transfer", "transfer-arrive": "transfer"}[flow]
    f = request.getfixturevalue(fixture)
    warehouse = f.warehouse
    if flow == "receipt":
        doc = f.receipt_approve()
        body = f.post_body(doc, "5")
        location, posting, expected = f.location["id"], lambda: f.post(doc, body), 5
    elif flow == "move":
        source, _ = f.putaway("80", "0")
        doc = f.move_approve(f.move_body(source, qty="5"))
        location, posting, expected = f.bin["id"], lambda: f.move_post(doc), 75
    elif flow == "supplier-return":
        f.received("10")
        doc = f.return_approve(f.return_body(f.return_sources()["items"][0], "4"))
        location, posting, expected = f.location["id"], lambda: f.return_post(doc), 6
    elif flow == "customer-return":
        source, _, _ = f.issued_source("7")
        doc = f.return_approve(f.return_body(source, "4", "CUSTOMER_RETURN", f.quarantine["id"]))
        location, posting, expected = f.quarantine["id"], lambda: f.return_post(doc), 4
    elif flow == "opening":
        doc = f.open_approve()
        location, posting, expected = f.location["id"], lambda: f.open_post(doc), 10
    elif flow == "transfer-dispatch":
        doc = f.tr_approve(f.tr_seed(), "5")
        location, posting, expected = f.location["id"], lambda: f.tr_dispatch(doc), 15
    else:
        doc = ok(f.tr_dispatch(f.tr_approve(f.tr_seed())))
        body = f.tr_receive_body(doc, "5")
        warehouse = f.destination
        location, posting, expected = f.arrival["id"], lambda: f.tr_receive(doc, body), 5
    count = create_count(f, location, warehouse)
    view = race(f, count, posting, first=first, monkeypatch=monkeypatch)
    if first == "post":
        from decimal import Decimal
        assert sum(Decimal(r["snapshot_quantity"]) for r in view["lines"]) == expected
    reconcile(f)


def test_issue_reservation_and_freeze_cannot_both_win(issuing, monkeypatch):  # noqa: F811
    f = issuing
    f.seed()
    doc = f.issue_approve()
    body = f.reserve_body(doc, "7")
    count = create_count(f, f.location["id"])
    race(f, count, lambda: f.issue_command(f"issues/{doc['id']}/reservations/reserve", body),
         first="freeze", monkeypatch=monkeypatch, blocked_code="INSUFFICIENT_STOCK")
    with f.engine.connect() as c:
        assert c.execute(text("SELECT COALESCE(sum(reserved),0) FROM wms.stock_balance")).scalar_one() == 0


def test_issue_post_consumes_reservation_before_freeze_snapshot(issuing, monkeypatch):  # noqa: F811
    f = issuing
    f.seed()
    held = f.reserve(f.issue_approve(), "7")
    count = create_count(f, f.location["id"])
    assert freeze(f, count).json()["code"] == "RESERVATION_OPEN"
    body = f.issue_post_body(held, "7")
    view = race(f, count, lambda: f.issue_post(held, body), first="post", monkeypatch=monkeypatch)
    assert view["lines"][0]["snapshot_quantity"] == "3.000000"
    reconcile(f)


@pytest.mark.parametrize("first", ["close", "post"])
def test_period_close_and_backdated_receipt_transaction_are_serialized(receiving, first, monkeypatch):  # noqa: F811
    f = receiving
    doc = f.receipt_approve()
    body = f.post_body(doc, "100")
    period = ok(f.client.get(f"/api/v1/periods?warehouse_id={f.warehouse}", headers=f.headers["controller"]))["items"][0]
    def close():
        return f.client.post(f"/api/v1/periods/{period['id']}/close",
            json=dict(expected_version=period["version"], reason="Đóng kỳ cạnh tranh"),
            headers={**f.headers["controller"], "Idempotency-Key": str(uuid4())})
    if first == "close":
        # A pending approved warehouse document explicitly prevents close; it is
        # not silently discarded to permit a competing post.
        assert close().json()["code"] == "DOCUMENT_PENDING"
        ok(f.post(doc, body))
        closed = ok(close())
    else:
        ready, release, attempted = Event(), Event(), Event()
        original = f.client.app.state.orders.effects
        def hold(*args, **kwargs):
            original(*args, **kwargs)
            ready.set()
            assert release.wait(10)
        def query(c, cursor, statement, parameters, context, many):
            if "wms.warehouse" in statement and "FOR UPDATE" in statement:
                attempted.set()
        with monkeypatch.context() as patch, ThreadPoolExecutor(2) as pool:
            patch.setattr(f.client.app.state.orders, "effects", hold)
            posted = pool.submit(f.post, doc, body)
            try:
                assert ready.wait(10)
                event.listen(f.engine, "before_cursor_execute", query)
                closing = pool.submit(close)
                assert attempted.wait(10) and not closing.done()
            finally:
                if event.contains(f.engine, "before_cursor_execute", query):
                    event.remove(f.engine, "before_cursor_execute", query)
                release.set()
            ok(posted.result(10))
            closed = ok(closing.result(10))
    assert closed["status"] == "CLOSED"
    # A subsequent creation in that business-date range also takes the period lock.
    user1, _ = f.iam.user("closed-one")
    user2, _ = f.iam.user("closed-two")
    for user in (user1, user2):
        f.iam.grant(user, "PICKER", f.warehouse)
    response = f.client.post("/api/v1/counts", json=dict(warehouse_id=str(f.warehouse), business_date="2026-10-02", reason="Backdate đã đóng",
        scope=[dict(location_id=f.location["id"], user_ids=[str(user1), str(user2)])]),
        headers={**f.headers["manager"], "Idempotency-Key": str(uuid4())})
    assert response.json()["code"] == "PERIOD_CLOSED"
    reconcile(f)
