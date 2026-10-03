import httpx
import pytest
from test_consignments import agreement
from test_opening_desktop import action, opening_ui  # noqa: F401
from test_openings import inventory, opening, orders  # noqa: F401
from test_orders import ok

pytestmark = [pytest.mark.integration, pytest.mark.gui]


def test_consignment_gui_opening_selects_owner_and_preserves_two_balances(opening_ui):  # noqa: F811
    f, view = opening_ui, opening_ui.view
    owner, contract = agreement(f)
    view.load()
    f.idle()
    f.fill_ui()
    view.owner.current(
        next(i for i, r in enumerate(view.catalogs["owners"]) if r["consignment_id"] == contract["id"])
    )
    view.variables["qty"].set("5")
    view.add_line()
    assert len(view.lines) == 2 and view.lines[1]["owner_id"] == owner["id"]
    action(f, "save")
    assert view.doc["plan"][1]["consignment_id"] == contract["id"]
    action(f, "submit")
    approved = ok(
        f.decision({**view.doc, "approval_request_id": view.doc["approvals"][-1]["id"]}, "director")
    )
    view.presenter.read(approved["id"])
    f.idle()
    action(f, "post")
    assert inventory(f) == (1, 2, 15, 0) and view.doc["status"] == "COMPLETED"
    assert owner["code"] in str(view.line_table.item("1", "values"))


def test_consignment_gui_receipt_real_http_unknown_ack_and_session_cleanup(opening_ui, monkeypatch):  # noqa: F811
    f = opening_ui
    f.iam.grant(f.buyer, "RECEIVER", f.warehouse)
    _, contract = agreement(f)
    location = f.master(
        "locations", code="CG-UI-IN", name="Nhận hàng ký gửi", kind="RECEIVING", warehouse_id=str(f.warehouse)
    )
    view = f.shell.consignment_view
    f.shell.notebook.select(view)

    def idle():
        f.wait(lambda: view.presenter.pending is None and not view.busy)

    def act(name):
        view.variables["reason"].set("Thao tác ký gửi từ desktop")
        view.action(name)
        idle()

    view.load()
    idle()
    view.new()
    view.variables["day"].set("2026-10-02")
    view.variables["reference"].set("Chứng từ giao nhận CG-UI")
    view.product.current(
        next(i for i, p in enumerate(view.catalogs["products"]) if p["id"] == f.product["id"])
    )
    view.product_changed()
    idle()
    view.location.current(
        next(i for i, p in enumerate(view.catalogs["locations"]) if p["id"] == location["id"])
    )
    view.owner.current(
        next(i for i, p in enumerate(view.catalogs["owners"]) if p["consignment_id"] == contract["id"])
    )
    view.variables["qty"].set("5")
    view.add_line()
    assert len(view.lines) == 1
    act("save")
    assert view.doc["delivery_reference"] == "Chứng từ giao nhận CG-UI"
    act("submit")
    approved = ok(f.decision({**view.doc, "approval_request_id": view.doc["approvals"][-1]["id"]}, "manager"))
    view.presenter.read(approved["id"])
    idle()
    send = view.presenter.api.client.send

    def lose_ack(request, **kwargs):
        response = send(request, **kwargs)
        if request.url.path.endswith("/post"):
            assert response.status_code == 200
            response.close()
            raise httpx.ReadTimeout("consigned receipt ACK lost")
        return response

    monkeypatch.setattr(view.presenter.api.client, "send", lose_ack)
    act("post")
    assert inventory(f) == (1, 1, 5, 0) and view.presenter.uncertain
    view.lookup()
    idle()
    assert view.presenter.uncertain is None and view.ack["transaction_id"]
    assert view.doc["status"] == "COMPLETED"
    f.shell.session_view.logout()
    assert not view.lines and not view.doc and not view.catalogs["owners"]
    f.wait(lambda: f.shell.session_view.status.get() == "Đã đăng xuất.")
