import tkinter as tk
from tkinter import ttk

from apps.desktop.presenters.master_data import MasterDataPresenter

ENTITIES = {
    "Đơn vị tính": ("uoms", "master.read", "master.write"),
    "Nhóm hàng": ("categories", "master.read", "master.write"),
    "Sản phẩm": ("products", "master.read", "master.write"),
    "Đối tác": ("partners", "partner.read", "partner.write"),
    "Kho": ("warehouses", "warehouse.configure", "warehouse.configure"),
    "Vị trí": ("locations", "warehouse.configure", "warehouse.configure"),
}
LABELS = {
    "code": "Mã", "sku": "SKU", "name": "Tên", "is_active": "Đang dùng",
    "decimal_places": "Số chữ số thập phân", "parent_id": "Cấp cha", "category_id": "Nhóm hàng",
    "base_uom_id": "Đơn vị cơ sở", "tracking": "Theo dõi", "expiry_required": "Bắt buộc hạn dùng",
    "is_customer": "Khách hàng", "is_supplier": "Nhà cung cấp", "address": "Địa chỉ",
    "warehouse_id": "Kho", "kind": "Loại vị trí",
}
FIELDS = {
    "uoms": ["code", "name", "decimal_places", "is_active"],
    "categories": ["code", "name", "parent_id", "is_active"],
    "products": ["sku", "name", "base_uom_id", "category_id", "tracking", "expiry_required", "is_active"],
    "partners": ["code", "name", "is_customer", "is_supplier", "is_active"],
    "warehouses": ["code", "name", "address", "is_active"],
    "locations": ["code", "name", "warehouse_id", "parent_id", "kind", "is_active"],
}
CHOICES = {
    "tracking": {"Không theo lô/serial": "NONE", "Theo lô": "LOT", "Theo serial": "SERIAL"},
    "kind": {"Zone / Rack": "GROUP", "Bin lưu trữ": "STORAGE", "Khu nhận": "RECEIVING",
             "Khu cách ly": "QUARANTINE", "Khu xuất": "SHIPPING"},
}


class MasterDataView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=16)
        self.presenter = MasterDataPresenter(self, api)
        self.permissions = set()
        self.actor_id = None
        self.suspended = {}
        self.entity = tk.StringVar(value="Đơn vị tính")
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Đăng nhập, sau đó chọn danh mục và bấm Tìm / tải lại.")
        self.reason = tk.StringVar()
        self.variables, self.inputs, self.references = {}, {}, {}
        self.rows, self.current, self.next_after = {}, None, None
        self.busy = False

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        self.selector = ttk.Combobox(toolbar, textvariable=self.entity, values=[], state="readonly", width=18)
        self.selector.pack(side="left", padx=(0, 8))
        self.selector.bind("<<ComboboxSelected>>", self.switch)
        self.search = ttk.Entry(toolbar, textvariable=self.query, width=25)
        self.search.pack(side="left", padx=(0, 8))
        self.load_button = ttk.Button(toolbar, text="Tìm / tải lại", command=self.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(toolbar, text="Trang sau", command=lambda: self.load(next_page=True))
        self.next_button.pack(side="left", padx=8)
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(fill="x", pady=10)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        listing = ttk.Frame(body)
        listing.pack(side="left", fill="both", expand=True, padx=(0, 14))
        self.table = ttk.Treeview(listing, columns=("code", "name", "state"), show="headings", height=12)
        for field, label, width in [("code", "Mã", 110), ("name", "Tên", 180), ("state", "Trạng thái", 95)]:
            self.table.heading(field, text=label)
            self.table.column(field, width=width, minwidth=50)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(listing, command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self.select)
        right = ttk.Frame(body)
        right.pack(side="right", fill="y")
        self.form = ttk.Frame(right)
        self.form.pack(fill="x")
        ttk.Label(right, text="Lý do tạo / sửa").pack(anchor="w", pady=(10, 2))
        self.reason_entry = ttk.Entry(right, textvariable=self.reason, width=35)
        self.reason_entry.pack(fill="x")
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=10)
        self.new_button = ttk.Button(actions, text="Tạo mới", command=self.new)
        self.new_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Lưu", command=self.save)
        self.save_button.pack(side="left", padx=8)
        self.retry_button = ttk.Button(right, text="Gửi lại cùng yêu cầu", command=self.presenter.retry)
        self.retry_button.pack(anchor="w")
        self.rebuild()
        self.enable()

    def resource(self):
        return ENTITIES[self.entity.get()][0]

    def session_changed(self, user=None):
        if self.actor_id and self.presenter.uncertain:
            self.suspended[self.actor_id] = self.presenter.uncertain
        self.presenter.reset()
        self.actor_id = user.id if user else None
        self.permissions = set(user.global_permissions if user else [])
        choices = [label for label, (_, permission, _) in ENTITIES.items() if permission in self.permissions]
        self.selector.configure(values=choices)
        if choices and self.entity.get() not in choices:
            self.entity.set(choices[0])
            self.rebuild()
        self.status.set("Chọn danh mục và bấm Tìm / tải lại." if choices else "Chưa có quyền xem danh mục.")
        pending = self.suspended.pop(self.actor_id, None)
        if pending:
            entity, record_id, payload, _ = pending
            self.entity.set(next(label for label, config in ENTITIES.items() if config[0] == entity))
            self.rebuild()
            self.presenter.uncertain = pending
            self.display({**payload, "id": record_id, "version": payload.get("expected_version", 1)})
            self.status.set("Yêu cầu trước chưa rõ kết quả. Gửi lại cùng yêu cầu để xác nhận.")
        self.enable()

    def switch(self, event=None):
        self.presenter.reset()
        self.rebuild()
        self.load()

    def rebuild(self):
        self.variables.clear()
        self.inputs.clear()
        for child in self.form.winfo_children():
            child.destroy()
        for index, field in enumerate(FIELDS[self.resource()]):
            ttk.Label(self.form, text=LABELS[field]).grid(row=index, column=0, sticky="w", pady=3)
            variable = tk.StringVar()
            self.variables[field] = variable
            if field in CHOICES or field.endswith("_id") or field.startswith("is_") or field == "expiry_required":
                options = list(CHOICES[field]) if field in CHOICES else (["Có", "Không"] if not field.endswith("_id") else [])
                widget = ttk.Combobox(self.form, textvariable=variable, values=options, state="readonly", width=25)
            else:
                widget = ttk.Entry(self.form, textvariable=variable, width=28)
            widget.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=3)
            self.inputs[field] = widget
        self.new()

    def new(self):
        if self.presenter.uncertain:
            return
        self.current = None
        self.reason.set("")
        for field, variable in self.variables.items():
            value = "Có" if field == "is_active" else "Không" if field.startswith("is_") or field == "expiry_required" else "0" if field == "decimal_places" else ""
            if field in CHOICES:
                value = next(iter(CHOICES[field]))
            variable.set(value)
        self.enable()

    def load(self, next_page=False):
        self.presenter.load(self.resource(), self.query.get(), self.next_after if next_page else None)

    def select(self, event=None):
        if self.busy or self.presenter.uncertain:
            return
        selection = self.table.selection()
        if selection:
            self.display(self.rows[selection[0]])

    def display(self, record):
        self.current = record
        self.reason.set("")
        for field, variable in self.variables.items():
            value = record.get(field)
            if field in CHOICES:
                value = next(label for label, code in CHOICES[field].items() if code == value)
            elif isinstance(value, bool):
                value = "Có" if value else "Không"
            elif field.endswith("_id"):
                label = next((label for label, target in self.references.get(field, {}).items() if target == value), "")
                if value and not label:
                    label = "Tham chiếu hiện tại (ngoài danh sách)"
                    self.references.setdefault(field, {})[label] = value
                    self.inputs[field].configure(values=list(self.references[field]))
                value = label
            variable.set("" if value is None else str(value))
        self.enable()

    def save(self):
        body = {}
        try:
            for field, variable in self.variables.items():
                value = variable.get()
                if field in CHOICES:
                    value = CHOICES[field][value]
                elif field.startswith("is_") or field == "expiry_required":
                    value = value == "Có"
                elif field == "decimal_places":
                    value = int(value)
                elif field.endswith("_id"):
                    # Preserve an existing inactive/unloaded reference unless the user explicitly chooses another.
                    value = self.references.get(field, {}).get(value, self.current.get(field) if self.current else None)
                elif field == "address" and not value:
                    value = None
                body[field] = value
            body["reason"] = self.reason.get()
            if self.current:
                body["expected_version"] = self.current["version"]
        except (ValueError, KeyError):
            self.catalog_error("Kiểm tra số chữ số thập phân và các lựa chọn trong form.", uncertain=False)
            return
        self.presenter.save(self.resource(), self.current["id"] if self.current else None, body)

    def catalog_busy(self):
        self.busy = True
        self.status.set("Đang xử lý…")
        self.enable()

    def enable(self):
        readable = ENTITIES[self.entity.get()][1] in self.permissions
        writable = ENTITIES[self.entity.get()][2] in self.permissions
        uncertain = bool(self.presenter.uncertain)
        free = not self.busy and not uncertain
        for widget in [self.selector, self.search, self.load_button]:
            widget.state(["!disabled"] if free and readable else ["disabled"])
        self.next_button.state(["!disabled"] if free and readable and self.next_after else ["disabled"])
        for widget in [self.new_button, self.save_button, self.reason_entry, *self.inputs.values()]:
            widget.state(["!disabled"] if free and writable else ["disabled"])
        for field in ("code", "sku"):
            if field in self.inputs and self.current:
                self.inputs[field].state(["disabled"])
        self.retry_button.state(["!disabled"] if uncertain and not self.busy else ["disabled"])

    def catalog_loaded(self, result, refs):
        self.busy = False
        self.rows = {record["id"]: record for record in result["items"]}
        self.next_after = result["next_after"]
        self.table.delete(*self.table.get_children())
        for record in self.rows.values():
            self.table.insert("", "end", iid=record["id"], values=(record.get("sku", record.get("code")), record["name"], "Đang dùng" if record["is_active"] else "Ngừng dùng"))
        self.references = {}
        for field, data in refs.items():
            mapping = {"— Không chọn —": None}
            mapping.update({f"{row['code']} · {row['name']}": row["id"] for row in data["items"]})
            self.references[field] = mapping
            self.inputs[field].configure(values=list(mapping))
        if self.current:
            self.display(self.current)
        truncated = any(data["next_after"] for data in refs.values())
        self.status.set(f"Đã tải {len(self.rows)} bản ghi." + (" Danh sách chọn chỉ hiển thị 200 mục đầu." if truncated else ""))
        self.enable()

    def catalog_saved(self, record):
        self.busy = False
        self.display(record)
        self.status.set(f"Đã lưu {record.get('sku', record.get('code'))}, phiên bản {record['version']}. Bấm Tìm / tải lại để cập nhật danh sách.")

    def catalog_error(self, message, *, uncertain):
        self.busy = False
        self.status.set(message + (" Chưa xác định đã lưu hay chưa; gửi lại cùng yêu cầu để xác nhận." if uncertain else ""))
        self.enable()

    def catalog_clear(self):
        self.busy = False
        self.rows, self.current, self.next_after = {}, None, None
        self.references = {}
        self.table.delete(*self.table.get_children())
        for field, widget in self.inputs.items():
            if field.endswith("_id"):
                widget.configure(values=[])
        self.new()

    def release_variables(self):
        self.variables.clear()
        self.suspended.clear()
        self.entity = self.query = self.reason = self.status = None
