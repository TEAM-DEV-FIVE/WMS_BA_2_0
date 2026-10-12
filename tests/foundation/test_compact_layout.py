import tkinter as tk
from tkinter import ttk

import pytest

from apps.desktop.views.document_review import ScrollPanel
from apps.desktop.views.ui_help import Disclosure


@pytest.mark.gui
def test_scroll_panel_fills_short_page_and_keeps_long_form_reachable():
    root = tk.Tk()
    root.geometry("800x600")
    try:
        panel = ScrollPanel(root)
        panel.pack(fill="both", expand=True)
        table = ttk.Treeview(panel.inner, height=3)
        table.pack(fill="both", expand=True)
        extra = Disclosure(panel.inner, "Thông tin bổ sung")
        extra.pack(fill="x")
        entries = [ttk.Entry(extra.body) for _ in range(40)]
        for entry in entries:
            entry.pack(fill="x", pady=3)
        entries[-1].insert(0, "Giữ nội dung nháp")
        root.update()
        assert panel.inner.winfo_height() == panel.canvas.winfo_height()
        assert table.winfo_height() > 500
        extra.toggle()
        root.update()
        assert panel.inner.winfo_height() > panel.canvas.winfo_height()
        panel.canvas.yview_moveto(1)
        root.update()
        bottom = entries[-1].winfo_rooty() + entries[-1].winfo_height()
        assert bottom <= panel.canvas.winfo_rooty() + panel.canvas.winfo_height()
        extra.toggle()
        root.update()
        assert panel.inner.winfo_height() == panel.canvas.winfo_height()
        assert entries[-1].get() == "Giữ nội dung nháp"
        root.geometry("800x760")
        root.update()
        assert table.winfo_height() > 660
    finally:
        root.destroy()


@pytest.mark.gui
def test_inbound_tables_fill_page_and_action_buttons_are_distinct(tmp_path):
    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    root = tk.Tk()
    root.geometry("1400x950")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        shell.authenticated = True
        shell.show_authenticated_header(True)
        shell.resize_workspace()
        for name in ("order_view", "receipt_view", "opening_view", "consignment_view"):
            root.geometry("1400x950")
            view = getattr(shell, name)
            shell.open_key(name)
            root.update()
            page_bottom = view.winfo_rooty() + view.winfo_height()
            bar_bottom = view.pagination.winfo_rooty() + view.pagination.winfo_height()
            assert 0 <= page_bottom - bar_bottom <= 30, (name, page_bottom, bar_bottom)
            assert view.table.winfo_height() > 450, name
            assert view.load_button.winfo_height() >= 30
            assert view.load_button.cget("style") != view.new_button.cget("style")
            assert view.new_button.cget("image")
            # Detail fields remain available, then the list fills the page again.
            view.document_pages.show_detail()
            root.update()
            view.document_pages.show_list()
            root.update()
            assert view.table.winfo_height() > 450, name
            root.geometry("900x690")
            root.update()
            assert view.pagination.winfo_rooty() + view.pagination.winfo_height() <= root.winfo_rooty() + root.winfo_height(), name
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_notebook_selection_keeps_tab_dimensions_in_both_themes():
    from apps.desktop.views.admin_theme import AdminTheme

    root = tk.Tk()
    root.geometry("720x240")
    style = ttk.Style(root)
    style.theme_use("clam")
    theme = AdminTheme(root)
    tabs = ttk.Notebook(root)
    tabs.pack(fill="both", expand=True)
    for title in ("Danh mục cơ sở", "Quy đổi / barcode / giá", "Chủ hàng / ký gửi"):
        tabs.add(ttk.Frame(tabs), text=title)

    def bounds():
        result = {}
        for y in range(45):
            for x in range(tabs.winfo_width()):
                if tabs.identify(x, y):
                    try:
                        index = tabs.index(f"@{x},{y}")
                    except tk.TclError:
                        continue
                    box = result.setdefault(index, [x, y, x, y])
                    box[0], box[1] = min(box[0], x), min(box[1], y)
                    box[2], box[3] = max(box[2], x), max(box[3], y)
        return result

    try:
        for dark in (False, True):
            theme.apply(dark)
            tabs.select(0)
            root.update()
            before = bounds()
            assert len(before) == 3
            for selected in (1, 2, 0):
                tabs.select(selected)
                root.update()
                assert bounds() == before
            assert style.lookup("TNotebook.Tab", "background", ("selected",)) == "#005b9e"
    finally:
        root.destroy()
        theme.close()


@pytest.mark.gui
def test_action_layout_and_feedback_remain_accessible_after_resize(tmp_path):
    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell
    from apps.desktop.views.ui_help import StatusButton

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        shell.authenticated = True
        shell.show_authenticated_header(True)
        for geometry in ("1500x950", "900x690"):
            root.geometry(geometry)
            shell.resize_workspace()
            for name in ("report_view", "print_view"):
                shell.open_key(name)
                root.update()
                view = getattr(shell, name)
                assert view.actions.winfo_ismapped()
                menu = view.actions.menu
                expected = 8 if name == "print_view" else 7
                assert menu.index("end") + 1 == expected
                menu.post(view.actions.winfo_rootx(), view.actions.winfo_rooty() + view.actions.winfo_height())
                root.update()
                assert menu.winfo_ismapped()
                assert menu.yposition(expected - 1) > menu.yposition(0)
                menu.unpost()
                if name == "print_view":
                    assert not view.preview_window.winfo_ismapped()
                else:
                    view.advanced.toggle()
                    root.update()
                    assert view.actions.winfo_ismapped()
                    assert view.tree.winfo_height() > 50
                    view.advanced.toggle()
                    root.update()
        report = shell.report_view
        feedback = next(widget for widget in report.winfo_children() if isinstance(widget, StatusButton))
        report.status.set("Không thể tải báo cáo: cần đăng nhập lại")
        assert feedback.cget("text") == "Cần kiểm tra · Xem"
        feedback.invoke()
        root.update()
        dialogs = [widget for widget in feedback.winfo_children() if isinstance(widget, tk.Toplevel)]
        assert len(dialogs) == 1
        assert feedback.help_text.get() == report.status.get()
        dialogs[0].destroy()
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_unified_combobox_keeps_native_arrow_interaction():
    from apps.desktop.views.admin_theme import AdminTheme

    root = tk.Tk()
    theme = AdminTheme(root)
    try:
        combo = ttk.Combobox(root, state="readonly", values=["Phiếu nhập", "Phiếu xuất"])
        combo.pack(padx=20, pady=20)
        combo.current(0)
        for dark in (False, True):
            theme.apply(dark)
            root.update()
            x, y = combo.winfo_width() - 10, combo.winfo_height() // 2
            assert "downarrow" in combo.identify(x, y)
            combo.event_generate("<ButtonPress-1>", x=x, y=y)
            combo.event_generate("<ButtonRelease-1>", x=x, y=y)
            root.update()
            popup = root.tk.call("ttk::combobox::PopdownWindow", str(combo))
            assert root.tk.call("winfo", "ismapped", popup)
            root.tk.call("ttk::combobox::Unpost", str(combo))
            root.update()
            assert combo.get() == "Phiếu nhập"
    finally:
        root.destroy()


@pytest.mark.gui
def test_scanner_and_document_share_one_status_button(tmp_path):
    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell
    from apps.desktop.views.ui_help import StatusButton

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))

    def status_buttons(parent):
        for child in parent.winfo_children():
            if isinstance(child, StatusButton):
                yield child
            yield from status_buttons(child)

    try:
        for name in ("receipt_view", "issue_view", "fulfillment_view", "transfer_view", "count_view"):
            view = getattr(shell, name)
            assert list(status_buttons(view)) == [view.status_button]
            view.variables["status"].set("Đã tải phiếu")
            view.scan_bar.status.set("Mã không hợp lệ")
            assert "Đã tải phiếu" in view.status_button.help_text.get()
            assert "Mã không hợp lệ" in view.status_button.help_text.get()
            assert view.status_button.cget("style") == "Danger.TButton"
            view.scan_bar.status.set("Đã chọn dòng")
            assert view.status_button.cget("text") == "Xem trạng thái"
            assert "Đã tải phiếu" in view.status_button.help_text.get()
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_preview_opens_only_on_request_and_import_fields_align(tmp_path, monkeypatch):
    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    root = tk.Tk()
    root.geometry("1400x900")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        shell.authenticated = True
        shell.show_authenticated_header(True)
        shell.open_key("print_view")
        root.update()
        view = shell.print_view
        assert not view.preview_window.winfo_ismapped()
        assert view.warehouse.winfo_width() < view.form.canvas.winfo_width() / 2
        # ScrollPanel reserves four pixels of padding on each edge.
        assert view.document_fields.winfo_height() >= view.form.canvas.winfo_height() - 8
        assert view.printer_fields.winfo_height() == view.document_fields.winfo_height()
        assert view.create_button.winfo_rooty() > view.document_fields.winfo_rooty() + view.document_fields.winfo_height()
        root.geometry("900x690")
        root.update()
        view.form.canvas.yview_moveto(1)
        root.update()
        assert view.reason_entry.winfo_rooty() + view.reason_entry.winfo_height() <= view.form.canvas.winfo_rooty() + view.form.canvas.winfo_height()
        assert view.create_button.winfo_ismapped()
        root.geometry("1400x900")
        root.update()
        view.preview(0)
        assert not view.preview_window.winfo_ismapped()
        view.presenter.job = {"status": "READY"}
        requests = []
        monkeypatch.setattr(view.presenter, "preview", requests.append)
        view.actions.menu.invoke(0)
        root.update()
        assert view.preview_window.winfo_ismapped()
        assert requests == [0]
        view.clear_preview()
        root.update()
        assert not view.preview_window.winfo_ismapped()
        shell.open_key("import_view")
        root.update()
        form = shell.import_view
        fields = form.metadata_entries
        assert len({entry.winfo_width() for entry in fields}) == 1
        assert len({entry.winfo_rootx() for entry in fields}) == 1
        refresh = form.buttons["refresh"]
        assert refresh.cget("style") == "Primary.TButton"
        assert refresh.winfo_rooty() > fields[-1].winfo_rooty() + fields[-1].winfo_height()
        assert abs(refresh.winfo_rootx() + refresh.winfo_width() - fields[-1].winfo_rootx() - fields[-1].winfo_width()) <= 2
    finally:
        shell.close()
        shell.finish()
