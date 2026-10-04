from datetime import date
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.returns import ReturnPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.returns import ReturnInput, ReturnPost, ReturnUpdate


class ReturnView(WorkflowView):
    def __init__(self, parent, api, kind):
        self.kind = kind
        super().__init__(parent, api, ReturnPresenter)
        self.doc, self.source_document_id = None, None
        self.lines, self.sources, self.locations = [], [], []
        self.cursors = {"returns": None, "returns/sources": None, "returns/locations": None}
        self.load_button = ttk.Button(self.top, text="Tải phiếu trả", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.cursors["returns"]))
        self.next_button.pack(side="left", padx=5)
        self.new_button = ttk.Button(self.top, text="Phiếu mới", command=self.new)
        self.new_button.pack(side="left")
        self.table = self.tree(self, ["number", "state", "version"], ["Phiếu trả", "Trạng thái", "Phiên bản"], [350, 220, 100])
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.variables["detail"], wraplength=800).pack(fill="x")
        refs = ttk.Frame(self)
        refs.pack(fill="x", pady=4)
        self.ref_buttons = {}
        for resource, label in [("returns/sources", "Nguồn đã ghi sổ"), ("returns/locations", "Vị trí kho")]:
            for more in (False, True):
                button = ttk.Button(refs, text=label + (" tiếp" if more else ""),
                    command=lambda r=resource, n=more: self.presenter.load(r, self.cursors[r] if n else None))
                button.pack(side="left", padx=(0, 5))
                self.ref_buttons[resource, more] = button
        edit = ttk.Frame(self)
        edit.pack(fill="x")
        ttk.Label(edit, text="Dòng nguồn").grid(row=0, column=0, sticky="w")
        self.source_selector = self.combo(edit, "source", 72)
        self.source_selector.grid(row=0, column=1, columnspan=3, sticky="ew")
        self.source_selector.bind("<<ComboboxSelected>>", self.source_selected)
        ttk.Label(edit, text="Vị trí nhận" if kind == "CUSTOMER_RETURN" else "Vị trí xuất").grid(row=1, column=0)
        self.location_selector = self.combo(edit, "location", 35)
        self.location_selector.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(edit, text="SL cơ sở").grid(row=1, column=2, padx=4)
        self.quantity_entry = ttk.Entry(edit, textvariable=self.variable("quantity", "1"), width=12)
        self.quantity_entry.grid(row=1, column=3)
        ttk.Label(edit, text="Ngày trả").grid(row=2, column=0)
        self.day_entry = ttk.Entry(edit, textvariable=self.variable("day", date.today().isoformat()), width=16)
        self.day_entry.grid(row=2, column=1, sticky="w", pady=3)
        edit.columnconfigure(1, weight=1)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=3)
        self.add_button = ttk.Button(bar, text="Thêm dòng", command=self.add_line)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(bar, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left", padx=5)
        self.warranty_button = ttk.Button(bar, text="Nguồn bảo hành serial", command=self.warranty)
        self.warranty_button.pack(side="left")
        self.line_table = self.tree(self, ["source", "stock", "location", "quantity"],
            ["Phiếu nguồn", "SKU / owner / lô-serial", "Vị trí", "SL cơ sở"], [160, 310, 120, 90])
        note = "Khách trả vào cách ly, cần kiểm định trước khi cất hàng." if kind == "CUSTOMER_RETURN" else "Ghi sổ kiểm tra lại tồn chưa giữ chỗ; hàng cách ly cần policy cho phép."
        ttk.Label(self, text=note, wraplength=800).pack(fill="x")
        self.reason_form()
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.buttons = {}
        for action, label in [("save", "Lưu nháp"), ("submit", "Gửi duyệt"), ("approve", "Duyệt"),
                              ("reject", "Từ chối"), ("revise", "Sửa lại"), ("cancel", "Hủy"), ("post", "Ghi sổ toàn phiếu")]:
            button = ttk.Button(bar, text=label, command=lambda a=action: self.action(a))
            button.pack(side="left", padx=(0, 4))
            self.buttons[action] = button
        self.retry_form(operation=True)
        self.session_changed()

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        editable = writable and ("edit" in self.doc["allowed_actions"] if self.doc else "return.draft" in self.permissions)
        for widget in (self.selector, self.load_button):
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.cursors["returns"])
        self.set_enabled(self.new_button, writable and "return.draft" in self.permissions)
        for (resource, more), widget in self.ref_buttons.items():
            self.set_enabled(widget, free and (not more or self.cursors[resource]))
        for widget in (self.source_selector, self.location_selector, self.quantity_entry, self.day_entry, self.add_button, self.remove_button):
            self.set_enabled(widget, editable)
        self.set_enabled(self.reason_entry, writable)
        self.set_enabled(self.warranty_button, free and "serial.read" in self.permissions)
        for action, widget in self.buttons.items():
            self.set_enabled(widget, editable if action == "save" else writable and self.doc and action in self.doc["allowed_actions"])
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain and self.presenter.uncertain[1].endswith("/post"))

    def workflow_clear(self):
        self.doc, self.source_document_id = None, None
        self.lines, self.sources, self.locations, self.permissions = [], [], [], []
        self.busy = False
        self.cursors = {key: None for key in self.cursors}
        self.table.delete(*self.table.get_children())
        self.line_table.delete(*self.line_table.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status"}:
                self.variables[name].set("")
        self.source_selector.configure(values=[])
        self.location_selector.configure(values=[])

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc, self.source_document_id, self.lines = None, None, []
        self.variable("day").set(date.today().isoformat())
        self.variables["reason"].set("")
        self.variables["detail"].set("Chọn các lần ghi sổ thuộc cùng một phiếu nguồn.")
        self.render_lines()
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def source_selected(self, event=None):
        index = self.source_selector.current()
        if index >= 0:
            row = self.sources[index]
            self.variables["detail"].set(f"{row['document_number']} · {row['sku']} · owner {row['owner_code']} · "
                f"đã ghi {row['posted_base']} · đã trả {row['returned_base']} · còn {row['remaining_base']} {row['base_uom_code']}" +
                (f" · {row['blocked_reason']}" if row["blocked_reason"] else ""))

    def add_line(self):
        si, li = self.source_selector.current(), self.location_selector.current()
        if si < 0 or li < 0:
            self.workflow_error("Chọn dòng đã ghi sổ và vị trí trong kho.")
            return
        source, location = self.sources[si], self.locations[li]
        if not source["returnable"]:
            self.workflow_error(source["blocked_reason"])
            return
        if self.source_document_id and self.source_document_id != source["document_id"]:
            self.workflow_error("Các dòng phải thuộc cùng một phiếu nguồn; tạo phiếu mới để trả nguồn khác.")
            return
        self.source_document_id = source["document_id"]
        self.lines.append(dict(source_move_id=source["id"], location_id=location["id"], quantity_base=self.variables["quantity"].get(),
            source_label=source["document_number"], label=f"{source['sku']} / {source['owner_code']} / {source['lot_code'] or source['serial_code'] or '—'}",
            location_code=location["code"], serial_id=source["serial_id"]))
        self.render_lines()

    def remove_line(self):
        selected = self.line_table.selection()
        if selected:
            self.lines.pop(int(selected[0]))
            if not self.lines and not self.doc:
                self.source_document_id = None
            self.render_lines()

    def render_lines(self):
        self.line_table.delete(*self.line_table.get_children())
        for index, row in enumerate(self.lines):
            self.line_table.insert("", "end", iid=str(index), values=(row["source_label"], row["label"], row["location_code"], row["quantity_base"]))

    def warranty(self):
        selected = self.line_table.selection()
        index = self.source_selector.current()
        serial = self.lines[int(selected[0])]["serial_id"] if selected else self.sources[index]["serial_id"] if index >= 0 else None
        if serial:
            self.presenter.warranty(serial)
        else:
            self.workflow_error("Chọn dòng serial để tra nguồn nhập và chứng cứ bảo hành.")

    def workflow_loaded(self, action, result, permissions):
        self.busy, self.permissions = False, permissions
        if action == "read":
            if result["kind"] != self.kind:
                self.workflow_error("Phiếu thuộc loại trả khác; mở tab tương ứng.")
                return
            self.doc, self.source_document_id = result, result["source_document_id"]
            plans = {p["document_line_id"]: p for p in result["plan"]}
            self.lines = [{**plans[r["id"]], "source_label": result["source_document_number"],
                "label": f"{r['sku']} / {r['owner_code']} / {plans[r['id']]['lot_code'] or plans[r['id']]['serial_code'] or '—'}"} for r in result["lines"]]
            self.variables["day"].set(result["business_date"])
            self.variables["reason"].set("")
            self.variables["detail"].set(f"{result['number']} · {result['status']} · v{result['version']} · " +
                "; ".join(f"Duyệt v{a['document_version']}: {a['status']}" for a in result["approvals"]))
            self.render_lines()
        elif action == "warranty":
            self.variables["detail"].set(f"Serial {result['serial_code']} · nhập {result['receipt_number'] or 'Chưa xác định'} · "
                f"NCC {result['supplier_name'] or 'Chưa xác định'} · ngày nhập {result['received_on'] or '—'} · "
                f"bảo hành {result['status']} · chứng cứ {result['warranty_evidence_ref'] or 'Chưa xác định'}")
        else:
            self.cursors[action] = result["next_after"]
            if action == "returns":
                self.table.delete(*self.table.get_children())
                for row in result["items"]:
                    self.table.insert("", "end", iid=row["id"], values=(row["number"], row["status"], row["version"]))
            elif action == "returns/sources":
                self.sources = result["items"]
                self.variables["source"].set("")
                self.source_selector.configure(values=[f"{r['document_number']} · {r['sku']} · {r['owner_code']} · {r['lot_code'] or r['serial_code'] or '—'} · còn {r['remaining_base']}" for r in self.sources])
            elif action == "returns/locations":
                self.locations = [r for r in result["items"] if self.kind == "SUPPLIER_RETURN" or r["kind"] == "QUARANTINE"]
                self.variables["location"].set("")
                self.location_selector.configure(values=[f"{r['code']} · {r['kind']} · {r['name']}" for r in self.locations])
        self.variables["status"].set("Đã tải dữ liệu." + (" Còn trang sau." if result.get("next_after") else ""))
        self.enable()

    def workflow_saved(self, result):
        self.busy = False
        self.presenter.read(result["id"])

    def action(self, action):
        if self.busy or self.presenter.uncertain:
            return
        try:
            reason = self.variables["reason"].get().strip()
            if action == "save":
                body = dict(kind=self.kind, source_document_id=self.source_document_id, business_date=self.variables["day"].get(), reason=reason,
                    lines=[{k: r[k] for k in ("source_move_id", "location_id", "quantity_base")} for r in self.lines])
                if self.doc:
                    body["expected_version"] = self.doc["version"]
                body = (ReturnUpdate if self.doc else ReturnInput).model_validate(body).model_dump(mode="json")
                self.presenter.command("PUT" if self.doc else "POST", "returns" + ("/" + self.doc["id"] if self.doc else ""), body)
            elif self.doc:
                body = {"expected_version": self.doc["version"], "reason": reason}
                path = "documents/" + self.doc["id"] + "/" + action
                if action == "post":
                    body = ReturnPost(**body, execution_key=uuid4()).model_dump(mode="json")
                    path = "returns/" + self.doc["id"] + "/post"
                elif action in {"approve", "reject"}:
                    approval = next(a for a in self.doc["approvals"] if a["can_decide"])
                    path = "approval-requests/" + approval["id"] + "/decide"
                    body["decision"] = action.upper()
                self.presenter.command("POST", path, body)
        except (ValueError, TypeError, StopIteration):
            self.workflow_error("Kiểm tra nguồn, lượng cơ sở, ngày YYYY-MM-DD, lý do và quyền duyệt.")
