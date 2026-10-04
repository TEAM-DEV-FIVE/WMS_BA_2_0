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
        self.busy, self.permissions = False, set()
        self.actor_id, self.suspended = None, {}
        self.evidence_vars, self.evidence_inputs = {}, []
        form = ttk.Frame(self)
        form.pack(fill="x")
        ttk.Label(form, text="Kho tra cứu").grid(row=0, column=0, sticky="w", pady=5)
        self.selector = ttk.Combobox(form, textvariable=self.warehouse, state="readonly", width=55)
        self.selector.grid(row=0, column=1, columnspan=2, sticky="w", padx=12)
        self.selector.bind("<<ComboboxSelected>>", self.scope_changed)
        self.entries = []
        for index, (label, variable) in enumerate([("Serial (giữ số 0 đầu)", self.code), ("SKU (nếu cần phân biệt)", self.sku)], 1):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=5)
            entry = ttk.Entry(form, textvariable=variable, width=40)
            entry.grid(row=index, column=1, sticky="w", padx=12)
            self.entries.append(entry)
            entry.bind("<Return>", lambda event: self.search())
        self.button = ttk.Button(form, text="Tra serial", command=self.search)
        self.button.grid(row=2, column=2, padx=10)
        ttk.Label(self, textvariable=self.status, wraplength=780).pack(fill="x", pady=12)
        self.table = ttk.Treeview(self, columns=("sku", "code", "status", "end"), show="headings", height=4)
        for field, label, width in [("sku", "SKU", 190), ("code", "Serial", 220), ("status", "Bảo hành", 170), ("end", "Đến ngày", 130)]:
            self.table.heading(field, text=label)
            self.table.column(field, width=width, minwidth=70)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.details, wraplength=780, justify="left").pack(fill="x", pady=6)
        evidence = ttk.LabelFrame(self, text="Chứng cứ bảo hành — ghi revision, giữ lịch sử", padding=8)
        evidence.pack(fill="x", pady=6)
        for index, (field, label) in enumerate((("starts_on", "Từ ngày (YYYY-MM-DD)"), ("ends_on", "Đến ngày (YYYY-MM-DD)"),
                                               ("evidence_ref", "Nguồn chứng cứ"), ("reason", "Lý do ghi / đính chính"))):
            ttk.Label(evidence, text=label).grid(row=index, column=0, sticky="w", pady=2)
            variable = self.evidence_vars[field] = tk.StringVar()
            widget = ttk.Entry(evidence, textvariable=variable, width=58)
            widget.grid(row=index, column=1, padx=8, sticky="ew", pady=2)
            self.evidence_inputs.append(widget)
        buttons = ttk.Frame(evidence)
        buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        self.save_button = ttk.Button(buttons, text="Ghi / đính chính chứng cứ", command=self.save_evidence)
        self.save_button.pack(side="left")
        self.withdraw_button = ttk.Button(buttons, text="Rút chứng cứ bằng revision mới", command=lambda: self.save_evidence(withdraw=True))
        self.withdraw_button.pack(side="left", padx=8)
        self.retry_button = ttk.Button(buttons, text="Gửi lại cùng yêu cầu", command=self.presenter.retry)
        self.retry_button.pack(side="left")
        ttk.Label(self, text="Tình trạng do máy chủ xác định từ chứng cứ và ngày nghiệp vụ. Thiếu thông tin sẽ hiển thị Chưa xác định.",
                  wraplength=780).pack(fill="x")
        self.enable()

    def session_changed(self, user=None, warehouses=None):
        if self.actor_id and self.presenter.uncertain:
            self.suspended[self.actor_id] = self.presenter.uncertain
        self.presenter.reset()
        self.actor_id = user.id if user else None
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
        self.presenter.uncertain = self.suspended.pop(self.actor_id, None)
        if self.presenter.uncertain:
            _, warehouse, body, _ = self.presenter.uncertain
            for index, row in enumerate(self.warehouses):
                if str(row.id) == warehouse:
                    self.selector.current(index)
            for field, variable in self.evidence_vars.items():
                variable.set(body.get(field) or "")
            self.status.set("Lệnh ghi trước chưa rõ kết quả. Gửi lại cùng yêu cầu để xác nhận.")
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset()
        self.status.set("Kho đã đổi; tra lại serial trong kho được chọn.")
        self.enable()

    def search(self):
        if self.busy or self.presenter.uncertain:
            return
        index = self.selector.current()
        if index < 0 or not self.code.get().strip():
            self.status.set("Chọn kho và nhập serial trước khi tra cứu.")
            return
        self.presenter.search(self.warehouses[index].id, self.code.get(), self.sku.get())

    def lookup_busy(self, *, writing=False):
        if not writing:
            self.lookup_clear()
        self.busy = True
        self.status.set("Đang ghi chứng cứ…" if writing else "Đang tra serial…")
        self.enable()

    def lookup_clear(self):
        self.rows = {}
        self.table.delete(*self.table.get_children())
        self.details.set("")
        self.busy, self.permissions = False, set()
        for variable in self.evidence_vars.values():
            variable.set("")

    def lookup_result(self, rows, permissions=()):
        self.lookup_clear()
        self.permissions = set(permissions)
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
        self.enable()

    def lookup_error(self, message, *, uncertain=False):
        self.busy = False
        self.status.set(message + (" Chưa rõ kết quả; gửi lại cùng yêu cầu." if uncertain else ""))
        self.enable()

    def lookup_saved(self, result):
        self.lookup_clear()
        self.status.set(f"Đã ghi chứng cứ revision {result['version']}. Tra lại serial để xem trạng thái hiện hành.")
        self.enable()

    def select(self, event=None):
        if self.busy or self.presenter.uncertain:
            return
        selected = self.table.selection()
        if not selected or selected[0] not in self.rows:
            return
        row = self.rows[selected[0]]
        self.details.set(f"{STATUSES[row.status]} · ngày tra cứu {row.as_of}\n"
                         f"Ngày nhập: {row.received_on or 'Chưa có nguồn'} · Bắt đầu bảo hành: {row.warranty_start_on or 'Chưa xác định'}\n"
                         f"Chứng cứ: {row.warranty_evidence_ref or 'Chưa có'}\n"
                         f"Phiếu nhận: {row.receipt_number or 'Chưa có'}\n"
                         f"Nhà cung cấp: {row.supplier_name or 'Chưa có'}")
        for field, value in (("starts_on", row.warranty_start_on), ("ends_on", row.warranty_ends_on),
                             ("evidence_ref", row.warranty_evidence_ref), ("reason", "")):
            self.evidence_vars[field].set(str(value) if value else "")
        self.enable()

    def save_evidence(self, *, withdraw=False):
        selected = self.table.selection()
        if self.busy or self.presenter.uncertain or "warranty.write" not in self.permissions or not selected:
            return
        row = self.rows.get(selected[0])
        if not row or not row.receipt_move_id:
            self.status.set("Chưa có nguồn nhận hợp lệ để ghi chứng cứ.")
            return
        body = {field: variable.get().strip() or None for field, variable in self.evidence_vars.items()}
        if not body["reason"] or len(body["reason"]) < 3:
            self.status.set("Nhập lý do ghi / đính chính / rút chứng cứ (ít nhất 3 ký tự).")
            return
        if withdraw:
            body.update(starts_on=None, ends_on=None, evidence_ref=None)
        body.update(expected_version=row.version, receipt_move_id=str(row.receipt_move_id))
        self.presenter.save(row.serial_id, row.warehouse_id, body)

    def enable(self):
        free = not self.busy and not self.presenter.uncertain
        for widget in (self.selector, *self.entries, self.button):
            widget.state(["!disabled"] if free and self.warehouses else ["disabled"])
        selected = self.table.selection()
        row = self.rows.get(selected[0]) if selected else None
        writable = free and "warranty.write" in self.permissions and row and row.receipt_move_id
        for widget in (*self.evidence_inputs, self.save_button, self.withdraw_button):
            widget.state(["!disabled"] if writable else ["disabled"])
        self.retry_button.state(["!disabled"] if self.presenter.uncertain and not self.busy else ["disabled"])

    def release_variables(self):
        self.evidence_vars.clear()
        self.suspended.clear()
        self.warehouse = self.code = self.sku = self.status = self.details = None
