import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.receipts import ReceiptPresenter
from apps.desktop.views.orders import STATUS, OrderView
from packages.contracts.receipts import ReceiptInput, ReceiptPost, ReceiptUpdate


class ReceiptView(ttk.Frame):
    combo, tree = OrderView.combo, OrderView.tree
    path = "receipts"

    def __init__(self, parent, api):
        super().__init__(parent, padding=10)
        self.variables = {
            k: tk.StringVar()
            for k in [
                "warehouse",
                "source",
                "line",
                "location",
                "qty",
                "lot",
                "serial",
                "made",
                "expiry",
                "day",
                "reason",
                "status",
                "heading",
                "history",
                "recovery",
            ]
        }
        self.presenter = ReceiptPresenter(self, api)
        self.warehouses, self.permissions, self.sources, self.locations = [], [], [], []
        self.doc, self.source_doc, self.next_after = None, None, None
        self.lines, self.source_lines = [], []
        self.busy = False
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.selector = self.combo(top, "warehouse", 28)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self.scope_changed)
        self.load_button = ttk.Button(top, text="Tải phiếu nhận", command=self.load)
        self.load_button.pack(side="left", padx=5)
        self.next_button = ttk.Button(top, text="Trang sau", command=lambda: self.load(self.next_after))
        self.next_button.pack(side="left")
        self.new_button = ttk.Button(top, text="Tạo từ PO", command=self.new)
        self.new_button.pack(side="right")
        ttk.Label(self, textvariable=self.variables["status"], wraplength=820).pack(fill="x", pady=4)
        self.table = self.tree(
            self,
            ["number", "status", "partner"],
            ["Phiếu nhận", "Trạng thái", "Nhà cung cấp"],
            [270, 190, 340],
            3,
        )
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.variables["heading"]).pack(fill="x", pady=3)
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="PO nguồn").pack(side="left")
        self.source = self.combo(header, "source", 52)
        self.source.pack(side="left", padx=5)
        self.source.bind("<<ComboboxSelected>>", self.source_changed)
        ttk.Label(header, text="Ngày nhận").pack(side="left")
        self.day = ttk.Entry(header, textvariable=self.variables["day"], width=12)
        self.day.pack(side="left", padx=5)
        self.line_table = self.tree(
            self,
            ["sku", "tracking", "location", "qty", "left"],
            ["SKU / ĐVT cơ sở", "Lô / serial", "Vị trí", "Kế hoạch", "Còn nhận"],
            [210, 210, 120, 100, 120],
            4,
        )
        self.line_table.bind("<<TreeviewSelect>>", self.line_selected)
        edit = ttk.Frame(self)
        edit.pack(fill="x", pady=3)
        self.line = self.combo(edit, "line", 50)
        self.line.pack(side="left")
        self.location = self.combo(edit, "location", 25)
        self.location.pack(side="left", padx=5)
        fields = ttk.Frame(self)
        fields.pack(fill="x", pady=3)
        self.entries = {}
        for name, label, width in [
            ("qty", "SL cơ sở", 9),
            ("lot", "Lô", 16),
            ("serial", "Serial", 20),
            ("made", "NSX", 11),
            ("expiry", "HSD", 11),
        ]:
            ttk.Label(fields, text=label).pack(side="left")
            entry = ttk.Entry(fields, textvariable=self.variables[name], width=width)
            entry.pack(side="left", padx=(2, 5))
            self.entries[name] = entry
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.add_button = ttk.Button(bar, text="Thêm dòng", command=self.add_line)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(bar, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left", padx=5)
        ttk.Label(bar, text="Ngày: YYYY-MM-DD · Mỗi serial một dòng, số lượng 1.").pack(side="left")
        reason = ttk.Frame(self)
        reason.pack(fill="x", pady=5)
        ttk.Label(reason, text="Lý do").pack(side="left")
        self.reason = ttk.Entry(reason, textvariable=self.variables["reason"])
        self.reason.pack(side="left", fill="x", expand=True, padx=5)
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.buttons = {}
        for action, label in [
            ("save", "Lưu nháp"),
            ("submit", "Gửi duyệt"),
            ("approve", "Duyệt"),
            ("reject", "Từ chối"),
            ("revise", "Sửa lại"),
            ("cancel", "Hủy"),
            ("post", "Nhận dòng chọn"),
        ]:
            button = ttk.Button(actions, text=label, command=lambda a=action: self.action(a))
            button.pack(side="left", padx=2)
            self.buttons[action] = button
        self.retry_button = ttk.Button(
            self, text="Gửi lại đúng yêu cầu chưa rõ kết quả", command=self.presenter.retry
        )
        self.retry_button.pack(anchor="w", pady=5)
        ttk.Label(self, textvariable=self.variables["recovery"], wraplength=820).pack(fill="x")
        ttk.Label(self, textvariable=self.variables["history"], wraplength=820).pack(fill="x")
        ttk.Label(
            self,
            text="Chọn dòng đã duyệt, nhập lượng thực nhận rồi ghi sổ. Chỉ báo thành công khi máy chủ xác nhận.",
            wraplength=820,
        ).pack(fill="x", pady=3)
        self.variables["status"].set("Đăng nhập để nhận hàng từ PO đã duyệt.")
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
        self.variables["status"].set(
            "Tải danh sách phiếu nhận theo kho." if user else "Đăng nhập để nhận hàng."
        )
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id)
        self.variables["status"].set("Tải lại danh sách theo kho vừa chọn.")
        self.enable()

    def orders_clear(self):
        self.doc = self.source_doc = self.next_after = None
        self.lines, self.source_lines, self.sources, self.locations, self.permissions = [], [], [], [], []
        self.busy = False
        self.table.delete(*self.table.get_children())
        self.line_table.delete(*self.line_table.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status", "recovery"}:
                self.variables[name].set("")
        for box in [self.source, self.line, self.location]:
            box.configure(values=[])

    def enable(self):
        active = bool(self.presenter.user_id and self.warehouses) and not self.busy and not self.presenter.recovery_busy
        editable = (
            active
            and not self.presenter.uncertain
            and ("edit" in self.doc["allowed_actions"] if self.doc else "receipt.draft" in self.permissions)
        )
        posting = (
            active and self.doc and "post" in self.doc["allowed_actions"] and not self.presenter.uncertain
        )
        for widget in [self.selector, self.load_button]:
            widget.state(["!disabled"] if active else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        self.new_button.state(
            ["!disabled"]
            if active and "receipt.draft" in self.permissions and not self.presenter.uncertain
            else ["disabled"]
        )
        self.source.state(["!disabled"] if editable and not self.doc else ["disabled"])
        for widget in [
            self.day,
            self.line,
            self.location,
            self.add_button,
            self.remove_button,
            *self.entries.values(),
        ]:
            widget.state(["!disabled"] if editable else ["disabled"])
        self.entries["qty"].state(["!disabled"] if editable or posting else ["disabled"])
        self.reason.state(["!disabled"] if active and not self.presenter.uncertain else ["disabled"])
        for action, button in self.buttons.items():
            allowed = (
                editable
                if action == "save"
                else active and self.doc and action in self.doc["allowed_actions"]
            )
            if action == "post":
                allowed = allowed and bool(self.line_table.selection())
            button.state(["!disabled"] if allowed and not self.presenter.uncertain else ["disabled"])
        self.retry_button.state(["!disabled"] if active and self.presenter.memory_uncertain else ["disabled"])

    def recovery_changed(self):
        if not self.presenter.user_id:
            message = ""
        elif self.presenter.recovery_busy:
            message = "Đang kiểm tra/lưu yêu cầu nhận hàng…"
        elif not self.presenter.recovery_ready:
            message = "Chưa mở được dữ liệu phục hồi. Kiểm tra tại tab Phục hồi nhận hàng trước khi ghi sổ."
        elif self.presenter.unresolved:
            message = "Còn lệnh chưa rõ kết quả. Mở tab Phục hồi nhận hàng để tra cứu hoặc gửi lại đúng lệnh."
        else:
            message = "Lệnh ghi sổ nhận hàng được lưu trên máy này để phục hồi sau khi mở lại ứng dụng."
        self.variables["recovery"].set(message)
        self.enable()

    def load(self, after=None):
        if self.warehouse_id():
            self.presenter.load(self.path, self.warehouse_id(), after=after)

    def orders_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def orders_loaded(self, page, refs, permissions):
        self.orders_clear()
        self.permissions, self.sources, self.locations = permissions, refs["sources"], refs["locations"]
        self.next_after = page["next_after"]
        self.source.configure(values=[f"{p['number']} · {p['partner_name']}" for p in self.sources])
        self.location.configure(values=[f"{p['code']} · {p['name']}" for p in self.locations])
        for doc in page["items"]:
            self.table.insert(
                "", "end", iid=doc["id"], values=(doc["number"], STATUS[doc["status"]], doc["partner_name"])
            )
        self.variables["status"].set(
            "Đã tải phiếu nhận. PO nguồn chỉ gồm phiếu có quyền xem, đã duyệt và còn nhận."
            + (
                " Danh sách chọn PO giới hạn 100 phiếu mỗi trạng thái."
                if refs.get("source_truncated")
                else ""
            )
        )
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy:
            self.presenter.read(self.path, selected[0])

    def new(self):
        self.doc = self.source_doc = None
        self.lines, self.source_lines = [], []
        for name in ["source", "line", "reason", "history", "lot", "serial", "made", "expiry"]:
            self.variables[name].set("")
        self.variables["day"].set(date.today().isoformat())
        self.variables["qty"].set("1")
        self.variables["heading"].set("Phiếu nhận mới · Hàng doanh nghiệp")
        if self.locations:
            self.location.current(0)
        self.render_lines()
        self.enable()

    def source_changed(self, event=None):
        index = self.source.current()
        if index >= 0 and not self.doc:
            self.lines = []
            self.render_lines()
            self.presenter.source(self.sources[index]["id"])

    def orders_conversions(self, doc):
        self.busy = False
        self.source_doc = doc
        self.source_lines = [line for line in doc["lines"] if Decimal(line["remaining_base"]) > 0]
        self.line.configure(
            values=[
                f"{r['line_no']}. {r['sku']} · {r['tracking']} · còn {r['remaining_base']} {r['base_uom_code']}"
                for r in self.source_lines
            ]
        )
        self.variables["line"].set("")
        if self.source_lines:
            self.line.current(0)
        self.variables["status"].set("Nhập kế hoạch nhận theo đơn vị cơ sở, lô/serial và vị trí.")
        self.enable()

    def add_line(self):
        source, destination = self.line.current(), self.location.current()
        if source < 0 or destination < 0:
            self.orders_error("Chọn dòng PO và vị trí nhận.")
            return
        line = self.source_lines[source]
        self.lines.append(
            dict(
                source_line_id=line["id"],
                quantity_base=self.variables["qty"].get(),
                destination_location_id=self.locations[destination]["id"],
                lot_code=self.variables["lot"].get() or None,
                serial_code=self.variables["serial"].get() or None,
                manufactured_on=self.variables["made"].get() or None,
                expires_on=self.variables["expiry"].get() or None,
                sku=line["sku"],
                base_uom_code=line["base_uom_code"],
                location_code=self.locations[destination]["code"],
                remaining_base="—",
            )
        )
        self.render_lines()

    def remove_line(self):
        selected = self.line_table.selection()
        if selected:
            self.lines.pop(int(selected[0]))
            self.render_lines()

    def render_lines(self):
        self.line_table.delete(*self.line_table.get_children())
        for index, line in enumerate(self.lines):
            self.line_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    f"{line['sku']} / {line['base_uom_code']}",
                    line.get("lot_code") or line.get("serial_code") or "—",
                    line["location_code"],
                    line["quantity_base"],
                    line["remaining_base"],
                ),
            )

    def line_selected(self, event=None):
        selected = self.line_table.selection()
        if selected:
            line = self.lines[int(selected[0])]
            self.variables["qty"].set(
                line["remaining_base"]
                if self.doc and "post" in self.doc["allowed_actions"]
                else line["quantity_base"]
            )
            for name, field in [
                ("lot", "lot_code"),
                ("serial", "serial_code"),
                ("made", "manufactured_on"),
                ("expiry", "expires_on"),
            ]:
                self.variables[name].set(line.get(field) or "")
        self.enable()

    def orders_read(self, doc):
        self.busy, self.doc = False, doc
        for index, warehouse in enumerate(self.warehouses):
            if str(warehouse.id) == doc["warehouse_id"]:
                self.selector.current(index)
                break
        plan = {p["document_line_id"]: p for p in doc["plan"]}
        self.lines = [{**line, **plan[line["id"]]} for line in doc["lines"]]
        self.variables["heading"].set(f"{doc['number']} · {STATUS[doc['status']]} · v{doc['version']}")
        self.variables["source"].set(
            next(
                (p["number"] for p in self.sources if p["id"] == doc["source_order_id"]),
                doc["source_order_id"],
            )
        )
        self.variables["day"].set(doc["business_date"])
        self.variables["reason"].set("")
        self.variables["history"].set(
            "\n".join(
                f"Duyệt v{a['document_version']}: {a['status']} · "
                + "; ".join(
                    f"{s['decider_name'] or 'Chưa duyệt'}: {s['comment'] or s['status']}" for s in a["steps"]
                )
                for a in doc["approvals"][-2:]
            )
        )
        self.render_lines()
        self.enable()
        self.variables["status"].set(
            "Đã tải chi tiết. Chọn dòng để xem ngày lô hoặc ghi nhận lượng thực nhận."
        )
        if "edit" in doc["allowed_actions"]:
            self.presenter.source(doc["source_order_id"])

    def action(self, action):
        reason = self.variables["reason"].get().strip()
        if not reason:
            self.orders_error("Nhập lý do thao tác.")
            return
        try:
            if action == "save":
                source_id = (
                    self.doc["source_order_id"]
                    if self.doc
                    else self.source_doc["id"]
                    if self.source_doc
                    else None
                )
                fields = [
                    "source_line_id",
                    "quantity_base",
                    "destination_location_id",
                    "lot_code",
                    "serial_code",
                    "manufactured_on",
                    "expires_on",
                ]
                body = dict(
                    source_order_id=source_id,
                    business_date=self.variables["day"].get(),
                    reason=reason,
                    lines=[{k: line[k] for k in fields} for line in self.lines],
                )
                if self.doc:
                    body["expected_version"] = self.doc["version"]
                body = (
                    (ReceiptUpdate if self.doc else ReceiptInput).model_validate(body).model_dump(mode="json")
                )
                self.presenter.command(
                    "PUT" if self.doc else "POST",
                    self.path + ("/" + self.doc["id"] if self.doc else ""),
                    body,
                )
            elif self.doc:
                body = dict(expected_version=self.doc["version"], reason=reason)
                path = "documents/" + self.doc["id"] + "/" + action
                if action == "post":
                    selected = self.line_table.selection()
                    if not selected:
                        return
                    body.update(
                        execution_key=str(uuid4()),
                        lines=[
                            dict(
                                document_line_id=self.lines[int(selected[0])]["id"],
                                quantity_base=self.variables["qty"].get(),
                            )
                        ],
                    )
                    body = ReceiptPost.model_validate(body).model_dump(mode="json")
                    path = self.path + "/" + self.doc["id"] + "/post"
                elif action in {"approve", "reject"}:
                    pending = next((a for a in self.doc["approvals"] if a["can_decide"]), None)
                    if not pending:
                        return
                    path = "approval-requests/" + pending["id"] + "/decide"
                    body["decision"] = action.upper()
                self.presenter.command("POST", path, body)
        except (ValueError, TypeError):
            self.orders_error("Kiểm tra PO, số lượng cơ sở, mã lô/serial và ngày YYYY-MM-DD.")

    def orders_saved(self, result):
        self.busy = False
        for index, warehouse in enumerate(self.warehouses):
            if str(warehouse.id) == result["warehouse_id"]:
                self.selector.current(index)
                break
        self.presenter.read(self.path, result["id"])

    def orders_error(self, message):
        self.busy = False
        self.enable()
        self.variables["status"].set(
            message + " Nội dung nhập được giữ; khi version đổi, tải lại để đối chiếu."
        )

    def release_variables(self):
        self.variables.clear()
