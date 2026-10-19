"""Blank cancel recovery must preserve reservations until a valid cancellation."""
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from test_issues import inventory, issuing  # noqa: F401
from test_openings import opening  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_return_recovery_validation import Variable

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.views.issues import IssueView
from packages.contracts.identity import SessionTokens


@pytest.mark.parametrize("action", ["cancel", "submit", "revise", "expire", "approve", "reject"])
@pytest.mark.parametrize("reason", ["", "  ", "ab", "x" * 2001])
def test_issue_actions_reject_bad_reason_before_journaling(action, reason):
    calls, errors = [], []
    view = SimpleNamespace(busy=False, presenter=SimpleNamespace(uncertain=None, command=lambda *a: calls.append(a)),
        doc={"id": str(uuid4()), "version": 6}, variables={"reason": Variable(reason), "qty": Variable("2")},
        orders_error=errors.append)
    IssueView.action(view, action)
    assert not calls and "3–2000" in errors[0]


def test_valid_cancel_preserves_version_and_trims_reason():
    calls = []
    doc_id = str(uuid4())
    view = SimpleNamespace(busy=False, presenter=SimpleNamespace(uncertain=None, command=lambda *a: calls.append(a)),
        doc={"id": doc_id, "version": 6}, variables={"reason": Variable("  Hủy phiếu cũ  "), "qty": Variable("2")},
        orders_error=lambda message: pytest.fail(message))
    IssueView.action(view, "cancel")
    assert calls == [("POST", f"documents/{doc_id}/cancel", {"expected_version": 6, "reason": "Hủy phiếu cũ"})]


@pytest.mark.integration
def test_unknown_cancel_recovery_is_read_only_then_cancel_exactly_once(issuing, tmp_path):  # noqa: F811
    f = issuing
    f.seed()
    doc = f.reserve(f.issue_approve(), "2")
    def transport(request):
        response = f.client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                    headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(transport))
    api._tokens = SessionTokens(access_token=f.headers["manager"]["Authorization"].split(" ", 1)[1],
                               refresh_token="test-only", expires_in=900)
    api.device_id = uuid4()
    api.enable_recovery()
    try:
        api.me()
        key, path = uuid4(), f"documents/{doc['id']}/cancel"
        bad = {"expected_version": doc["version"], "reason": ""}
        api._journal_call("prepare_command", "POST", path, bad, key, str(f.warehouse))
        api._journal_call("command_transition", key, "SENDING")
        api._journal_call("command_transition", key, "UNKNOWN")
        before, detail = inventory(f), f.issue_read(doc)
        with pytest.raises(ApiError) as error:
            api.recover(key)
        assert error.value.confirmed_rejection and error.value.code == "VALIDATION_ERROR"
        entry = api._journal_call("checked", key)
        assert entry["state"] == "CONFLICT" and entry["envelope"]["body"] == bad
        assert inventory(f) == before and f.issue_read(doc) == detail
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        fresh = uuid4()
        result = api.command("POST", path, {**bad, "reason": "Hủy phiếu không sử dụng"}, fresh)
        assert result["status"] == "CANCELLED" and result["version"] == doc["version"] + 1
        assert api.recover(fresh) == result
        assert inventory(f) == (0, 10, 0, 0)
        response = f.client.post("/api/v1/" + path, json=bad,
            headers={**f.headers["manager"], "Idempotency-Key": str(fresh), "X-WMS-Recovery": "lookup-v1"})
        assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
    finally:
        api.close()


@pytest.mark.integration
def test_cancel_proof_checks_shape_kind_version_permissions_and_existing_key(issuing):  # noqa: F811
    f = issuing
    doc = ok(f.issue_create(), 201)
    path = f"documents/{doc['id']}/cancel"
    def lookup(body, who="manager", key=None, target=path):
        return f.client.post("/api/v1/" + target, json=body, headers={**f.headers[who],
            "Idempotency-Key": str(key or uuid4()), "X-WMS-Recovery": "lookup-v1"})
    bad = {"expected_version": doc["version"], "reason": ""}
    for body in [{**bad, "expected_version": 99}, {**bad, "extra": 1}, {**bad, "reason": "ab"},
                 {**bad, "expected_version": True}]:
        response = lookup(body)
        assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
    source = f.sales()
    response = lookup({**bad, "expected_version": source["version"]}, target=f"documents/{source['id']}/cancel")
    assert "X-WMS-Rejected" not in response.headers
    untouched = ok(f.issue_create(), 201)
    untouched_path = f"documents/{untouched['id']}/cancel"
    key = uuid4()
    ok(f.action(doc, "cancel", who="manager", key=key))
    response = lookup(bad, key=key, target=untouched_path)
    assert "X-WMS-Rejected" not in response.headers
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:user"), {"user": f.manager})
    response = lookup(bad, target=untouched_path)
    assert "X-WMS-Rejected" not in response.headers


@pytest.mark.gui
def test_real_issue_cancel_button_blocks_blank_reason():
    import gc
    import tkinter as tk
    root = tk.Tk()
    view = IssueView(root, SimpleNamespace(session_generation=1))
    try:
        view.pack(fill="both", expand=True)
        view.session_changed(SimpleNamespace(id=uuid4()), [SimpleNamespace(id=uuid4(), code="TEST", name="Kho thử")])
        view.doc = {"id": str(uuid4()), "version": 6, "allowed_actions": ["cancel"]}
        view.enable()
        root.update()
        view.buttons["cancel"].invoke()
        assert "3–2000" in view.variables["status"].get()
        assert view.presenter.pending is None and not view.presenter.commands
    finally:
        view.presenter.close()
        view.presenter.finish()
        view.variables.clear()
        root.destroy()
        del view
        gc.collect()
