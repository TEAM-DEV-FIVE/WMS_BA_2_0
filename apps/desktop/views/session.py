import tkinter as tk
from tkinter import ttk

from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.session import SessionPresenter
from packages.contracts.identity import Enrollment


class SessionView(ttk.Frame):
    def __init__(self, parent, settings):
        super().__init__(parent, padding=20)
        self.presenter = SessionPresenter(self, IdentityClient(settings))
        self.on_session_change = lambda user=None, warehouses=None: None
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.code = tk.StringVar()
        self.status = tk.StringVar(value="Đăng nhập để làm việc với các kho được cấp quyền.")
        self.secret = tk.StringVar()
        self.warehouse = tk.StringVar()
        self.permissions = tk.StringVar()
        self.factor_id = None
        self.warehouses = []
        self.buttons = []

        form = ttk.Frame(self)
        form.pack(anchor="w", fill="x")
        for index, (label, variable, mask) in enumerate([
            ("Tài khoản", self.username, ""), ("Mật khẩu", self.password, "•"), ("Mã MFA (6 số)", self.code, "•")
        ]):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=4)
            ttk.Entry(form, textvariable=variable, show=mask, width=32).grid(row=index, column=1, padx=12, pady=4)
        actions = ttk.Frame(self)
        actions.pack(anchor="w", pady=12)
        for text, command in [
            ("Đăng nhập", self.login), ("Xác nhận MFA", self.mfa),
            ("Tải lại phiên", self.reload), ("Đăng xuất", self.logout),
        ]:
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        ttk.Label(self, textvariable=self.status, wraplength=740).pack(anchor="w", pady=8)
        ttk.Label(self, text="Kho hiện hành").pack(anchor="w")
        self.selector = ttk.Combobox(self, textvariable=self.warehouse, state="readonly", width=55)
        self.selector.pack(anchor="w", pady=6)
        self.selector.bind("<<ComboboxSelected>>", self.select_warehouse)
        ttk.Label(self, textvariable=self.permissions, wraplength=740).pack(anchor="w", pady=6)
        ttk.Separator(self).pack(fill="x", pady=12)
        ttk.Label(self, text="Bật MFA: nhập lại mật khẩu, lấy khóa rồi thêm vào ứng dụng xác thực.").pack(anchor="w")
        enroll = ttk.Frame(self)
        enroll.pack(anchor="w", pady=8)
        for text, command in [("Lấy khóa MFA", self.enroll), ("Xác nhận bật MFA", self.confirm)]:
            button = ttk.Button(enroll, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        ttk.Label(self, textvariable=self.secret, wraplength=740).pack(anchor="w")

    def take(self, variable):
        value = variable.get()
        variable.set("")
        return value

    def login(self):
        self.clear_scope()
        self.presenter.submit("login", self.username.get(), self.take(self.password))

    def mfa(self):
        self.presenter.submit("mfa", self.take(self.code))

    def reload(self):
        self.clear_scope()
        self.presenter.submit("reload")

    def logout(self):
        self.clear_scope()
        self.presenter.submit("logout")

    def enroll(self):
        self.presenter.submit("enroll", self.take(self.password))

    def confirm(self):
        if self.factor_id:
            self.presenter.submit("confirm", self.factor_id, self.take(self.code))
        else:
            self.status.set("Lấy khóa MFA trước khi xác nhận.")

    def select_warehouse(self, event=None):
        self.permissions.set("")
        index = self.selector.current()
        if index >= 0:
            self.presenter.submit("warehouse", self.warehouses[index].id)

    def clear_scope(self):
        self.on_session_change()
        self.warehouses = []
        self.selector.configure(values=[])
        self.warehouse.set("")
        self.permissions.set("")
        self.secret.set("")
        self.factor_id = None

    def release_variables(self):
        # Run on the UI thread before destroying Tk. Worker-side cyclic GC must
        # never become responsible for finalizing Tk variables/interpreters.
        for name in ("username", "password", "code", "status", "secret", "warehouse", "permissions"):
            setattr(self, name, None)

    def session_busy(self):
        for button in self.buttons:
            button.state(["disabled"])
        self.selector.state(["disabled"])
        self.status.set("Đang xử lý…")

    def enable(self):
        for button in self.buttons:
            button.state(["!disabled"])
        self.selector.state(["!disabled", "readonly"])

    def session_error(self, message, *, signed_out):
        self.enable()
        if signed_out:
            self.clear_scope()
        self.status.set(message)

    def session_result(self, action, result):
        self.enable()
        if result == "MFA_REQUIRED":
            self.status.set("Nhập mã trong ứng dụng xác thực rồi bấm Xác nhận MFA.")
        elif result == "SIGNED_OUT":
            self.clear_scope()
            self.status.set("Đã đăng xuất.")
        elif isinstance(result, Enrollment):
            self.factor_id = result.factor_id
            self.secret.set("Khóa MFA (chỉ hiển thị tại đây): " + result.secret)
            self.status.set("Thêm khóa vào ứng dụng xác thực; nhập mã rồi bấm Xác nhận bật MFA trong 5 phút.")
        elif action == "warehouse":
            self.permissions.set("Quyền tại kho: " + ", ".join(result))
            self.status.set("Đã chọn kho. Quyền sẽ được kiểm tra lại ở server cho mỗi thao tác.")
        else:
            self.clear_scope()
            self.warehouses = result["warehouses"]
            user = result["user"]
            self.on_session_change(user, result["warehouses"])
            self.selector.configure(values=[f"{item.code} — {item.name}" for item in self.warehouses])
            state = "MFA đã xác thực" if user.mfa_verified else "Chưa bật/xác thực MFA"
            self.status.set(f"{user.display_name} · {state}. " + ("Chọn kho để xem quyền." if self.warehouses else "Chưa có quyền kho."))
