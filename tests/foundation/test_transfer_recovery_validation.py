"""A same-warehouse transfer must reject definitively without creating any rows."""
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


@pytest.mark.integration
def test_same_warehouse_legacy_retry_rejects_then_corrected_create_replays(transfer, tmp_path):  # noqa: F811
    f = transfer
    stock = f.tr_seed()
    bad = dict(warehouse_id=str(f.warehouse), destination_warehouse_id=str(f.warehouse),
               business_date="2026-10-02", reason="Chuyển kho kiểm thử",
               lines=[dict(stock_item_id=stock, source_location_id=f.location["id"], quantity_base="1")])

    def transport(request):
        response = f.client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                    headers=dict(request.headers))
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)

    def counts():
        with f.engine.connect() as c:
            return {table: c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one()
                    for table in ("document", "location", "document_line", "transfer_line",
                                  "stock_move", "inventory_transaction", "idempotency_record")}

    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(transport))
    api._tokens = SessionTokens(access_token=f.headers["manager"]["Authorization"].split(" ", 1)[1],
                                refresh_token="test-only", expires_in=900)
    api.device_id = uuid4()
    api.enable_recovery()
    try:
        api.me()
        key = uuid4()
        api._journal_call("prepare_command", "POST", "transfers", bad, key, str(f.warehouse))
        api._journal_call("command_transition", key, "SENDING")
        api._journal_call("command_transition", key, "UNKNOWN")
        before = counts()
        with pytest.raises(ApiError) as lookup:
            api.recover(key)
        assert lookup.value.code == "OPERATION_UNCONFIRMED"
        assert api._journal_call("checked", key)["state"] == "UNKNOWN"
        assert counts() == before
        with pytest.raises(ApiError) as retry:
            api.recover(key, retry=True)
        assert retry.value.code == "INVALID_WAREHOUSE" and retry.value.confirmed_rejection
        saved = api._journal_call("checked", key)
        assert saved["state"] == "CONFLICT" and saved["envelope"]["body"] == bad
        assert counts() == before

        # Authorization still runs before the handler can certify a rejection.
        unauthorized = f.client.post("/api/v1/transfers", json=bad,
            headers={**f.headers["sender"], "Idempotency-Key": str(uuid4()), "X-WMS-Recovery": "send-v1"})
        assert unauthorized.status_code == 403 and "X-WMS-Rejected" not in unauthorized.headers

        good = {**bad, "destination_warehouse_id": str(f.destination)}
        new_key = uuid4()
        result = api.command("POST", "transfers", good, new_key)
        assert result["status"] == "DRAFT" and result["version"] == 1
        assert api.recover(new_key) == result
        after = counts()
        assert after["document"] == before["document"] + 1
        assert after["location"] == before["location"] + 1
        assert after["idempotency_record"] == before["idempotency_record"] + 1
        assert after["stock_move"] == before["stock_move"]
        mismatch = f.client.post("/api/v1/transfers", json=bad,
            headers={**f.headers["manager"], "Idempotency-Key": str(new_key), "X-WMS-Recovery": "send-v1"})
        assert mismatch.status_code == 409 and mismatch.json()["code"] == "IDEMPOTENCY_MISMATCH"
        assert "X-WMS-Rejected" not in mismatch.headers
        assert counts() == after
    finally:
        api.close()


@pytest.mark.gui
def test_new_transfer_clears_old_document_and_blocks_same_warehouse_save():
    import gc
    import tkinter as tk

    root = tk.Tk()
    source, destination = uuid4(), uuid4()
    view = TransferView(root, SimpleNamespace(session_generation=1))
    try:
        view.pack(fill="both", expand=True)
        view.session_changed(SimpleNamespace(id=uuid4()), [
            SimpleNamespace(id=source, code="SRC", name="Kho nguồn"),
            SimpleNamespace(id=destination, code="DST", name="Kho đích")])
        view.permissions = ["transfer.draft"]
        view.doc = {"id": str(uuid4()), "status": "PARTIAL"}
        for field in ("detail", "reason", "evidence"):
            view.variable(field).set("Old transfer")
        view.destination_selector.current(0)
        view.new()
        assert view.doc is None and "Lệnh chuyển mới" in view.variable("detail").get()
        assert view.destination_selector.current() == -1
        assert view.variable("reason").get() == view.variable("evidence").get() == ""

        view.destination_selector.current(0)
        view.variable("reason").set("Chuyển kho kiểm thử")
        view.lines = [dict(stock_item_id=str(uuid4()), source_location_id=str(uuid4()), quantity_base="1")]
        calls = []
        view.presenter.command = lambda *args: calls.append(args)
        view.buttons["save"].invoke()
        assert not calls and "phải khác nhau" in view.variable("status").get()
        view.destination_selector.current(1)
        view.buttons["save"].invoke()
        assert len(calls) == 1 and calls[0][:2] == ("POST", "transfers")
        assert calls[0][2]["warehouse_id"] == str(source)
        assert calls[0][2]["destination_warehouse_id"] == str(destination)
    finally:
        view.presenter.close()
        view.presenter.finish()
        view.variables.clear()
        root.destroy()
        del view
        gc.collect()
