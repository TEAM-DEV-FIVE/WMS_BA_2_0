import tkinter as tk
from tkinter import ttk

from apps.desktop.presenters.serial_lookup import SerialLookupPresenter

STATUSES = {"VALID": "Còn bảo hành", "EXPIRED": "Hết bảo hành", "UNKNOWN": "Chưa xác định"}


class SerialLookupView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=20)
        self.presenter = SerialLookupPresenter(self, api)
        self.warehouse = tk.StringVar()
        self.code = tk.StringVar()
        self.sku = tk.StringVar()
        self.status = tk.StringVar(value="Đăng nhập để tra serial trong kho được cấp quyền.")
        self.details = tk.StringVar()
        self.warehouses, self.rows = [], {}
        form = ttk.Frame(self)
        form.pack(fill="x")
        ttk.Label(form, text="Kho tra cứu").grid(row=0, column=0, sticky="w", pady=5)
        self.selector = ttk.Combobox(form, textvariable=self.warehouse, state="readonly", width=55)
        self.selector.grid(row=0, column=1, columnspan=2, sticky="w", padx=12)
        self.selector.bind("<<ComboboxSelected>>", lambda event: self.presenter.reset())
        self.entries = []
        for index, (label, variable) in enumerate([("Serial (giữ số 0 đầu)", self.code), ("SKU (nếu cần phân biệt)", self.sku)], 1):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=5)
            entry = ttk.Entry(form, textvariable=variable, width=40)
            entry.grid(row=index, column=1, sticky="w", padx=12)
            self.entries.append(entry)
        self.button = ttk.Button(form, text="Tra serial", command=self.search)
        self.button.grid(row=2, column=2, padx=10)
        ttk.Label(self, textvariable=self.status, wraplength=780).pack(fill="x", pady=12)
        self.table = ttk.Treeview(self, columns=("sku", "code", "status", "end"), show="headings", height=8)
        for field, label, width in [("sku", "SKU", 190), ("code", "Serial", 220), ("status", "Bảo hành", 170), ("end", "Đến ngày", 130)]:
            self.table.heading(field, text=label)
            self.table.column(field, width=width, minwidth=70)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.details, wraplength=780, justify="left").pack(fill="x", pady=14)
        ttk.Label(self, text="Tình trạng do máy chủ xác định từ chứng cứ và ngày nghiệp vụ. Thiếu thông tin sẽ hiển thị Chưa xác định.",
                  wraplength=780).pack(fill="x")

    def session_changed(self, user=None, warehouses=None):
        self.presenter.reset()
        self.warehouses = list(warehouses or [])
        self.selector.configure(values=[f"{row.code} · {row.name}" for row in self.warehouses])
        self.warehouse.set("")
        for widget in [self.selector, *self.entries]:
            widget.state(["!disabled"])
        self.code.set("")
        self.sku.set("")
        if self.warehouses:
            self.selector.current(0)
        self.button.state(["!disabled"] if user and self.warehouses else ["disabled"])
        self.status.set("Chọn kho, nhập hoặc quét serial rồi bấm Tra serial." if user else "Đăng nhập để tra serial.")

    def search(self):
        index = self.selector.current()
        if index < 0 or not self.code.get().strip():
            self.status.set("Chọn kho và nhập serial trước khi tra cứu.")
            return
        self.presenter.search(self.warehouses[index].id, self.code.get(), self.sku.get())

    def lookup_busy(self):
        self.lookup_clear()
        self.button.state(["disabled"])
        for widget in [self.selector, *self.entries]:
            widget.state(["disabled"])
        self.status.set("Đang tra serial…")

    def lookup_clear(self):
        self.rows = {}
        self.table.delete(*self.table.get_children())
        self.details.set("")

    def lookup_result(self, rows):
        self.lookup_clear()
        self.rows = {str(row.serial_id): row for row in rows}
        for row in rows:
            self.table.insert("", "end", iid=str(row.serial_id), values=(row.sku, row.serial_code, STATUSES[row.status], row.warranty_ends_on or "—"))
        self.button.state(["!disabled"])
        for widget in [self.selector, *self.entries]:
            widget.state(["!disabled"])
        self.status.set(f"Tìm thấy {len(rows)} serial trong phạm vi được phép." if rows else "Không tìm thấy serial trong phạm vi được phép.")
        if rows:
            self.table.selection_set(str(rows[0].serial_id))
            self.select()

    def lookup_error(self, message):
        for widget in [self.selector, *self.entries]:
            widget.state(["!disabled"])
        self.button.state(["!disabled"] if self.warehouses else ["disabled"])
        self.status.set(message)

    def select(self, event=None):
        selected = self.table.selection()
        if not selected or selected[0] not in self.rows:
            return
        row = self.rows[selected[0]]
        self.details.set(f"{STATUSES[row.status]} · ngày tra cứu {row.as_of}\n"
                         f"Ngày nhập: {row.received_on or 'Chưa có nguồn'} · Bắt đầu bảo hành: {row.warranty_start_on or 'Chưa xác định'}\n"
                         f"Chứng cứ: {row.warranty_evidence_ref or 'Chưa có'}\n"
                         f"Phiếu nhận: {row.receipt_number or 'Chưa có'}\n"
                         f"Nhà cung cấp: {row.supplier_name or 'Chưa có'}")

    def release_variables(self):
        self.warehouse = self.code = self.sku = self.status = self.details = None
