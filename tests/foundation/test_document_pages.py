from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.desktop.views.document_pages import DocumentPages, reset_document_page, show_document


def test_navigation_changes_geometry_only_and_preserves_pending_draft():
    pages = DocumentPages.__new__(DocumentPages)
    listing, editor, footer = Mock(), Mock(), Mock()
    pages.groups = {"list": [(listing, {"fill": "both"})],
                    "detail": [(footer, {"side": "bottom"}), (editor, {"fill": "both"})]}
    pages.current = None
    pages.list_button, pages.detail_button, pages.hint = Mock(), Mock(), Mock()
    pages.bar = SimpleNamespace(master=None)
    draft = {"quantity": "17", "reason": "Chuyển sang kệ mới"}
    pending = ("same-idempotency-key", "moves/1/post")
    view = SimpleNamespace(document_pages=pages, draft=draft, uncertain=pending)

    show_document(view)
    assert pages.current == "detail"
    listing.pack.assert_not_called()
    editor.pack.assert_called_once_with(fill="both")
    footer.pack.assert_called_once_with(side="bottom")
    reset_document_page(view)
    assert pages.current == "list"
    listing.pack.assert_called_once_with(fill="both")
    assert view.draft is draft and draft["quantity"] == "17"
    assert view.uncertain is pending
    reset_document_page(view)
    listing.pack.assert_called_once()  # Repeated reset does not reorder widgets.
    show_document(view)
    assert editor.pack.call_count == 2


def test_open_requires_selection_and_does_not_open_from_blank_area():
    pages = DocumentPages.__new__(DocumentPages)
    pages.table = Mock()
    pages.show_detail = Mock()
    pages.table.selection.return_value = ()
    pages.open_selected()
    pages.show_detail.assert_not_called()
    pages.table.selection.return_value = ("move-id",)
    pages.table.identify_row.return_value = ""
    pages.open_selected(SimpleNamespace(type=SimpleNamespace(name="ButtonPress"), y=400))
    pages.show_detail.assert_not_called()
    pages.open_selected()
    pages.show_detail.assert_called_once_with()


def test_reset_during_constructor_does_not_require_pages():
    view = SimpleNamespace()
    reset_document_page(view)
    show_document(view)


@pytest.mark.gui
def test_all_document_views_separate_list_and_detail_without_losing_input(tmp_path):
    import tkinter as tk

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    root = tk.Tk()
    root.geometry("1280x850")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    try:
        shell.authenticated = True
        shell.show_authenticated_header(True)
        shell.resize_workspace()
        views = [view for view in vars(shell).values() if hasattr(view, "document_pages")]
        assert len(views) >= 12
        for view in views:
            shell.notebook.select(view)
            root.update()
            pages = view.document_pages
            assert pages.current == "list"
            assert view.table.winfo_ismapped()
            if view in [shell.quality_view, *shell.return_views]:
                assert view.status_button.winfo_rooty() == pages.hint.winfo_rooty() == pages.list_button.winfo_rooty()
                assert view.status_button.winfo_height() == pages.hint.winfo_height()
                assert abs(view.top.winfo_rootx() + view.top.winfo_width() - pages.bar.winfo_rootx() - pages.bar.winfo_width()) <= 2
            assert all(not widget.winfo_ismapped() for widget, _ in pages.groups["detail"])
            view.variables["reason"].set("Nội dung nháp còn nguyên")
            pages.show_detail()
            root.update()
            assert not view.table.winfo_ismapped()
            assert all(widget.winfo_ismapped() for widget, _ in pages.groups["detail"])
            pages.show_list()
            root.update()
            assert view.table.winfo_ismapped()
            pages.show_detail()
            assert view.variables["reason"].get() == "Nội dung nháp còn nguyên"
            view.session_changed()
            root.update()
            assert pages.current == "list"
        assert not errors
    finally:
        shell.close()
        shell.finish()
