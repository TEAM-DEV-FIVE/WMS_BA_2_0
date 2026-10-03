import tkinter as tk
from datetime import date
from tkinter import ttk

from apps.desktop.presenters.orders import OrderPresenter
from packages.contracts.orders import OrderInput, OrderUpdate
from packages.contracts.traceability import COMPANY_OWNER

STATUS = {
    "DRAFT": "Nháp",
    "SUBMITTED": "Chờ duyệt",
    "APPROVED": "Đã duyệt",
    "REJECTED": "Từ chối",
    "PARTIAL": "Thực hiện một phần",
    "COMPLETED": "Hoàn tất",
    "CANCELLED": "Đã hủy",
}


class OrderView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=10)
        self.presenter = OrderPresenter(self, api)
        self.variables = {
            name: tk.StringVar()
            for name in [
                "warehouse",
                "kind",
                "filter",
                "partner",
                "day",
                "product",
                "conversion",
                "qty",
                "reason",
                "status",
                "heading",
                "history",
            ]
        }
        self.variables["kind"].set("PO")
        self.variables["day"].set(date.today().isoformat())
        self.variables["qty"].set("1")
        self.variables["status"].set("Đăng nhập để tạo và duyệt PO/SO.")
        self.warehouses = []
        self.permissions = []
        self.catalog_ready = False
        self.doc = None
        self.lines = []
        self.products = []
        self.uoms = {}
        self.partners = []
        self.conversions = []
        self.next_after = None
        self.busy = False
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.kind = self.combo(top, "kind", 7, ["PO", "SO"])
        self.kind.pack(side="left")
        self.selector = self.combo(top, "warehouse", 32)
        self.selector.pack(side="left", padx=5)
        self.filter = self.combo(top, "filter", 17, [""] + list(STATUS))
        self.filter.pack(side="left")
        self.load_button = ttk.Button(top, text="Tải danh sách", command=self.load)
        self.load_button.pack(side="left", padx=5)
        self.next_button = ttk.Button(top, text="Trang sau", command=lambda: self.load(self.next_after))
        self.next_button.pack(side="left")
        for box in [self.kind, self.selector, self.filter]:
            box.bind("<<ComboboxSelected>>", self.scope_changed)
        ttk.Label(self, textvariable=self.variables["status"], wraplength=820).pack(fill="x", pady=5)
        self.table = self.tree(
            self,
            ["number", "status", "partner", "day"],
            ["Số phiếu", "Trạng thái", "Đối tác", "Ngày"],
            [220, 150, 290, 120],
            4,
        )
        self.table.bind("<<TreeviewSelect>>", self.select)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(5, 2))
        ttk.Label(bar, textvariable=self.variables["heading"]).pack(side="left")
        self.new_button = ttk.Button(bar, text="Tạo mới", command=self.new)
        self.new_button.pack(side="right")
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="Đối tác").pack(side="left")
        self.partner = self.combo(header, "partner", 49)
        self.partner.pack(side="left", padx=5)
        ttk.Label(header, text="Ngày").pack(side="left")
        self.day = ttk.Entry(header, textvariable=self.variables["day"], width=12)
        self.day.pack(side="left", padx=5)
        self.line_table = self.tree(
            self,
            ["sku", "unit", "qty", "posted", "remaining"],
            ["Sản phẩm", "Đơn vị", "Yêu cầu", "Đã TH (cơ sở)", "Còn (cơ sở)"],
            [330, 100, 110, 110, 110],
            4,
        )
        editor = ttk.Frame(self)
        editor.pack(fill="x", pady=4)
        self.product = self.combo(editor, "product", 35)
        self.product.pack(side="left")
        self.product.bind("<<ComboboxSelected>>", self.product_changed)
        self.conversion = self.combo(editor, "conversion", 20)
        self.conversion.pack(side="left", padx=4)
        self.qty = ttk.Entry(editor, textvariable=self.variables["qty"], width=10)
        self.qty.pack(side="left")
        self.add_button = ttk.Button(editor, text="Thêm dòng", command=self.add_line)
        self.add_button.pack(side="left", padx=4)
        self.remove_button = ttk.Button(editor, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left")
        reason = ttk.Frame(self)
        reason.pack(fill="x", pady=4)
        ttk.Label(reason, text="Lý do").pack(side="left")
        self.reason = ttk.Entry(reason, textvariable=self.variables["reason"])
        self.reason.pack(side="left", fill="x", expand=True, padx=5)
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=4)
        self.buttons = {}
        for action, label in [
            ("save", "Lưu nháp"),
            ("submit", "Gửi duyệt"),
            ("approve", "Duyệt"),
            ("reject", "Từ chối"),
            ("revise", "Sửa lại"),
            ("cancel", "Hủy"),
            ("close", "Đóng thiếu"),
        ]:
            button = ttk.Button(actions, text=label, command=lambda a=action: self.action(a))
            button.pack(side="left", padx=2)
            self.buttons[action] = button
        self.retry_button = ttk.Button(
            self, text="Gửi lại đúng yêu cầu chưa rõ kết quả", command=self.presenter.retry
        )
        self.retry_button.pack(anchor="w", pady=3)
        ttk.Label(self, textvariable=self.variables["history"], wraplength=820, justify="left").pack(
            fill="x", pady=3
        )
        ttk.Label(
            self,
            text="PO/SO chưa làm thay đổi tồn. Hàng ký gửi và giá tham chiếu chưa nhập trên màn này.",
            wraplength=820,
        ).pack(fill="x")
        self.enable()

    def combo(self, parent, name, width, values=()):
        return ttk.Combobox(
            parent, textvariable=self.variables[name], state="readonly", width=width, values=values
        )

    def tree(self, parent, columns, labels, widths, height):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height, selectmode="browse")
        for column, label, width in zip(columns, labels, widths):
            tree.heading(column, text=label)
            tree.column(column, width=width, minwidth=55)
        tree.pack(fill="x", pady=3)
        return tree

    @property
    def path(self):
        return "purchase-orders" if self.variables["kind"].get() == "PO" else "sales-orders"

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
            "Chọn loại phiếu/kho rồi tải danh sách." if user else "Đăng nhập để tạo và duyệt PO/SO."
        )
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id)
        self.variables["status"].set("Tải lại danh sách theo loại phiếu và kho vừa chọn.")
        self.enable()

    def orders_clear(self):
        self.doc = None
        self.lines = []
        self.permissions = []
        self.catalog_ready = False
        self.products = []
        self.uoms = {}
        self.partners = []
        self.conversions = []
        self.next_after = None
        self.table.delete(*self.table.get_children())
        self.line_table.delete(*self.line_table.get_children())
        for name in ["partner", "product", "conversion", "reason", "heading", "history"]:
            self.variables[name].set("")
        self.partner.configure(values=[])
        self.product.configure(values=[])
        self.conversion.configure(values=[])
        self.busy = False

    def enable(self):
        active = bool(self.presenter.user_id and self.warehouses) and not self.busy
        editable = self.catalog_ready and (
            active
            and not self.presenter.uncertain
            and (
                "edit" in self.doc["allowed_actions"]
                if self.doc
                else ("po.draft" if self.path == "purchase-orders" else "so.draft") in self.permissions
            )
        )
        for widget in [self.kind, self.selector, self.filter, self.load_button]:
            widget.state(["!disabled"] if active else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        for widget in [
            self.partner,
            self.day,
            self.product,
            self.conversion,
            self.qty,
            self.add_button,
            self.remove_button,
        ]:
            widget.state(["!disabled"] if editable else ["disabled"])
        self.reason.state(["!disabled"] if active and not self.presenter.uncertain else ["disabled"])
        self.new_button.state(
            ["!disabled"]
            if active
            and self.catalog_ready
            and not self.presenter.uncertain
            and ("po.draft" if self.path == "purchase-orders" else "so.draft") in self.permissions
            else ["disabled"]
        )
        for action, button in self.buttons.items():
            allowed = (
                editable
                if action == "save"
                else active and self.doc and action in self.doc["allowed_actions"]
            )
            button.state(["!disabled"] if allowed and not self.presenter.uncertain else ["disabled"])
        self.retry_button.state(["!disabled"] if active and self.presenter.uncertain else ["disabled"])

    def load(self, after=None):
        if self.warehouse_id():
            self.presenter.load(self.path, self.warehouse_id(), self.variables["filter"].get(), after)

    def orders_busy(self):
        self.busy = True
        self.enable()
        self.variables["status"].set("Đang xử lý…")

    def orders_loaded(self, page, refs, permissions):
        self.orders_clear()
        self.permissions = permissions
        self.catalog_ready = all(key in refs for key in ["products", "partners", "uoms"])
        self.next_after = page["next_after"]
        self.products = refs.get("products", {}).get("items", [])
        self.uoms = {u["id"]: u["code"] for u in refs.get("uoms", {}).get("items", [])}
        self.partners = [
            p
            for p in refs.get("partners", {}).get("items", [])
            if p["is_supplier" if self.path == "purchase-orders" else "is_customer"]
        ]
        self.partner.configure(values=[f"{p['code']} · {p['name']}" for p in self.partners])
        self.product.configure(values=[f"{p['sku']} · {p['name']}" for p in self.products])
        for doc in page["items"]:
            self.table.insert(
                "",
                "end",
                iid=doc["id"],
                values=(doc["number"], STATUS[doc["status"]], doc["partner_name"], doc["business_date"]),
            )
        limited = any(v.get("next_after") for v in refs.values())
        self.variables["status"].set(
            "Đã tải phiếu. Chọn một phiếu để xem hoặc bấm Tạo mới."
            + (" Danh mục chọn giới hạn 200 mục." if limited else "")
        )
        if (
            "po.draft" if self.path == "purchase-orders" else "so.draft"
        ) in permissions and not self.catalog_ready:
            self.variables["status"].set(
                "Đã tải phiếu. Cần quyền đọc danh mục và đối tác GLOBAL để lập/sửa trên màn này."
            )
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy:
            self.presenter.read(self.path, selected[0])

    def new(self):
        self.doc = None
        self.lines = []
        self.render_lines()
        self.variables["heading"].set("Phiếu mới · Hàng doanh nghiệp")
        self.variables["history"].set("")
        self.variables["reason"].set("")
        self.variables["day"].set(date.today().isoformat())
        if self.partners:
            self.partner.current(0)
        self.enable()

    def orders_read(self, doc):
        self.busy = False
        self.doc = doc
        self.lines = doc["lines"]
        self.variables["heading"].set(
            f"{doc['number']} · {STATUS[doc['status']]} · phiên bản {doc['version']} · người lập {doc['creator_name']}"
        )
        index = next((i for i, p in enumerate(self.partners) if p["id"] == doc["partner_id"]), None)
        if index is not None:
            self.partner.current(index)
        else:
            self.variables["partner"].set(doc["partner_name"] or "")
        self.variables["day"].set(doc["business_date"])
        self.variables["reason"].set("")
        history = []
        for approval in doc["approvals"][-2:]:
            decisions = "; ".join(
                f"Bước {s['step_no']}: {s['decider_name'] or 'Chưa duyệt'} — {s['comment'] or s['status']}"
                for s in approval["steps"]
            )
            label = {**STATUS, "PENDING": "Chờ duyệt", "INVALIDATED": "Đã vô hiệu"}.get(
                approval["status"], approval["status"]
            )
            history.append(f"Lần gửi v{approval['document_version']}: {label} · {decisions}")
        self.variables["history"].set("\n".join(history))
        self.render_lines()
        self.enable()
        self.variables["status"].set("Đã tải chi tiết. Lượng đã thực hiện/còn lại do máy chủ tính.")

    def product_changed(self, event=None):
        index = self.product.current()
        if index >= 0:
            self.presenter.conversions(self.products[index]["id"])

    def orders_conversions(self, page):
        self.busy = False
        self.conversions = page["items"]
        self.conversion.configure(
            values=[
                f"{self.uoms.get(r['uom_id'], 'ĐVT')} ×{r['factor']} · r{r['revision']}"
                for r in self.conversions
            ]
        )
        self.variables["conversion"].set("")
        if self.conversions:
            self.conversion.current(0)
        self.enable()
        self.variables["status"].set("Chọn quy cách và nhập số lượng rồi thêm dòng.")

    def add_line(self):
        p, u = self.product.current(), self.conversion.current()
        if p < 0 or u < 0:
            return
        product, conversion = self.products[p], self.conversions[u]
        self.lines.append(
            dict(
                product_id=product["id"],
                product_uom_id=conversion["id"],
                quantity=self.variables["qty"].get(),
                owner_id=str(COMPANY_OWNER),
                consignment_id=None,
                sku=product["sku"],
                uom_code=self.uoms.get(conversion["uom_id"], f"×{conversion['factor']}"),
                posted_base="0",
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
                    line["sku"],
                    line["uom_code"],
                    line["quantity"],
                    line["posted_base"],
                    line["remaining_base"],
                ),
            )

    def action(self, action):
        reason = self.variables["reason"].get().strip()
        if not reason:
            self.orders_error("Nhập lý do trước khi lưu hoặc chuyển trạng thái.")
            return
        if action == "save":
            partner = self.partner.current()
            if partner < 0:
                self.orders_error("Chọn đối tác đang hoạt động.")
                return
            body = dict(
                warehouse_id=self.warehouse_id(),
                partner_id=self.partners[partner]["id"],
                business_date=self.variables["day"].get(),
                reason=reason,
                lines=[
                    {
                        k: line[k]
                        for k in ["product_id", "product_uom_id", "quantity", "owner_id", "consignment_id"]
                    }
                    for line in self.lines
                ],
            )
            if self.doc:
                body["expected_version"] = self.doc["version"]
            try:
                body = (OrderUpdate if self.doc else OrderInput).model_validate(body).model_dump(mode="json")
            except ValueError:
                self.orders_error(
                    "Kiểm tra ngày, số lượng và quy cách. Quy đổi đã ngừng dùng cần bỏ/thêm lại dòng."
                )
                return
            self.presenter.command(
                "PUT" if self.doc else "POST", self.path + ("/" + self.doc["id"] if self.doc else ""), body
            )
        elif self.doc:
            body = dict(expected_version=self.doc["version"], reason=reason)
            path = "documents/" + self.doc["id"] + "/" + action
            if action in {"approve", "reject"}:
                pending = next((r for r in self.doc["approvals"] if r["can_decide"]), None)
                if not pending:
                    return
                path = "approval-requests/" + pending["id"] + "/decide"
                body["decision"] = action.upper()
            self.presenter.command("POST", path, body)

    def orders_saved(self, result):
        self.busy = False
        self.variables["kind"].set(result["kind"])
        for index, warehouse in enumerate(self.warehouses):
            if str(warehouse.id) == result["warehouse_id"]:
                self.selector.current(index)
                break
        self.presenter.read(self.path, result["id"])

    def orders_error(self, message):
        self.busy = False
        self.enable()
        suffix = (
            " Nội dung nhập vẫn được giữ; tải lại phiếu để đối chiếu khi version đã đổi."
            if self.doc or self.lines
            else ""
        )
        self.variables["status"].set(message + suffix)

    def release_variables(self):
        self.variables.clear()
