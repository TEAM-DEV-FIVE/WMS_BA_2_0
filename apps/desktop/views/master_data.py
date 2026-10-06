import tkinter as tk
from tkinter import ttk

from apps.desktop.presenters.master_data import REFERENCES, MasterDataPresenter
from apps.desktop.views.catalog_lookup import CatalogLookup, reference_label

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
    "partner_id": "Nhà cung cấp", "owner_id": "Chủ hàng", "valid_from": "Từ ngày (YYYY-MM-DD)",
    "valid_until": "Đến ngày (YYYY-MM-DD)", "source_ref": "Nguồn hợp đồng",
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
    entities = ENTITIES
    fields = FIELDS
    choices = CHOICES

    def __init__(self, parent, api):
        super().__init__(parent, padding=16)
        self.presenter = MasterDataPresenter(self, api)
        self.permissions = set()
        self.actor_id = None
        self.suspended = {}
        self.entity = tk.StringVar(value=next(iter(self.entities)))
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Đăng nhập, sau đó chọn danh mục và bấm Tìm / tải lại.")
        self.reason = tk.StringVar()
        self.variables, self.inputs, self.references = {}, {}, {}
        self.rows, self.current, self.next_after = {}, None, None
        self.busy = False
        self.lookup = None
        self.reference_buttons = {}

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        self.selector = ttk.Combobox(toolbar, textvariable=self.entity, values=[], state="readonly", width=18)
        self.selector.pack(side="left", padx=(0, 8))
        self.selector.bind("<<ComboboxSelected>>", self.switch)
        self.search = ttk.Entry(toolbar, textvariable=self.query, width=25)
        self.search.pack(side="left", padx=(0, 8))
        self.search.bind("<Return>", lambda event: self.load())
        self.load_button = ttk.Button(toolbar, text="Tìm / tải lại", command=self.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(toolbar, text="Trang sau", command=lambda: self.load(next_page=True))
        self.next_button.pack(side="left", padx=8)
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(fill="x", pady=10)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, minsize=180)
        body.columnconfigure(1, weight=1, minsize=260)
        body.rowconfigure(0, weight=1)
        listing = ttk.Frame(body)
        listing.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
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
        right.grid(row=0, column=1, sticky="nsew")
        self.form = ttk.Frame(right)
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
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
        self.bind("<Control-s>", lambda event: self.save() if not self.busy else None)
        self.rebuild()
        self.enable()

    def resource(self):
        return self.entities[self.entity.get()][0]

    def session_changed(self, user=None):
        if self.lookup:
            self.lookup.cancel()
        if self.actor_id and self.presenter.uncertain:
            self.suspended[self.actor_id] = self.presenter.uncertain
        self.presenter.reset()
        self.query.set("")
        self.actor_id = user.id if user else None
        self.permissions = set(user.global_permissions if user else [])
        choices = [label for label, (_, permission, _) in self.entities.items() if permission in self.permissions]
        self.selector.configure(values=choices)
        if choices and self.entity.get() not in choices:
            self.entity.set(choices[0])
            self.rebuild()
        self.status.set("Chọn danh mục và bấm Tìm / tải lại." if choices else "Chưa có quyền xem danh mục.")
        pending = self.suspended.pop(self.actor_id, None)
        if pending:
            entity, record_id, payload, _ = pending
            self.entity.set(next(label for label, config in self.entities.items() if config[0] == entity))
            self.rebuild()
            self.presenter.uncertain = pending
            self.display({**payload, "id": record_id, "version": payload.get("expected_version", 1)})
            self.status.set("Yêu cầu trước chưa rõ kết quả. Gửi lại cùng yêu cầu để xác nhận.")
        self.enable()

    def switch(self, event=None):
        if self.busy or self.presenter.uncertain:
            return
        self.presenter.reset()
        self.query.set("")
        self.rebuild()
        self.load()

    def rebuild(self):
        self.variables.clear()
        self.inputs.clear()
        self.reference_buttons.clear()
        for child in self.form.winfo_children():
            child.destroy()
        for index, field in enumerate(self.fields[self.resource()]):
            ttk.Label(self.form, text=LABELS[field]).grid(row=index, column=0, sticky="w", pady=3)
            variable = tk.StringVar()
            self.variables[field] = variable
            if field in self.choices or field.endswith("_id") or field.startswith("is_") or field == "expiry_required":
                options = list(self.choices[field]) if field in self.choices else (["Có", "Không"] if not field.endswith("_id") else [])
                widget = ttk.Combobox(self.form, textvariable=variable, values=options, state="readonly", width=25)
            else:
                widget = ttk.Entry(self.form, textvariable=variable, width=28)
            widget.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=3)
            self.inputs[field] = widget
            if field in REFERENCES.get(self.resource(), {}):
                button = ttk.Button(self.form, text="Tìm…", width=6, command=lambda f=field: self.open_reference(f))
                button.grid(row=index, column=2, padx=3)
                self.reference_buttons[field] = button
            if field == "warehouse_id" and self.resource() == "locations":
                widget.bind("<<ComboboxSelected>>", lambda event: self.warehouse_changed())
        self.new()

    def new(self):
        if self.presenter.uncertain:
            return
        self.current = None
        self.reason.set("")
        for field, variable in self.variables.items():
            value = "Có" if field == "is_active" else "Không" if field.startswith("is_") or field == "expiry_required" else "0" if field == "decimal_places" else ""
            if field in self.choices:
                value = next(iter(self.choices[field]))
            variable.set(value)
        self.enable()
        if self.inputs:
            next(iter(self.inputs.values())).focus_set()

    def load(self, next_page=False):
        if self.busy or self.presenter.uncertain:
            return
        filters = {}
        if self.resource() == "locations" and self.reference_value("warehouse_id"):
            filters["warehouse_id"] = self.reference_value("warehouse_id")
        self.presenter.load(self.resource(), self.query.get(), self.next_after if next_page else None, filters=filters)

    def reference_value(self, field):
        return self.references.get(field, {}).get(self.variables[field].get())

    def warehouse_changed(self):
        self.variables["parent_id"].set("")
        self.references["parent_id"] = {}
        self.inputs["parent_id"].configure(values=[])
        self.next_after = None

    def open_reference(self, field):
        if self.busy or self.presenter.uncertain or self.lookup:
            return
        filters = {"active": "true"}
        if field == "parent_id" and self.resource() == "locations":
            warehouse = self.reference_value("warehouse_id")
            if not warehouse:
                self.status.set("Chọn kho trước khi tìm Zone / Rack cha.")
                return
            filters["warehouse_id"] = warehouse
        self.lookup = CatalogLookup(self, "master/" + REFERENCES[self.resource()][field],
                                    lambda row: self.set_reference(field, row), filters=filters)
        self.lookup.load()

    def set_reference(self, field, row):
        label = reference_label(row)
        self.references.setdefault(field, {})[label] = row["id"]
        self.inputs[field].configure(values=list(self.references[field]))
        self.variables[field].set(label)
        if field == "warehouse_id" and self.resource() == "locations":
            self.warehouse_changed()

    def catalog_reference_loaded(self, result):
        self.busy = False
        if self.lookup:
            self.lookup.loaded(result)
        self.enable()

    def select(self, event=None):
        if self.busy or self.presenter.uncertain:
            return
        selection = self.table.selection()
        if selection and selection[0] in self.rows:
            self.display(self.rows[selection[0]])

    def display(self, record):
        self.current = record
        self.reason.set("")
        for field, variable in self.variables.items():
            value = record.get(field)
            if field in self.choices:
                value = next((label for label, code in self.choices[field].items() if code == value), value)
            elif isinstance(value, bool):
                value = "Có" if value else "Không"
            elif field.endswith("_id"):
                label = next((label for label, target in self.references.get(field, {}).items() if target == value), "")
                if value and not label:
                    label = f"Tham chiếu hiện tại [{value}]"
                    self.references.setdefault(field, {})[label] = value
                    self.inputs[field].configure(values=list(self.references[field]))
                value = label
            variable.set("" if value is None else str(value))
        self.enable()

    def save(self):
        if self.busy or self.presenter.uncertain or self.entities[self.entity.get()][2] not in self.permissions:
            return
        body = {}
        try:
            for field, variable in self.variables.items():
                value = variable.get()
                if field in self.choices:
                    value = self.choices[field][value]
                elif field.startswith("is_") or field == "expiry_required":
                    value = value == "Có"
                elif field == "decimal_places":
                    value = int(value)
                elif field.endswith("_id"):
                    # Preserve an existing inactive/unloaded reference unless the user explicitly chooses another.
                    value = self.references.get(field, {}).get(value)
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
        if self.lookup:
            self.lookup.busy()

    def enable(self):
        readable = self.entities[self.entity.get()][1] in self.permissions
        writable = self.entities[self.entity.get()][2] in self.permissions
        uncertain = bool(self.presenter.uncertain)
        free = not self.busy and not uncertain
        for widget in [self.selector, self.search, self.load_button]:
            widget.state(["!disabled"] if free and readable else ["disabled"])
        self.next_button.state(["!disabled"] if free and readable and self.next_after else ["disabled"])
        for widget in [self.new_button, self.save_button, self.reason_entry, *self.inputs.values(), *self.reference_buttons.values()]:
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
        self.table.configure(show="tree headings" if self.resource() == "locations" else "headings")
        self.table.column("#0", width=85, minwidth=40)
        for warehouse in result.get("warehouses", {}).values():
            self.table.insert("", "end", iid="wh:" + warehouse["id"], text="Kho", values=(warehouse["code"], warehouse["name"], ""), open=True)
        nodes = {**result.get("ancestors", {}), **self.rows}
        def insert(record):
            if self.table.exists(record["id"]):
                return
            parent = ""
            if self.resource() == "locations":
                parent = record.get("parent_id")
                if parent and parent in nodes:
                    insert(nodes[parent])
                else:
                    parent = "wh:" + record["warehouse_id"]
            self.table.insert(parent, "end", iid=record["id"], text=record.get("kind", ""),
                              values=(record.get("sku", record.get("code")), record.get("name", record.get("source_ref", "")),
                                      "Đang dùng" if record.get("is_active", True) else "Ngừng dùng"), open=True)
        for record in nodes.values():
            insert(record)
        previous_references = self.references
        self.references = {}
        for field, data in refs.items():
            mapping = {"— Không chọn —": None}
            mapping.update({reference_label(row): row["id"] for row in data["items"]})
            selected = self.variables[field].get()
            if selected in previous_references.get(field, {}):
                mapping[selected] = previous_references[field][selected]
            self.references[field] = mapping
            self.inputs[field].configure(values=list(mapping))
        if self.current:
            self.display(self.rows.get(self.current["id"], self.current))
        truncated = any(data["next_after"] for data in refs.values())
        self.status.set(f"Đã tải {len(self.rows)} bản ghi." + (" Bấm Tìm… bên cạnh ô tham chiếu để tìm hoặc chuyển trang." if truncated else ""))
        self.enable()

    def catalog_saved(self, record):
        self.busy = False
        self.display(record)
        self.status.set(f"Đã lưu {record.get('sku', record.get('code'))}, phiên bản {record['version']}. Bấm Tìm / tải lại để cập nhật danh sách.")

    def catalog_error(self, message, *, uncertain):
        self.busy = False
        self.status.set(message + (" Chưa xác định đã lưu hay chưa; gửi lại cùng yêu cầu để xác nhận." if uncertain else ""))
        self.enable()
        if self.lookup:
            self.lookup.error(message)

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
        if self.lookup:
            self.lookup.cancel()
        self.variables.clear()
        self.suspended.clear()
        self.entity = self.query = self.reason = self.status = None
