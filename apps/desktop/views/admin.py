import tkinter as tk
from tkinter import ttk

from apps.desktop.presenters.admin import AdminPresenter

RESOURCES = {"Tài khoản": "users", "Role": "roles", "Grant đã cấp": "grants",
             "Yêu cầu chờ duyệt": "grant-requests"}
FIELDS = ("username", "display_name", "password", "reason", "user_id", "role_code",
          "scope_kind", "warehouse_id", "valid_until")
COLUMNS = {
    "users": [("username", "Tài khoản", 150), ("display_name", "Tên hiển thị", 180),
              ("is_active", "Hoạt động", 80), ("id", "UUID", 290)],
    "roles": [("code", "Role", 200), ("name", "Tên", 450)],
    "grants": [("role_code", "Role", 140), ("scope_kind", "Scope", 130),
               ("user_id", "Người nhận (UUID)", 285), ("warehouse_id", "Kho (UUID)", 285),
               ("valid_until", "Hết hạn", 200), ("revoked_at", "Thu hồi lúc", 200)],
    "grant-requests": [("role_code", "Role", 140), ("scope_kind", "Scope", 130),
                       ("user_id", "Người nhận (UUID)", 285), ("warehouse_id", "Kho (UUID)", 285),
                       ("valid_until", "Hết hạn", 200), ("reason", "Lý do", 280)],
}
LABELS = {"id": "UUID", "username": "Tài khoản", "display_name": "Tên hiển thị",
          "is_active": "Hoạt động", "code": "Role", "name": "Tên role", "role_code": "Role",
          "scope_kind": "Scope", "user_id": "Người nhận (UUID)", "warehouse_id": "Kho (UUID)",
          "valid_from": "Hiệu lực từ", "valid_until": "Hết hạn", "revoked_at": "Thu hồi lúc",
          "requested_by": "Người yêu cầu (UUID)", "requested_at": "Yêu cầu lúc", "reason": "Lý do"}


class AdminView(ttk.Frame):
    def __init__(self, parent, identity):
        super().__init__(parent, padding=12)
        self.presenter = AdminPresenter(self, identity)
        self.on_signed_out = lambda message: None
        self.entity = tk.StringVar(value="Tài khoản")
        self.status = tk.StringVar()
        self.notice = tk.StringVar()
        self.variables = {field: tk.StringVar() for field in FIELDS}
        self.rows = {}
        self.current = None
        self.next_after = None
        self.busy = False
        self.page = 0
        self.last_result = None
        self.inputs = {}
        self.action_buttons = {}

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        self.selector = ttk.Combobox(toolbar, textvariable=self.entity, values=list(RESOURCES),
                                     state="readonly", width=23)
        self.selector.pack(side="left", padx=(0, 8))
        self.selector.bind("<<ComboboxSelected>>", self.switch)
        self.load_button = ttk.Button(toolbar, text="Tải lại từ đầu", command=self.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(toolbar, text="Trang sau", command=lambda: self.load(next_page=True))
        self.next_button.pack(side="left", padx=8)
        self.ack_button = ttk.Button(toolbar, text="Đã đối chiếu", command=self.presenter.acknowledge)
        self.ack_button.pack(side="left")
        ttk.Label(self, textvariable=self.status, wraplength=820).pack(fill="x", pady=(8, 4))
        ttk.Label(self, textvariable=self.notice, wraplength=820).pack(fill="x", pady=(0, 4))

        listing = ttk.Frame(self)
        listing.pack(fill="both", expand=True)
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(listing, show="headings", height=5, selectmode="browse")
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(listing, command=self.table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(listing, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", self.select)
        detail_frame = ttk.Frame(self)
        detail_frame.pack(fill="x", pady=6)
        self.details = tk.Text(detail_frame, height=4, wrap="word", state="disabled", font=("TkDefaultFont", 9))
        self.details.pack(side="left", fill="x", expand=True)
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.details.yview)
        detail_scroll.pack(side="right", fill="y")
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.form = ttk.Frame(self)
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
        self.actions = ttk.Frame(self)
        self.actions.pack(fill="x", pady=(6, 0))
        self.hint = ttk.Label(self, wraplength=820)
        self.hint.pack(fill="x", pady=(6, 0))
        self.switch()
        self.session_changed()

    def resource(self):
        return RESOURCES[self.entity.get()]

    def session_changed(self, user=None, warehouses=None):
        self.presenter.reset(user)
        self.status.set("Chọn danh sách và tải lại. Cần MFA và quyền GLOBAL iam.manage / role.manage.")
        self.enable()

    def clear_listing(self):
        self.rows = {}
        self.current = self.next_after = None
        self.page = 0
        self.table.delete(*self.table.get_children())
        self.show_details("")

    def switch(self, event=None):
        if self.busy:
            return
        self.clear_listing()
        self.variables["password"].set("")
        for child in self.form.winfo_children():
            child.destroy()
        for child in self.actions.winfo_children():
            child.destroy()
        self.inputs, self.action_buttons = {}, {}
        resource = self.resource()
        columns = COLUMNS[resource]
        self.table.configure(columns=[field for field, _, _ in columns])
        for field, label, width in columns:
            self.table.heading(field, text=label)
            self.table.column(field, width=width, minwidth=60, stretch=resource in {"users", "roles"})
        fields, actions, hint = [], [], "Role đang hoạt động; chọn để điền mã vào form yêu cầu cấp quyền."
        if resource == "users":
            fields = [("username", "Tài khoản mới"), ("display_name", "Tên hiển thị"),
                      ("password", "Mật khẩu mới (12–128 ký tự)"), ("reason", "Lý do khóa / mở / thu hồi phiên")]
            actions = [("create_user", "Tạo tài khoản", self.create_user),
                       ("lock", "Khóa", lambda: self.set_active(False)),
                       ("unlock", "Mở khóa", lambda: self.set_active(True)),
                       ("revoke_sessions", "Thu hồi phiên", self.revoke_sessions)]
            hint = "Chọn dòng để khóa/mở hoặc thu hồi phiên. UUID người được chọn sẽ điền vào form yêu cầu cấp quyền."
        elif resource == "grant-requests":
            fields = [("user_id", "Người nhận (UUID)"), ("role_code", "Mã role"), ("scope_kind", "Scope"),
                      ("warehouse_id", "Kho (UUID; chỉ cho WAREHOUSE)"),
                      ("valid_until", "Hết hạn ISO + múi giờ; trống = vô hạn"), ("reason", "Lý do yêu cầu")]
            actions = [("request_grant", "Lập yêu cầu", self.request_grant),
                       ("approve_grant", "Duyệt dòng đã chọn", self.approve_grant)]
            hint = ("GLOBAL: toàn hệ thống; WAREHOUSE: một kho; ALL_WAREHOUSES: mọi kho. "
                    "Nhập UUID kho từ quản trị danh mục; SYSADMIN không tự có quyền đọc kho. "
                    "Ví dụ hạn: 2027-01-31T17:00:00+07:00. Người duyệt phải khác người yêu cầu và người nhận.")
        elif resource == "grants":
            fields = [("reason", "Lý do thu hồi grant")]
            actions = [("revoke_grant", "Thu hồi grant đã chọn", self.revoke_grant)]
            hint = "Danh sách gồm cả grant đã thu hồi/hết hạn. API hiện chưa trả lý do cấp/thu hồi trong danh sách grant."
        for index, (field, label) in enumerate(fields):
            ttk.Label(self.form, text=label).grid(row=index, column=0, sticky="w", pady=2, padx=(0, 10))
            if field == "scope_kind":
                widget = ttk.Combobox(self.form, textvariable=self.variables[field],
                                      values=["GLOBAL", "WAREHOUSE", "ALL_WAREHOUSES"], state="readonly")
                widget.bind("<<ComboboxSelected>>", self.scope_changed)
            else:
                widget = ttk.Entry(self.form, textvariable=self.variables[field], show="•" if field == "password" else "")
            widget.grid(row=index, column=1, sticky="ew", pady=2)
            self.inputs[field] = widget
        for name, label, command in actions:
            button = ttk.Button(self.actions, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.action_buttons[name] = button
        self.hint.configure(text=hint)
        self.status.set("Tải lại từ đầu để xem danh sách đã chọn.")
        self.enable()

    def scope_changed(self, event=None):
        if self.variables["scope_kind"].get() != "WAREHOUSE":
            self.variables["warehouse_id"].set("")
        self.enable()

    def load(self, next_page=False):
        if next_page and not self.next_after:
            return
        self.presenter.load(self.resource(), self.next_after if next_page else None)

    def create_user(self):
        body = {field: self.variables[field].get() for field in ("username", "display_name", "password")}
        self.variables["password"].set("")
        self.presenter.write("create_user", body)

    def set_active(self, active):
        if self.current:
            self.presenter.write("set_active", {"is_active": active, "reason": self.variables["reason"].get()}, self.current["id"])

    def revoke_sessions(self):
        if self.current:
            self.presenter.write("revoke_sessions", {"reason": self.variables["reason"].get()}, self.current["id"])

    def request_grant(self):
        body = {field: self.variables[field].get().strip()
                for field in ("user_id", "role_code", "scope_kind", "warehouse_id", "valid_until", "reason")}
        body["warehouse_id"] = body["warehouse_id"] or None
        body["valid_until"] = body["valid_until"] or None
        self.presenter.write("request_grant", body)

    def approve_grant(self):
        if self.current:
            self.presenter.write("approve_grant", record_id=self.current["id"])

    def revoke_grant(self):
        if self.current:
            self.presenter.write("revoke_grant", {"reason": self.variables["reason"].get()}, self.current["id"])

    def select(self, event=None):
        selected = self.table.selection()
        self.current = self.rows.get(selected[0]) if selected else None
        if self.current:
            self.show_details("\n".join(f"{LABELS.get(key, key)}: {self.display_value(key, value)}"
                                        for key, value in self.current.items()))
            if self.resource() == "users":
                self.variables["user_id"].set(self.current["id"])
            elif self.resource() == "roles":
                self.variables["role_code"].set(self.current["code"])
        self.enable()

    @staticmethod
    def display_value(field, value):
        if field == "is_active":
            return "Có" if value else "Không"
        if value is None:
            return "Không thời hạn" if field == "valid_until" else "—"
        return str(value)

    def show_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def enable(self):
        resource = self.resource()
        allowed = self.presenter.allowed(resource)
        free = allowed and not self.busy
        writable = free and not self.presenter.uncertain_resource
        choices = [label for label, name in RESOURCES.items() if self.presenter.allowed(name)]
        self.selector.configure(values=choices)
        self.selector.state(["!disabled"] if choices and not self.busy else ["disabled"])
        self.load_button.state(["!disabled"] if free else ["disabled"])
        self.next_button.state(["!disabled"] if free and self.next_after else ["disabled"])
        self.ack_button.state(["!disabled"] if not self.busy and self.presenter.reloaded else ["disabled"])
        for field, widget in self.inputs.items():
            enabled = writable and (field != "warehouse_id" or self.variables["scope_kind"].get() == "WAREHOUSE")
            widget.state(["!disabled"] if enabled else ["disabled"])
        actor = str(self.presenter.user.id) if self.presenter.user else None
        current = self.current or {}
        for action, button in self.action_buttons.items():
            enabled = writable
            if action not in {"create_user", "request_grant"}:
                enabled = enabled and bool(current)
            if action in {"lock", "unlock"}:
                enabled = enabled and current.get("id") != actor and current.get("is_active") == (action == "lock")
            if action == "approve_grant":
                enabled = enabled and actor not in {current.get("requested_by"), current.get("user_id")}
            if action == "revoke_grant":
                enabled = enabled and not current.get("revoked_at")
            button.state(["!disabled"] if enabled else ["disabled"])
        self.notice.set("Chưa rõ kết quả lệnh trước. Không tự gửi lại. Tải lại danh sách liên quan, đối chiếu rồi bấm Đã đối chiếu. "
                        "Danh sách không chứng minh lệnh cũ chưa chạy; thu hồi phiên cần xác minh ở phiên bị thu hồi."
                        if self.presenter.uncertain_resource else "")

    def admin_busy(self):
        self.busy = True
        self.status.set("Đang xử lý…")
        self.enable()

    def admin_loaded(self, resource, rows, next_after, after):
        self.busy = False
        page = self.page + 1 if after else 1
        self.clear_listing()
        self.page = page
        self.next_after = next_after
        key = "code" if resource == "roles" else "id"
        self.rows = {record[key]: record for record in rows}
        for item, record in self.rows.items():
            self.table.insert("", "end", iid=item,
                              values=[self.display_value(field, record.get(field)) for field, _, _ in COLUMNS[resource]])
        self.status.set(f"Trang {self.page}: {len(rows)} dòng. " +
                        ("Có thể còn dữ liệu; bấm Trang sau." if next_after else "Đã đến cuối danh sách tại thời điểm tải."))
        self.enable()

    def admin_saved(self, action, result):
        self.busy = False
        self.last_result = result
        self.clear_listing()
        if action == "create_user":
            self.variables["user_id"].set(result["id"])
            self.variables["username"].set("")
            self.variables["display_name"].set("")
        self.status.set("Đã xử lý thành công" + (f" · UUID: {result['id']}" if result.get("id") else "") +
                        ". Tải lại danh sách để xem trạng thái mới.")
        self.enable()

    def admin_error(self, message):
        self.busy = False
        self.status.set(message)
        self.enable()

    def admin_signed_out(self, message):
        self.on_signed_out(message)
        self.admin_error(message)

    def admin_clear(self):
        self.busy = False
        self.last_result = None
        self.clear_listing()
        for variable in self.variables.values():
            variable.set("")
        self.variables["scope_kind"].set("GLOBAL")
        self.enable()

    def release_variables(self):
        self.variables.clear()
        self.entity = self.status = self.notice = None
        self.on_signed_out = None
