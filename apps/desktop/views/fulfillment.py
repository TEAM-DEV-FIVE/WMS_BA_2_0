"""Keyboard/scan-friendly B10 view. Scanner adapters call scan()/confirm_pick() on Tk's thread."""
from tkinter import ttk

from apps.desktop.presenters.fulfillment import FulfillmentPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.fulfillment import (
    FulfillmentAction,
    PackageCreate,
    PickAssign,
    PickConfirm,
    PickCreate,
)


class FulfillmentView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, FulfillmentPresenter)
        self.doc, self.next_after, self.assignee_after = None, None, None
        self.reservations, self.tasks, self.packages, self.assignees, self.pack_lines = {}, {}, {}, [], []
        self.load_button = ttk.Button(self.top, text="Tải phiếu xuất", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.next_after))
        self.next_button.pack(side="left", padx=5)
        self.refresh_button = ttk.Button(self.top, text="Tải lại phiếu", command=lambda: self.presenter.read(self.doc["id"]) if self.doc else None)
        self.refresh_button.pack(side="left")
        self.table = self.tree(self, ["number", "status", "version"], ["Phiếu xuất", "Trạng thái", "Version"], [300, 180, 90], height=2)
        self.table.bind("<<TreeviewSelect>>", self.select_document)
        ttk.Label(self, textvariable=self.variables["detail"], wraplength=820).pack(fill="x", pady=3)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        pick, pack = ttk.Frame(self.tabs, padding=6), ttk.Frame(self.tabs, padding=6)
        self.tabs.add(pick, text="Soạn / quét mã")
        self.tabs.add(pack, text="Đóng kiện")
        allocation = ttk.Frame(pick)
        allocation.pack(fill="x")
        ttk.Label(allocation, text="Giữ chỗ").grid(row=0, column=0, sticky="w")
        self.reservation_selector = self.combo(allocation, "reservation", 78)
        self.reservation_selector.grid(row=0, column=1, columnspan=3, sticky="ew")
        ttk.Label(allocation, text="Người soạn").grid(row=1, column=0, sticky="w")
        self.assignee_selector = self.combo(allocation, "assignee", 30)
        self.assignee_selector.grid(row=1, column=1, sticky="ew", pady=4)
        self.assignee_button = ttk.Button(allocation, text="Tải người soạn", command=lambda: self.presenter.assignees(self.doc["id"]) if self.doc else None)
        self.assignee_button.grid(row=1, column=2, padx=5)
        self.assignee_next = ttk.Button(allocation, text="Người soạn tiếp", command=lambda: self.presenter.assignees(self.doc["id"], self.assignee_after))
        self.assignee_next.grid(row=1, column=3)
        allocation.columnconfigure(1, weight=1)
        quantities = ttk.Frame(pick)
        quantities.pack(fill="x", pady=3)
        ttk.Label(quantities, text="Lượng giao / xác nhận (đơn vị cơ sở)").pack(side="left")
        self.quantity_entry = ttk.Entry(quantities, textvariable=self.variable("quantity", "1"), width=14)
        self.quantity_entry.pack(side="left", padx=6)
        self.create_button = ttk.Button(quantities, text="Giao soạn", command=lambda: self.action("pick", "create"))
        self.create_button.pack(side="left")
        self.task_table = self.tree(pick, ["source", "picker", "quantity", "status"],
            ["Vị trí · SKU · lô/serial", "Người soạn", "Giao / soạn / xuất", "Trạng thái · version"], [300, 160, 150, 160], height=3)
        self.task_table.bind("<<TreeviewSelect>>", self.task_selected)
        scans = ttk.Frame(pick)
        scans.pack(fill="x", pady=4)
        self.scan_entries = {}
        for field, label in [("location_code", "Vị trí"), ("item_code", "SKU/barcode"), ("trace_code", "Lô/serial")]:
            ttk.Label(scans, text=label).pack(side="left", padx=(0, 3))
            entry = ttk.Entry(scans, textvariable=self.variable(field), width=18)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.scan_entries[field] = entry
        self.scan_entries["location_code"].bind("<Return>", lambda event: self.scan_entries["item_code"].focus_set())
        self.scan_entries["item_code"].bind("<Return>", lambda event: self.scan_entries["trace_code"].focus_set())
        self.scan_entries["trace_code"].bind("<Return>", lambda event: self.confirm_pick())
        bar = ttk.Frame(pick)
        bar.pack(fill="x")
        self.pick_buttons = {}
        for action, label in [("assign", "Giao lại"), ("start", "Bắt đầu"), ("confirm", "Xác nhận lượng đã soạn"), ("reject", "Không có hàng"), ("cancel", "Hủy nhiệm vụ")]:
            button = ttk.Button(bar, text=label, command=lambda a=action: self.action("pick", a))
            button.pack(side="left", padx=(0, 4))
            self.pick_buttons[action] = button
        ttk.Label(pick, text="Thiếu một phần: nhập lượng thực soạn và lý do. Không có hàng: chọn Không có hàng.", wraplength=790).pack(anchor="w", pady=3)
        packing = ttk.Frame(pack)
        packing.pack(fill="x")
        ttk.Label(packing, text="Nhiệm vụ đã soạn").grid(row=0, column=0)
        self.pack_selector = self.combo(packing, "pack_task", 62)
        self.pack_selector.grid(row=0, column=1, columnspan=3, sticky="ew")
        ttk.Label(packing, text="Lượng đóng kiện").grid(row=1, column=0)
        self.pack_quantity = ttk.Entry(packing, textvariable=self.variable("pack_quantity", "1"), width=12)
        self.pack_quantity.grid(row=1, column=1, sticky="w", pady=4)
        self.add_button = ttk.Button(packing, text="Thêm dòng", command=self.add_line)
        self.add_button.grid(row=1, column=2)
        self.remove_button = ttk.Button(packing, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.grid(row=1, column=3)
        packing.columnconfigure(1, weight=1)
        self.line_table = self.tree(pack, ["task", "quantity"], ["Nguồn soạn", "Lượng trong kiện mới"], [550, 160], height=2)
        codes = ttk.Frame(pack)
        codes.pack(fill="x", pady=4)
        ttk.Label(codes, text="Mã kiện mới").pack(side="left")
        self.code_entry = ttk.Entry(codes, textvariable=self.variable("package_code"), width=24)
        self.code_entry.pack(side="left", padx=6)
        self.package_create = ttk.Button(codes, text="Tạo kiện", command=lambda: self.action("package", "create"))
        self.package_create.pack(side="left")
        self.package_table = self.tree(pack, ["code", "status", "quantity"],
            ["Mã kiện", "Trạng thái · version", "Lượng đóng / đã xuất"], [280, 240, 220], height=3)
        self.package_table.bind("<<TreeviewSelect>>", lambda event: self.enable())
        self.package_buttons = {}
        for action, label in [("seal", "Chốt kiện"), ("cancel", "Hủy phần kiện chưa xuất")]:
            button = ttk.Button(codes, text=label, command=lambda a=action: self.action("package", a))
            button.pack(side="left", padx=5)
            self.package_buttons[action] = button
        self.reason_form()
        ttk.Label(self, text="Soạn/đóng kiện giữ nguyên tồn. Xuất hàng tại tab Giữ hàng / xuất kho. Hủy kiện trước khi hủy nhiệm vụ.", wraplength=820).pack(anchor="w")
        self.retry_form(operation=True)
        self.operation_button.configure(text="Tra ACK soạn/kiện")
        self.session_changed()

        from apps.desktop.scanner.widget import ScanBar
        self.scan_bar = ScanBar(self, self, "PICK")
        self.scan_bar.pack(fill="x", pady=3, before=self.winfo_children()[0])

    def selected(self, table, rows):
        selection = table.selection()
        return rows.get(selection[0]) if selection else None

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        task = self.selected(self.task_table, self.tasks)
        package = self.selected(self.package_table, self.packages)
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.next_after)
        self.set_enabled(self.refresh_button, free and self.doc)
        for widget in [self.assignee_button, self.assignee_selector]:
            self.set_enabled(widget, writable and self.doc)
        self.set_enabled(self.assignee_next, writable and self.doc and self.assignee_after)
        actions = self.doc["allowed_actions"] if self.doc else []
        self.set_enabled(self.create_button, writable and "pick.create" in actions)
        for widget in [self.reservation_selector, self.quantity_entry, self.reason_entry, *self.scan_entries.values()]:
            self.set_enabled(widget, writable and self.doc)
        for action, button in self.pick_buttons.items():
            self.set_enabled(button, writable and task and action in task["allowed_actions"])
        for widget in [self.pack_selector, self.pack_quantity, self.add_button, self.remove_button, self.code_entry, self.package_create]:
            self.set_enabled(widget, writable and "package.create" in actions)
        for action, button in self.package_buttons.items():
            self.set_enabled(button, writable and package and action in package["allowed_actions"])
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain)

    def workflow_clear(self):
        self.doc, self.next_after, self.assignee_after = None, None, None
        self.reservations, self.tasks, self.packages, self.assignees, self.pack_lines = {}, {}, {}, [], []
        self.permissions, self.busy = [], False
        for table in [self.table, self.task_table, self.line_table, self.package_table]:
            table.delete(*table.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status"}:
                self.variables[name].set("")
        for selector in [self.reservation_selector, self.assignee_selector, self.pack_selector]:
            selector.configure(values=[])

    def select_document(self, event=None):
        selection = self.table.selection()
        if selection and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selection[0])

    def task_label(self, task):
        res = self.reservations[task["reservation_id"]]
        return f"{res['location_code']} · {res['sku']} · {res['lot_code'] or res['serial_code'] or '—'}"

    def task_selected(self, event=None):
        task = self.selected(self.task_table, self.tasks)
        if task and not self.busy and not self.presenter.uncertain:
            self.variables["quantity"].set(task["target_quantity"] or "")
            for field in self.scan_entries:
                self.variables[field].set("")
        self.enable()

    def workflow_loaded(self, action, result, permissions):
        self.permissions, self.busy = permissions, False
        if action == "fulfillment":
            self.next_after = result["next_after"]
            self.table.delete(*self.table.get_children())
            for row in result["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["number"], row["status"], row["version"]))
        elif action == "assignees":
            self.assignees, self.assignee_after = result["items"], result["next_after"]
            self.variables["assignee"].set("")
            self.assignee_selector.configure(values=[r["display_name"] for r in self.assignees])
            if self.assignees:
                self.assignee_selector.current(0)
        else:
            self.doc = result
            self.reservations = {r["id"]: r for r in result["reservations"]}
            self.tasks = {r["id"]: r for r in result["tasks"]}
            self.packages = {r["id"]: r for r in result["packages"]}
            self.pack_lines = []
            self.line_table.delete(*self.line_table.get_children())
            self.variables["detail"].set(f"{result['number']} · {result['status']} · v{result['version']}")
            self.variables["reason"].set("")
            for name in ["reservation", "pack_task", "location_code", "item_code", "trace_code"]:
                self.variables[name].set("")
            self.reservation_selector.configure(values=[f"{r['sku']} · {r['location_code']} · {r['lot_code'] or r['serial_code'] or '—'} · còn {r['remaining_base']}" for r in self.reservations.values()])
            self.pack_selector.configure(values=[f"{self.task_label(r)} · chưa đóng {r['unpacked_base']}" for r in self.tasks.values()])
            for table in [self.task_table, self.package_table]:
                table.delete(*table.get_children())
            for row in self.tasks.values():
                self.task_table.insert("", "end", iid=row["id"], values=(self.task_label(row), row["assignee_name"],
                    f"{row['target_quantity'] or '?'} / {row['picked_quantity']} / {row['consumed_quantity']}", f"{row['status']} · v{row['version']}"))
            from decimal import Decimal
            for row in self.packages.values():
                quantity = sum(Decimal(line["quantity"]) for line in row["lines"])
                consumed = sum(Decimal(line["consumed_quantity"]) for line in row["lines"])
                self.package_table.insert("", "end", iid=row["id"], values=(row["code"], f"{row['status'] or 'Cũ'} · v{row['version']}", f"{quantity} / {consumed}"))
            self.assignees, self.assignee_after = [], None
            self.assignee_selector.configure(values=[])
            self.variables["assignee"].set("")
        self.variables["status"].set("Đã tải dữ liệu." + (" Còn trang sau." if result.get("next_after") else ""))
        self.enable()

    def workflow_saved(self, result):
        self.busy = False
        self.presenter.read(result["id"])

    def scan(self, field, code):
        """B18 hook: explicit field, no quantity increments or local confirmation."""
        if field not in self.scan_entries or not self.doc or self.busy or self.presenter.uncertain:
            return False
        self.variables[field].set(code)
        return True

    def confirm_pick(self):
        return self.action("pick", "confirm")

    def add_line(self):
        index = self.pack_selector.current()
        if index < 0 or self.busy or self.presenter.uncertain:
            return
        task = list(self.tasks.values())[index]
        self.pack_lines.append(dict(pick_task_id=task["id"], quantity_base=self.variables["pack_quantity"].get()))
        self.render_lines()

    def remove_line(self):
        selected = self.line_table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.pack_lines.pop(int(selected[0]))
            self.render_lines()

    def render_lines(self):
        self.line_table.delete(*self.line_table.get_children())
        for index, row in enumerate(self.pack_lines):
            self.line_table.insert("", "end", iid=str(index), values=(self.task_label(self.tasks[row["pick_task_id"]]), row["quantity_base"]))

    def action(self, kind, action):
        if not self.doc or self.busy or self.presenter.uncertain:
            return False
        try:
            body = dict(expected_version=self.doc["version"], reason=self.variables["reason"].get())
            path = f"fulfillment/{self.doc['id']}/" + ("picks" if kind == "pick" else "packages")
            if action == "create" and kind == "pick":
                res, user = self.reservation_selector.current(), self.assignee_selector.current()
                if res < 0 or user < 0:
                    raise ValueError("Select reservation and picker")
                body.update(reservation_id=list(self.reservations)[res], assigned_to=self.assignees[user]["id"], quantity_base=self.variables["quantity"].get())
                model = PickCreate
            elif action == "create":
                body.update(code=self.variables["package_code"].get(), lines=self.pack_lines)
                model = PackageCreate
            else:
                entity = self.selected(self.task_table, self.tasks) if kind == "pick" else self.selected(self.package_table, self.packages)
                if not entity or action not in entity["allowed_actions"]:
                    raise ValueError("Select an eligible task/package")
                path += f"/{entity['id']}/{action}"
                body["entity_version"] = entity["version"]
                model = FulfillmentAction
                if action == "assign":
                    index = self.assignee_selector.current()
                    if index < 0:
                        raise ValueError("Select picker")
                    body["assigned_to"] = self.assignees[index]["id"]
                    model = PickAssign
                elif action == "confirm":
                    body.update(quantity_base=self.variables["quantity"].get(), location_code=self.variables["location_code"].get(),
                                item_code=self.variables["item_code"].get(), trace_code=self.variables["trace_code"].get().strip() or None)
                    model = PickConfirm
            return self.presenter.command("POST", path, model.model_validate(body).model_dump(mode="json"))
        except (ValueError, TypeError, IndexError):
            self.workflow_error("Chọn đúng nguồn/người soạn/nhiệm vụ/kiện; nhập mã quét, lượng cơ sở và lý do hợp lệ.")
            return False
