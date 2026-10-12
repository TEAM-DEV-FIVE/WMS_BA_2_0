"""Inline recovery forms; delivery and reset use the existing session worker."""

import re
import tkinter as tk
from tkinter import ttk

from apps.desktop.views.auth_controls import RoundedField


class PasswordRecovery:
    def __init__(self, view):
        self.view = view
        self.channel = "email"
        self.values = {name: tk.StringVar(master=view) for name in
                       ("contact", "username", "reset_token", "new_password", "confirm_password")}
        self.request_panel = ttk.Frame(view.card, style="Auth.Card.TFrame")
        self.contact_label = ttk.Label(self.request_panel, text="Email đã xác minh:", style="Auth.TLabel")
        self.contact_label.pack(anchor="w", pady=(8, 5))
        self.contact_entry = self.field(self.request_panel, "contact")
        self.contact_entry.bind("<Return>", lambda event: self.request())
        self.send_button = view.button(self.request_panel, "Khôi phục", self.request, primary=True)
        self.send_button.configure(width=160)
        self.send_button.pack(pady=(28, 12))
        self.channel_button = view.button(self.request_panel, "Dùng số điện thoại", self.switch_channel, link=True)
        self.channel_button.pack()
        view.button(self.request_panel, "Tôi đã có mã khôi phục", self.open_reset, link=True).pack()
        view.button(self.request_panel, "Quên tên tài khoản?", lambda: self.request(purpose="account"), link=True).pack()

        self.reset_panel = ttk.Frame(view.card, style="Auth.Card.TFrame")
        self.reset_fields = {}
        for name, label in (("username", "Tên tài khoản WMS:"), ("reset_token", "Mã khôi phục trong email/SMS:"),
                            ("new_password", "Mật khẩu mới (12–128 ký tự):"), ("confirm_password", "Nhập lại mật khẩu mới:")):
            ttk.Label(self.reset_panel, text=label, style="Auth.TLabel").pack(anchor="w", pady=(10, 5))
            self.reset_fields[name] = self.field(self.reset_panel, name, secret=name != "username")
        self.reset_fields["confirm_password"].bind("<Return>", lambda event: self.reset())
        view.button(self.reset_panel, "Đặt lại mật khẩu", self.reset, primary=True).pack(fill="x", pady=(24, 10))
        view.button(self.reset_panel, "Gửi lại hướng dẫn khôi phục", self.show_request, link=True).pack()

    def field(self, panel, name, *, secret=False):
        field = RoundedField(panel, textvariable=self.values[name], show="•" if secret else "")
        field.pack(fill="x")
        self.view.inputs.append(field)
        return field

    def switch_channel(self):
        if self.view.presenter.pending:
            return
        self.channel = "sms" if self.channel == "email" else "email"
        self.values["contact"].set("")
        self.contact_label.configure(text="Email đã xác minh:" if self.channel == "email" else "Số điện thoại đã xác minh:")
        self.channel_button.configure(text="Dùng số điện thoại" if self.channel == "email" else "Dùng email")
        self.show_request()

    def show_request(self):
        if self.view.presenter.pending:
            return
        self.clear_secrets()
        self.view.status.set("")
        self.view.set_screen("recovery")
        self.contact_entry.focus_set()

    def request(self, *, purpose="password"):
        if self.view.presenter.pending:
            return
        value = self.values["contact"].get().strip()
        if self.channel == "email":
            valid = value.isascii() and len(value) <= 254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
            error = "Nhập địa chỉ email hợp lệ đã xác minh trên tài khoản WMS"
        else:
            value = re.sub(r"[\s().-]", "", value)
            valid = re.fullmatch(r"\+?[0-9]{9,15}", value)
            error = "Nhập số điện thoại đã xác minh, ví dụ 09xxxxxxxx hoặc +84xxxxxxxxx"
        if not valid:
            self.view.status.set(error)
            self.contact_entry.focus_set()
            return
        if not self.view.capabilities.get(self.channel):
            self.view.status.set("Máy chủ chưa bật gửi hướng dẫn qua " + ("email" if self.channel == "email" else "SMS") +
                                 "; Vui lòng liên hệ quản trị viên: 0329511628")
            return
        self.view.presenter.submit("forgot", dict(kind=self.channel, value=value, purpose=purpose))

    def open_reset(self):
        if self.view.presenter.pending:
            return
        self.clear_secrets()
        username = self.view.username.get().strip()
        self.values["username"].set(username if "@" not in username else "")
        self.view.status.set("")
        self.view.set_screen("recovery_reset")
        self.reset_fields["username"].focus_set()

    def reset(self):
        if self.view.presenter.pending:
            return
        username = self.values["username"].get().strip()
        token = self.values["reset_token"].get().strip()
        password = self.values["new_password"].get()
        if not username or not token:
            self.view.status.set("Nhập tên tài khoản và mã khôi phục đã nhận")
            return
        if not 12 <= len(password) <= 128:
            self.view.status.set("Mật khẩu mới cần từ 12 đến 128 ký tự")
            return
        if password != self.values["confirm_password"].get():
            self.view.status.set("Hai mật khẩu chưa trùng nhau; Vui lòng nhập lại")
            return
        self.clear_secrets()
        self.view.presenter.submit("self_reset", dict(username=username, reset_token=token, new_password=password))

    def clear_secrets(self):
        for name in ("reset_token", "new_password", "confirm_password"):
            self.values[name].set("")

    def clear(self):
        for value in self.values.values():
            value.set("")

    def release(self):
        self.clear()
        self.values.clear()
