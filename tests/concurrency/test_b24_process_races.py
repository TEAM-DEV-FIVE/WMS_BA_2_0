"""Real multiprocess HTTPS competitors against non-owner PostgreSQL runtime role."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_orders import ok
from test_transfers import missing_loss

from scripts.b24_harness import command, race, reconcile, save_evidence, tls_server

pytestmark = pytest.mark.integration
CASES = {
    "receipt": "receiving",
    "opening": "opening",
    "consignment": "consignment",
    "issue": "issuing",
    "move": "movement",
    "supplier_return": "returning",
    "customer_return": "returning",
    "dispatch": "transfer",
    "arrival": "transfer",
    "loss": "transfer",
    "count": "counting",
    "reversal": "reversal",
}


def prepare(f, case):
    who = "buyer"
    if case == "receipt":
        doc = f.receipt_approve()
        body = f.post_body(doc)
        path = f"receipts/{doc['id']}/post"
    elif case == "opening":
        doc = f.open_approve()
        body = f.open_post_body(doc)
        path = f"openings/{doc['id']}/post"
    elif case == "consignment":
        doc = f.cg_approve()
        body = f.open_post_body(doc)
        path = f"consignment-receipts/{doc['id']}/post"
    elif case == "issue":
        f.seed()
        doc = f.reserve(f.issue_approve())
        body = f.issue_post_body(doc)
        path = f"issues/{doc['id']}/post"
    elif case == "move":
        source, _ = f.putaway()
        doc = f.move_approve(f.move_body(source, qty="10"))
        body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="B24 movement")
        path = f"moves/{doc['id']}/post"
    elif case in {"supplier_return", "customer_return"}:
        if case == "supplier_return":
            f.received("10")
            source = f.return_sources()["items"][0]
            payload = f.return_body(source)
        else:
            source, _, _ = f.issued_source()
            payload = f.return_body(source, kind="CUSTOMER_RETURN", location=f.quarantine["id"])
        doc = f.return_approve(payload)
        body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="B24 return")
        path = f"returns/{doc['id']}/post"
        who = "manager"
    elif case in {"dispatch", "arrival", "loss"}:
        doc = f.tr_approve(f.tr_seed())
        body = f.tr_post_body(doc)
        path = f"transfers/{doc['id']}/dispatch"
        who = "sender"
        if case != "dispatch":
            doc = ok(f.tr_dispatch(doc))
            body = f.tr_receive_body(doc)
            path = f"transfers/{doc['id']}/receive"
            who = "receiver"
        if case == "loss":
            doc = ok(f.tr_receive(doc))
            _, loss = missing_loss(f, doc)
            doc = ok(f.decision(ok(f.action(loss, "submit", "manager"))))
            body = f.tr_post_body(doc)
            path = f"transfers/{doc['id']}/loss-post"
            who = "controller"
    elif case == "count":
        f.count_received()
        doc = f.count_approved()
        body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="B24 count")
        path = f"counts/{doc['id']}/post"
        who = "controller"
    else:
        doc = f.rev_approve(f.original["transaction_id"])
        body = dict(expected_version=doc["version"], execution_key=str(uuid4()), reason="B24 reversal")
        path = f"reversals/{doc['id']}/post"
        who = "controller"
    return command(f, path, body, who)


@pytest.mark.parametrize("iteration", [0, 1])
@pytest.mark.parametrize("case", CASES)
def test_every_posting_multiprocess_same_execution_once(request, tmp_path, case, iteration):
    f = request.getfixturevalue(CASES[case])
    first = prepare(f, case)
    second = deepcopy(first)
    # One run same HTTP key, one run different HTTP keys sharing the frozen execution key.
    if iteration:
        second["headers"]["Idempotency-Key"] = str(uuid4())
    with f.engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM wms.inventory_transaction")).scalar_one()
    with tls_server(f.iam, tmp_path / "tls") as server:
        results, proof = race(server, [first, second])
    assert [r["status"] for r in results] == [200, 200], results
    assert results[0]["body"] == results[1]["body"]
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction")).scalar_one() == before + 1
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.inventory_transaction WHERE execution_key=:key"),
                {"key": first["body"]["execution_key"]},
            ).scalar_one()
            == 1
        )
    proof.update(
        case=case, iteration=iteration, statuses=[r["status"] for r in results], reconcile=reconcile(f.engine)
    )
    save_evidence(f"race-{case}-{iteration}", proof)


@pytest.mark.parametrize("case", ["approval", "reserve", "cancel_post", "freeze_post", "period_post"])
@pytest.mark.parametrize("iteration", [0, 1])
def test_competing_business_transitions(request, tmp_path, case, iteration):
    fixture = {
        "approval": "orders",
        "reserve": "issuing",
        "cancel_post": "issuing",
        "freeze_post": "counting",
        "period_post": "receiving",
    }[case]
    f = request.getfixturevalue(fixture)
    if case == "approval":
        doc = f.submit()
        path = f"approval-requests/{doc['approval_request_id']}/decide"
        calls = [
            command(
                f,
                path,
                dict(expected_version=doc["version"], reason="B24 competing decision", decision=d),
                "controller",
            )
            for d in ["APPROVE", "REJECT"]
        ]
    elif case in {"reserve", "cancel_post"}:
        f.seed()
        if case == "reserve":
            docs = [f.issue_approve(), f.issue_approve()]
            calls = [command(f, f"issues/{d['id']}/reservations/reserve", f.reserve_body(d)) for d in docs]
        else:
            doc = f.reserve(f.issue_approve())
            calls = [
                command(f, f"issues/{doc['id']}/post", f.issue_post_body(doc)),
                command(
                    f,
                    f"documents/{doc['id']}/cancel",
                    dict(expected_version=doc["version"], reason="B24 cancel"),
                    "manager",
                ),
            ]
    elif case == "freeze_post":
        doc = f.receipt_approve()
        count = f.count_create()
        calls = [
            command(f, f"receipts/{doc['id']}/post", f.post_body(doc)),
            command(
                f,
                f"counts/{count['id']}/freeze",
                dict(expected_version=count["version"], reason="B24 freeze"),
                "manager",
            ),
        ]
    else:
        doc = f.receipt_approve()
        period = ok(
            f.client.get(f"/api/v1/periods?warehouse_id={f.warehouse}", headers=f.headers["controller"])
        )["items"][0]
        calls = [
            command(f, f"receipts/{doc['id']}/post", f.post_body(doc, "100")),
            command(
                f,
                f"periods/{period['id']}/close",
                dict(expected_version=period["version"], reason="B24 close"),
                "controller",
            ),
        ]
    with tls_server(f.iam, tmp_path / "tls") as server:
        results, proof = race(server, calls[::-1] if iteration else calls)
    statuses = sorted(r["status"] for r in results)
    if case in {"approval", "reserve", "cancel_post"}:
        assert statuses == [200, 409], results
    else:
        assert statuses in ([200, 200], [200, 409]), results
    assert all(r["body"].get("code") not in {"INTERNAL_ERROR", "DATABASE_ERROR"} for r in results)
    proof.update(case=case, iteration=iteration, statuses=statuses, reconcile=reconcile(f.engine))
    save_evidence(f"race-{case}-{iteration}", proof)


@pytest.mark.parametrize("iteration", [0, 1])
def test_same_serial_cannot_exist_in_two_warehouses(request, tmp_path, iteration):
    from test_openings import second_warehouse, tracking

    f = request.getfixturevalue("opening")
    _, body = tracking(f, "SERIAL", serial_code="B24-shared-serial")
    docs = [f.open_approve(body), f.open_approve(second_warehouse(f, body))]
    calls = [command(f, f"openings/{doc['id']}/post", f.open_post_body(doc)) for doc in docs]
    with tls_server(f.iam, tmp_path / "tls") as server:
        results, proof = race(server, calls[::-1] if iteration else calls)
    assert sorted(r["status"] for r in results) == [200, 409], results
    assert next(r for r in results if r["status"] == 409)["body"]["code"] == "SERIAL_ALREADY_PRESENT"
    with f.engine.connect() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM wms.serial_position").scalar_one() == 1
        assert c.exec_driver_sql("SELECT sum(on_hand) FROM wms.stock_balance").scalar_one() == 1
    proof.update(statuses=[r["status"] for r in results], reconcile=reconcile(f.engine))
    save_evidence(f"race-serial-{iteration}", proof)
