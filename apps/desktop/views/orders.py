import tkinter as tk
from datetime import date
from tkinter import ttk

from apps.desktop.presenters.orders import OrderPresenter
from apps.desktop.views.document_review import ReviewPanel, ScrollPanel, fulfillment_label
from packages.contracts.orders import AssignmentInput, OrderInput, OrderUpdate
from packages.contracts.traceability import COMPANY_OWNER

STATUS = {
    "DRAFT": "Nháp",
    "SUBMITTED": "Chờ duyệt",
    "APPROVED": "Đã duyệt",
    "REJECTED": "Từ chối",
    "PARTIAL": "Thực hiện một phần",
    "COMPLETED": "Kết thúc · xem chi tiết",
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
                "query",
                "candidate_query",
                "uncertainty",
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
        self.candidates = []
        self.assignees = {}
        self.candidate_after = None
        self.page_cursors = [None]
        self.page_index = 0
        self.page_query = ""
        self.on_open_receipt = None
        self.on_open_approvals = None
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
        for box in [self.kind, self.selector, self.filter]:
            box.bind("<<ComboboxSelected>>", self.scope_changed)
        search = ttk.Frame(self)
        search.pack(fill="x", pady=3)
        ttk.Label(search, text="Số phiếu / đối tác").pack(side="left")
        self.search = ttk.Entry(search, textvariable=self.variables["query"], width=35)
        self.search.pack(side="left", padx=4)
        self.search.bind("<Return>", lambda event: self.load())
        ttk.Button(search, text="Tìm", command=self.load).pack(side="left")
        self.next_button = ttk.Button(search, text="Trang sau", command=lambda: self.load(self.next_after))
        self.next_button.pack(side="right")
        self.previous_button = ttk.Button(search, text="Trang trước", command=self.previous_page)
        self.previous_button.pack(side="right", padx=4)
        ttk.Label(self, textvariable=self.variables["status"], wraplength=820).pack(fill="x", pady=5)
        self.table = self.tree(
            self,
            ["number", "status", "partner", "day"],
            ["Số phiếu", "Trạng thái", "Đối tác", "Ngày"],
            [220, 150, 290, 120],
            3,
        )
        self.table.bind("<<TreeviewSelect>>", self.select)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(5, 2))
        self.new_button = ttk.Button(bar, text="Tạo mới", command=self.new)
        self.new_button.pack(side="right")
        self.reload_button = ttk.Button(bar, text="Đọc lại phiếu", command=self.reload)
        self.reload_button.pack(side="right", padx=5)
        ttk.Label(bar, textvariable=self.variables["heading"], wraplength=520).pack(side="left", fill="x", expand=True)
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        self.details = ttk.Notebook(self)
        self.details.pack(fill="both", expand=True)
        self.form_panels = [ScrollPanel(self.details) for _ in range(3)]
        for panel, name in zip(self.form_panels, ("Nội dung", "Phân công", "Lịch sử duyệt")):
            self.details.add(panel, text=name)
        content, assignment, history = [panel.inner for panel in self.form_panels]
        self.review_panel = ReviewPanel(self.details, self.load_review)
        self.details.add(self.review_panel, text="So sánh phiên bản")
        self.history_text = tk.Text(history, height=7, wrap="word", state="disabled")
        self.history_text.pack(fill="both", expand=True)
        assignment_search = ttk.Frame(assignment)
        assignment_search.pack(fill="x")
        ttk.Label(assignment_search, text="Tên / tài khoản").pack(side="left")
        self.candidate_search = ttk.Entry(assignment_search, textvariable=self.variables["candidate_query"])
        self.candidate_search.pack(side="left", padx=4)
        self.candidate_search.bind("<Return>", lambda event: self.load_candidates())
        self.candidate_button = ttk.Button(assignment_search, text="Tìm người", command=self.load_candidates)
        self.candidate_button.pack(side="left")
        self.candidate_next = ttk.Button(assignment_search, text="Trang sau", command=lambda: self.load_candidates(self.candidate_after))
        self.candidate_next.pack(side="left", padx=4)
        lists = ttk.Frame(assignment)
        lists.pack(fill="both", expand=True)
        available = ttk.LabelFrame(lists, text="Có quyền đọc tại kho")
        available.pack(side="left", fill="both", expand=True)
        selected = ttk.LabelFrame(lists, text="Được phân công (giữ qua các trang tìm)")
        selected.pack(side="left", fill="both", expand=True)
        self.candidate_table = self.tree(available, ["name"], ["Người xử lý"], [300], 4)
        self.assignee_table = self.tree(selected, ["name"], ["Tên hoặc mã người dùng"], [300], 4)
        self.candidate_table.bind("<Return>", lambda event: self.add_assignee())
        self.candidate_table.bind("<Double-1>", lambda event: self.add_assignee())
        self.assignee_table.bind("<Delete>", lambda event: self.remove_assignee())
        self.assign_add = ttk.Button(available, text="Thêm →", command=self.add_assignee)
        self.assign_add.pack(anchor="w")
        self.assign_remove = ttk.Button(selected, text="Bỏ người đã chọn", command=self.remove_assignee)
        self.assign_remove.pack(anchor="w")
        self.assign_save = ttk.Button(assignment, text="Lưu phân công", command=self.save_assignments)
        self.assign_save.pack(anchor="w", pady=4)
        header = ttk.Frame(content)
        header.pack(fill="x")
        ttk.Label(header, text="Đối tác").pack(side="left")
        self.partner = self.combo(header, "partner", 49)
        self.partner.pack(side="left", padx=5)
        ttk.Label(header, text="Ngày").pack(side="left")
        self.day = ttk.Entry(header, textvariable=self.variables["day"], width=12)
        self.day.pack(side="left", padx=5)
        self.line_table = self.tree(
            content,
            ["sku", "unit", "qty", "posted", "remaining", "closed"],
            ["Sản phẩm", "Đơn vị", "Yêu cầu", "Đã nhận/xuất", "Còn mở", "Đã đóng"],
            [220, 80, 100, 100, 100, 100],
            4,
        )
        editor = ttk.Frame(content)
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
        links = ttk.Frame(content)
        links.pack(fill="x", pady=3)
        self.receipt_button = ttk.Button(links, text="Mở nhận hàng", command=self.open_receipt)
        self.receipt_button.pack(side="left")
        self.approval_button = ttk.Button(links, text="Mở hộp thư duyệt", command=self.open_approvals)
        self.approval_button.pack(side="left", padx=4)
        ttk.Label(content, text="Đã nhận/xuất, còn mở và đã đóng tính theo đơn vị cơ sở; đóng thiếu không phải nhận/xuất đủ.",
                  wraplength=760).pack(fill="x", pady=3)
        reason = ttk.Frame(footer)
        reason.pack(fill="x", pady=4)
        ttk.Label(reason, text="Lý do").pack(side="left")
        self.reason = ttk.Entry(reason, textvariable=self.variables["reason"])
        self.reason.pack(side="left", fill="x", expand=True, padx=5)
        actions = ttk.Frame(footer)
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
            footer, text="Gửi lại đúng yêu cầu chưa rõ kết quả", command=self.presenter.retry
        )
        self.retry_button.pack(anchor="w", pady=3)
        ttk.Label(footer, textvariable=self.variables["uncertainty"], wraplength=730).pack(fill="x")
        ttk.Label(
            footer,
            text="PO/SO không ghi sổ tồn. Màn này chưa có thao tác xuất kho; số đã xuất chỉ đọc từ máy chủ.",
            wraplength=730,
        ).pack(fill="x")
        for panel in self.form_panels:
            panel.bind_scrolling()
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
        self.page_cursors, self.page_index, self.page_query = [None], 0, ""
        self.variables["query"].set("")
        self.variables["candidate_query"].set("")
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
        self.page_cursors, self.page_index = [None], 0
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
        self.assignees = {}
        self.candidates = []
        self.candidate_after = None
        self.candidate_table.delete(*self.candidate_table.get_children())
        self.assignee_table.delete(*self.assignee_table.get_children())
        self.review_panel.clear()
        self.set_history("")

    def enable(self):
        active = bool(self.presenter.user_id and self.warehouses) and not self.busy
        editable = self.catalog_ready and (
            active
            and not self.presenter.uncertain
            and not self.presenter.needs_reload
            and (
                "edit" in self.doc["allowed_actions"]
                if self.doc
                else ("po.draft" if self.path == "purchase-orders" else "so.draft") in self.permissions
            )
        )
        for widget in [self.kind, self.selector, self.filter, self.load_button]:
            widget.state(["!disabled"] if active else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        self.previous_button.state(["!disabled"] if active and self.page_index else ["disabled"])
        self.reload_button.state(["!disabled"] if active and self.doc else ["disabled"])
        self.review_panel.load_button.state(["!disabled"] if active and self.doc else ["disabled"])
        assignable = bool(active and self.doc and "assign" in self.doc["allowed_actions"]
                          and not self.presenter.uncertain and not self.presenter.needs_reload)
        for widget in [self.candidate_button, self.candidate_search, self.assign_add, self.assign_remove, self.assign_save]:
            widget.state(["!disabled"] if assignable else ["disabled"])
        self.candidate_next.state(["!disabled"] if assignable and self.candidate_after else ["disabled"])
        self.receipt_button.state(["!disabled"] if active and self.doc and self.doc["kind"] == "PO"
                                  and self.doc["status"] in {"APPROVED", "PARTIAL"} else ["disabled"])
        self.approval_button.state(["!disabled"] if active else ["disabled"])
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
            button.state(["!disabled"] if allowed and not self.presenter.uncertain and not self.presenter.needs_reload else ["disabled"])
        self.retry_button.state(["!disabled"] if active and self.presenter.uncertain else ["disabled"])
        self.variables["uncertainty"].set(
            "UNKNOWN · Chưa rõ kết quả lệnh trước. Yêu cầu và khóa chống trùng vẫn được giữ khi đổi màn hình."
            if self.presenter.uncertain else "")

    def load(self, after=None):
        if self.warehouse_id() and not self.busy:
            query = self.variables["query"].get().strip()
            if query != self.page_query:
                after = None
            self.page_query = query
            if after is None:
                self.page_cursors, self.page_index = [None], 0
            elif self.page_index + 1 == len(self.page_cursors):
                self.page_cursors.append(after)
                self.page_index += 1
            else:
                self.page_index += 1
                self.page_cursors[self.page_index:] = [after]
            self.presenter.load(self.path, self.warehouse_id(), self.variables["filter"].get(), after,
                                self.page_query)

    def previous_page(self):
        if self.page_index and not self.busy:
            self.page_index -= 1
            self.presenter.load(self.path, self.warehouse_id(), self.variables["filter"].get(),
                                self.page_cursors[self.page_index], self.page_query)

    def reload(self):
        if self.doc and not self.busy:
            self.presenter.read(self.path, self.doc["id"])

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
        if self.new_button.instate(["disabled"]):
            return
        self.doc = None
        self.lines = []
        self.render_lines()
        self.variables["heading"].set("Phiếu mới · Hàng doanh nghiệp")
        self.variables["history"].set("")
        self.set_history("")
        self.review_panel.clear()
        self.assignees = {}
        self.render_assignees()
        self.presenter.needs_reload = False
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
            f"{doc['number']} · {fulfillment_label(doc)} · v{doc['version']} · {doc['creator_name']}"
        )
        index = next((i for i, p in enumerate(self.partners) if p["id"] == doc["partner_id"]), None)
        if index is not None:
            self.partner.current(index)
        else:
            self.variables["partner"].set(doc["partner_name"] or "")
        self.variables["day"].set(doc["business_date"])
        self.variables["reason"].set("")
        history = []
        for approval in doc["approvals"]:
            decisions = "; ".join(
                f"Bước {s['step_no']} ({'/'.join(s['roles'])}): {s['decider_name'] or 'Chưa duyệt'} — {s['comment'] or s['status']}"
                for s in approval["steps"]
            )
            label = {**STATUS, "PENDING": "Chờ duyệt", "INVALIDATED": "Đã vô hiệu"}.get(
                approval["status"], approval["status"]
            )
            history.append(f"Lần gửi v{approval['document_version']}: {label} · {decisions}")
        self.variables["history"].set("\n".join(history))
        self.set_history(self.variables["history"].get())
        self.assignees = {user_id: user_id for user_id in doc["assigned_user_ids"]}
        self.render_assignees()
        self.candidates = []
        self.candidate_after = None
        self.candidate_table.delete(*self.candidate_table.get_children())
        self.review_panel.clear()
        self.line_table.heading("posted", text="Đã nhận (CS)" if doc["kind"] == "PO" else "Đã xuất (CS)")
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
                    line.get("closed_base", "0"),
                ),
            )

    def action(self, action):
        if self.busy or self.buttons[action].instate(["disabled"]):
            return
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
        self.review_panel.release_variables()
        self.variables.clear()
        self.on_open_receipt = self.on_open_approvals = None

    def set_history(self, value):
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.insert("1.0", value)
        self.history_text.configure(state="disabled")

    def load_review(self):
        if self.doc and not self.busy:
            self.presenter.review(self.doc["id"])

    def orders_review(self, result):
        self.busy = False
        self.review_panel.loaded(result)
        if self.doc and result["current_version"] != self.doc["version"]:
            self.presenter.needs_reload = True
            self.orders_error("Version máy chủ đã đổi. Đọc lại phiếu trước khi quyết định.")
        else:
            self.variables["status"].set("Đã tải các bản lưu gửi duyệt để đối chiếu.")
            self.enable()

    def load_candidates(self, after=None):
        if self.doc and not self.busy and not self.candidate_button.instate(["disabled"]):
            self.presenter.candidates(self.doc["id"], self.variables["candidate_query"].get().strip(), after)

    def orders_candidates(self, page):
        self.busy = False
        self.candidates = page["items"]
        self.candidate_after = page["next_after"]
        self.candidate_table.delete(*self.candidate_table.get_children())
        for person in self.candidates:
            label = f"{person['display_name']} · {person['username']}"
            self.candidate_table.insert("", "end", iid=person["id"], values=(label,))
            if person["id"] in self.assignees:
                self.assignees[person["id"]] = label
        self.render_assignees()
        self.variables["status"].set("Chọn người để thêm/bỏ; nhập lý do rồi lưu toàn bộ phân công.")
        self.enable()

    def render_assignees(self):
        self.assignee_table.delete(*self.assignee_table.get_children())
        for user_id, label in self.assignees.items():
            self.assignee_table.insert("", "end", iid=user_id, values=(label,))

    def add_assignee(self):
        if self.assign_add.instate(["disabled"]):
            return
        for user_id in self.candidate_table.selection():
            self.assignees[user_id] = self.candidate_table.item(user_id, "values")[0]
        self.render_assignees()

    def remove_assignee(self):
        if self.assign_remove.instate(["disabled"]):
            return
        for user_id in self.assignee_table.selection():
            self.assignees.pop(user_id, None)
        self.render_assignees()

    def save_assignments(self):
        if not self.doc or self.assign_save.instate(["disabled"]):
            return
        try:
            body = AssignmentInput(expected_version=self.doc["version"], user_ids=list(self.assignees),
                                   reason=self.variables["reason"].get().strip()).model_dump(mode="json")
        except ValueError:
            self.orders_error("Nhập lý do và chọn tối đa 50 người được phân công.")
            return
        self.presenter.command("POST", f"documents/{self.doc['id']}/assignments", body)

    def open_receipt(self):
        if self.on_open_receipt and not self.receipt_button.instate(["disabled"]):
            self.on_open_receipt(self.doc)

    def open_approvals(self):
        if self.on_open_approvals and not self.approval_button.instate(["disabled"]):
            self.on_open_approvals(self.variables["kind"].get(), self.warehouse_id())
