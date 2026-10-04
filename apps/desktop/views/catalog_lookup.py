"""A bounded, keyboard-accessible reference picker using its host's HTTP worker."""

import tkinter as tk
from tkinter import ttk


def reference_label(row):
    code = row.get("sku", row.get("code", row.get("uom_id", row["id"])))
    name = row.get("name", f"× {row['factor']} · revision {row['revision']}" if "factor" in row else "")
    return f"{code} · {name} [{row['id']}]"


class CatalogLookup(tk.Toplevel):
    def __init__(self, host, path, on_select, *, filters=None, searchable=True):
        super().__init__(host)
        self.host, self.path, self.on_select = host, path, on_select
        self.filters, self.searchable = filters or {}, searchable
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Nhập mã/tên rồi tìm; danh sách có thể chuyển trang.")
        self.rows, self.next_after = {}, None
        self.title("Chọn dữ liệu tham chiếu")
        self.geometry("720x420")
        self.transient(host.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        self.entry = ttk.Entry(bar, textvariable=self.query, width=35)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.load())
        if not searchable:
            self.entry.state(["disabled"])
        self.find = ttk.Button(bar, text="Tìm / đầu", command=self.load)
        self.find.pack(side="left", padx=8)
        self.next = ttk.Button(bar, text="Trang sau", command=lambda: self.load(True))
        self.next.pack(side="left")
        listing = ttk.Frame(self, padding=(10, 0))
        listing.pack(fill="both", expand=True)
        self.table = ttk.Treeview(listing, columns=("label",), show="headings", selectmode="browse")
        self.table.heading("label", text="Mã · tên / quy cách · định danh")
        self.table.column("label", width=650)
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(listing, command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<Return>", self.choose)
        self.table.bind("<Double-1>", self.choose)
        ttk.Label(self, textvariable=self.status, wraplength=670).pack(fill="x", padx=10, pady=8)
        actions = ttk.Frame(self, padding=10)
        actions.pack(fill="x")
        self.pick = ttk.Button(actions, text="Chọn", command=self.choose)
        self.pick.pack(side="left")
        ttk.Button(actions, text="Hủy", command=self.cancel).pack(side="right")
        self.bind("<Escape>", lambda event: self.cancel())
        self.grab_set()
        self.entry.focus_set()

    def load(self, next_page=False):
        self.host.presenter.reference(self.path, self.query.get(), self.next_after if next_page else None,
                                      filters=self.filters, searchable=self.searchable)

    def busy(self):
        for widget in (self.find, self.next, self.pick, self.entry):
            widget.state(["disabled"])
        self.status.set("Đang tải…")

    def loaded(self, result):
        self.rows = {row["id"]: row for row in result["items"]}
        self.next_after = result["next_after"]
        self.table.delete(*self.table.get_children())
        for row in self.rows.values():
            self.table.insert("", "end", iid=row["id"], values=(reference_label(row),))
        self.ready(f"{len(self.rows)} mục trên trang này.")

    def error(self, message):
        self.rows, self.next_after = {}, None
        self.table.delete(*self.table.get_children())
        self.ready(message)

    def ready(self, message):
        self.status.set(message)
        self.find.state(["!disabled"])
        self.pick.state(["!disabled"] if self.rows else ["disabled"])
        self.next.state(["!disabled"] if self.next_after else ["disabled"])
        if self.searchable:
            self.entry.state(["!disabled"])

    def choose(self, event=None):
        selected = self.table.selection()
        if self.host.busy or not selected:
            return
        row = self.rows[selected[0]]
        callback = self.on_select
        self.cancel()
        callback(row)

    def cancel(self):
        self.host.presenter.sequence += 1
        if self.host.presenter.pending:
            self.host.presenter.pending.cancel()
        self.host.busy = False
        self.host.lookup = None
        self.host.enable()
        self.query = self.status = None
        self.on_select = None
        self.grab_release()
        self.destroy()
