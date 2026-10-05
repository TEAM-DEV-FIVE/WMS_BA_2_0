from datetime import date
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.transfers import POST_ACTIONS, TransferPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.transfers import TransferInput, TransferUpdate


class TransferView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, TransferPresenter)
        self.doc = None
        self.lines, self.stock, self.locations, self.users = [], [], [], []
        self.cursors = {}
        self.load_button = ttk.Button(self.top, text="Tải lệnh chuyển", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(
            self.top,
            text="Trang sau",
            command=lambda: self.presenter.load(after=self.cursors.get("transfers")),
        )
        self.next_button.pack(side="left", padx=4)
        self.new_button = ttk.Button(self.top, text="Lệnh mới", command=self.new)
        self.new_button.pack(side="left")
        self.table = self.tree(
            self, ["number", "status"], ["Lệnh chuyển", "Trạng thái"], [470, 200], height=2
        )
        self.table.bind("<<TreeviewSelect>>", lambda event: self.select())
        ttk.Label(self, textvariable=self.variables["detail"], wraplength=810).pack(fill="x")
        tabs = self.tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, pady=4)
        self.pages = {}
        for key, title in [
            ("draft", "Kế hoạch"),
            ("arrival", "Nhận / thiếu"),
            ("loss", "Điều chỉnh mất"),
            ("history", "Lịch sử"),
            ("assign", "Phân công"),
        ]:
            page = self.pages[key] = ttk.Frame(tabs, padding=6)
            tabs.add(page, text=title)
        draft = self.pages["draft"]
        row = ttk.Frame(draft)
        row.pack(fill="x")
        ttk.Label(row, text="Kho đích").pack(side="left")
        self.destination_selector = self.combo(row, "destination", 28)
        self.destination_selector.pack(side="left", padx=4)
        ttk.Label(row, text="Ngày").pack(side="left")
        self.day_entry = ttk.Entry(row, textvariable=self.variable("day", date.today().isoformat()), width=12)
        self.day_entry.pack(side="left", padx=4)
        ttk.Button(row, text="Tải tồn nguồn", command=self.load_stock).pack(side="left")
        ttk.Button(
            row,
            text="Tồn tiếp",
            command=lambda: self.load_stock(True),
        ).pack(side="left", padx=4)
        row = ttk.Frame(draft)
        row.pack(fill="x", pady=4)
        self.stock_selector = self.combo(row, "stock", 67)
        self.stock_selector.pack(side="left", fill="x", expand=True)
        self.quantity_entry = ttk.Entry(row, textvariable=self.variable("quantity", "1"), width=9)
        self.quantity_entry.pack(side="left", padx=4)
        self.add_button = ttk.Button(row, text="Thêm", command=self.add_line)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(row, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left", padx=4)
        self.line_table = self.tree(
            draft,
            ["stock", "source", "quantity"],
            ["SKU / chủ / lô-serial", "Nguồn", "SL cơ sở"],
            [420, 190, 100],
            height=4,
        )
        arrival = self.pages["arrival"]
        self.source_selector = self.combo(arrival, "source", 92)
        self.source_selector.pack(fill="x")
        row = ttk.Frame(arrival)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Vị trí kho đích", command=self.load_locations).pack(side="left")
        ttk.Button(row, text="Vị trí tiếp", command=lambda: self.load_locations(True)).pack(
            side="left", padx=4
        )
        self.location_selector = self.combo(row, "location", 40)
        self.location_selector.pack(side="left", fill="x", expand=True)
        row = ttk.Frame(arrival)
        row.pack(fill="x", pady=4)
        for label, key, value in [
            ("Số thực nhận", "received", "18"),
            ("Ngày nhận", "receive_day", date.today().isoformat()),
        ]:
            ttk.Label(row, text=label).pack(side="left")
            ttk.Entry(row, textvariable=self.variable(key, value), width=12).pack(side="left", padx=4)
        self.condition_selector = self.combo(row, "condition", 16)
        self.condition_selector.configure(values=["Hàng tốt", "Hư hỏng"])
        self.condition_selector.current(0)
        self.condition_selector.pack(side="left")
        self.receive_button = ttk.Button(
            row, text="Nhận dòng đã chọn", command=lambda: self.action("receive")
        )
        self.receive_button.pack(side="left", padx=4)
        row = ttk.Frame(arrival)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Lượng chưa nhận").pack(side="left")
        ttk.Entry(row, textvariable=self.variable("missing", "2"), width=12).pack(side="left", padx=4)
        self.discrepancy_button = ttk.Button(
            row, text="Ghi biên bản thiếu", command=lambda: self.action("discrepancy")
        )
        self.discrepancy_button.pack(side="left")
        ttk.Label(
            arrival, text="Phần chưa nhận giữ ở transit. Hàng hỏng phải vào vị trí cách ly.", wraplength=760
        ).pack(anchor="w", pady=6)
        self.evidence_table = self.tree(
            arrival, ["kind", "qty", "evidence"], ["Biên bản", "SL", "Chứng cứ"], [120, 100, 500], height=2
        )
        loss = self.pages["loss"]
        ttk.Label(loss, text="Chọn biên bản thiếu, lập phiếu riêng và gửi kiểm soát duyệt.").pack(anchor="w")
        evidence_bar = ttk.Frame(loss)
        evidence_bar.pack(fill="x")
        for label, resource, next_page in [
            ("Tải biên bản", "discrepancies", False),
            ("Biên bản tiếp", "discrepancies", True),
            ("Tải điều chỉnh", "adjustments", False),
            ("Điều chỉnh tiếp", "adjustments", True),
        ]:
            ttk.Button(
                evidence_bar, text=label, command=lambda r=resource, n=next_page: self.load_related(r, n)
            ).pack(side="left", padx=(0, 4))
        self.evidence_selector = self.combo(loss, "loss_evidence", 90)
        self.evidence_selector.pack(fill="x", pady=4)
        row = ttk.Frame(loss)
        row.pack(fill="x")
        ttk.Label(row, text="Lượng mất xác minh").pack(side="left")
        ttk.Entry(row, textvariable=self.variable("loss_qty", "2"), width=12).pack(side="left", padx=4)
        ttk.Label(row, text="Ngày điều chỉnh").pack(side="left")
        ttk.Entry(row, textvariable=self.variable("loss_day", date.today().isoformat()), width=12).pack(
            side="left", padx=4
        )
        self.loss_button = ttk.Button(row, text="Lập điều chỉnh", command=lambda: self.action("loss"))
        self.loss_button.pack(side="left")
        self.parent_button = ttk.Button(row, text="Về lệnh chuyển", command=self.back)
        self.parent_button.pack(side="left", padx=4)
        self.adjustment_table = self.tree(
            loss, ["number", "status"], ["Phiếu điều chỉnh", "Trạng thái"], [440, 220], height=3
        )
        self.adjustment_table.bind("<<TreeviewSelect>>", lambda event: self.select_loss())
        history = self.pages["history"]
        row = ttk.Frame(history)
        row.pack(fill="x")
        ttk.Button(row, text="Tải lịch sử", command=self.history).pack(side="left")
        ttk.Button(row, text="Trang tiếp", command=lambda: self.history(True)).pack(side="left", padx=4)
        self.history_table = self.tree(
            history,
            ["op", "qty", "destination", "evidence", "at"],
            ["Thao tác", "SL", "Đích", "Chứng cứ", "Thời điểm"],
            [105, 75, 130, 260, 175],
            height=5,
        )
        assign = self.pages["assign"]
        ttk.Button(assign, text="Tải nhân viên hai kho", command=self.load_users).pack(anchor="w")
        ttk.Button(assign, text="Nhân viên tiếp", command=lambda: self.load_users(True)).pack(anchor="w")
        self.user_selector = self.combo(assign, "user", 70)
        self.user_selector.pack(fill="x", pady=4)
        self.assign_button = ttk.Button(
            assign, text="Thêm người được giao", command=lambda: self.action("assign")
        )
        self.assign_button.pack(anchor="w")
        ttk.Label(
            assign,
            text="Phân công trước khi gửi duyệt. Người được giao vẫn chỉ thao tác theo quyền kho của mình.",
            wraplength=760,
        ).pack(anchor="w", pady=8)
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Chứng cứ giao/nhận").pack(side="left")
        self.evidence_entry = ttk.Entry(row, textvariable=self.variable("evidence"))
        self.evidence_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.reason_form()
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.buttons = {}
        for action, label in [
            ("save", "Lưu nháp"),
            ("submit", "Gửi duyệt"),
            ("approve", "Duyệt"),
            ("reject", "Từ chối"),
            ("revise", "Sửa lại"),
            ("cancel", "Hủy"),
            ("dispatch", "Xuất toàn phiếu"),
            ("post", "Ghi điều chỉnh"),
        ]:
            widget = ttk.Button(row, text=label, command=lambda a=action: self.action(a))
            widget.pack(side="left", padx=(0, 3))
            self.buttons[action] = widget
        self.retry_form(operation=True)
        self.session_changed()

        from apps.desktop.scanner.widget import ScanBar
        self.scan_bar = ScanBar(self, self, "TRANSFER")
        self.scan_bar.pack(fill="x", pady=3, before=self.winfo_children()[0])

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        allowed = self.doc["allowed_actions"] if self.doc else []
        editable = writable and ("edit" in allowed if self.doc else "transfer.draft" in self.permissions)
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.cursors.get("transfers"))
        self.set_enabled(self.new_button, writable and "transfer.draft" in self.permissions)
        for widget in [
            self.destination_selector,
            self.stock_selector,
            self.quantity_entry,
            self.add_button,
            self.remove_button,
            self.day_entry,
        ]:
            self.set_enabled(widget, editable)
        for action, widget in self.buttons.items():
            self.set_enabled(widget, editable if action == "save" else writable and action in allowed)
        for action, widget in [
            ("receive", self.receive_button),
            ("discrepancy", self.discrepancy_button),
            ("loss", self.loss_button),
            ("assign", self.assign_button),
        ]:
            self.set_enabled(widget, writable and action in allowed)
        self.set_enabled(self.parent_button, free and self.doc and self.doc["source_transfer_id"])
        self.set_enabled(self.reason_entry, writable)
        self.set_enabled(self.evidence_entry, writable)
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(
            self.operation_button,
            free and self.presenter.uncertain and self.presenter.uncertain[1].split("/")[-1] in POST_ACTIONS,
        )

    def session_changed(self, user=None, warehouses=None):
        super().session_changed(user, warehouses)
        self.destination_selector.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])

    def workflow_clear(self):
        self.doc = None
        self.lines = []
        self.stock = []
        self.locations = []
        self.users = []
        self.permissions = []
        self.cursors = {}
        self.busy = False
        for table in [
            self.table,
            self.line_table,
            self.evidence_table,
            self.adjustment_table,
            self.history_table,
        ]:
            table.delete(*table.get_children())
        for name, var in self.variables.items():
            if name not in {"warehouse", "status"}:
                var.set("")
        for combo in [
            self.stock_selector,
            self.location_selector,
            self.source_selector,
            self.evidence_selector,
            self.user_selector,
        ]:
            combo.configure(values=[])

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc = None
        self.lines = []
        self.line_table.delete(*self.line_table.get_children())
        self.variable("day").set(date.today().isoformat())
        self.tabs.select(self.pages["draft"])
        self.enable()

    def select(self):
        ids = self.table.selection()
        if ids:
            self.presenter.read(ids[0])

    def select_loss(self):
        ids = self.adjustment_table.selection()
        if ids:
            self.presenter.read(ids[0])

    def back(self):
        if self.doc and self.doc["source_transfer_id"]:
            self.presenter.read(self.doc["source_transfer_id"])

    def load_locations(self, next_page=False):
        if self.doc:
            self.presenter.load(
                "transfers/locations",
                self.cursors.get("transfers/locations") if next_page else None,
                self.doc["destination_warehouse_id"],
            )

    def load_stock(self, next_page=False):
        self.presenter.load(
            "transfers/stock",
            self.cursors.get("transfers/stock") if next_page else None,
            self.doc["warehouse_id"] if self.doc else None,
        )

    def history(self, next_page=False):
        if self.doc:
            self.presenter.history(
                self.doc["source_transfer_id"] or self.doc["id"],
                self.cursors.get("history") if next_page else None,
            )

    def load_related(self, resource, next_page=False):
        if self.doc:
            path = f"transfers/{self.doc['source_transfer_id'] or self.doc['id']}/{resource}?limit=50"
            if next_page and self.cursors.get(resource):
                path += "&after=" + self.cursors[resource]
            self.presenter.submit(resource, "GET", path)

    def load_users(self, next_page=False):
        if self.doc:
            path = f"transfers/{self.doc['id']}/assignees"
            if next_page and self.cursors.get("users"):
                path += "?after=" + self.cursors["users"]
            self.presenter.submit("users", "GET", path)

    def add_line(self):
        index = self.stock_selector.current()
        if index < 0:
            return
        stock = self.stock[index]
        self.lines.append(
            dict(
                stock_item_id=stock["stock_item_id"],
                source_location_id=stock["source_location_id"],
                quantity_base=self.variable("quantity").get(),
                label=f"{stock['sku']} / {stock['owner_code']} / {stock['lot_code'] or stock['serial_code'] or '—'}",
                source=stock["source_code"],
            )
        )
        self.render_lines()

    def remove_line(self):
        ids = self.line_table.selection()
        if ids:
            del self.lines[int(ids[0])]
            self.render_lines()

    def render_lines(self):
        self.line_table.delete(*self.line_table.get_children())
        for i, line in enumerate(self.lines):
            self.line_table.insert(
                "", "end", iid=str(i), values=(line["label"], line["source"], line["quantity_base"])
            )

    def action(self, action):
        try:
            reason = self.variable("reason").get()
            if action == "save":
                dest = self.destination_selector.current()
                if dest < 0:
                    raise ValueError("Chọn kho đích.")
                payload = dict(
                    warehouse_id=self.doc["warehouse_id"] if self.doc else self.warehouse_id(),
                    destination_warehouse_id=str(self.warehouses[dest].id),
                    business_date=self.variable("day").get(),
                    reason=reason,
                    lines=[
                        {k: r[k] for k in ["stock_item_id", "source_location_id", "quantity_base"]}
                        for r in self.lines
                    ],
                )
                if self.doc:
                    payload["expected_version"] = self.doc["version"]
                payload = (
                    (TransferUpdate if self.doc else TransferInput)
                    .model_validate(payload)
                    .model_dump(mode="json")
                )
                self.presenter.command(
                    "PUT" if self.doc else "POST",
                    "transfers/" + self.doc["id"] if self.doc else "transfers",
                    payload,
                )
                return
            if not self.doc:
                return
            payload = dict(expected_version=self.doc["version"], reason=reason)
            if action in {"approve", "reject"}:
                req = next(r for r in reversed(self.doc["approvals"]) if r["status"] == "PENDING")
                self.presenter.command(
                    "POST",
                    f"approval-requests/{req['id']}/decide",
                    {**payload, "decision": "APPROVE" if action == "approve" else "REJECT"},
                )
                return
            if action == "assign":
                index = self.user_selector.current()
                if index < 0:
                    raise ValueError("Chọn nhân viên.")
                users = list(dict.fromkeys([*self.doc["assigned_user_ids"], self.users[index]["id"]]))
                self.presenter.command(
                    "POST", f"documents/{self.doc['id']}/assignments", {**payload, "user_ids": users}
                )
                return
            if action in {"submit", "revise", "cancel"}:
                self.presenter.command("POST", f"documents/{self.doc['id']}/{action}", payload)
                return
            path = f"transfers/{self.doc['id']}/"
            if action in {"dispatch", "post", "receive"}:
                payload.update(execution_key=str(uuid4()), evidence_ref=self.variable("evidence").get())
                path += "loss-post" if action == "post" else action
                if action == "receive":
                    source = self.source_selector.current()
                    destination = self.location_selector.current()
                    if source < 0 or destination < 0:
                        raise ValueError("Chọn dòng đang vận chuyển và vị trí nhận.")
                    payload.update(
                        business_date=self.variable("receive_day").get(),
                        lines=[
                            dict(
                                dispatch_move_id=self.doc["sources"][source]["dispatch_move_id"],
                                destination_location_id=self.locations[destination]["id"],
                                quantity_base=self.variable("received").get(),
                                disposition="DAMAGED" if self.condition_selector.current() == 1 else "GOOD",
                            )
                        ],
                    )
            elif action == "discrepancy":
                source = self.source_selector.current()
                if source < 0:
                    raise ValueError("Chọn dòng đang vận chuyển.")
                path += "discrepancies"
                payload.update(
                    dispatch_move_id=self.doc["sources"][source]["dispatch_move_id"],
                    kind="MISSING",
                    quantity_base=self.variable("missing").get(),
                    evidence_ref=self.variable("evidence").get(),
                )
            elif action == "loss":
                index = self.evidence_selector.current()
                if index < 0:
                    raise ValueError("Chọn biên bản thiếu.")
                path += "adjustments"
                payload.update(
                    discrepancy_id=self.doc["discrepancies"][index]["id"],
                    quantity_base=self.variable("loss_qty").get(),
                    business_date=self.variable("loss_day").get(),
                )
            self.presenter.command("POST", path, payload)
        except Exception as exc:
            self.workflow_error(str(exc))

    def workflow_saved(self, data):
        self.busy = False
        self.variables["status"].set("Máy chủ đã xác nhận. Đang tải lại chứng từ.")
        self.presenter.read(data["id"])

    def workflow_loaded(self, action, data, permissions):
        self.busy = False
        self.permissions = permissions
        if isinstance(data, dict) and "next_after" in data:
            self.cursors[action] = data["next_after"]
        if action == "transfers":
            self.table.delete(*self.table.get_children())
            for row in data["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["number"], row["status"]))
        elif action == "transfers/stock":
            self.stock = data["items"]
            self.stock_selector.configure(
                values=[
                    f"{r['sku']} · {r['owner_code']} · {r['lot_code'] or r['serial_code'] or '—'} · {r['source_code']} · khả dụng {r['available_base']}"
                    for r in self.stock
                ]
            )
        elif action == "transfers/locations":
            self.locations = data["items"]
            self.location_selector.configure(values=[f"{r['code']} · {r['kind']}" for r in self.locations])
        elif action == "users":
            self.users = data["items"]
            self.user_selector.configure(
                values=[f"{r['display_name']} ({r['username']})" for r in self.users]
            )
        elif action == "discrepancies" and self.doc:
            self.doc["discrepancies"] = data["items"]
            self.evidence_selector.configure(
                values=[f"{r['kind']} · {r['quantity_base']} · {r['evidence_ref']}" for r in data["items"]]
            )
            self.evidence_table.delete(*self.evidence_table.get_children())
            for r in data["items"]:
                self.evidence_table.insert(
                    "", "end", values=(r["kind"], r["quantity_base"], r["evidence_ref"])
                )
        elif action == "adjustments" and self.doc:
            self.doc["adjustments"] = data["items"]
            self.adjustment_table.delete(*self.adjustment_table.get_children())
            for r in data["items"]:
                self.adjustment_table.insert("", "end", iid=r["id"], values=(r["number"], r["status"]))
        elif action == "history":
            self.history_table.delete(*self.history_table.get_children())
            for r in data["items"]:
                self.history_table.insert(
                    "",
                    "end",
                    values=(
                        r["operation"] + " / " + r["disposition"],
                        r["quantity_base"],
                        r["destination_code"] or "—",
                        r["evidence_ref"],
                        r["posted_at"],
                    ),
                )
        elif action == "read":
            self.doc = data
            self.variables["detail"].set(
                f"{data['number']} · {data['status']} · phiên bản {data['version']} · {len(data['sources'])} dòng vận chuyển"
            )
            self.variable("day").set(data["business_date"])
            self.variable("receive_day").set(date.today().isoformat())
            self.variable("loss_day").set(
                data["business_date"] if data["source_transfer_id"] else date.today().isoformat()
            )
            dest = next(
                (i for i, w in enumerate(self.warehouses) if str(w.id) == data["destination_warehouse_id"]),
                -1,
            )
            if dest >= 0:
                self.destination_selector.current(dest)
            self.lines = [
                dict(
                    document_line_id=r["document_line_id"],
                    stock_item_id=r["stock_item_id"],
                    source_location_id=r["source_location_id"],
                    quantity_base=r["quantity_base"],
                    label=f"{r['sku']} / {r['owner_code']} / {r['lot_code'] or r['serial_code'] or '—'}",
                    source=r["source_code"] or "Kho nguồn",
                )
                for r in data["plan"]
            ]
            self.render_lines()
            self.source_selector.configure(
                values=[
                    f"{r['sku']} · {r['owner_code']} · {r['lot_code'] or r['serial_code'] or '—'} · gửi {r['dispatched_base']} / nhận {r['received_base']} / mất {r['lost_base']} / còn {r['remaining_base']}"
                    for r in data["sources"]
                ]
            )
            self.evidence_selector.configure(
                values=[
                    f"{r['kind']} · {r['quantity_base']} · {r['evidence_ref']}" for r in data["discrepancies"]
                ]
            )
            for table in [self.evidence_table, self.adjustment_table]:
                table.delete(*table.get_children())
            for r in data["discrepancies"]:
                self.evidence_table.insert(
                    "", "end", values=(r["kind"], r["quantity_base"], r["evidence_ref"])
                )
            for r in data["adjustments"]:
                self.adjustment_table.insert("", "end", iid=r["id"], values=(r["number"], r["status"]))
            if data["source_transfer_id"]:
                self.tabs.select(self.pages["loss"])
        self.variables["status"].set("Đã tải dữ liệu từ máy chủ.")
        self.enable()
