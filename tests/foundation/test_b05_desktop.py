"""B05 UI evidence using Tk → HTTP → FastAPI → disposable PostgreSQL."""

import socket
import threading
import time
import tkinter as tk
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
import uvicorn
from sqlalchemy import text
from test_traceability import trace  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.views.shell import DesktopShell

pytestmark = [pytest.mark.integration, pytest.mark.gui]


@contextmanager
def desktop(iam, username="keeper"):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 8
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        def wait(predicate):
            deadline = time.monotonic() + 8
            while not predicate() and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            assert predicate()
        session = shell.session_view
        session.username.set(username)
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: shell.master_view.actor_id is not None)
        root.update()
        yield shell, wait
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=8)
        sock.close()
        assert not thread.is_alive()


def fill(view, **values):
    for field, value in values.items():
        view.variables[field].set(value)


def switch(view, label):
    view.entity.set(label)
    view.switch()


def pick(view, field, query, wait):
    view.open_reference(field)
    wait(lambda: not view.busy)
    dialog = view.lookup
    dialog.query.set(query)
    dialog.load()
    wait(lambda: not view.busy)
    assert len(dialog.rows) == 1
    dialog.table.selection_set(next(iter(dialog.rows)))
    dialog.choose()


def test_b05_large_lookup_location_tree_versions_and_keyboard(trace):  # noqa: F811
    with trace.engine.begin() as connection:
        connection.execute(text("""INSERT INTO wms.uom(id,code,name,decimal_places,is_active,version)
            VALUES (:id,:code,:name,0,true,1)"""),
                           [{"id": UUID(int=10000 + i), "code": f"B05-{i:03}", "name": f"Đơn vị {i}"} for i in range(235)])
    with desktop(trace.iam) as (shell, wait):
        view = shell.master_view
        shell.notebook.select(shell.master_container)
        switch(view, "Sản phẩm")
        wait(lambda: not view.busy)
        view.open_reference("base_uom_id")
        wait(lambda: not view.busy)
        dialog = view.lookup
        assert len(dialog.rows) == 50
        seen = set(dialog.rows)
        for _ in range(4):
            dialog.load(True)
            wait(lambda: not view.busy)
            assert not seen.intersection(dialog.rows)
            seen.update(dialog.rows)
        assert len(seen) == 235
        dialog.query.set("B05-234")
        dialog.load()
        wait(lambda: not view.busy)
        assert len(dialog.rows) == 1
        chosen = next(iter(dialog.rows))
        dialog.table.selection_set(chosen)
        dialog.choose()
        fill(view, sku="LOOKUP-LARGE", name="Sản phẩm tiếng Việt")
        view.reason.set("Tạo bằng lookup hơn 200 dòng")
        view.save()
        wait(lambda: not view.busy)
        assert view.current["base_uom_id"] == chosen
        assert view.search.bind("<Return>")
        product = view.current.copy()
        payload = {k: v for k, v in product.items() if k not in {"id", "version"}}
        result = trace.client.put("/api/v1/master/products/" + product["id"],
                                  json={**payload, "expected_version": 1, "reason": "Cập nhật cạnh tranh"},
                                  headers={**trace.headers, "Idempotency-Key": str(uuid4())})
        assert result.status_code == 200
        view.variables["name"].set("Nội dung phải được giữ")
        view.reason.set("Thử stale version")
        view.save()
        wait(lambda: not view.busy)
        assert view.current["version"] == 1
        assert view.variables["name"].get() == "Nội dung phải được giữ"
        assert "Dữ liệu đã thay đổi" in view.status.get()
        view.query.set(product["sku"])
        view.load()
        wait(lambda: not view.busy)
        assert view.current["version"] == 2

        switch(view, "Vị trí")
        wait(lambda: not view.busy)
        pick(view, "warehouse_id", "TRACE", wait)
        fill(view, code="ZONE-B05", name="Phân khu", kind="Zone / Rack")
        view.reason.set("Tạo Zone qua GUI")
        view.save()
        wait(lambda: not view.busy)
        zone = view.current.copy()
        view.new()
        pick(view, "warehouse_id", "TRACE", wait)
        pick(view, "parent_id", "ZONE-B05", wait)
        fill(view, code="RACK-B05", name="Kệ", kind="Zone / Rack")
        view.reason.set("Tạo Rack qua GUI")
        view.save()
        wait(lambda: not view.busy)
        rack = view.current.copy()
        view.new()
        pick(view, "warehouse_id", "TRACE", wait)
        pick(view, "parent_id", "RACK-B05", wait)
        fill(view, code="BIN-B05", name="Ô lưu trữ", kind="Bin lưu trữ")
        view.reason.set("Tạo Bin qua GUI")
        view.save()
        wait(lambda: not view.busy)
        bin_row = view.current.copy()
        view.query.set("BIN-B05")
        view.load()
        wait(lambda: not view.busy)
        assert view.table.parent(bin_row["id"]) == rack["id"]
        assert view.table.parent(rack["id"]) == zone["id"]
        assert view.table.parent(zone["id"]) == "wh:" + str(trace.warehouse)
        # An invalid self-parent is rejected by the real API and retains the form.
        view.new()
        view.display(zone)
        view.set_reference("parent_id", zone)
        view.reason.set("Thử tạo vòng lặp")
        view.save()
        wait(lambda: not view.busy)
        assert not view.status.get().startswith("Đã lưu")


def test_b05_product_uom_barcode_and_price_permissions(trace):  # noqa: F811
    product = trace.product()
    unit = trace.create("uoms", code="BOX-B05", name="Hộp", decimal_places=0)
    trace.iam.grant(trace.user, "CONTROLLER")  # GLOBAL price.write does not confer warehouse price.read.
    with desktop(trace.iam) as (shell, wait):
        view = shell.product_details_view
        shell.notebook.select(shell.master_container)
        shell.master_container.select(view)
        view.set_product(product)
        view.set_uom(unit)
        fill(view, factor="12", reason="Mỗi hộp 12 chiếc")
        view.save()
        wait(lambda: not view.busy)
        assert view.status.get().startswith("Đã lưu")
        view.set_product(product)
        view.load()
        wait(lambda: not view.busy)
        assert view.product["version"] == 2
        conversion = next(row for row in view.rows.values() if row["uom_id"] == unit["id"])
        view.mode.set("Barcode")
        view.switch()
        view.set_product(product)
        view.set_conversion(conversion)
        fill(view, code="0000123456", reason="Mã quét giữ số 0 đầu")
        view.save()
        wait(lambda: not view.busy)
        assert view.current["code"] == "0000123456"
        view.new()
        view.set_conversion(conversion)
        fill(view, code="0000123456", reason="Thử mã trùng")
        view.save()
        wait(lambda: not view.busy)
        assert "Mã đã tồn tại" in view.status.get()
        assert view.variables["code"].get() == "0000123456"
        view.query.set("0000123456")
        view.load()
        wait(lambda: not view.busy)
        view.table.selection_set(next(iter(view.rows)))
        view.select()
        fill(view, is_active="Không", reason="Ngừng barcode")
        view.save()
        wait(lambda: not view.busy)
        assert view.current["is_active"] is False

        view.mode.set("Giá tham chiếu")
        view.switch()
        view.set_product(product)
        fill(view, effective_on="2026-10-03", amount="1234.5000", currency="VND", source="Báo giá thử B05")
        view.save()
        wait(lambda: not view.busy)
        assert view.status.get().startswith("Đã lưu")
        assert not view.save_button.instate(["disabled"])
        view.load()
        wait(lambda: not view.busy)
        # Warehouse manager intentionally has no price.read by default.
        assert not view.rows
        trace.iam.grant(trace.user, "CONTROLLER", trace.warehouse)
        view.set_product(product)
        view.load()
        wait(lambda: not view.busy)
        assert view.rows, view.status.get()
        assert next(iter(view.rows.values()))["amount"] == "1234.5000"
        with trace.engine.begin() as connection:
            connection.execute(text("DELETE FROM wms.user_role_grant WHERE user_id=:user AND role_id IN "
                                    "(SELECT id FROM wms.role WHERE code='CONTROLLER')"), {"user": trace.user})
        view.load()
        wait(lambda: not view.busy)
        assert not view.rows and not view.product


def test_b05_owner_agreement_forms_and_ten_plus_five(trace):  # noqa: F811
    with desktop(trace.iam) as (shell, wait):
        catalog = shell.ownership_view.catalog
        shell.notebook.select(shell.master_container)
        shell.master_container.select(shell.ownership_view)
        catalog.load()
        wait(lambda: not catalog.busy)
        fill(catalog, code="OWNER-GUI", name="Chủ hàng từ GUI")
        pick(catalog, "partner_id", "NCC-01", wait)
        catalog.reason.set("Lập chủ hàng từ GUI")
        catalog.save()
        wait(lambda: not catalog.busy)
        owner = catalog.current.copy()
        switch(catalog, "Hợp đồng ký gửi")
        wait(lambda: not catalog.busy)
        pick(catalog, "owner_id", "OWNER-GUI", wait)
        pick(catalog, "warehouse_id", "TRACE", wait)
        fill(catalog, code="AGREE-GUI", valid_from="2026-01-01", valid_until="2027-12-31", source_ref="Hợp đồng fixture B05")
        catalog.reason.set("Tạo hợp đồng từ GUI")
        catalog.save()
        wait(lambda: not catalog.busy)
        agreement = catalog.current.copy()
        assert agreement["owner_id"] == owner["id"]
        catalog.variables["source_ref"].set("Hợp đồng hiệu chỉnh")
        catalog.reason.set("Hiệu chỉnh trước phát sinh")
        catalog.save()
        wait(lambda: not catalog.busy)
        assert catalog.current["version"] == 2
        product = trace.product()
        owned = trace.receipt(product, qty=10)
        trace.receipt(product, qty=5, owner=owner["id"], agreement=agreement["id"])
        stock = shell.ownership_view.stock
        stock.location.set(str(trace.location))
        stock.item.set(str(owned["item"]))
        stock.search()
        wait(lambda: not stock.busy)
        assert "Vật lý: 15.000000" in stock.totals.get()
        assert "Doanh nghiệp: 10.000000" in stock.totals.get()
        assert "Ký gửi: 5.000000" in stock.totals.get()
        assert stock.table.item(stock.table.get_children()[0], "values")[0] == owner["id"]
        stock.scope_changed()
        assert not stock.totals.get() and not stock.table.get_children()


def test_b05_serial_evidence_revisions_stale_withdraw_and_scope(trace):  # noqa: F811
    receipt = trace.receipt(serial_code="000-B05-WARRANTY")
    with desktop(trace.iam) as (shell, wait):
        view = shell.serial_view
        shell.notebook.select(view)
        view.code.set("000-B05-WARRANTY")
        view.search()
        wait(lambda: not view.busy)
        assert next(iter(view.rows.values())).status == "UNKNOWN"
        assert "Nhà cung cấp giả" in view.details.get()
        for field, value in {"starts_on": "2026-01-01", "ends_on": "2027-01-01", "evidence_ref": "Chứng cứ GUI",
                             "reason": "Ghi theo phiếu bảo hành"}.items():
            view.evidence_vars[field].set(value)
        view.save_evidence()
        wait(lambda: not view.busy)
        assert "revision 1" in view.status.get()
        view.search()
        wait(lambda: not view.busy)
        assert next(iter(view.rows.values())).status == "VALID"
        assert trace.record(receipt, version=1, starts_on="2025-01-01", ends_on="2026-01-01", evidence_ref="Chứng cứ hết hạn").status_code == 201
        view.evidence_vars["reason"].set("Thử stale warranty")
        view.save_evidence()
        wait(lambda: not view.busy)
        assert "Dữ liệu đã thay đổi" in view.status.get()
        assert view.evidence_vars["evidence_ref"].get() == "Chứng cứ GUI"
        view.search()
        wait(lambda: not view.busy)
        assert next(iter(view.rows.values())).status == "EXPIRED"
        view.evidence_vars["reason"].set("Rút chứng cứ bị sai nguồn")
        view.save_evidence(withdraw=True)
        wait(lambda: not view.busy)
        assert "revision 3" in view.status.get()
        view.search()
        wait(lambda: not view.busy)
        assert next(iter(view.rows.values())).status == "UNKNOWN"
        with trace.engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM wms.serial_warranty_record WHERE serial_id=:id"),
                                      {"id": receipt["serial"]}).scalar_one() == 3
        # Lose the HTTP acknowledgement after a real commit, then reload the same
        # identity and explicitly replay the retained command through HTTP.
        api = shell.session_view.presenter.api
        command = api.command
        def lose_ack(method, path, body, key):
            command(method, path, body, key)
            raise ApiError("TIMEOUT", "Mất ACK sau commit")
        api.command = lose_ack
        view.evidence_vars["reason"].set("Ghi nhận vẫn thiếu nguồn")
        view.save_evidence()
        wait(lambda: not view.busy)
        pending = view.presenter.uncertain
        assert pending and "Chưa rõ kết quả" in view.status.get()
        api.command = command
        shell.session_view.reload()
        wait(lambda: view.presenter.uncertain == pending and shell.session_view.presenter.pending is None)
        view.presenter.retry()
        wait(lambda: not view.busy)
        assert not view.presenter.uncertain and "revision 4" in view.status.get()
        with trace.engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM wms.serial_warranty_record WHERE serial_id=:id"),
                                      {"id": receipt["serial"]}).scalar_one() == 4
        view.code.set("DOES-NOT-EXIST")
        view.search()
        wait(lambda: not view.busy)
        assert not view.rows and not view.details.get()
        with trace.engine.begin() as connection:
            connection.execute(text("DELETE FROM wms.user_role_grant WHERE id=:id"), {"id": trace.grant})
        view.code.set("000-B05-WARRANTY")
        view.search()
        wait(lambda: not view.busy)
        assert not view.rows and not view.details.get() and not view.permissions
        assert view.save_button.instate(["disabled"])
