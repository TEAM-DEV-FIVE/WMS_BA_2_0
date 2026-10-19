"""Blank transfer evidence/reason is locally blocked and legacy UNKNOWN is recoverable."""
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from test_openings import opening, orders  # noqa: F401
from test_transfers import transfer  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.views.transfers import TransferView
from packages.contracts.identity import SessionTokens


@pytest.mark.parametrize("action", ["dispatch", "receive"])
@pytest.mark.parametrize("field", ["reason", "evidence"])
@pytest.mark.parametrize("invalid", ["", "  ", "ab", "x" * 2001])
def test_transfer_post_validates_before_journalling(action, field, invalid):
    values = dict(reason="Nhận hàng kiểm thử", evidence="BB-001", receive_day="2026-10-19", received="1")
    values[field] = invalid
    calls, errors = [], []
    view = SimpleNamespace(
        doc=dict(id=str(uuid4()), version=4, sources=[dict(dispatch_move_id=str(uuid4()))]),
        locations=[dict(id=str(uuid4()))], variable=lambda name: SimpleNamespace(get=lambda: values[name]),
        source_selector=SimpleNamespace(current=lambda: 0), location_selector=SimpleNamespace(current=lambda: 0),
        condition_selector=SimpleNamespace(current=lambda: 0), workflow_error=errors.append,
        presenter=SimpleNamespace(command=lambda *args: calls.append(args)))
    TransferView.action(view, action)
    assert not calls and len(errors) == 1 and "3–2000" in errors[0]


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["dispatch", "receive"])
def test_legacy_blank_post_lookup_rejects_read_only_then_post_once(transfer, tmp_path, operation):  # noqa: F811
    f = transfer
    doc = f.tr_approve(f.tr_seed())
    if operation == "receive":
        response = f.tr_dispatch(doc)
        assert response.status_code == 200
        doc = response.json()
        good = f.tr_receive_body(doc, "20")
    else:
        good = f.tr_post_body(doc)
    path = f"transfers/{doc['id']}/{operation}"
    bad = {**good, "reason": "", "evidence_ref": ""}

    def transport(request):
        response = f.client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                    headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)

    def snapshot():
        with f.engine.connect() as c:
            counts = {table: c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one()
                      for table in ("document", "stock_move", "inventory_transaction", "idempotency_record")}
            counts["version"] = c.execute(text("SELECT version FROM wms.document WHERE id=:id"),
                                           {"id": doc["id"]}).scalar_one()
            counts["balances"] = c.execute(text("SELECT id,on_hand,reserved,version FROM wms.stock_balance ORDER BY id")).all()
            return counts

    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(transport))
    api._tokens = SessionTokens(access_token=f.headers["manager"]["Authorization"].split(" ", 1)[1],
                                refresh_token="test-only", expires_in=900)
    api.device_id = uuid4()
    api.enable_recovery()
    try:
        api.me()
        key = uuid4()
        api._journal_call("prepare_command", "POST", path, bad, key, str(f.warehouse))
        api._journal_call("command_transition", key, "SENDING")
        api._journal_call("command_transition", key, "UNKNOWN")
        before = snapshot()
        # Both blank, one blank, and whitespace-only legacy bodies are certifiable.
        for body in (bad, {**good, "reason": "  "}, {**good, "evidence_ref": ""}):
            response = f.client.post("/api/v1/" + path, json=body,
                headers={**f.headers["manager"], "Idempotency-Key": str(uuid4()), "X-WMS-Recovery": "lookup-v1"})
            assert response.status_code == 422 and "X-WMS-Rejected" in response.headers
        # Bad versions, other invalid fields, nonblank invalid evidence and unknown
        # fields must not cause a terminal rejection under this narrow recovery rule.
        for body in ({**bad, "expected_version": doc["version"] - 1},
                     {**bad, "execution_key": "not-a-uuid"}, {**good, "reason": "ab"},
                     {**bad, "unexpected": "value"}):
            response = f.client.post("/api/v1/" + path, json=body,
                headers={**f.headers["manager"], "Idempotency-Key": str(uuid4()), "X-WMS-Recovery": "lookup-v1"})
            assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
        for who in (["receiver", "buyer"] if operation == "dispatch" else ["sender", "buyer"]):
            response = f.client.post("/api/v1/" + path, json=bad,
                headers={**f.headers[who], "Idempotency-Key": str(uuid4()), "X-WMS-Recovery": "lookup-v1"})
            assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers

        with pytest.raises(ApiError) as lookup:
            api.recover(key)
        assert lookup.value.code == "VALIDATION_ERROR" and lookup.value.confirmed_rejection
        saved = api._journal_call("checked", key)
        assert saved["state"] == "CONFLICT" and saved["envelope"]["body"] == bad
        assert snapshot() == before
        new_key = uuid4()
        result = api.command("POST", path, good, new_key)
        assert result["status"] == ("PARTIAL" if operation == "dispatch" else "COMPLETED")
        after = snapshot()
        assert after["inventory_transaction"] == before["inventory_transaction"] + 1
        assert after["stock_move"] == before["stock_move"] + 1
        assert after["version"] == before["version"] + 1
        assert api.recover(new_key) == result and snapshot() == after
        response = f.client.post("/api/v1/" + path, json=bad,
            headers={**f.headers["manager"], "Idempotency-Key": str(new_key), "X-WMS-Recovery": "lookup-v1"})
        assert response.status_code == 422 and "X-WMS-Rejected" not in response.headers
        assert api._journal_call("checked", new_key)["state"] == "COMMITTED"
    finally:
        api.close()


@pytest.mark.gui
def test_receive_button_blocks_blank_evidence_then_sends_validated_body():
    import gc
    import tkinter as tk

    root = tk.Tk()
    view = TransferView(root, SimpleNamespace(session_generation=1))
    try:
        view.pack(fill="both", expand=True)
        warehouse, move, location = uuid4(), uuid4(), uuid4()
        view.session_changed(SimpleNamespace(id=uuid4()), [SimpleNamespace(id=warehouse, code="TEST", name="Kho")])
        view.doc = dict(id=str(uuid4()), version=4, source_transfer_id=None,
                        allowed_actions=["receive"], sources=[dict(dispatch_move_id=str(move))])
        view.source_selector.configure(values=["Hàng đang chuyển"])
        view.source_selector.current(0)
        view.locations = [dict(id=str(location))]
        view.location_selector.configure(values=["BD-RECEIVING"])
        view.location_selector.current(0)
        view.variable("received").set("1")
        view.variable("receive_day").set("2026-10-19")
        view.variable("reason").set("Nhận hàng kiểm thử")
        view.variable("evidence").set("")
        view.enable()
        root.update()
        calls = []
        view.presenter.command = lambda *args: calls.append(args)
        view.receive_button.invoke()
        assert not calls and "Chứng cứ" in view.variable("status").get()
        view.variable("evidence").set("  BB-001  ")
        view.receive_button.invoke()
        assert len(calls) == 1, view.variable("status").get()
        assert calls[0][2]["evidence_ref"] == "BB-001"
        assert calls[0][2]["lines"][0]["quantity_base"] == "1"
        assert calls[0][2]["lines"][0]["destination_location_id"] == str(location)
    finally:
        view.presenter.close()
        view.presenter.finish()
        view.variables.clear()
        root.destroy()
        del view
        gc.collect()
