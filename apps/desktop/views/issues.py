import tkinter as tk
from datetime import date
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.issues import IssuePresenter
from apps.desktop.views.orders import STATUS, OrderView
from packages.contracts.issues import IssueInput, IssuePost, IssueUpdate, ReleaseInput, ReserveInput


class IssueView(ttk.Frame):
    combo, tree = OrderView.combo, OrderView.tree

    def __init__(self, parent, api):
        super().__init__(parent, padding=10)
        self.variables = {name: tk.StringVar() for name in (
            "warehouse", "source", "source_line", "day", "qty", "expiry", "reason", "status", "heading", "pending")}
        self.presenter = IssuePresenter(self, api)
        self.warehouses, self.sources, self.permissions, self.lines = [], [], [], []
        self.source_doc = self.doc = self.next_after = self.proposal = None
        self.busy = False
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.selector = self.combo(top, "warehouse", 26)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self.scope_changed)
        self.load_button = ttk.Button(top, text="Tải phiếu xuất", command=self.load)
        self.load_button.pack(side="left", padx=4)
        self.next_button = ttk.Button(top, text="Trang sau", command=lambda: self.load(self.next_after))
        self.next_button.pack(side="left")
        self.new_button = ttk.Button(top, text="Tạo từ SO", command=self.new)
        self.new_button.pack(side="right")
        ttk.Label(self, textvariable=self.variables["status"], wraplength=820).pack(fill="x", pady=3)
        self.table = self.tree(self, ["number", "status", "partner"], ["Phiếu xuất", "Trạng thái", "Khách hàng"], [240, 180, 360], 3)
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.variables["heading"]).pack(fill="x", pady=3)
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="SO nguồn").pack(side="left")
        self.source = self.combo(header, "source", 48)
        self.source.pack(side="left", padx=4)
        self.source.bind("<<ComboboxSelected>>", self.source_changed)
        ttk.Label(header, text="Ngày xuất").pack(side="left")
        self.day = ttk.Entry(header, textvariable=self.variables["day"], width=12)
        self.day.pack(side="left", padx=4)
        self.line_table = self.tree(self, ["sku", "qty", "posted", "remaining"],
                                    ["SKU / ĐVT / Chủ sở hữu", "Kế hoạch", "Đã xuất", "Còn xuất"], [390, 120, 120, 120], 3)
        self.line_table.bind("<<TreeviewSelect>>", self.line_selected)
        edit = ttk.Frame(self)
        edit.pack(fill="x", pady=3)
        self.source_line = self.combo(edit, "source_line", 42)
        self.source_line.pack(side="left")
        ttk.Label(edit, text="SL cơ sở").pack(side="left", padx=4)
        self.quantity = ttk.Entry(edit, textvariable=self.variables["qty"], width=10)
        self.quantity.pack(side="left")
        self.add_button = ttk.Button(edit, text="Thêm / đổi dòng", command=self.add_line)
        self.add_button.pack(side="left", padx=4)
        self.remove_button = ttk.Button(edit, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left")
        self.reservation_table = self.tree(self, ["stock", "location", "held", "expiry"],
            ["Giữ chỗ / đề xuất · SKU / lô / serial", "Vị trí", "Còn giữ / đề xuất", "Hạn giữ chỗ"], [310, 140, 130, 190], 3)
        self.reservation_table.bind("<<TreeviewSelect>>", self.reservation_selected)
        expiry = ttk.Frame(self)
        expiry.pack(fill="x", pady=3)
        ttk.Label(expiry, text="Hạn giữ (ISO có múi giờ, bỏ trống = không hạn)").pack(side="left")
        self.expiry = ttk.Entry(expiry, textvariable=self.variables["expiry"], width=29)
        self.expiry.pack(side="left", padx=4)
        reason = ttk.Frame(self)
        reason.pack(fill="x", pady=3)
        ttk.Label(reason, text="Lý do").pack(side="left")
        self.reason = ttk.Entry(reason, textvariable=self.variables["reason"])
        self.reason.pack(side="left", fill="x", expand=True, padx=4)
        self.buttons = {}
        for actions in (
            [("save", "Lưu nháp"), ("submit", "Gửi duyệt"), ("approve", "Duyệt"), ("reject", "Từ chối"),
             ("revise", "Sửa lại"), ("cancel", "Hủy"), ("close", "Đóng thiếu")],
            [("plan", "Đề xuất FEFO"), ("reserve", "Giữ theo đề xuất"), ("release", "Giải phóng dòng chọn"),
             ("expire", "Giải phóng hết hạn"), ("post", "Xuất dòng giữ chọn")],
        ):
            bar = ttk.Frame(self)
            bar.pack(fill="x", pady=3)
            for action, label in actions:
                button = ttk.Button(bar, text=label, command=lambda a=action: self.action(a))
                button.pack(side="left", padx=2)
                self.buttons[action] = button
        recovery = ttk.Frame(self)
        recovery.pack(fill="x", pady=3)
        self.lookup_button = ttk.Button(recovery, text="Tra ACK", command=self.presenter.lookup)
        self.lookup_button.pack(side="left")
        self.retry_button = ttk.Button(recovery, text="Gửi lại đúng lệnh", command=self.presenter.retry)
        self.retry_button.pack(side="left", padx=4)
        ttk.Label(self, textvariable=self.variables["pending"], wraplength=820).pack(fill="x")
        self.variables["status"].set("Đăng nhập để giữ hàng và xuất từ SO đã duyệt.")
        self.enable()

    def warehouse_id(self):
        index = self.selector.current()
        return str(self.warehouses[index].id) if index >= 0 else None

    def session_changed(self, user=None, warehouses=None):
        self.presenter.reset(user.id if user else None)
        self.warehouses = list(warehouses or [])
        self.selector.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])
        self.variables["warehouse"].set("")
        if self.warehouses:
            self.selector.current(0)
        self.variables["status"].set("Tải phiếu xuất theo kho." if user else "Đăng nhập để xuất hàng.")
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id)
        self.variables["status"].set("Tải lại phiếu theo kho vừa chọn.")
        self.enable()

    def orders_clear(self):
        self.doc = self.source_doc = self.proposal = self.next_after = None
        self.lines, self.sources, self.permissions = [], [], []
        self.busy = False
        for table in (self.table, self.line_table, self.reservation_table):
            table.delete(*table.get_children())
        for name, variable in self.variables.items():
            if name not in {"warehouse", "status"}:
                variable.set("")
        self.source.configure(values=[])
        self.source_line.configure(values=[])

    def editable(self):
        return bool("edit" in self.doc["allowed_actions"] if self.doc else "issue.draft" in self.permissions)

    def enable(self):
        active = bool(self.presenter.user_id and self.warehouses) and not self.busy
        safe = active and not self.presenter.uncertain
        editable = safe and self.editable()
        self.selector.state(["!disabled"] if active else ["disabled"])
        self.load_button.state(["!disabled"] if active else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        self.new_button.state(["!disabled"] if safe and "issue.draft" in self.permissions else ["disabled"])
        self.source.state(["!disabled"] if editable and not self.doc else ["disabled"])
        for widget in (self.day, self.source_line, self.add_button, self.remove_button):
            widget.state(["!disabled"] if editable else ["disabled"])
        for widget in (self.quantity, self.reason, self.expiry):
            widget.state(["!disabled"] if safe else ["disabled"])
        allowed = self.doc["allowed_actions"] if self.doc else []
        selected = self.reservation_table.selection()
        for action, button in self.buttons.items():
            enabled = editable if action == "save" else safe and action in allowed
            if action == "plan":
                enabled = enabled and bool(self.line_table.selection())
            elif action == "reserve":
                enabled = enabled and bool(self.proposal)
            elif action in {"post", "release"}:
                enabled = enabled and bool(selected) and not self.proposal
            button.state(["!disabled"] if enabled else ["disabled"])
        for widget in (self.lookup_button, self.retry_button):
            widget.state(["!disabled"] if active and self.presenter.uncertain else ["disabled"])
        pending = self.presenter.uncertain
        self.variables["pending"].set(
            f"{pending['state']} · Key {pending['key']} · Giữ cửa sổ; tra ACK hoặc gửi lại đúng lệnh."
            if pending else "Giữ hàng không giảm tồn vật lý. Chỉ ACK máy chủ xác nhận đã xuất; hàng ký gửi chưa được hỗ trợ."
        )

    def load(self, after=None):
        if self.warehouse_id():
            self.presenter.load(self.warehouse_id(), after)

    def orders_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def orders_loaded(self, page, sources, permissions, truncated):
        self.orders_clear()
        self.sources, self.permissions, self.next_after = sources, permissions, page["next_after"]
        self.source.configure(values=[f"{s['number']} · {s['partner_name']}" for s in sources])
        for doc in page["items"]:
            self.table.insert("", "end", iid=doc["id"], values=(doc["number"], STATUS[doc["status"]], doc["partner_name"]))
        self.variables["status"].set("Đã tải phiếu xuất. " + ("Danh sách SO giới hạn 100 phiếu mỗi trạng thái." if truncated else "Chọn SO đã duyệt để tạo phiếu."))
        self.enable()

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc = self.source_doc = self.proposal = None
        self.lines = []
        self.variables["source"].set("")
        self.variables["heading"].set("Phiếu xuất mới · Hàng doanh nghiệp")
        self.variables["day"].set(date.today().isoformat())
        self.variables["reason"].set("")
        self.source_line.configure(values=[])
        self.render()
        self.enable()

    def select(self, event=None):
        selection = self.table.selection()
        if selection and not self.busy:
            self.presenter.read(selection[0])

    def source_changed(self, event=None):
        index = self.source.current()
        if index >= 0 and not self.doc:
            self.presenter.source(self.sources[index]["id"])

    def source_loaded(self, source):
        self.busy = False
        self.source_doc = source
        self.source_line.configure(values=[f"{line['line_no']}. {line['sku']} · còn {line['remaining_base']} {line['base_uom_code']}"
                                           for line in source["lines"]])
        if source["lines"]:
            self.source_line.current(0)
        self.variables["status"].set("Đã đọc SO nguồn. Chọn dòng và số lượng cơ sở.")
        self.enable()

    def add_line(self):
        try:
            if not self.editable() or not self.source_doc or self.source_line.current() < 0:
                return
            parent = self.source_doc["lines"][self.source_line.current()]
            raw = dict(source_line_id=parent["id"], quantity_base=self.variables["qty"].get().strip())
            from packages.contracts.issues import IssueLineInput
            IssueLineInput.model_validate(raw)
            row = {**raw, "sku": parent["sku"], "base_uom_code": parent["base_uom_code"], "owner_code": parent["owner_code"]}
            existing = next((i for i, line in enumerate(self.lines) if line["source_line_id"] == parent["id"]), None)
            if existing is None:
                self.lines.append(row)
            else:
                self.lines[existing] = row
            self.render()
        except Exception:
            self.orders_error("Nhập số lượng dương dạng thập phân, không dùng dấu phẩy.")

    def remove_line(self):
        selection = self.line_table.selection()
        if selection and self.editable():
            self.lines.pop(int(selection[0]))
            self.render()

    def line_selected(self, event=None):
        selection = self.line_table.selection()
        if selection:
            line = self.lines[int(selection[0])]
            self.variables["qty"].set(line.get("remaining_base", line["quantity_base"]))
        self.enable()

    def reservation_selected(self, event=None):
        selected = self.reservation_table.selection()
        if selected and self.doc and not self.proposal:
            row = next((r for r in self.doc["reservations"] if r["id"] == selected[0]), None)
            if row:
                self.variables["qty"].set(row["remaining_base"])
        self.enable()

    def render(self):
        self.line_table.delete(*self.line_table.get_children())
        for index, line in enumerate(self.lines):
            self.line_table.insert("", "end", iid=str(index), values=(
                f"{line['sku']} / {line['base_uom_code']} / {line.get('owner_code', 'COMPANY')}",
                line["quantity_base"], line.get("posted_base", "0"), line.get("remaining_base", line["quantity_base"])))
        self.reservation_table.delete(*self.reservation_table.get_children())
        rows = self.proposal["lines"] if self.proposal else (self.doc["reservations"] if self.doc else [])
        for index, row in enumerate(rows):
            self.reservation_table.insert("", "end", iid=f"proposal-{index}" if self.proposal else row["id"], values=(
                f"{'Đề xuất · ' if self.proposal else ''}{row['sku']} / {row['lot_code'] or row['serial_code'] or '—'}",
                row["location_code"], row["quantity_base"] if self.proposal else row["remaining_base"],
                (str(row.get("expires_on") or "") if self.proposal else ("HẾT HẠN · " if row["expired"] else "") + str(row["expires_at"] or "—")),
            ))

    def orders_read(self, doc):
        self.busy = False
        self.doc, self.proposal, self.source_doc = doc, None, None
        self.lines = [{**line, "document_line_id": line["id"], "source_line_id": doc["source_line_ids"][line["id"]],
                       "quantity_base": line["base_quantity"]} for line in doc["lines"]]
        self.variables["source"].set(doc["source_order_id"])
        self.variables["day"].set(doc["business_date"])
        self.variables["heading"].set(f"{doc['number']} · {STATUS[doc['status']]} · phiên bản {doc['version']}")
        self.variables["status"].set("Đã tải phiếu và chi tiết giữ chỗ. Chọn dòng phiếu để đề xuất, hoặc dòng giữ để xuất.")
        self.render()
        self.enable()
        if "edit" in doc["allowed_actions"]:
            self.presenter.source(doc["source_order_id"])

    def plan_loaded(self, proposal):
        self.busy = False
        self.proposal = proposal
        self.render()
        self.variables["status"].set("Kiểm tra nguồn/lô/serial và lượng đề xuất, rồi bấm Giữ theo đề xuất để xác nhận.")
        self.enable()

    def orders_saved(self, result):
        self.busy = False
        self.variables["status"].set("Máy chủ đã xác nhận thao tác.")
        self.presenter.read(result["id"])

    def orders_error(self, message):
        self.busy = False
        self.proposal = None
        self.variables["status"].set(message)
        self.render()
        self.enable()

    def action(self, action):
        try:
            if self.busy or self.presenter.uncertain:
                return
            reason = self.variables["reason"].get().strip()
            if action == "save":
                if not self.source_doc:
                    raise ValueError("Chọn SO nguồn.")
                body = dict(source_order_id=self.source_doc["id"], business_date=self.variables["day"].get(), reason=reason,
                            lines=[{k: line[k] for k in ("source_line_id", "quantity_base")} for line in self.lines])
                if self.doc:
                    body["expected_version"] = self.doc["version"]
                model = IssueUpdate if self.doc else IssueInput
                body = model.model_validate(body).model_dump(mode="json")
                self.presenter.command("PUT" if self.doc else "POST", "issues/" + self.doc["id"] if self.doc else "issues", body)
                return
            if not self.doc:
                return
            body = dict(expected_version=self.doc["version"], reason=reason)
            qty = self.variables["qty"].get().strip()
            if action == "plan":
                line = self.lines[int(self.line_table.selection()[0])]
                self.presenter.plan(self.doc["id"], line["document_line_id"], qty)
                return
            if action == "reserve":
                body["expected_version"] = self.proposal["version"]
                body["lines"] = [{k: row[k] for k in ("document_line_id", "stock_item_id", "location_id", "quantity_base")}
                                 for row in self.proposal["lines"]]
                body["expires_at"] = self.variables["expiry"].get().strip() or None
                body = ReserveInput.model_validate(body).model_dump(mode="json")
            elif action in {"post", "release"}:
                body["lines"] = [dict(reservation_id=self.reservation_table.selection()[0], quantity_base=qty)]
                if action == "post":
                    body["execution_key"] = str(uuid4())
                body = (IssuePost if action == "post" else ReleaseInput).model_validate(body).model_dump(mode="json")
            if action in {"reserve", "release", "expire", "post"}:
                path = f"issues/{self.doc['id']}/" + ("post" if action == "post" else "reservations/" + action)
            elif action in {"approve", "reject"}:
                approval = next(a for a in self.doc["approvals"] if a["can_decide"])
                body["decision"] = "APPROVE" if action == "approve" else "REJECT"
                path = f"approval-requests/{approval['id']}/decide"
            else:
                path = f"documents/{self.doc['id']}/{action}"
            self.presenter.command("POST", path, body)
        except Exception:
            self.orders_error("Kiểm tra dòng được chọn, số lượng, ngày và lý do; hạn giữ cần kèm múi giờ.")

    def release_variables(self):
        self.variables.clear()
