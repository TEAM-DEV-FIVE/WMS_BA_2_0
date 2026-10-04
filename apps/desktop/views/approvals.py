import tkinter as tk
from tkinter import ttk

from apps.desktop.presenters.approvals import PATHS, ApprovalPresenter, decision_explanation
from apps.desktop.views.document_review import ReviewPanel, fulfillment_label
from packages.contracts.orders import DecisionInput


class ApprovalView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=10)
        self.presenter = ApprovalPresenter(self, api)
        self.variables = {k: tk.StringVar() for k in ("kind", "warehouse", "status", "heading", "reason", "uncertainty")}
        self.variables["kind"].set("PO")
        self.warehouses, self.permissions = [], []
        self.doc = None
        self.busy = False
        self.next_after = None
        self.cursors, self.page_index = [None], 0
        self.on_open_document = None
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.kind = ttk.Combobox(bar, textvariable=self.variables["kind"], values=list(PATHS), state="readonly", width=12)
        self.kind.pack(side="left")
        self.selector = ttk.Combobox(bar, textvariable=self.variables["warehouse"], state="readonly", width=32)
        self.selector.pack(side="left", padx=4)
        for box in (self.kind, self.selector):
            box.bind("<<ComboboxSelected>>", self.scope_changed)
        self.load_button = ttk.Button(bar, text="Phiếu chờ duyệt", command=self.load)
        self.load_button.pack(side="left")
        self.prev_button = ttk.Button(bar, text="Trang trước", command=self.previous)
        self.prev_button.pack(side="left", padx=4)
        self.next_button = ttk.Button(bar, text="Trang sau", command=lambda: self.load(self.next_after))
        self.next_button.pack(side="left")
        ttk.Label(self, textvariable=self.variables["status"], wraplength=790).pack(fill="x", pady=4)
        self.table = ttk.Treeview(self, columns=("number", "partner", "creator", "version"), show="headings", height=4)
        for column, label, width in [("number", "Số phiếu", 230), ("partner", "Đối tác", 250),
                                     ("creator", "Người lập", 180), ("version", "Version", 80)]:
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=50)
        self.table.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.table.bind("<Return>", self.select)
        heading = ttk.Frame(self)
        heading.pack(fill="x", pady=3)
        ttk.Label(heading, textvariable=self.variables["heading"]).pack(side="left")
        self.open_button = ttk.Button(heading, text="Mở form nghiệp vụ", command=self.open_document)
        self.open_button.pack(side="right")
        self.reload_button = ttk.Button(heading, text="Đọc lại", command=self.reload)
        self.reload_button.pack(side="right", padx=4)
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        summary = ttk.Frame(self.tabs)
        self.tabs.add(summary, text="Nội dung và các bước duyệt")
        self.content = tk.Text(summary, height=9, wrap="word", state="disabled")
        self.content.pack(fill="both", expand=True)
        self.review_panel = ReviewPanel(self.tabs, self.load_review)
        self.tabs.add(self.review_panel, text="Đối chiếu snapshot")
        reason = ttk.Frame(footer)
        reason.pack(fill="x", pady=4)
        ttk.Label(reason, text="Lý do quyết định").pack(side="left")
        self.reason = ttk.Entry(reason, textvariable=self.variables["reason"])
        self.reason.pack(side="left", fill="x", expand=True, padx=4)
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        self.approve_button = ttk.Button(buttons, text="Duyệt", command=lambda: self.decide("APPROVE"))
        self.approve_button.pack(side="left")
        self.reject_button = ttk.Button(buttons, text="Từ chối", command=lambda: self.decide("REJECT"))
        self.reject_button.pack(side="left", padx=5)
        self.retry_button = ttk.Button(buttons, text="Gửi lại yêu cầu UNKNOWN đang giữ", command=self.presenter.retry)
        self.retry_button.pack(side="left")
        ttk.Label(footer, textvariable=self.variables["uncertainty"], wraplength=730).pack(fill="x", pady=4)
        self.orders_clear()
        self.variables["status"].set("Đăng nhập và chọn kho để mở hộp thư duyệt.")
        self.enable()

    @property
    def path(self):
        return PATHS[self.variables["kind"].get()]

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
        self.cursors, self.page_index = [None], 0
        self.variables["status"].set("Chọn loại phiếu/kho rồi tải hộp thư duyệt." if user else "Đã đăng xuất.")
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id)
        self.cursors, self.page_index = [None], 0
        self.variables["status"].set("Tải hộp thư theo loại phiếu và kho vừa chọn.")
        self.enable()

    def orders_clear(self):
        self.doc = None
        self.permissions = []
        self.busy = False
        self.next_after = None
        self.table.delete(*self.table.get_children())
        self.variables["heading"].set("")
        self.variables["reason"].set("")
        self.set_content("")
        self.review_panel.clear()

    def set_content(self, value):
        self.content.configure(state="normal")
        self.content.delete("1.0", "end")
        self.content.insert("1.0", value)
        self.content.configure(state="disabled")

    def enable(self):
        active = bool(self.presenter.user_id and self.warehouses) and not self.busy
        pending = next((a for a in self.doc["approvals"] if a["can_decide"]), None) if self.doc else None
        decide = (active and pending and "document.approve" in self.permissions
                  and not self.presenter.uncertain and not self.presenter.needs_reload)
        for widget in (self.kind, self.selector, self.load_button):
            widget.state(["!disabled"] if active else ["disabled"])
        for widget in (self.approve_button, self.reject_button, self.reason):
            widget.state(["!disabled"] if decide else ["disabled"])
        for widget in (self.reload_button, self.open_button, self.review_panel.load_button):
            widget.state(["!disabled"] if active and self.doc else ["disabled"])
        self.prev_button.state(["!disabled"] if active and self.page_index else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        self.retry_button.state(["!disabled"] if active and self.presenter.uncertain else ["disabled"])
        self.variables["uncertainty"].set(
            "UNKNOWN · Kết quả chưa xác định. Giữ nguyên yêu cầu/khóa, kể cả khi đổi màn hình hoặc kho."
            if self.presenter.uncertain else "")

    def load(self, after=None):
        if not self.warehouse_id() or self.busy:
            return
        if after is None:
            self.cursors, self.page_index = [None], 0
        else:
            self.page_index += 1
            self.cursors[self.page_index:] = [after]
        self.presenter.load(self.path, self.warehouse_id(), after=after)

    def previous(self):
        if self.page_index and not self.busy:
            self.page_index -= 1
            self.presenter.load(self.path, self.warehouse_id(), after=self.cursors[self.page_index])

    def orders_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def orders_loaded(self, page, refs, permissions):
        self.orders_clear()
        self.permissions = permissions
        self.next_after = page["next_after"]
        for doc in page["items"]:
            self.table.insert("", "end", iid=doc["id"], values=(doc["number"], doc["partner_name"],
                              doc["creator_name"], doc["version"]))
        self.variables["status"].set(f"Trang {self.page_index + 1} · {len(page['items'])} phiếu chờ. "
                                     "Chọn phiếu để kiểm tra nội dung, quyền kho và SOD.")
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy:
            self.presenter.read(self.path, selected[0])

    def reload(self):
        if self.doc and not self.busy:
            self.presenter.read(self.path, self.doc["id"])

    def orders_read(self, doc):
        self.permissions = doc.pop("_permissions", self.permissions)
        self.doc, self.busy = doc, False
        if doc["status"] != "SUBMITTED" and self.table.exists(doc["id"]):
            self.table.delete(doc["id"])
        self.review_panel.clear()
        self.variables["reason"].set("")
        self.variables["heading"].set(f"{doc['number']} · v{doc['version']} · {fulfillment_label(doc)}")
        text = [f"Người lập: {doc['creator_name']} · Ngày: {doc['business_date']}",
                "Số lượng đã thực hiện/còn mở/đóng theo đơn vị cơ sở:"]
        for line in doc["lines"]:
            text.append(f"{line['line_no']}. {line['sku']} · {line['quantity']} {line['uom_code']} · "
                        f"Đã TH {line['posted_base']} · Còn {line['remaining_base']} · Đóng {line['closed_base']}")
        if doc.get("source_order_id"):
            text.append(f"PO nguồn: {doc['source_order_id']}")
            for plan in doc["plan"]:
                text.append(f"Nhận tại {plan['location_code']} · Lô {plan['lot_code'] or '—'} · "
                            f"Serial {plan['serial_code'] or '—'} · Hạn {plan['expires_on'] or '—'}")
        for approval in doc["approvals"]:
            text.append(f"\nGửi duyệt v{approval['document_version']} · policy r{approval['policy_revision']} · {approval['status']}")
            for step in approval["steps"]:
                text.append(f"  Bước {step['step_no']} · {' / '.join(step['roles'])} · {step['status']} · "
                            f"{step['decider_name'] or 'Chưa quyết định'} · {step['comment'] or ''}")
        self.set_content("\n".join(text))
        self.variables["status"].set(decision_explanation(doc, self.presenter.user_id, self.permissions))
        self.enable()

    def decide(self, decision):
        if self.approve_button.instate(["disabled"]) or not self.doc:
            return
        pending = next(a for a in self.doc["approvals"] if a["can_decide"])
        try:
            body = DecisionInput(expected_version=self.doc["version"], decision=decision,
                                 reason=self.variables["reason"].get().strip()).model_dump(mode="json")
        except ValueError:
            self.orders_error("Nhập lý do quyết định trước khi gửi.")
            return
        self.presenter.command("POST", f"approval-requests/{pending['id']}/decide", body)

    def orders_saved(self, result):
        self.variables["kind"].set(result["kind"])
        for index, warehouse in enumerate(self.warehouses):
            if str(warehouse.id) == result["warehouse_id"]:
                self.selector.current(index)
                break
        self.presenter.read(self.path, result["id"])

    def orders_error(self, message):
        self.busy = False
        self.variables["status"].set(message + (" Đọc lại phiếu trước khi quyết định tiếp." if self.presenter.needs_reload else ""))
        self.enable()

    def load_review(self):
        if self.doc and not self.busy:
            self.presenter.review(self.doc["id"])

    def orders_review(self, result):
        self.busy = False
        self.review_panel.loaded(result)
        if self.doc and result["current_version"] != self.doc["version"]:
            self.presenter.needs_reload = True
            self.orders_error("Phiên bản phiếu đã thay đổi.")
        else:
            self.enable()

    def open_document(self):
        if self.doc and not self.open_button.instate(["disabled"]) and self.on_open_document:
            self.on_open_document(self.doc)

    def release_variables(self):
        self.review_panel.release_variables()
        self.variables.clear()
        self.on_open_document = None
