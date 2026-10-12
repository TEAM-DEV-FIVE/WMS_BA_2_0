import tkinter as tk
from pathlib import Path

import pytest

from apps.desktop.views.admin_theme import AdminTheme
from apps.desktop.views.data_table import DataTable, cell_lines, column_alignment


@pytest.mark.parametrize("width", [0, 1, 6, 7, 20, 45, 100, 500])
def test_wrapped_cells_fit_without_changing_values(width):
    value = "Samsung Note 5 | 64GB, 6inch, Black và thông tin mô tả sản phẩm"
    def measure(text):
        return len(text) * 7
    lines = cell_lines(value, width, measure)
    assert len(lines) <= 2
    assert all(measure(line) <= width for line in lines)
    assert value.endswith("mô tả sản phẩm")
    assert cell_lines("120.000000", 120, measure, limit=1) == ["120.000000"]


def test_column_alignment_keeps_codes_separate_from_amounts():
    assert column_alignment("quantity_base") == "e"
    assert column_alignment("inbound_reference_value") == "e"
    assert column_alignment("code") == "w"
    assert column_alignment("business_date") == "center"


def test_all_business_tables_use_shared_component():
    root = Path(__file__).resolve().parents[2] / "apps/desktop/views"
    direct = [path.name for path in root.glob("*.py") if "ttk.Treeview(" in path.read_text()]
    assert direct == ["admin_workspace.py"]


@pytest.mark.gui
def test_grid_keeps_selection_scrolling_theme_and_tree_column():
    root = tk.Tk()
    root.geometry("700x420")
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    theme = AdminTheme(root)
    theme.apply()
    tree = DataTable(root, columns=("number", "name", "qty"), show="headings", selectmode="extended")
    for column, title, width in [("number", "Số phiếu", 120), ("name", "Mặt hàng", 310), ("qty", "Số lượng", 130)]:
        tree.heading(column, text=title)
        tree.column(column, width=width, stretch=False)
    tree.pack(fill="both", expand=True)
    for index in range(40):
        tree.insert("", "end", iid=str(index), values=(f"PO{index:03}", "Mặt hàng có tên dài cần xuống dòng trong bảng", "123.000000"))
    try:
        root.update()
        assert tree._surface.winfo_ismapped()
        texts = [tree._surface.itemcget(item, "text") for item in tree._surface.find_all() if tree._surface.type(item) == "text"]
        assert "PO000" in texts
        first = tree.bbox("0")
        tree._surface.event_generate("<ButtonPress-1>", x=30, y=first[1]-tree._body_y+8)
        tree._surface.event_generate("<ButtonRelease-1>", x=30, y=first[1]-tree._body_y+8)
        root.update()
        assert tree.selection() == ("0",)
        tree.yview_moveto(.7)
        root.update()
        assert not tree.bbox("0")
        assert tree.set("0", "qty") == "123.000000"
        theme.apply(True)
        theme.native(tree)
        root.update()
        assert tree._surface.cget("background") == "#1d2635"
        tree.configure(show="tree headings")
        tree.column("#0", width=100)
        root.update()
        assert tree._body_x >= 100
        tree.delete(*tree.get_children())
        tree.configure(columns=("code", "qty"))
        tree.insert("", "end", iid="new", values=("NEW", "2"))
        root.update()
        assert tree.set("new", "qty") == "2"
        assert not errors
    finally:
        tree.destroy()
        root.update_idletasks()
        theme.close()
        root.destroy()
