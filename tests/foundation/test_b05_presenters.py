import threading
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.presenters.master_data import MasterDataPresenter
from apps.desktop.presenters.ownership import OwnershipPresenter
from apps.desktop.presenters.serial_lookup import SerialLookupPresenter


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.events = []

    def __getattr__(self, name):
        if name.startswith(("catalog_", "lookup_")):
            def event(*args, **kwargs):
                assert threading.get_ident() == self.main
                self.events.append((name, args, kwargs))
            return event
        raise AttributeError(name)


def drain(presenter):
    try:
        presenter.pending.result(timeout=5)
    except ApiError:
        pass
    presenter.drain()


def finish(presenter):
    presenter.close()
    presenter.finish()


@pytest.mark.parametrize("presenter_type", [MasterDataPresenter, OwnershipPresenter, SerialLookupPresenter])
def test_b05_presenters_drop_completed_response_after_session_generation_changes(presenter_type):
    gate, started = threading.Event(), threading.Event()
    class Api:
        session_generation = 0
        def in_session(self, generation, action):
            return action()
        def permissions(self, warehouse):
            return ["serial.read", "warranty.write"]
        def get(self, path):
            started.set()
            assert gate.wait(5)
            if presenter_type is SerialLookupPresenter:
                return []
            if presenter_type is OwnershipPresenter:
                return {"warehouse_id": str(uuid4()), "location_id": str(uuid4()), "stock_item_id": str(uuid4()),
                        "physical_base": "15.000000", "owned_base": "10.000000", "unclassified_base": "0.000000",
                        "consigned_by_owner": [], "as_of": "2026-10-03T00:00:00Z"}
            return {"items": [{"id": "old-user"}], "next_after": None}
    api, view = Api(), View()
    presenter = presenter_type(view, api)
    try:
        if presenter_type is SerialLookupPresenter:
            presenter.search(uuid4(), "000001")
        elif presenter_type is OwnershipPresenter:
            presenter.search(uuid4(), uuid4(), uuid4())
        else:
            presenter.reference("master/products", "ĐIỆN%_")
        assert started.wait(5)
        api.session_generation += 1
        gate.set()
        drain(presenter)
        assert not any(event[0] in {"catalog_loaded", "catalog_reference_loaded", "lookup_result"} for event in view.events)
    finally:
        gate.set()
        finish(presenter)


@pytest.mark.parametrize("resource", ["prices", "stock-owners", "consignment-agreements"])
def test_b05_commands_keep_identical_key_and_payload_on_unknown_result(resource):
    class Api:
        session_generation = 0
        def __init__(self):
            self.calls = []
        def in_session(self, generation, action):
            return action()
        def command(self, method, path, body, key):
            assert threading.get_ident() != view.main
            self.calls.append((method, path, body.copy(), key))
            if len(self.calls) == 1:
                raise ApiError("TIMEOUT", "Quá hạn")
            return {"id": str(uuid4()), "status": "CREATED"}
    api, view = Api(), View()
    presenter = MasterDataPresenter(view, api)
    try:
        body = {"product_id": str(uuid4()), "source": "Nguồn giá", "amount": "1234.5000"} if resource == "prices" else {"code": "OWNER", "reason": "Lý do thử"}
        presenter.save(resource, None, body)
        body["source"] = "Changed externally"
        drain(presenter)
        assert presenter.uncertain
        presenter.retry()
        drain(presenter)
        assert api.calls[0] == api.calls[1]
        assert not presenter.uncertain
        if resource == "prices":
            assert api.calls[0][1].startswith("master/products/")
            assert api.calls[0][1].endswith("/prices")
            assert "product_id" not in api.calls[0][2]
    finally:
        finish(presenter)


def test_b05_warranty_unknown_retry_deepcopy_and_reset():
    class Api:
        session_generation = 0
        def __init__(self):
            self.calls = []
        def in_session(self, generation, action):
            return action()
        def command(self, method, path, body, key):
            self.calls.append((method, path, body.copy(), key))
            if len(self.calls) == 1:
                raise ApiError("NETWORK_ERROR", "Mất phản hồi")
            return {"version": 1}
    api, view = Api(), View()
    presenter = SerialLookupPresenter(view, api)
    try:
        body = {"expected_version": 0, "receipt_move_id": str(uuid4()), "evidence_ref": "Chứng cứ ban đầu", "reason": "Đối chiếu"}
        presenter.save(uuid4(), uuid4(), body)
        body["evidence_ref"] = "Bị sửa ngoài luồng"
        drain(presenter)
        assert presenter.uncertain
        presenter.search(uuid4(), "must-not-send")
        assert len(api.calls) == 1
        presenter.retry()
        drain(presenter)
        assert api.calls[0] == api.calls[1]
        assert api.calls[0][2]["evidence_ref"] == "Chứng cứ ban đầu"
        assert not presenter.uncertain
        assert view.events[-1][0] == "lookup_saved"
        presenter.reset()
        assert view.events[-1][0] == "lookup_clear"
    finally:
        finish(presenter)


def test_b05_reference_search_preserves_literal_query_scope_and_cursor():
    class Api:
        session_generation = 0
        def in_session(self, generation, action):
            return action()
        def get(self, path):
            self.path = path
            return {"items": [], "next_after": None}
    api, view = Api(), View()
    presenter = MasterDataPresenter(view, api)
    try:
        warehouse, after = str(uuid4()), str(uuid4())
        presenter.reference("master/locations", "Kệ %_&", after, filters={"warehouse_id": warehouse, "active": "true"})
        drain(presenter)
        assert parse_qs(urlsplit(api.path).query) == {"limit": ["50"], "q": ["Kệ %_&"], "after": [after],
                                                     "warehouse_id": [warehouse], "active": ["true"]}
    finally:
        finish(presenter)


@pytest.mark.gui
def test_b05_forms_fit_default_window_and_clear_user_state():
    import tkinter as tk
    from datetime import date

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell
    from packages.contracts.identity import CurrentUser, WarehouseSummary
    from packages.contracts.traceability import SerialWarranty

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    user = CurrentUser(id=uuid4(), username="layout", display_name="Người kiểm thử", is_active=True, mfa_verified=False,
                       global_permissions=["master.read", "master.write", "partner.read", "partner.write", "warehouse.configure", "price.write"])
    warehouse = WarehouseSummary(id=uuid4(), code="LAYOUT", name="Kho kiểm thử")
    try:
        shell.session_changed(user, [warehouse])
        shell.notebook.select(shell.master_container)
        master = shell.master_view
        for entity in master.entities:
            master.entity.set(entity)
            master.rebuild()
            root.update()
            for widget in (*master.inputs.values(), *master.reference_buttons.values(), master.save_button):
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.master_container.select(shell.product_details_view)
        for mode in shell.product_details_view.modes:
            view = shell.product_details_view
            view.mode.set(mode)
            view.rebuild()
            root.update()
            for widget in (*view.inputs.values(), view.save_button, view.retry_button):
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.master_container.select(shell.ownership_view)
        owner = shell.ownership_view.catalog
        owner.entity.set("Hợp đồng ký gửi")
        owner.rebuild()
        root.update()
        for widget in (*owner.inputs.values(), owner.save_button):
            assert widget.winfo_ismapped()
            assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        view = shell.serial_view
        shell.notebook.select(view)
        row = SerialWarranty(serial_id=uuid4(), product_id=uuid4(), sku="B05", serial_code="00001", warehouse_id=warehouse.id,
                            receipt_id=uuid4(), receipt_number="RECEIPT-B05", receipt_move_id=uuid4(),
                            supplier_partner_id=uuid4(), supplier_code="NCC", supplier_name="Nhà cung cấp kiểm thử",
                            received_on=date(2026, 10, 3), warranty_start_on=None, warranty_ends_on=None, warranty_evidence_ref=None,
                            status="UNKNOWN", as_of=date(2026, 10, 3), version=0, evidence_record_id=None)
        view.lookup_result([row], ["warranty.write"])
        root.update()
        for widget in (*view.evidence_inputs, view.save_button, view.withdraw_button, view.retry_button):
            assert widget.winfo_ismapped()
            assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
            assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        shell.session_changed()
        assert not view.rows and not view.details.get()
        assert all(not variable.get() for variable in view.evidence_vars.values())
        assert view.save_button.instate(["disabled"])
    finally:
        shell.close()
        shell.finish()
