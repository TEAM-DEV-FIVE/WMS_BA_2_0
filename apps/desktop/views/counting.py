from datetime import date
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.counting import CountPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.counting import (
    CountDecisionInput,
    CountEmptyInput,
    CountExtraInput,
    CountInput,
    CountObservationInput,
    CountPost,
)
from packages.contracts.orders import OrderAction


class CountView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, CountPresenter, scrollable=True)
        self.doc, self.page_after = None, None
        self.scope, self.catalogs, self.catalog_after = [], {}, {}
        self.inputs, self.buttons, self.catalog_buttons = [], {}, []
        self.load_button = ttk.Button(self.top, text="Tải phiên", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.page_after))
        self.next_button.pack(side="left", padx=4)
        self.new_button = ttk.Button(self.top, text="Phiên mới", command=self.new)
        self.new_button.pack(side="left")
        self.table = self.tree(self.content, ["number", "date", "status"], ["Phiên kiểm kê", "Ngày nghiệp vụ", "Trạng thái"], [380, 150, 220])
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self.content, textvariable=self.variables["detail"], wraplength=700).pack(fill="x", pady=3)
        actions = ttk.Frame(self.content)
        actions.pack(fill="x")
        for index, (action, title) in enumerate([("freeze", "Khóa vị trí / snapshot"), ("submit", "Gửi duyệt"), ("approve", "Duyệt bước hiện tại"),
                              ("reject", "Từ chối / đếm lại"), ("post", "Ghi sổ điều chỉnh"), ("cancel", "Hủy phiên / giải khóa")]):
            self.buttons[action] = ttk.Button(actions, text=title, command=lambda a=action: self.action(a))
            self.buttons[action].grid(row=index // 3, column=index % 3, padx=2, pady=2, sticky="ew")
        self.tabs = ttk.Notebook(self.content)
        self.tabs.pack(fill="both", expand=True, pady=5)
        planning, counting, extra = [ttk.Frame(self.tabs, padding=8) for _ in range(3)]
        for tab, title in [(planning, "Phân công"), (counting, "Đếm / duyệt"), (extra, "Hàng ngoài snapshot")]:
            self.tabs.add(tab, text=title)
        self.field(planning, "business_date", "Ngày ghi sổ (YYYY-MM-DD)", date.today().isoformat())
        self.catalog_row(planning, "locations", "location", "Vị trí")
        self.catalog_row(planning, "users", "counter1", "Người đếm thứ nhất")
        self.counter2 = self.combo(planning, "counter2", 65)
        ttk.Label(planning, text="Người đếm thứ hai (khác người thứ nhất)").pack(anchor="w")
        self.counter2.pack(fill="x")
        self.inputs.append(self.counter2)
        bar = ttk.Frame(planning)
        bar.pack(fill="x", pady=4)
        self.add_scope_button = ttk.Button(bar, text="Thêm vị trí / hai người đếm", command=self.add_scope)
        self.add_scope_button.pack(side="left")
        self.remove_scope_button = ttk.Button(bar, text="Bỏ vị trí đã chọn", command=self.remove_scope)
        self.remove_scope_button.pack(side="left", padx=5)
        self.scope_table = self.tree(planning, ["location", "users"], ["Vị trí", "Người đếm"], [230, 500])
        self.create_button = ttk.Button(planning, text="Tạo phiên nháp", command=self.create)
        self.create_button.pack(anchor="w", pady=5)
        self.lines = self.tree(counting, ["sku", "owner", "trace", "location", "round", "snapshot", "approved", "delta"],
            ["SKU", "Chủ hàng / hợp đồng", "Lô / serial", "Vị trí", "Vòng kế tiếp", "Snapshot", "Lượng duyệt", "Chênh lệch"],
            [110, 240, 160, 110, 100, 100, 100, 100], height=5)
        self.lines.bind("<<TreeviewSelect>>", self.select_line)
        self.field(counting, "quantity", "Số đếm thực tế (serial: 0 hoặc 1)")
        self.observe_button = ttk.Button(counting, text="Lưu vòng đếm độc lập", command=self.observe)
        self.observe_button.pack(anchor="w", pady=3)
        self.history = self.tree(counting, ["round", "quantity", "counter", "reason"],
                                 ["Vòng", "Số đếm", "Người đếm", "Lý do"], [65, 95, 285, 350])
        ttk.Label(counting, text="Người được phân công chỉ thấy danh tính hàng và vòng kế tiếp. Hai vòng liên tiếp phải độc lập và khớp nhau.", wraplength=700).pack(fill="x")
        for resource, name, title in [("products", "product", "SKU đã xác minh"), ("owners", "owner", "Chủ hàng"),
                                      ("agreements", "agreement", "Hợp đồng ký gửi (nếu có)")]:
            self.catalog_row(extra, resource, name, title)
        self.extra_location = self.combo(extra, "extra_location", 65)
        ttk.Label(extra, text="Vị trí thuộc phạm vi phân công").pack(anchor="w")
        self.extra_location.pack(fill="x")
        self.inputs.append(self.extra_location)
        self.empty_button = ttk.Button(extra, text="Xác nhận vị trí này trống", command=self.confirm_empty)
        self.empty_button.pack(anchor="w", pady=3)
        for name, title in [("lot", "Mã lô (LOT)"), ("serial", "Mã serial (SERIAL)"), ("expires", "Hạn dùng lô YYYY-MM-DD (nếu có)")]:
            self.field(extra, name, title)
        self.extra_button = ttk.Button(extra, text="Thêm danh tính vào phiên", command=self.add_extra)
        self.extra_button.pack(anchor="w", pady=5)
        self.reason_form()
        self.retry_form(operation=True)
        self.session_changed()

        from apps.desktop.scanner.widget import ScanBar
        self.scan_bar = ScanBar(self.content, self, "COUNT")
        self.scan_bar.pack(fill="x", pady=3, before=self.content.winfo_children()[0])

    def field(self, parent, name, title, value=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=title, width=39).pack(side="left")
        entry = ttk.Entry(row, textvariable=self.variable(name, value))
        entry.pack(side="left", fill="x", expand=True)
        self.inputs.append(entry)
        return entry

    def catalog_row(self, parent, resource, name, title):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=title, width=25).pack(side="left")
        combo = self.combo(row, name, 48)
        combo.pack(side="left", fill="x", expand=True)
        setattr(self, name + "_selector", combo)
        self.inputs.append(combo)
        search = ttk.Entry(row, textvariable=self.variable("search_" + resource), width=12)
        search.pack(side="left", padx=3)
        for title, more in [("Tìm / tải", False), ("Tiếp", True)]:
            button = ttk.Button(row, text=title, command=lambda r=resource, m=more: self.presenter.catalog(r,
                self.catalog_after.get(r) if m else None, self.variables["search_" + r].get()))
            button.pack(side="left", padx=2)
            self.catalog_buttons.append(button)

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.page_after)
        for widget in self.inputs + self.catalog_buttons + [self.reason_entry, self.new_button]:
            self.set_enabled(widget, writable)
        for widget in [self.create_button, self.add_scope_button, self.remove_scope_button]:
            self.set_enabled(widget, writable and not self.doc and "count.create" in self.permissions)
        allowed = self.doc["allowed_actions"] if self.doc else []
        for action, button in self.buttons.items():
            self.set_enabled(button, writable and ("decide" if action in {"approve", "reject"} else action) in allowed)
        line = self.selected_line()
        self.set_enabled(self.observe_button, writable and line and line["can_count"])
        self.set_enabled(self.extra_button, writable and "extra" in allowed)
        self.set_enabled(self.empty_button, writable and "confirm-empty" in allowed)
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain)

    def workflow_clear(self):
        self.doc, self.page_after, self.scope = None, None, []
        self.catalogs, self.catalog_after, self.permissions = {}, {}, []
        self.busy = False
        for table in [self.table, self.scope_table, self.lines, self.history]:
            table.delete(*table.get_children())
        for name, variable in self.variables.items():
            if name not in {"warehouse", "status"}:
                variable.set("")
        for name in ("location", "counter1", "product", "owner", "agreement"):
            getattr(self, name + "_selector").configure(values=[])
        self.counter2.configure(values=[])
        self.extra_location.configure(values=[])

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc, self.scope = None, []
        self.scope_table.delete(*self.scope_table.get_children())
        self.lines.delete(*self.lines.get_children())
        self.history.delete(*self.history.get_children())
        self.variables["business_date"].set(date.today().isoformat())
        self.variables["detail"].set("Phiên mới: chọn vị trí và ít nhất hai người đếm độc lập.")
        self.tabs.select(0)
        self.enable()

    def selected_catalog(self, resource, combo):
        index = combo.current()
        rows = self.catalogs.get(resource, [])
        return rows[index] if 0 <= index < len(rows) else None

    def add_scope(self):
        loc = self.selected_catalog("locations", self.location_selector)
        users = [self.selected_catalog("users", w) for w in (self.counter1_selector, self.counter2)]
        if not loc or not all(users) or users[0]["id"] == users[1]["id"]:
            return self.workflow_error("Chọn vị trí và hai người đếm khác nhau từ danh sách.")
        if any(r["location_id"] == loc["id"] for r in self.scope):
            return self.workflow_error("Vị trí đã có trong phạm vi.")
        self.scope.append(dict(location_id=loc["id"], user_ids=[u["id"] for u in users]))
        self.scope_table.insert("", "end", iid=loc["id"], values=(loc["code"], " / ".join(u["name"] for u in users)))

    def remove_scope(self):
        for selected in self.scope_table.selection():
            self.scope = [r for r in self.scope if r["location_id"] != selected]
            self.scope_table.delete(selected)

    def create(self):
        self.send("", CountInput, warehouse_id=self.warehouse_id(), business_date=self.variables["business_date"].get(), scope=self.scope)

    def send(self, action, model, **fields):
        if self.busy or self.presenter.uncertain:
            return
        try:
            body = model(reason=self.variables["reason"].get(), **fields).model_dump(mode="json")
            path = "counts" + ("/" + self.doc["id"] + "/" + action if action else "")
            self.presenter.command("POST", path, body)
        except (ValueError, TypeError):
            self.workflow_error("Kiểm tra dữ liệu, ngày, phân công, số lượng và lý do (ít nhất 3 ký tự).")

    def action(self, action):
        if not self.doc:
            return
        fields = {"expected_version": self.doc["version"]}
        model = OrderAction
        if action in {"approve", "reject"}:
            fields["decision"] = "APPROVE" if action == "approve" else "REJECT"
            action, model = "decide", CountDecisionInput
        if action == "post":
            model, fields["execution_key"] = CountPost, str(uuid4())
        self.send(action, model, **fields)

    def selected_line(self):
        selected = self.lines.selection()
        return next((r for r in self.doc["lines"] if selected and r["id"] == selected[0]), None) if self.doc else None

    def select_line(self, event=None):
        self.history.delete(*self.history.get_children())
        line = self.selected_line()
        if line and self.doc["mode"] == "REVIEW":
            for obs in line["observations"]:
                self.history.insert("", "end", values=(obs["round_no"], obs["quantity"], obs["counted_by"], obs["reason"]))
        self.enable()

    def observe(self):
        line = self.selected_line()
        if line:
            self.send("observe", CountObservationInput, expected_version=self.doc["version"], line_id=line["id"],
                round_no=line["next_round"], quantity=self.variables["quantity"].get(), scan_event_key=str(uuid4()))

    def add_extra(self):
        product = self.selected_catalog("products", self.product_selector)
        owner = self.selected_catalog("owners", self.owner_selector)
        agreement = self.selected_catalog("agreements", self.agreement_selector)
        idx = self.extra_location.current()
        if not product or not owner or idx < 0 or not self.doc:
            return self.workflow_error("Chọn SKU, chủ hàng và vị trí được phân công.")
        self.send("extra", CountExtraInput, expected_version=self.doc["version"], location_id=self.doc["scope"][idx]["location_id"],
            product_id=product["id"], owner_id=owner["id"], consignment_id=agreement["id"] if agreement else None,
            lot_code=self.variables["lot"].get().strip() or None, serial_code=self.variables["serial"].get().strip() or None,
            expires_on=self.variables["expires"].get().strip() or None)

    def confirm_empty(self):
        idx = self.extra_location.current()
        if self.doc and idx >= 0:
            self.send("confirm-empty", CountEmptyInput, expected_version=self.doc["version"], location_id=self.doc["scope"][idx]["location_id"])

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def workflow_loaded(self, action, data, permissions):
        self.busy, self.permissions = False, permissions
        if action == "counts":
            self.page_after = data["next_after"]
            self.table.delete(*self.table.get_children())
            for row in data["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["number"], row["business_date"], row["status"]))
        elif action.startswith("catalog/"):
            resource = action.split("/")[1]
            self.catalogs[resource], self.catalog_after[resource] = data["items"], data["next_after"]
            widgets = {"locations": [self.location_selector], "users": [self.counter1_selector, self.counter2],
                       "products": [self.product_selector], "owners": [self.owner_selector], "agreements": [self.agreement_selector]}[resource]
            for widget in widgets:
                widget.set("")
                widget.configure(values=[r["code"] + " · " + r["name"] for r in data["items"]])
        else:
            self.doc = data
            mode = "Đếm mù" if data["mode"] == "BLIND" else "Xem xét / duyệt"
            self.variables["detail"].set(f"{data['number']} · {data['status']} · v{data['version']} · {mode}")
            if data["mode"] == "REVIEW" and data["decisions"]:
                decisions = data["decisions"]
                progress = " | ".join(f"Bước {d['step_no']}: {d['decision']} · {d['decided_by']} · {d['reason']}" for d in decisions)
                self.variables["detail"].set(self.variables["detail"].get() + "\n" + progress)
            if data["mode"] == "REVIEW" and data["empty_confirmations"]:
                self.variables["detail"].set(self.variables["detail"].get() + "\nXác nhận trống: " + " | ".join(
                    f"{r['location_id']} · {r['counted_by']} · {r['reason']}" for r in data["empty_confirmations"]))
            self.variables["reason"].set("")
            self.variables["quantity"].set("")
            self.lines.delete(*self.lines.get_children())
            self.history.delete(*self.history.get_children())
            self.lines.configure(displaycolumns=("sku", "owner", "trace", "location", "round") if data["mode"] == "BLIND" else "#all")
            for row in data["lines"]:
                self.lines.insert("", "end", iid=row["id"], values=(row["sku"], row["owner_code"] + (" / " + row["consignment_id"] if row["consignment_id"] else ""),
                    row["lot_code"] or row["serial_code"] or "—", row["location_code"], row["next_round"],
                    row.get("snapshot_quantity", ""), row.get("approved_quantity") or "", row.get("delta") or ""))
            self.extra_location.set("")
            self.extra_location.configure(values=[r["location_id"] for r in data["scope"]])
            self.tabs.select(1)
        self.variables["status"].set("Đã tải dữ liệu máy chủ.")
        self.enable()

    def workflow_saved(self, result):
        self.busy = False
        self.variables["status"].set("Máy chủ đã xác nhận " + result["status"])
        self.presenter.read(result["id"])
