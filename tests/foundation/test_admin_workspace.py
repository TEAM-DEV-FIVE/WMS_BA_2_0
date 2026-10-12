import tkinter as tk
from types import SimpleNamespace

import pytest

from apps.desktop.api.client import DesktopSettings
from apps.desktop.views.admin_theme import DARK
from apps.desktop.views.admin_workspace import SECTIONS
from apps.desktop.views.shell import DesktopShell


@pytest.mark.gui
def test_workspace_navigation_theme_resize_and_signout_preserve_business_state(tmp_path):
    root = tk.Tk()
    root.geometry("1366x900")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        root.update()
        assert not shell.open_key("master_container")
        assert not shell.sidebar.winfo_ismapped()
        shell.authenticated = True
        shell.show_authenticated_header(True)
        shell.resize_workspace()
        assert not hasattr(shell, "home_view")
        assert all(key != "home_view" for _, key, _, _ in SECTIONS)
        shell.order_view.variables["qty"].set("17")
        for _, key, title, _ in SECTIONS:
            assert shell.open_key(key)
            root.update()
            assert shell.notebook.select() == str(getattr(shell, key))
            assert shell.page_title.cget("text") == title
            assert shell.sidebar.tree.selection() == (key,)
        shell.toggle_theme(True)
        root.update()
        assert shell.admin_view.details.cget("background") == DARK["surface"]
        assert shell.order_view.variables["qty"].get() == "17"
        assert shell.sidebar.winfo_ismapped()
        shell.open_key("serial_view")
        root.update()
        group = shell.sidebar.tree.parent("master_container")
        shell.sidebar.tree.item(group, open=False)
        shell.sidebar.tree.see(group)
        root.update()
        bounds = shell.sidebar.tree.bbox(group)
        shell.sidebar.activate(SimpleNamespace(num=1, y=bounds[1] + 5))
        assert not shell.sidebar.tree.item(group, "open")
        root.geometry("900x690")
        root.update()
        assert not shell.sidebar.winfo_ismapped()
        assert shell.navigation.winfo_ismapped()
        assert not shell.open_key("home_view")
        # Navigation remains available when the sidebar folds away.
        index = shell.notebook.index(shell.print_view)
        shell.navigation.current(index)
        shell.navigation.event_generate("<<ComboboxSelected>>")
        root.update()
        assert shell.notebook.select() == str(shell.print_view)
        shell.draft_only.set(True)
        shell.set_draft_mode()
        assert shell.session_view.presenter.api.draft_only
        shell.session_changed(None, [])
        root.update()
        assert not shell.sidebar.winfo_ismapped() and not shell.navigation_bar.winfo_ismapped()
        assert shell.notebook.select() == str(shell.session_view)
        assert not shell.current_user
        assert not shell.open_key("admin_view")
    finally:
        shell.close()
        shell.finish()
    assert shell.admin_theme.style is None and not shell.admin_theme.images


@pytest.mark.gui
def test_new_product_fields_stay_reachable_by_keyboard_at_small_size(tmp_path, monkeypatch):
    root = tk.Tk()
    root.geometry("900x690")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        shell.authenticated = True
        shell.resize_workspace()
        view = shell.master_view
        view.permissions = {"master.read", "master.write"}
        view.entity.set("Sản phẩm")
        view.rebuild()
        view.enable()
        monkeypatch.setattr(view.presenter, "load", lambda *args, **kwargs: None)
        shell.open_key("master_container")
        view.show_details(True)
        root.update()
        view.reason_entry.focus_force()
        root.update()
        assert view.reason_entry.winfo_rooty() >= view.detail_scroll.canvas.winfo_rooty()
        assert (
            view.reason_entry.winfo_rooty() + view.reason_entry.winfo_height()
            <= view.detail_scroll.canvas.winfo_rooty() + view.detail_scroll.canvas.winfo_height()
        )
        view.detail_scroll.canvas.yview_moveto(1)
        root.update()
        assert (
            view.save_button.winfo_rooty() + view.save_button.winfo_height()
            < root.winfo_rooty() + root.winfo_height()
        )
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_catalog_navigation_preserves_edits_and_does_not_repeat_load(tmp_path, monkeypatch):
    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    view = shell.master_view
    calls = []
    monkeypatch.setattr(view.presenter, "load", lambda *args, **kwargs: calls.append(args))
    try:
        shell.authenticated = True
        shell.open_key("master_container")
        assert not calls and "chưa có quyền" in view.status.get()
        view.permissions = {"master.read", "master.write"}
        view.variables["name"].set("Nội dung chưa lưu")
        shell.open_key("master_container")
        assert not calls and view.variables["name"].get() == "Nội dung chưa lưu"
        assert "chưa lưu" in view.status.get()
        view.new()
        shell.open_key("master_container")
        assert calls[0][0] == "products"
        view.catalog_loaded({"items": [], "next_after": None}, {})
        view.variables["name"].set("Sản phẩm chưa lưu")
        shell.open_key("serial_view")
        shell.open_key("master_container")
        assert len(calls) == 1 and view.variables["name"].get() == "Sản phẩm chưa lưu"
        assert view.loaded_resource == "products"
        shell.session_changed(None, [])
        assert view.loaded_resource is None and not view.rows
    finally:
        shell.close()
        shell.finish()
