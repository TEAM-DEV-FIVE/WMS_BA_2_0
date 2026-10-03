import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk
from uuid import UUID, uuid4

from pydantic import ValidationError

from apps.desktop.presenters.openings import OpeningPresenter, validate_lines
from packages.contracts.openings import OpeningInput, OpeningPost, OpeningUpdate
from packages.contracts.orders import DecisionInput, OrderAction
from packages.contracts.traceability import COMPANY_OWNER

STATUS = {
    "DRAFT": "Nháp",
    "SUBMITTED": "Chờ duyệt",
    "APPROVED": "Đã duyệt",
    "REJECTED": "Từ chối",
    "COMPLETED": "Hoàn tất",
    "CANCELLED": "Đã hủy",
}
LINE_FIELDS = (
    "product_id",
    "quantity_base",
    "owner_id",
    "destination_location_id",
    "lot_code",
    "serial_code",
    "manufactured_on",
    "expires_on",
)


class OpeningView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent)
        self.presenter = OpeningPresenter(self, api)
        self.variables = {
            name: tk.StringVar()
            for name in (
                "warehouse",
                "filter",
                "status",
                "heading",
                "batch",
                "day",
                "reference",
                "reason",
                "product",
                "location",
                "product_query",
                "location_query",
                "unit",
                "qty",
                "lot",
                "serial",
                "manufactured",
                "expiry",
                "history",
                "operation",
                "ack",
                "reconciliation",
            )
        }
        self.doc = self.ack = None
        self.lines, self.warehouses, self.permissions = [], [], []
        self.products, self.locations, self.units = {}, {}, {}
        self.catalogs = {"products": [], "locations": []}
        self.cursors = {"products": None, "locations": None}
        self.queries = {"products": "", "locations": ""}
        self.next_after = None
        self.busy = self.catalog_ready = self.dirty = False
        self.edit_index = None
        # The form stays usable on the shell's minimum size and at large fonts.
        canvas = self.canvas = tk.Canvas(self, highlightthickness=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = self.content = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        top = self.row()
        self.selector = self.combo(top, "warehouse", 30)
        self.filter = self.combo(top, "filter", 13, [""] + list(STATUS))
        self.selector.bind("<<ComboboxSelected>>", self.scope_changed)
        self.filter.bind("<<ComboboxSelected>>", self.scope_changed)
        self.load_button = self.button(top, "Tải phiếu", self.load)
        self.next_button = self.button(top, "Trang sau", lambda: self.load(self.next_after))
        self.new_button = self.button(top, "Tạo mới", self.new)
        self.label("status")
        self.table = self.tree(
            ["number", "status", "day", "creator"], ["Số phiếu", "Trạng thái", "Ngày", "Người lập"], 3
        )
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.label("heading")
        header = self.row()
        self.batch = self.entry(header, "batch", "Batch UUID", 37)
        self.day = self.entry(header, "day", "Ngày", 12)
        self.reference = self.entry(self.row(), "reference", "Biên bản đã ký", 65)
        self.line_table = self.tree(
            ["sku", "unit", "qty", "location", "tracking", "posted", "remaining"],
            ["SKU", "ĐVT cơ sở", "Lượng", "Vị trí", "Lô / Serial", "Đã ghi", "Còn"],
            4,
        )
        self.line_table.bind("<<TreeviewSelect>>", self.edit_line)
        self.search_widgets = []
        for resource, name, label in [("products", "product", "SKU"), ("locations", "location", "Vị trí")]:
            row = self.row()
            query = self.entry(row, name + "_query", label, 17)
            search = self.button(row, "Tìm", lambda r=resource, n=name: self.search(r, n))
            more = self.button(row, "Trang sau", lambda r=resource, n=name: self.search(r, n, True))
            box = self.combo(row, name, 39)
            setattr(self, name, box)
            self.search_widgets.extend([query, search, more, box])
        self.product.bind("<<ComboboxSelected>>", self.product_changed)
        row = self.row()
        self.qty = self.entry(row, "qty", "Lượng cơ sở", 13)
        ttk.Label(row, textvariable=self.variables["unit"]).pack(side="left", padx=4)
        row = self.row()
        self.lot = self.entry(row, "lot", "Lô", 22)
        self.serial = self.entry(row, "serial", "Serial", 27)
        row = self.row()
        self.manufactured = self.entry(row, "manufactured", "NSX YYYY-MM-DD", 12)
        self.expiry = self.entry(row, "expiry", "HSD YYYY-MM-DD", 12)
        row = self.row()
        self.add_button = self.button(row, "Thêm dòng", self.add_line)
        self.update_button = self.button(row, "Cập nhật dòng chọn", lambda: self.add_line(replace=True))
        self.remove_button = self.button(row, "Bỏ dòng chọn", self.remove_line)
        self.reason = self.entry(self.row(), "reason", "Lý do", 70)
        row = self.row()
        self.buttons = {
            action: self.button(row, label, lambda a=action: self.action(a))
            for action, label in [
                ("save", "Lưu nháp"),
                ("submit", "Gửi duyệt"),
                ("approve", "Duyệt"),
                ("reject", "Từ chối"),
                ("revise", "Sửa lại"),
                ("cancel", "Hủy"),
                ("post", "Ghi sổ"),
            ]
        }
        self.label("history")
        row = self.row()
        self.operation = self.entry(row, "operation", "HTTP key / ACK", 37)
        self.lookup_button = self.button(row, "Tra trạng thái / ACK", self.lookup)
        self.retry_button = self.button(self.row(), "Gửi lại nguyên yêu cầu đã tra", self.presenter.retry)
        self.label("ack")
        self.label("reconciliation")
        ttk.Label(
            content,
            text="COMPANY · Tối đa 200 dòng · Chỉ một lần ghi toàn bộ/kho chưa có lịch sử.\n"
            "DRAFT: nháp trên màn hình · SYNCED: máy chủ đã lưu · UNKNOWN: chưa rõ kết quả · "
            "POSTED: đã nhận ACK ghi sổ.\nYêu cầu chưa rõ kết quả chỉ được giữ trong lần mở ứng dụng này.",
            wraplength=740,
            justify="left",
        ).pack(fill="x", pady=4)
        self.opening_clear()
        self.variables["status"].set("Đăng nhập, chọn kho rồi tải phiếu tồn đầu kỳ.")
        self.enable()

    def row(self):
        row = ttk.Frame(self.content)
        row.pack(fill="x", pady=3)
        return row

    def label(self, name):
        ttk.Label(self.content, textvariable=self.variables[name], wraplength=740, justify="left").pack(
            fill="x", pady=3
        )

    def combo(self, row, name, width, values=()):
        box = ttk.Combobox(
            row, textvariable=self.variables[name], width=width, values=values, state="readonly"
        )
        box.pack(side="left", padx=3)
        return box

    def entry(self, row, name, label, width):
        ttk.Label(row, text=label).pack(side="left", padx=3)
        entry = ttk.Entry(row, textvariable=self.variables[name], width=width)
        entry.pack(side="left", padx=3, fill="x", expand=True)
        if name in {"day", "reference", "batch"}:
            entry.bind("<KeyRelease>", lambda event: self.mark_dirty())
        return entry

    def button(self, row, label, callback):
        button = ttk.Button(row, text=label, command=callback)
        button.pack(side="left", padx=2)
        return button

    def tree(self, columns, labels, height):
        container = ttk.Frame(self.content)
        container.pack(fill="x", pady=3)
        container.columnconfigure(0, weight=1)
        tree = ttk.Treeview(container, columns=columns, show="headings", height=height, selectmode="browse")
        for column, label in zip(columns, labels):
            tree.heading(column, text=label)
            tree.column(column, width=105, minwidth=65)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return tree

    def warehouse_id(self):
        index = self.selector.current()
        return str(self.warehouses[index].id) if index >= 0 else None

    def session_changed(self, user=None, warehouses=None):
        self.warehouses = list(warehouses or [])
        self.selector.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])
        self.variables["warehouse"].set("")
        if self.warehouses:
            self.selector.current(0)
        self.presenter.reset(user.id if user else None, self.warehouse_id())
        self.variables["status"].set(
            "Chọn kho rồi tải phiếu." if user else "Đăng nhập để thao tác tồn đầu kỳ."
        )
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id, self.warehouse_id())
        self.variables["status"].set("Tải lại danh sách theo kho và bộ lọc vừa chọn.")
        self.enable()

    def opening_clear(self):
        self.doc = self.ack = None
        self.lines, self.permissions = [], []
        self.products, self.locations, self.units = {}, {}, {}
        self.catalogs = {"products": [], "locations": []}
        self.cursors = {"products": None, "locations": None}
        self.queries = {"products": "", "locations": ""}
        self.next_after = self.edit_index = None
        self.busy = self.catalog_ready = self.dirty = False
        self.table.delete(*self.table.get_children())
        self.line_table.delete(*self.line_table.get_children())
        for name, variable in self.variables.items():
            if name not in {"warehouse", "filter", "status"}:
                variable.set("")
        self.product.configure(values=[])
        self.location.configure(values=[])
        self.enable()

    @property
    def editable(self):
        return (
            self.catalog_ready
            and not self.busy
            and not self.presenter.uncertain
            and ("edit" in self.doc["allowed_actions"] if self.doc else "opening.draft" in self.permissions)
        )

    def enable(self):
        active = bool(all(self.presenter.scope)) and not self.busy
        uncertain = self.presenter.uncertain
        for widget in [self.selector, self.filter, self.load_button]:
            widget.state(["!disabled"] if active else ["disabled"])
        self.next_button.state(["!disabled"] if active and self.next_after else ["disabled"])
        self.new_button.state(
            ["!disabled"]
            if active and self.catalog_ready and not uncertain and "opening.draft" in self.permissions
            else ["disabled"]
        )
        for widget in [
            self.day,
            self.reference,
            self.qty,
            self.lot,
            self.serial,
            self.manufactured,
            self.expiry,
            self.add_button,
            self.remove_button,
            *self.search_widgets,
        ]:
            widget.state(["!disabled"] if self.editable else ["disabled"])
        self.update_button.state(
            ["!disabled"] if self.editable and self.edit_index is not None else ["disabled"]
        )
        self.batch.state(["!disabled"] if self.editable and not self.doc else ["disabled"])
        self.reason.state(["!disabled"] if active and not uncertain else ["disabled"])
        for action, button in self.buttons.items():
            allowed = (
                self.editable
                if action == "save"
                else active and self.doc and action in self.doc["allowed_actions"]
            )
            button.state(["!disabled"] if allowed and not uncertain else ["disabled"])
        self.operation.state(["!disabled"] if active and not uncertain else ["disabled"])
        self.lookup_button.state(["!disabled"] if active else ["disabled"])
        self.retry_button.state(["!disabled"] if active and uncertain and uncertain.checked else ["disabled"])
        if uncertain:
            self.variables["operation"].set(uncertain.key)
            self.variables["ack"].set(
                "UNKNOWN · "
                + (f"Execution: {uncertain.body['execution_key']} · " if uncertain.post else "")
                + "Giữ nguyên batch, HTTP key và nội dung. Tra trạng thái trước khi gửi lại."
            )

    def load(self, after=None):
        self.presenter.load(self.variables["filter"].get(), after)

    def opening_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def opening_loaded(self, page, refs, permissions):
        self.opening_clear()
        self.permissions = permissions
        self.catalog_ready = all(key in refs for key in ("products", "locations"))
        self.next_after = page["next_after"]
        for resource, values in refs.items():
            self.set_catalog(resource, values)
        for doc in page["items"]:
            self.table.insert(
                "",
                "end",
                iid=doc["id"],
                values=(
                    doc["number"],
                    STATUS.get(doc["status"], doc["status"]),
                    doc["business_date"],
                    doc["creator_name"],
                ),
            )
        self.variables["status"].set(
            "Đã tải phiếu. Chọn phiếu hoặc Tạo mới."
            + (" Cần quyền đọc danh mục để lập/sửa." if not self.catalog_ready else "")
        )
        self.enable()

    def set_catalog(self, resource, page):
        rows = page["items"]
        if resource == "locations":
            rows = [
                r
                for r in rows
                if r["kind"] in {"STORAGE", "RECEIVING", "QUARANTINE", "SHIPPING"}
                and r["warehouse_id"] == self.presenter.warehouse
            ]
        self.catalogs[resource] = rows
        self.cursors[resource] = page.get("next_after")
        cache = self.products if resource == "products" else self.locations
        cache.update({r["id"]: r for r in rows})
        name = "product" if resource == "products" else "location"
        getattr(self, name).configure(values=[f"{r.get('sku', r.get('code'))} · {r['name']}" for r in rows])
        self.variables[name].set("")
        if name == "product":
            self.variables["unit"].set("")

    def search(self, resource, name, more=False):
        if self.editable:
            query = self.variables[name + "_query"].get()
            more = more and query == self.queries[resource]
            if more and not self.cursors[resource]:
                return
            self.queries[resource] = query
            self.presenter.catalog(resource, query, self.cursors[resource] if more else None)

    def opening_catalog(self, resource, page):
        self.busy = False
        self.set_catalog(resource, page)
        self.variables["status"].set(
            "Đã tải danh mục." + (" Còn trang sau." if page.get("next_after") else " Hết danh sách.")
        )
        self.enable()

    def selected_id(self, name):
        index = getattr(self, name).current()
        rows = self.catalogs["products" if name == "product" else "locations"]
        return rows[index]["id"] if 0 <= index < len(rows) else None

    def product_changed(self, event=None):
        product_id = self.selected_id("product")
        if product_id:
            self.presenter.product(product_id)

    def opening_product(self, product, unit):
        self.busy = False
        self.products[product["id"]] = product
        self.units[unit["id"]] = unit
        self.variables["unit"].set(
            f"{unit['code']} · {product['tracking']} · {unit['decimal_places']} chữ số lẻ"
        )
        self.variables["status"].set("Nhập lượng theo đơn vị cơ sở; giữ nguyên mã lô/serial, kể cả số 0 đầu.")
        self.enable()

    def new(self):
        if self.presenter.uncertain or self.busy or "opening.draft" not in self.permissions:
            return
        self.doc = self.ack = None
        self.lines = []
        self.edit_index = None
        for name in (
            "reference",
            "reason",
            "history",
            "operation",
            "ack",
            "reconciliation",
            "lot",
            "serial",
            "manufactured",
            "expiry",
        ):
            self.variables[name].set("")
        self.variables["batch"].set(str(uuid4()))
        self.variables["day"].set(date.today().isoformat())
        self.variables["qty"].set("1")
        self.variables["heading"].set("Phiếu mới · COMPANY")
        self.mark_dirty()
        self.render_lines()

    def mark_dirty(self):
        if not self.editable:
            return
        self.dirty = True
        self.variables["status"].set("DRAFT · Nội dung trên màn hình chưa lưu máy chủ.")
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy:
            self.presenter.read(selected[0])

    def opening_read(self, doc, *, stale=False):
        self.busy = self.dirty = False
        self.doc = doc
        self.edit_index = None
        plans = {p["document_line_id"]: p for p in doc["plan"]}
        self.lines = [{**line, **plans[line["id"]]} for line in doc["lines"]]
        self.variables["batch"].set(doc["batch_key"])
        self.variables["day"].set(doc["business_date"])
        self.variables["reference"].set(doc["signed_count_reference"])
        self.variables["reason"].set("")
        self.variables["heading"].set(
            f"{doc['number']} · {STATUS.get(doc['status'], doc['status'])} · v{doc['version']} · {doc['creator_name']}"
        )
        self.variables["history"].set(
            "\n".join(
                f"Duyệt v{r['document_version']} · {r['status']} · "
                + "; ".join(
                    f"Bước {s['step_no']} ({'/'.join(s['roles'])}): {s['decider_name'] or 'Chưa duyệt'} · {s['comment'] or s['status']}"
                    for s in r["steps"]
                )
                for r in doc["approvals"]
            )
        )
        posted = self.ack and self.ack["id"] == doc["id"]
        state = (
            "UNKNOWN · Yêu cầu đang chờ tra ACK/kết quả."
            if self.presenter.uncertain
            else "POSTED · Đã nhận ACK ghi sổ."
            if posted
            else "SYNCED · Đã tải phiên bản máy chủ."
        )
        self.variables["status"].set(
            state + (" STALE: đã làm mới; kiểm tra nội dung trước khi thao tác tiếp." if stale else "")
        )
        if not posted and not self.presenter.uncertain:
            self.variables["ack"].set("Chưa tra ACK cho phiếu này.")
        complete = bool(self.lines) and all(
            Decimal(line["posted_base"]) == Decimal(line["base_quantity"])
            and Decimal(line["remaining_base"]) == 0
            for line in self.lines
        )
        self.variables["reconciliation"].set(
            "Đối chiếu dòng từ máy chủ: "
            + ("đã ghi đủ mọi dòng, còn lại 0." if complete else "xem cột Đã ghi / Còn.")
            + " Lượng ở đơn vị cơ sở từng SKU; đây không phải báo cáo đối soát toàn bộ sổ/số dư."
        )
        self.render_lines()
        self.enable()

    def line_payloads(self, lines=None):
        return [
            {key: line.get(key) for key in LINE_FIELDS} for line in (self.lines if lines is None else lines)
        ]

    def add_line(self, replace=False):
        if not self.editable:
            return
        product_id, location_id = self.selected_id("product"), self.selected_id("location")
        product = self.products.get(product_id)
        unit = self.units.get(product["base_uom_id"]) if product else None
        if not product or not unit or not location_id:
            self.opening_error("Chọn SKU, tải đơn vị cơ sở và chọn vị trí trong kho.")
            return
        line = dict(
            product_id=product_id,
            quantity_base=self.variables["qty"].get(),
            owner_id=str(COMPANY_OWNER),
            destination_location_id=location_id,
            sku=product["sku"],
            base_uom_code=unit["code"],
            location_code=self.locations[location_id]["code"],
            posted_base="0",
            remaining_base="—",
        )
        for field, name in [
            ("lot_code", "lot"),
            ("serial_code", "serial"),
            ("manufactured_on", "manufactured"),
            ("expires_on", "expiry"),
        ]:
            line[field] = self.variables[name].get() or None
        lines = list(self.lines)
        if replace:
            if self.edit_index is None:
                return
            lines[self.edit_index] = line
        else:
            lines.append(line)
        try:
            validate_lines(self.line_payloads(lines), self.products, self.units)
        except ValueError as error:
            self.validation_error(error)
            return
        self.lines, self.edit_index = lines, None
        self.mark_dirty()
        self.render_lines()

    def edit_line(self, event=None):
        selected = self.line_table.selection()
        if not selected or not self.editable:
            return
        self.edit_index = int(selected[0])
        line = self.lines[self.edit_index]
        for name, resource, field in [
            ("product", "products", "product_id"),
            ("location", "locations", "destination_location_id"),
        ]:
            rows = self.catalogs[resource]
            index = next((i for i, r in enumerate(rows) if r["id"] == line[field]), None)
            self.variables[name].set("")
            if index is not None:
                getattr(self, name).current(index)
        for field, name in [
            ("quantity_base", "qty"),
            ("lot_code", "lot"),
            ("serial_code", "serial"),
            ("manufactured_on", "manufactured"),
            ("expires_on", "expiry"),
        ]:
            self.variables[name].set(line.get(field) or "")
        self.product_changed()
        self.enable()

    def remove_line(self):
        selected = self.line_table.selection()
        if selected and self.editable:
            self.lines.pop(int(selected[0]))
            self.edit_index = None
            self.mark_dirty()
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
                    line["base_uom_code"],
                    line["quantity_base"],
                    line["location_code"],
                    line.get("lot_code") or line.get("serial_code") or "—",
                    line["posted_base"],
                    line["remaining_base"],
                ),
            )

    def action(self, action):
        if self.busy or self.presenter.uncertain:
            return
        reason = self.variables["reason"].get().strip()
        try:
            if action == "save":
                if not self.editable:
                    return
                lines = self.line_payloads()
                validate_lines(lines, self.products, self.units)
                body = dict(
                    warehouse_id=self.warehouse_id(),
                    batch_key=self.variables["batch"].get(),
                    business_date=self.variables["day"].get(),
                    signed_count_reference=self.variables["reference"].get(),
                    reason=reason,
                    lines=lines,
                )
                if self.doc:
                    body["expected_version"] = self.doc["version"]
                body = (
                    (OpeningUpdate if self.doc else OpeningInput).model_validate(body).model_dump(mode="json")
                )
                doc_id = self.doc["id"] if self.doc else None
                self.presenter.command(
                    "PUT" if doc_id else "POST", "openings" + ("/" + doc_id if doc_id else ""), body, doc_id
                )
            elif self.doc and action in self.doc["allowed_actions"]:
                # Reason is an action comment, but other unsaved edits must not
                # silently disappear when submitting/approving a server version.
                if self.editable and (
                    self.line_payloads() != self.line_payloads(self.doc["plan"])
                    or self.variables["reference"].get() != self.doc["signed_count_reference"]
                    or self.variables["day"].get() != self.doc["business_date"]
                ):
                    raise ValueError("Lưu các thay đổi nháp trước khi chuyển trạng thái.")
                body = dict(expected_version=self.doc["version"], reason=reason)
                path, contract = "documents/" + self.doc["id"] + "/" + action, OrderAction
                if action in {"approve", "reject"}:
                    pending = next((r for r in self.doc["approvals"] if r["can_decide"]), None)
                    if not pending:
                        return
                    path, contract = "approval-requests/" + pending["id"] + "/decide", DecisionInput
                    body["decision"] = action.upper()
                elif action == "post":
                    path, contract = "openings/" + self.doc["id"] + "/post", OpeningPost
                    body["execution_key"] = str(uuid4())
                body = contract.model_validate(body).model_dump(mode="json")
                self.presenter.command("POST", path, body, self.doc["id"], post=action == "post")
        except ValueError as error:
            self.validation_error(error)

    def validation_error(self, error):
        if isinstance(error, ValidationError):
            fields = ", ".join(".".join(map(str, e["loc"])) for e in error.errors())
            self.opening_error(
                "Kiểm tra UUID, ngày YYYY-MM-DD, lượng dương và lý do/biên bản từ 3 ký tự: " + fields
            )
        else:
            self.opening_error(str(error))

    def lookup(self):
        if self.presenter.uncertain:
            self.presenter.lookup()
            return
        try:
            key = str(UUID(self.variables["operation"].get()))
        except ValueError:
            self.opening_error("Nhập HTTP Idempotency-Key UUID của lần ghi sổ để tra ACK.")
            return
        self.presenter.lookup(key)

    def opening_saved(self, result, key, post):
        self.busy = False
        self.variables["operation"].set(key)
        if post:
            self.ack = result
            self.variables["ack"].set(
                f"POSTED · ACK transaction: {result['transaction_id']} · request: {result['request_id']}"
            )
        self.presenter.read(result["id"])

    def opening_checked(self, doc):
        self.busy = False
        summary = (
            f"Máy chủ: {doc['number']} · {doc['status']} · v{doc['version']}. "
            if doc
            else "Chưa tìm thấy ACK/kết quả. "
        )
        self.variables["status"].set(
            "UNKNOWN · " + summary + "Chỉ gửi lại đúng yêu cầu đang giữ; không tạo batch mới."
        )
        self.enable()

    def opening_error(self, message):
        self.busy = False
        self.variables["status"].set(("UNKNOWN · " if self.presenter.uncertain else "") + message)
        self.enable()

    def release_variables(self):
        self.variables.clear()
