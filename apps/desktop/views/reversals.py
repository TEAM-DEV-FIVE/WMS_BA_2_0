from datetime import date
from tkinter import messagebox, ttk
from uuid import uuid4

from apps.desktop.presenters.reversals import ReversalPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.orders import DecisionInput, OrderAction
from packages.contracts.reversals import ReversalInput, ReversalPost, ReversalUpdate


class ReversalView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, ReversalPresenter, scrollable=True)
        self.doc, self.preview_data = None, None
        self.sources, self.cursors, self.buttons = [], {"reversals": None, "reversals/sources": None}, {}
        for action, label, command in [("load", "Tải phiếu", self.presenter.load),
            ("next", "Phiếu tiếp", lambda: self.presenter.load(after=self.cursors["reversals"])),
            ("new", "Phiếu mới", self.new)]:
            self.buttons[action] = ttk.Button(self.top, text=label, command=command)
            self.buttons[action].pack(side="left", padx=3)
        self.table = self.tree(self.content, ["number", "status", "version"], ["Phiếu đảo", "Trạng thái", "Phiên bản"], [340, 220, 100])
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self.content, textvariable=self.variables["detail"], wraplength=680).pack(fill="x", pady=4)
        refs = ttk.Frame(self.content)
        refs.pack(fill="x")
        for action, label, more in [("sources", "Tải lần ghi sổ gốc", False), ("sources_next", "Nguồn tiếp", True)]:
            self.buttons[action] = ttk.Button(refs, text=label, command=lambda m=more: self.presenter.load("reversals/sources", self.cursors["reversals/sources"] if m else None))
            self.buttons[action].pack(side="left", padx=3)
        self.source_selector = self.combo(self.content, "source", 60)
        self.source_selector.pack(fill="x", pady=4)
        self.source_selector.bind("<<ComboboxSelected>>", self.source_changed)
        dates = ttk.Frame(self.content)
        dates.pack(fill="x")
        ttk.Label(dates, text="Ngày đảo (YYYY-MM-DD)").pack(side="left")
        self.day_entry = ttk.Entry(dates, textvariable=self.variable("day"), width=14)
        self.day_entry.pack(side="left", padx=5)
        self.buttons["preview"] = ttk.Button(dates, text="Xem trước ảnh hưởng", command=self.preview)
        self.buttons["preview"].pack(side="left")
        self.plan = self.tree(self.content, ["sku", "owner", "trace", "source", "destination", "qty"],
            ["SKU", "Chủ hàng", "Lô / serial", "Lấy từ", "Trả về", "Lượng cơ sở"], [100, 130, 130, 100, 100, 110])
        self.effects = self.tree(self.content, ["stock", "location", "before", "reserved", "delta", "after"],
            ["Danh tính tồn", "Vị trí", "Hiện tại", "Giữ chỗ", "Thay đổi", "Sau đảo"], [210, 100, 90, 90, 90, 100])
        self.reason_form()
        actions = ttk.Frame(self.content)
        actions.pack(fill="x")
        for index, (action, title) in enumerate([("save", "Lưu nháp"), ("submit", "Gửi duyệt"), ("approve", "Duyệt"),
            ("reject", "Từ chối"), ("revise", "Sửa lại"), ("cancel", "Hủy"), ("post", "Ghi sổ đảo")]):
            self.buttons[action] = ttk.Button(actions, text=title, command=lambda a=action: self.action(a))
            self.buttons[action].grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
        self.history = self.tree(self.content, ["revision", "step", "decision", "actor", "reason"],
            ["Phiên duyệt", "Bước", "Kết quả", "Người duyệt", "Ý kiến"], [110, 60, 100, 130, 250])
        self.retry_form(operation=True)
        self.operation_button.configure(text="Tra ACK yêu cầu")
        self.session_changed()

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        allowed = self.doc["allowed_actions"] if self.doc else []
        editable = writable and ("edit" in allowed if self.doc else "adjustment.draft" in self.permissions)
        for action, button in self.buttons.items():
            enabled = free if action == "load" else writable if action in {"new", "sources", "preview"} else (
                free and self.cursors["reversals"] if action == "next" else
                writable and self.cursors["reversals/sources"] if action == "sources_next" else
                editable and self.preview_data and self.preview_data["eligible"] if action == "save" else
                writable and action in allowed)
            self.set_enabled(button, enabled)
        self.set_enabled(self.selector, free)
        self.set_enabled(self.source_selector, editable and not self.doc)
        self.set_enabled(self.day_entry, editable)
        self.set_enabled(self.reason_entry, writable)
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain)

    def workflow_clear(self):
        self.doc, self.preview_data, self.sources, self.permissions = None, None, [], []
        self.cursors = {"reversals": None, "reversals/sources": None}
        self.busy = False
        for table in [self.table, self.plan, self.effects, self.history]:
            table.delete(*table.get_children())
        self.source_selector.configure(values=[])
        for name in ["source", "detail", "reason", "day"]:
            self.variables[name].set("")

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc, self.preview_data = None, None
        for table in [self.plan, self.effects, self.history]:
            table.delete(*table.get_children())
        self.variables["day"].set(date.today().isoformat())
        self.variables["reason"].set("")
        self.variables["detail"].set("Chọn một lần ghi sổ gốc và xem trước toàn bộ ảnh hưởng.")
        self.enable()

    def source_changed(self, event=None):
        self.preview_data = None
        self.plan.delete(*self.plan.get_children())
        self.effects.delete(*self.effects.get_children())
        self.enable()

    def preview(self):
        try:
            day = date.fromisoformat(self.variables["day"].get()).isoformat()
            source = self.doc["source_transaction_id"] if self.doc else self.sources[self.source_selector.current()]["id"] if self.source_selector.current() >= 0 else None
            if not source:
                raise ValueError()
            self.presenter.preview(source, day)
        except (ValueError, IndexError):
            self.workflow_error("Chọn nguồn và nhập ngày đảo YYYY-MM-DD.")

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def action(self, action):
        if self.busy or self.presenter.uncertain:
            return
        try:
            reason = self.variables["reason"].get()
            if action == "save":
                p = self.preview_data
                if not p or not p["eligible"] or p["business_date"] != self.variables["day"].get():
                    return self.workflow_error("Xem trước lại đúng nguồn và ngày trước khi lưu nháp.")
                fields = dict(source_transaction_id=p["source"]["id"], source_version=p["source"]["source_version"], business_date=p["business_date"], reason=reason)
                body = ReversalUpdate(**fields, expected_version=self.doc["version"]) if self.doc else ReversalInput(**fields)
                method, path = ("PUT", "reversals/" + self.doc["id"]) if self.doc else ("POST", "reversals")
            else:
                if not self.doc:
                    return
                fields = dict(expected_version=self.doc["version"], reason=reason)
                method, path = "POST", f"documents/{self.doc['id']}/{action}"
                if action in {"approve", "reject"}:
                    approval = next(r for r in self.doc["approvals"] if r["can_decide"])
                    path = f"approval-requests/{approval['id']}/decide"
                    body = DecisionInput(**fields, decision="APPROVE" if action == "approve" else "REJECT")
                elif action == "post":
                    if not messagebox.askyesno("Ghi sổ đảo", "Ghi đảo toàn bộ lần ghi sổ đã chọn theo nội dung được duyệt?", parent=self):
                        return
                    path, body = f"reversals/{self.doc['id']}/post", ReversalPost(**fields, execution_key=uuid4())
                else:
                    body = OrderAction(**fields)
            self.presenter.command(method, path, body.model_dump(mode="json"))
        except (ValueError, TypeError, StopIteration):
            self.workflow_error("Kiểm tra nguồn, ngày, quyền duyệt và lý do (ít nhất 3 ký tự).")

    def display_preview(self, data):
        self.preview_data = data
        self.plan.delete(*self.plan.get_children())
        self.effects.delete(*self.effects.get_children())
        for row in data["plan"]:
            self.plan.insert("", "end", values=(row["sku"], row["owner_code"], row["lot_code"] or row["serial_code"] or "—",
                row["source_code"], row["destination_code"], row["quantity_base"]))
        for row in data["effects"]:
            self.effects.insert("", "end", values=tuple(row[k] for k in ["stock_item_id", "location_code", "on_hand", "reserved", "delta", "projected_on_hand"]))
        original = data["source"]
        message = "Đủ điều kiện tại thời điểm xem trước." if data["eligible"] else " | ".join(r["message"] for r in data["blockers"])
        self.variables["detail"].set(f"Nguồn {original['document_number']} · {original['operation']} · {original['id']}\n{message}")

    def workflow_loaded(self, action, data, permissions):
        self.busy, self.permissions = False, permissions
        if action == "reversals":
            self.cursors[action] = data["next_after"]
            self.table.delete(*self.table.get_children())
            for row in data["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["number"], row["status"], row["version"]))
        elif action == "reversals/sources":
            self.sources, self.cursors[action] = data["items"], data["next_after"]
            self.source_selector.set("")
            self.source_selector.configure(values=[f"{r['document_number']} · {r['operation']} · {r['id']}" for r in self.sources])
            if not self.doc:
                self.source_changed()
        elif action == "preview":
            self.display_preview(data)
        elif action == "read":
            self.doc = data
            self.variables["day"].set(data["business_date"])
            self.variables["reason"].set(data["reversal_reason"])
            self.display_preview(data["preview"])
            self.variables["detail"].set(f"{data['number']} · {data['status']} · v{data['version']}\n" + self.variables["detail"].get() +
                (f"\nGiao dịch đảo: {data['transaction_id']}" if data["transaction_id"] else ""))
            self.history.delete(*self.history.get_children())
            for approval in data["approvals"]:
                for step in approval["steps"]:
                    self.history.insert("", "end", values=(approval["document_version"], step["step_no"], step["status"], step["decider_name"] or "—", step["comment"] or ""))
        self.variables["status"].set("Đã tải dữ liệu máy chủ.")
        self.enable()

    def workflow_saved(self, result):
        self.busy = False
        self.variables["status"].set("Máy chủ đã xác nhận " + result["status"])
        self.presenter.read(result["id"])
