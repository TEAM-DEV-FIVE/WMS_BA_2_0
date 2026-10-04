import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_orders import ok, orders  # noqa: F401
from test_receipts import receiving  # noqa: F401

from apps.desktop.views.document_review import snapshot_diff

pytestmark = pytest.mark.integration


def get(f, doc, resource, who="manager", **params):
    return f.client.get(f"/api/v1/documents/{doc['id']}/{resource}", params=params, headers=f.headers[who])


def test_scoped_search_is_literal_and_keyset_paged(orders):  # noqa: F811
    f = orders
    docs = [ok(f.create(), 201) for _ in range(3)]
    url = "/api/v1/purchase-orders"
    params = {"warehouse_id": str(f.warehouse), "q": f.partner["name"].lower(), "limit": 1}
    seen, cursor = [], None
    for _ in range(3):
        page = ok(f.client.get(url, params={**params, **({"after": cursor} if cursor else {})}, headers=f.headers["buyer"]))
        seen.extend(row["id"] for row in page["items"])
        cursor = page["next_after"]
    assert set(seen) == {d["id"] for d in docs} and cursor is None
    for query in ("%", "_", "' OR true --"):
        assert ok(f.client.get(url, params={**params, "q": query}, headers=f.headers["buyer"]))["items"] == []
    found = ok(f.client.get(url, params={**params, "q": docs[0]["number"]}, headers=f.headers["buyer"]))
    assert [d["id"] for d in found["items"]] == [docs[0]["id"]]
    hidden = f.iam.warehouse("OTHER")
    assert f.client.get(url, params={**params, "warehouse_id": str(hidden)}, headers=f.headers["buyer"]).status_code == 404


def test_candidates_scope_paging_expiry_and_revocation(orders):  # noqa: F811
    f = orders
    doc = ok(f.create(), 201)
    other = f.iam.warehouse("OTHER")
    wanted = []
    for i in range(3):
        user, _ = f.iam.user(f"candidate-{i}")
        f.iam.grant(user, "BUYER", f.warehouse)
        wanted.append(str(user))
    hidden, _ = f.iam.user("candidate-hidden")
    f.iam.grant(hidden, "BUYER", other)
    expired, _ = f.iam.user("candidate-expired")
    f.iam.grant(expired, "BUYER", f.warehouse, until=f.iam.now)
    seen, cursor = [], None
    for _ in range(3):
        page = ok(get(f, doc, "assignment-candidates", q="candidate-", limit=1,
                      **({"after": cursor} if cursor else {})))
        seen.extend(p["id"] for p in page["items"])
        cursor = page["next_after"]
    assert set(seen) == set(wanted) and cursor is None
    assert get(f, doc, "assignment-candidates", who="buyer").status_code == 403
    assigned = ok(f.action(doc, "assignments", "manager", user_ids=[wanted[0]]))
    # A candidate may lose its grant between lookup and saving; existing command rechecks.
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": wanted[0]})
    assert f.action(assigned, "assignments", "manager", user_ids=[wanted[0]]).status_code == 403
    assert wanted[0] not in [p["id"] for p in ok(get(f, doc, "assignment-candidates", q="candidate-"))["items"]]
    assert ok(f.read(assigned))["assigned_user_ids"] == [wanted[0]]  # rejected mutation is atomic
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:id"), {"id": f.manager})
    assert get(f, doc, "assignment-candidates").status_code == 404


def test_approval_snapshots_compare_submission_versions_and_never_expose_price(orders):  # noqa: F811
    f = orders
    submitted = f.submit()
    approved = ok(f.decision(submitted))
    revised = ok(f.action(approved, "revise"))
    changed = ok(f.client.put(f"/api/v1/purchase-orders/{revised['id']}",
        json={**f.body, "expected_version": revised["version"],
              "lines": [{**f.body["lines"][0], "quantity": "120"}]},
        headers={**f.headers["buyer"], "Idempotency-Key": str(uuid4())}))
    submitted2 = ok(f.action(changed, "submit"))
    review = ok(get(f, submitted2, "approval-snapshots"))
    assert review["current_version"] == submitted2["version"]
    assert [s["document_version"] for s in review["snapshots"]] == [submitted["version"], submitted2["version"]]
    before, after = [s["content"] for s in review["snapshots"]]
    assert ("Dòng 1.quantity", "100.000000", "120.000000") in snapshot_diff(before, after)
    assert snapshot_diff(after, review["current"]) == []
    assert "reference_unit_price" not in json.dumps(review)
    # A legacy priced draft can be submitted but its price/private attributes must stay hidden.
    legacy = ok(f.create(), 201)
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.document_line SET reference_unit_price=987654321 WHERE document_id=:id"), {"id": legacy["id"]})
        c.execute(text("UPDATE wms.document SET attributes='{" + '"private":"hidden-price"' + "}' WHERE id=:id"), {"id": legacy["id"]})
    legacy = ok(f.action(legacy, "submit"))
    projection = get(f, legacy, "approval-snapshots").text
    assert "987654321" not in projection and "hidden-price" not in projection
    receiver, _ = f.iam.user("scoped-receiver")
    f.iam.grant(receiver, "RECEIVER", f.warehouse)
    f.headers["scoped-receiver"] = f.iam.headers(f.iam.login("scoped-receiver"))
    assert get(f, legacy, "approval-snapshots", who="scoped-receiver").status_code == 404


def test_receipt_review_preserves_source_and_tracking_plan(receiving):  # noqa: F811
    f = receiving
    doc = ok(f.action(ok(f.receipt_create(), 201), "submit"))
    review = ok(get(f, doc, "approval-snapshots"))
    assert review["current"]["source_order_id"] == f.po["id"]
    assert review["current"]["lines"][0]["source_line_id"] == f.source_line
    assert review["current"]["lines"][0]["receipt_plan"]["destination_location_id"] == f.location["id"]
    assert snapshot_diff(review["snapshots"][0]["content"], review["current"]) == []


def test_legacy_approval_without_snapshot_is_explicitly_unavailable(orders):  # noqa: F811
    f = orders
    doc = ok(f.create(), 201)
    with f.engine.begin() as c:
        c.execute(text("""INSERT INTO wms.approval_request
            (id,document_id,document_version,policy_id,requested_by,status,created_at,content_snapshot)
            SELECT :id,:doc,1,id,:user,'INVALIDATED',now(),NULL FROM wms.approval_policy
            WHERE document_kind='PO' AND is_active"""), {"id": uuid4(), "doc": doc["id"], "user": f.buyer})
    review = ok(get(f, doc, "approval-snapshots"))
    assert review["snapshots"][0]["content"] is None
    assert review["current"]["lines"][0]["quantity"] == "100.000000"
