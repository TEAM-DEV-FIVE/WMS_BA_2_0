import httpx
import pytest
from sqlalchemy import text
from test_count_period_desktop import count_ui, counting, orders, receiving  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.gui]
# ruff: noqa: F811


def test_reversal_gui_preview_approve_post_timeout_ack_and_small_window(count_ui, monkeypatch):
    f = count_ui
    source = f.count_received("40")
    f.login_ui("manager")
    view = f.shell.reversal_view
    f.shell.notebook.select(view)
    f.shell.root.geometry("800x620")
    view.presenter.load()
    f.idle_ui(view)
    view.new()
    view.presenter.load("reversals/sources")
    f.idle_ui(view)
    view.source_selector.current(next(i for i, r in enumerate(view.sources) if r["id"] == source["transaction_id"]))
    view.variables["day"].set("2026-10-02")
    view.buttons["preview"].invoke()
    f.idle_ui(view)
    assert view.preview_data["eligible"] and view.plan.get_children() and view.effects.get_children()
    view.variables["reason"].set("Nhập nhầm lần nhận; đảo toàn bộ")
    view.buttons["save"].invoke()
    f.idle_ui(view)
    assert view.doc and view.doc["status"] == "DRAFT", view.variables["status"].get()
    doc_id = view.doc["id"]
    view.buttons["submit"].invoke()
    f.idle_ui(view)
    assert view.doc["status"] == "SUBMITTED" and view.buttons["post"].instate(["disabled"])
    f.login_ui("controller")
    view.presenter.read(doc_id)
    f.idle_ui(view)
    view.buttons["approve"].invoke()
    f.idle_ui(view)
    assert view.doc["status"] == "APPROVED", view.variables["status"].get()
    assert view.history.get_children()
    # A fresh DB connection has the default search_path, unlike the migration
    # connection. Deferred ledger guards must not depend on a warmed pool.
    f.engine.dispose()
    api, lost = view.presenter.api, False
    original = api.client.request
    def timeout(method, url, **kwargs):
        nonlocal lost
        result = original(method, url, **kwargs)
        if method == "POST" and str(url).endswith("/post") and not lost:
            assert result.status_code == 200, result.text
            lost = True
            raise httpx.ReadTimeout("Response lost after commit")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(api.client, "request", timeout)
        patch.setattr("apps.desktop.views.reversals.messagebox.askyesno", lambda *args, **kwargs: True)
        view.buttons["post"].invoke()
        f.idle_ui(view)
    assert lost and view.presenter.uncertain and view.doc["status"] == "APPROVED"
    view.operation_button.invoke()
    f.idle_ui(view)
    assert view.doc["status"] == "COMPLETED" and view.doc["transaction_id"] and not view.presenter.uncertain, view.variables["status"].get()
    view.canvas.yview_moveto(1)
    f.shell.root.update()
    assert view.operation_button.winfo_ismapped()
    assert view.operation_button.winfo_rooty() + view.operation_button.winfo_height() <= f.shell.root.winfo_rooty() + f.shell.root.winfo_height()
    with f.engine.connect() as c:
        assert c.execute(text("SELECT sum(on_hand) FROM wms.stock_balance")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.inventory_transaction WHERE operation='REVERSE'")).scalar_one() == 1
