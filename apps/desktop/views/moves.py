import tkinter as tk
from datetime import date
from tkinter import ttk
from uuid import uuid4

from apps.desktop.presenters.moves import MovePresenter
from packages.contracts.moves import MoveInput, MovePost, MoveUpdate


class WorkflowView(ttk.Frame):
    """Small shared view primitives; all methods are called on the Tk thread."""

    def __init__(self, parent, api, presenter_class=MovePresenter, *, scrollable=False):
        super().__init__(parent, padding=12)
        self.content = self
        if scrollable:
            self.canvas = tk.Canvas(self, highlightthickness=0)
            scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            scroll.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)
            self.canvas.configure(yscrollcommand=scroll.set)
            self.content = ttk.Frame(self.canvas)
            window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
            self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
            self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.variables = {name: tk.StringVar() for name in ["warehouse", "status", "reason", "detail"]}
        self.presenter = presenter_class(self, api)
        self.warehouses, self.permissions = [], []
        self.busy = False
        self.on_signed_out = lambda message: None
        self.top = ttk.Frame(self.content)
        self.top.pack(fill="x")
        self.selector = self.combo(self.top, "warehouse", 28)
        self.selector.pack(side="left", padx=(0, 6))
        self.selector.bind("<<ComboboxSelected>>", self.scope_changed)
        ttk.Label(self.content, textvariable=self.variables["status"], wraplength=700).pack(fill="x", pady=5)

    def variable(self, name, value=""):
        if name not in self.variables:
            self.variables[name] = tk.StringVar(value=value)
        return self.variables[name]

    def combo(self, parent, name, width):
        return ttk.Combobox(parent, textvariable=self.variable(name), state="readonly", width=width)

    @staticmethod
    def tree(parent, names, labels, widths, height=3):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=names, show="headings", height=height, selectmode="browse")
        for name, label, width in zip(names, labels, widths):
            table.heading(name, text=label)
            table.column(name, width=width, minwidth=40)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        return table

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
        self.variables["status"].set("Chọn kho và tải dữ liệu." if user else "Đăng nhập để làm việc.")
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset(self.presenter.user_id, self.warehouse_id())
        self.variables["status"].set("Kho đã đổi; tải lại dữ liệu. Lệnh chưa rõ kết quả được giữ riêng theo người/kho trong RAM.")
        self.enable()

    def workflow_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def workflow_error(self, message):
        self.busy = False
        self.variables["status"].set(message + (" Chưa rõ kết quả: tra ACK hoặc gửi lại đúng yêu cầu đang giữ."
                                               if self.presenter.uncertain else ""))
        self.enable()

    def workflow_signed_out(self, message):
        self.on_signed_out(message)
        self.workflow_error(message)

    def reason_form(self):
        frame = ttk.Frame(self.content)
        frame.pack(fill="x", pady=4)
        ttk.Label(frame, text="Lý do").pack(side="left")
        self.reason_entry = ttk.Entry(frame, textvariable=self.variables["reason"])
        self.reason_entry.pack(side="left", fill="x", expand=True, padx=6)

    def retry_form(self, operation=False):
        frame = ttk.Frame(self.content)
        frame.pack(fill="x", pady=5)
        self.retry_button = ttk.Button(frame, text="Gửi lại đúng yêu cầu", command=self.presenter.retry)
        self.retry_button.pack(side="left")
        if operation:
            self.operation_button = ttk.Button(frame, text="Tra ACK ghi sổ", command=self.presenter.operation)
            self.operation_button.pack(side="left", padx=6)
        ttk.Label(frame, text="Chỉ máy chủ xác nhận mới hoàn tất. Lệnh hiện giữ trong RAM.").pack(side="left", padx=6)

    @staticmethod
    def set_enabled(widget, enabled):
        widget.state(["!disabled"] if enabled else ["disabled"])

    def release_variables(self):
        self.variables.clear()
        self.on_signed_out = None


class MoveView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api)
        self.doc = None
        self.lines, self.stock, self.locations = [], [], []
        self.cursors = {"moves": None, "moves/stock": None, "moves/locations": None}
        self.load_button = ttk.Button(self.top, text="Tải phiếu chuyển", command=lambda: self.presenter.load())
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.cursors["moves"]))
        self.next_button.pack(side="left", padx=5)
        self.new_button = ttk.Button(self.top, text="Phiếu mới", command=self.new)
        self.new_button.pack(side="left")
        self.table = self.tree(self, ["number", "state", "version"], ["Phiếu di chuyển", "Trạng thái", "Version"], [360, 220, 140])
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(self, textvariable=self.variables["detail"], wraplength=820).pack(fill="x", pady=3)
        refs = ttk.Frame(self)
        refs.pack(fill="x", pady=4)
        self.ref_buttons = {}
        for resource, label in [("moves/stock", "Tồn nguồn"), ("moves/locations", "Vị trí đích")]:
            for next_page in [False, True]:
                button = ttk.Button(refs, text=label + (" tiếp" if next_page else ""),
                    command=lambda r=resource, n=next_page: self.presenter.load(r, self.cursors[r] if n else None))
                button.pack(side="left", padx=(0, 6))
                self.ref_buttons[resource, next_page] = button
        edit = ttk.Frame(self)
        edit.pack(fill="x")
        ttk.Label(edit, text="Hàng / nguồn").grid(row=0, column=0, sticky="w")
        self.stock_selector = self.combo(edit, "stock", 78)
        self.stock_selector.grid(row=0, column=1, columnspan=3, sticky="ew", pady=3)
        self.stock_selector.bind("<<ComboboxSelected>>", self.stock_selected)
        ttk.Label(edit, text="Vị trí đích").grid(row=1, column=0, sticky="w")
        self.location_selector = self.combo(edit, "location", 40)
        self.location_selector.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(edit, text="SL cơ sở").grid(row=1, column=2, padx=5)
        self.quantity_entry = ttk.Entry(edit, textvariable=self.variable("quantity", "1"), width=14)
        self.quantity_entry.grid(row=1, column=3)
        ttk.Label(edit, text="UUID quyết định chất lượng").grid(row=2, column=0, sticky="w")
        self.quality_entry = ttk.Entry(edit, textvariable=self.variable("quality_id"), width=40)
        self.quality_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(edit, text="Ngày chuyển").grid(row=2, column=2, padx=5)
        self.day_entry = ttk.Entry(edit, textvariable=self.variable("day", date.today().isoformat()), width=14)
        self.day_entry.grid(row=2, column=3)
        edit.columnconfigure(1, weight=1)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        self.add_button = ttk.Button(bar, text="Thêm dòng", command=self.add_line)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(bar, text="Bỏ dòng", command=self.remove_line)
        self.remove_button.pack(side="left", padx=6)
        ttk.Label(bar, text="Nguồn nhận/cách ly cần UUID từ tab Kiểm định; nguồn STORAGE có thể để trống.").pack(side="left")
        self.line_table = self.tree(self, ["stock", "source", "destination", "quantity", "quality"],
            ["SKU / owner / lô-serial", "Nguồn", "Đích", "Số lượng", "Quyết định"], [230, 100, 100, 90, 300])
        self.reason_form()
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.buttons = {}
        for action, label in [("save", "Lưu nháp"), ("submit", "Gửi duyệt"), ("approve", "Duyệt"),
                              ("reject", "Từ chối"), ("revise", "Sửa lại"), ("cancel", "Hủy"), ("post", "Ghi sổ toàn phiếu")]:
            button = ttk.Button(actions, text=label, command=lambda a=action: self.action(a))
            button.pack(side="left", padx=(0, 4))
            self.buttons[action] = button
        self.retry_form(operation=True)
        self.session_changed()

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        editable = writable and ("edit" in self.doc["allowed_actions"] if self.doc else "move.draft" in self.permissions)
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.cursors["moves"])
        self.set_enabled(self.new_button, writable and "move.draft" in self.permissions)
        for (resource, next_page), widget in self.ref_buttons.items():
            self.set_enabled(widget, free and (not next_page or self.cursors[resource]))
        for widget in [self.stock_selector, self.location_selector, self.quantity_entry, self.quality_entry,
                       self.day_entry, self.add_button, self.remove_button]:
            self.set_enabled(widget, editable)
        self.set_enabled(self.reason_entry, writable)
        for action, widget in self.buttons.items():
            self.set_enabled(widget, editable if action == "save" else writable and self.doc and action in self.doc["allowed_actions"])
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain and self.presenter.uncertain[1].endswith("/post"))

    def workflow_clear(self):
        self.doc, self.lines, self.stock, self.locations, self.permissions = None, [], [], [], []
        self.busy = False
        self.cursors = {key: None for key in self.cursors}
        self.table.delete(*self.table.get_children())
        self.line_table.delete(*self.line_table.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status"}:
                self.variables[name].set("")
        self.stock_selector.configure(values=[])
        self.location_selector.configure(values=[])

    def new(self):
        if self.busy or self.presenter.uncertain:
            return
        self.doc, self.lines = None, []
        self.variable("day").set(date.today().isoformat())
        self.variables["reason"].set("")
        self.variables["quality_id"].set("")
        self.variables["detail"].set("Phiếu mới; tải tồn nguồn và vị trí đích, rồi thêm dòng.")
        self.render_lines()
        self.enable()

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def stock_selected(self, event=None):
        index = self.stock_selector.current()
        if index >= 0:
            row = self.stock[index]
            self.variables["detail"].set(f"Nguồn {row['source_code']} · owner {row['owner_code']} · "
                f"lô/serial {row['lot_code'] or row['serial_code'] or '—'} · tồn {row['on_hand']} · giữ {row['reserved']} · "
                f"chưa giữ {row['movable_base']} · UUID {row['stock_item_id']}")

    def add_line(self):
        source, target = self.stock_selector.current(), self.location_selector.current()
        if source < 0 or target < 0:
            self.workflow_error("Chọn hàng/vị trí nguồn và vị trí đích; tải các trang danh sách nếu cần.")
            return
        stock, location = self.stock[source], self.locations[target]
        self.lines.append(dict(stock_item_id=stock["stock_item_id"], source_location_id=stock["source_location_id"],
            destination_location_id=location["id"], quantity_base=self.variables["quantity"].get(),
            quality_decision_id=self.variables["quality_id"].get().strip() or None,
            label=f"{stock['sku']} / {stock['owner_code']} / {stock['lot_code'] or stock['serial_code'] or '—'}",
            source_code=stock["source_code"], destination_code=location["code"]))
        self.render_lines()

    def remove_line(self):
        selected = self.line_table.selection()
        if selected:
            self.lines.pop(int(selected[0]))
            self.render_lines()

    def render_lines(self):
        self.line_table.delete(*self.line_table.get_children())
        for i, row in enumerate(self.lines):
            self.line_table.insert("", "end", iid=str(i), values=(row["label"], row["source_code"], row["destination_code"],
                row["quantity_base"], row["quality_decision_id"] or "—"))

    def workflow_loaded(self, action, result, permissions):
        self.busy, self.permissions = False, permissions
        if action == "read":
            self.doc = result
            plans = {p["document_line_id"]: p for p in result["plan"]}
            self.lines = [{**plans[r["id"]], "label": f"{r['sku']} / {r['owner_code']} / "
                           f"{plans[r['id']]['lot_code'] or plans[r['id']]['serial_code'] or '—'}"} for r in result["lines"]]
            self.variables["day"].set(result["business_date"])
            self.variables["reason"].set("")
            self.variables["detail"].set(f"{result['number']} · {result['status']} · v{result['version']} · " +
                "; ".join(f"Duyệt v{a['document_version']}: {a['status']}" for a in result["approvals"]))
            self.render_lines()
        else:
            self.cursors[action] = result["next_after"]
            if action == "moves":
                self.table.delete(*self.table.get_children())
                for row in result["items"]:
                    self.table.insert("", "end", iid=row["id"], values=(row["number"], row["status"], row["version"]))
            elif action == "moves/stock":
                self.stock = result["items"]
                self.variables["stock"].set("")
                self.stock_selector.configure(values=[f"{r['sku']} · {r['source_code']} · {r['owner_code']} · {r['lot_code'] or r['serial_code'] or '—'} · chưa giữ {r['movable_base']}" for r in self.stock])
            elif action == "moves/locations":
                self.locations = result["items"]
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
                fields = ["stock_item_id", "source_location_id", "destination_location_id", "quantity_base", "quality_decision_id"]
                body = dict(warehouse_id=self.warehouse_id(), business_date=self.variables["day"].get(), reason=reason,
                            lines=[{k: row[k] for k in fields} for row in self.lines])
                if self.doc:
                    body["expected_version"] = self.doc["version"]
                body = (MoveUpdate if self.doc else MoveInput).model_validate(body).model_dump(mode="json")
                self.presenter.command("PUT" if self.doc else "POST", "moves" + ("/" + self.doc["id"] if self.doc else ""), body)
            elif self.doc:
                body = {"expected_version": self.doc["version"], "reason": reason}
                path = "documents/" + self.doc["id"] + "/" + action
                if action == "post":
                    body = MovePost(**body, execution_key=uuid4()).model_dump(mode="json")
                    path = "moves/" + self.doc["id"] + "/post"
                elif action in {"approve", "reject"}:
                    approval = next(a for a in self.doc["approvals"] if a["can_decide"])
                    path = "approval-requests/" + approval["id"] + "/decide"
                    body["decision"] = action.upper()
                self.presenter.command("POST", path, body)
        except (ValueError, TypeError, StopIteration):
            self.workflow_error("Kiểm tra UUID quyết định, lượng cơ sở, ngày YYYY-MM-DD, lý do và quyền duyệt.")
