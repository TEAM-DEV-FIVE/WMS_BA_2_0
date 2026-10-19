"""Regression: a rejected empty reason must not permanently block a saved return."""
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from test_move_quality import movement, receiving  # noqa: F401
from test_orders import ok, orders  # noqa: F401
from test_returns import returning  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.local_store.commands import CommandStore
from apps.desktop.local_store.recovery import recover_command
from apps.desktop.views.recovery import RecoveryView
from apps.desktop.views.returns import ReturnView
from packages.contracts.identity import SessionTokens


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.mark.parametrize("action", ["submit", "revise", "cancel", "approve", "reject", "post"])
@pytest.mark.parametrize("reason", ["", "  ", "ab", "x" * 2001])
def test_return_actions_validate_before_creating_a_command(action, reason):
    calls, errors = [], []
    view = SimpleNamespace(busy=False, presenter=SimpleNamespace(uncertain=None, command=lambda *a: calls.append(a)),
                           doc={"id": str(uuid4()), "version": 1}, variables={"reason": Variable(reason)},
                           workflow_error=errors.append)
    ReturnView.action(view, action)
    assert not calls
    assert errors and "3–2000" in errors[0]


def test_valid_return_submit_keeps_exact_version_and_trimmed_reason():
    calls = []
    doc_id = str(uuid4())
    view = SimpleNamespace(busy=False, presenter=SimpleNamespace(uncertain=None, command=lambda *a: calls.append(a)),
                           doc={"id": doc_id, "version": 1}, variables={"reason": Variable("  Khách trả hàng  ")},
                           workflow_error=lambda message: pytest.fail(message))
    ReturnView.action(view, "submit")
    assert calls == [("POST", f"documents/{doc_id}/submit", {"expected_version": 1, "reason": "Khách trả hàng"})]


@pytest.mark.parametrize("confirmed", [False, True])
def test_unknown_only_becomes_conflict_with_confirmed_rejection(tmp_path, confirmed):
    store = CommandStore(tmp_path, server_id="test", user_id=uuid4(), device_id=uuid4())
    try:
        key = uuid4()
        store.prepare_command("POST", f"documents/{uuid4()}/submit", {"expected_version": 1, "reason": ""}, key)
        store.command_transition(key, "SENDING")
        store.command_transition(key, "UNKNOWN")
        def request(*args, **kwargs):
            failure = ApiError("VALIDATION_ERROR", "Dữ liệu không hợp lệ")
            failure.confirmed_rejection = confirmed
            raise failure
        api = SimpleNamespace(_recovery_request=request, _journal_call=lambda action, *a: getattr(store, action)(*a))
        original = store.checked(key)["envelope"]
        with pytest.raises(ApiError):
            recover_command(api, store.checked(key), retry=True)
        record = store.checked(key)
        assert record["state"] == ("CONFLICT" if confirmed else "UNKNOWN")
        assert record["envelope"] == original
    finally:
        store.close()


def test_failed_lookup_preserves_recovery_rows_and_selection():
    from concurrent.futures import Future
    future = Future()
    future.set_result((None, None, "Dữ liệu không hợp lệ"))
    queue = Queue()
    queue.put((1, 2, future))
    rows = {"old-key": {"state": "UNKNOWN"}}
    view = SimpleNamespace(results=queue, closed=False, sequence=1, pending=future,
                           api=SimpleNamespace(session_generation=2), rows=rows, status=Variable(""))
    RecoveryView.drain(view)
    assert view.rows is rows and view.status.get() == "Dữ liệu không hợp lệ"
    assert view.pending is None


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["CUSTOMER_RETURN", "SUPPLIER_RETURN"])
def test_invalid_submit_recovered_then_valid_submit_once(returning, tmp_path, kind):  # noqa: F811
    f = returning
    if kind == "CUSTOMER_RETURN":
        source, _, _ = f.issued_source("2")
        payload = f.return_body(source, "1", kind, f.quarantine["id"])
    else:
        f.received("2")
        source = f.return_sources()["items"][0]
        payload = f.return_body(source, "1")
    doc = ok(f.request("POST", "returns", payload), 201)
    def transport(request):
        response = f.client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                    headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(transport))
    api._tokens = SessionTokens(access_token=f.headers["buyer"]["Authorization"].split(" ", 1)[1],
                                refresh_token="test-only", expires_in=900)
    api.device_id = uuid4()
    api.enable_recovery()
    try:
        api.me()
        path, key = f"documents/{doc['id']}/submit", uuid4()
        bad = {"expected_version": 1, "reason": ""}
        # Reconstruct a legacy journal entry. No new invalid command is sent.
        api._journal_call("prepare_command", "POST", path, bad, key, str(f.warehouse))
        api._journal_call("command_transition", key, "SENDING")
        api._journal_call("command_transition", key, "UNKNOWN")
        before = ok(f.read(doc, kind="returns"))
        with pytest.raises(ApiError) as error:
            api.recover(key)
        assert error.value.code == "VALIDATION_ERROR" and error.value.confirmed_rejection
        record = api._journal_call("checked", key)
        assert record["state"] == "CONFLICT" and record["envelope"]["body"] == bad
        assert ok(f.read(doc, kind="returns")) == before
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 0
        new_key = uuid4()
        good = {"expected_version": 1, "reason": "Khách trả hàng chờ kiểm tra"}
        result = api.command("POST", path, good, new_key)
        assert result["status"] == "SUBMITTED" and result["version"] == 2
        assert api.recover(new_key) == result
        assert len(api.recovery_records()) == 2
        # Never certify invalid payload against an existing committed key or a changed document.
        response = f.client.post("/api/v1/" + path, json=bad, headers={**f.headers["buyer"],
            "Idempotency-Key": str(new_key), "X-WMS-Recovery": "lookup-v1"})
        assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
        assert api._journal_call("checked", new_key)["state"] == "COMMITTED"
    finally:
        api.close()


@pytest.mark.integration
def test_invalid_lookup_requires_current_owner_scope_and_matching_version(returning):  # noqa: F811
    f = returning
    f.received("2")
    doc = ok(f.request("POST", "returns", f.return_body(f.return_sources()["items"][0], "1")), 201)
    path = f"documents/{doc['id']}/submit"
    key = uuid4()
    for who, version in [("manager", 1), ("buyer", 2)]:
        bad = {"expected_version": version, "reason": ""}
        response = f.client.post("/api/v1/" + path, json=bad, headers={**f.headers[who],
            "Idempotency-Key": str(key), "X-WMS-Recovery": "lookup-v1"})
        assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
    with f.engine.begin() as c:
        c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE user_id=:user"), {"user": f.buyer})
    bad = {"expected_version": 1, "reason": ""}
    response = f.client.post("/api/v1/" + path, json=bad, headers={**f.headers["buyer"],
        "Idempotency-Key": str(key), "X-WMS-Recovery": "lookup-v1"})
    assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers


@pytest.mark.gui
def test_real_return_widgets_block_empty_reason_before_sending():
    import gc
    import tkinter as tk
    root = tk.Tk()
    view = ReturnView(root, SimpleNamespace(session_generation=1), "CUSTOMER_RETURN")
    try:
        view.pack(fill="both", expand=True)
        view.session_changed(SimpleNamespace(id=uuid4()), [SimpleNamespace(id=uuid4(), code="TEST", name="Kho thử")])
        view.doc = {"id": str(uuid4()), "version": 1, "allowed_actions": ["submit"]}
        view.enable()
        root.update()
        assert view.buttons["submit"].instate(["!disabled"])
        view.buttons["submit"].invoke()
        assert "3–2000" in view.variables["status"].get()
        assert not view.presenter.commands and view.presenter.pending is None
        calls = []
        view.presenter.command = lambda *args: calls.append(args)
        view.variables["reason"].set("Khách trả hàng kiểm thử")
        view.buttons["submit"].invoke()
        assert calls[0][2] == {"expected_version": 1, "reason": "Khách trả hàng kiểm thử"}
    finally:
        view.presenter.close()
        view.presenter.finish()
        view.variables.clear()
        root.destroy()
        del view
        gc.collect()
