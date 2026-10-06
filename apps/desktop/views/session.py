import tkinter as tk
from tkinter import ttk

from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.session import SessionPresenter
from packages.contracts.identity import Enrollment, RecoveryCodes


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
        self.enrollment_timer = None
        self.warehouses = []
        self.buttons = []
        self.lifecycle_dialog = None
        self.secret_dialog = None
        self.secret_timer = None
        self.lifecycle_variables = {}

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
        for text, command in [("Lấy khóa MFA", self.enroll), ("Xác nhận bật MFA", self.confirm),
                              ("Mật khẩu / khôi phục", self.open_security)]:
            button = ttk.Button(enroll, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        ttk.Label(self, textvariable=self.secret, wraplength=740).pack(anchor="w")

    def open_security(self):
        self.close_security()
        dialog = self.lifecycle_dialog = tk.Toplevel(self)
        dialog.title("Mật khẩu và khôi phục MFA")
        dialog.transient(self.winfo_toplevel())
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        actions = {"Đổi mật khẩu": "change_password", "Dùng mã reset mật khẩu": "reset_password",
                   "Tạo lại 8 mã khôi phục MFA": "recovery_codes", "Reset MFA bằng mã TOTP": "reset_mfa",
                   "Mất TOTP: dùng mã khôi phục": "recover_mfa"}
        choice = tk.StringVar(value="Đổi mật khẩu")
        self.lifecycle_variables = {name: tk.StringVar() for name in
                                    ("username", "password", "code", "new_password", "recovery_code")}
        self.lifecycle_variables["choice"] = choice
        self.lifecycle_variables["username"].set(self.username.get())
        ttk.Combobox(body, textvariable=choice, values=list(actions), state="readonly", width=42).grid(row=0, columnspan=2, sticky="ew")
        labels = [("username", "Tài khoản (khi dùng mã reset)"), ("password", "Mật khẩu hiện tại"),
                  ("code", "Mã TOTP mới (nếu đã bật MFA)"), ("new_password", "Mật khẩu mới (12–128 ký tự)"),
                  ("recovery_code", "Mã reset / mã khôi phục")]
        for index, (name, label) in enumerate(labels, 1):
            ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", pady=5)
            ttk.Entry(body, textvariable=self.lifecycle_variables[name], show="" if name == "username" else "•", width=35).grid(row=index, column=1)
        ttk.Label(body, text="Đổi/reset sẽ đăng xuất mọi phiên. Reset mật khẩu giữ MFA hiện có.\n"
                  "Mất TOTP: đăng nhập bằng mật khẩu để nhận yêu cầu MFA trước.\n"
                  "Sau reset MFA, đăng nhập và bật MFA mới; quyền quản trị vẫn cần MFA.",
                  wraplength=610).grid(row=6, columnspan=2, pady=10)
        def send():
            action = actions[choice.get()]
            values = {key: value.get() for key, value in self.lifecycle_variables.items()}
            payload = {"password": values["password"], "code": values["code"] or None}
            if action == "change_password":
                payload["new_password"] = values["new_password"]
            elif action == "reset_password":
                payload = {"username": values["username"], "reset_token": values["recovery_code"], "new_password": values["new_password"]}
            elif action == "recover_mfa":
                payload = {"recovery_code": values["recovery_code"]}
            self.close_security()
            self.presenter.submit(action, payload)
        ttk.Button(body, text="Thực hiện", command=send).grid(row=7, columnspan=2)
        dialog.protocol("WM_DELETE_WINDOW", self.close_security)

    def close_security(self):
        for variable in self.lifecycle_variables.values():
            variable.set("")
        self.lifecycle_variables.clear()
        if self.lifecycle_dialog is not None:
            self.lifecycle_dialog.destroy()
            self.lifecycle_dialog = None

    def hide_codes(self):
        if self.secret_timer:
            self.after_cancel(self.secret_timer)
            self.secret_timer = None
        if self.secret_dialog is not None:
            self.secret_dialog.destroy()
            self.secret_dialog = None

    def show_codes(self, codes):
        self.hide_codes()
        dialog = self.secret_dialog = tk.Toplevel(self)
        dialog.title("Mã khôi phục — chỉ hiển thị một lần")
        ttk.Label(dialog, padding=12, text="Lưu ở nơi riêng an toàn. Bộ mã cũ đã bị thu hồi.\n"
                  "Sau khôi phục, toàn bộ bộ mã này hết hiệu lực. Cửa sổ đóng sau 60 giây.").pack()
        text = tk.Text(dialog, height=9, width=50)
        text.insert("1.0", "\n".join(codes))
        text.configure(state="disabled")
        text.pack(padx=12)
        ttk.Button(dialog, text="Đã lưu — đóng", command=self.hide_codes).pack(pady=12)
        dialog.protocol("WM_DELETE_WINDOW", self.hide_codes)
        self.secret_timer = self.after(60000, self.hide_codes)

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

    def hide_enrollment(self):
        if self.enrollment_timer:
            self.after_cancel(self.enrollment_timer)
            self.enrollment_timer = None
        self.secret.set("")
        self.factor_id = None

    def clear_scope(self):
        self.hide_enrollment()
        self.close_security()
        self.hide_codes()
        self.on_session_change()
        self.warehouses = []
        self.selector.configure(values=[])
        self.warehouse.set("")
        self.permissions.set("")
        self.secret.set("")
        self.factor_id = None

    def release_variables(self):
        self.hide_enrollment()
        self.close_security()
        self.hide_codes()
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
            self.status.set("Đã đăng xuất." if action == "logout" else
                            "Đã đăng xuất. Đăng nhập lại; sau reset MFA hãy bật MFA mới.")
        elif isinstance(result, RecoveryCodes):
            self.show_codes(result.codes)
            self.status.set("Mã khôi phục mới chỉ hiển thị một lần trong cửa sổ riêng.")
        elif isinstance(result, Enrollment):
            self.hide_enrollment()
            self.enrollment_timer = self.after(result.expires_in * 1000, self.hide_enrollment)
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
