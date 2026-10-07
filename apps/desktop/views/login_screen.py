# apps/desktop/views/login_screen.py
# SC01 Đăng nhập và SC02 Nhập mã MFA.
from tkinter import *
from tkinter import messagebox

from api.client import ApiError, UnknownResult

FONT = ("Segoe UI", 11)


class LoginScreen(Frame):
    def __init__(self, parent, app):
        Frame.__init__(self, parent, bg="white", padx=40, pady=30)
        self.app = app

        Label(self, text="Đăng nhập", bg="white", fg="#1F3A5F",
              font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=(0, 15))

        Label(self, text="Tên đăng nhập:", bg="white", font=FONT).grid(
            row=1, column=0, sticky="w")
        self.user_entry = Entry(self, font=FONT, width=30)
        self.user_entry.grid(row=2, column=0, pady=(0, 10))

        Label(self, text="Mật khẩu:", bg="white", font=FONT).grid(
            row=3, column=0, sticky="w")
        self.pass_entry = Entry(self, font=FONT, width=30, show="*")  # show="*" ẩn mật khẩu
        self.pass_entry.grid(row=4, column=0, pady=(0, 10))

        self.login_button = Button(self, text="Đăng nhập", command=self.do_login,
                                   bg="#1F3A5F", fg="white", font=FONT, width=28,
                                   relief="flat", cursor="hand2",
                                   activebackground="#1F3A5F", activeforeground="white")
        self.login_button.grid(row=5, column=0, pady=5, ipady=4)

        self.message = Label(self, text="", bg="white", fg="#C62828",
                             font=FONT, wraplength=300)
        self.message.grid(row=6, column=0, pady=(5, 0))

        # Chỉ để thử với server giả, bỏ khi có backend thật
        Label(self, text="Thử: admin / admin123 (MFA: 123456)\nhoặc nhan01 / 123456",
              bg="white", fg="#757575", font=("Segoe UI", 9)).grid(row=7, column=0, pady=(15, 0))

        self.user_entry.focus()                       # con trỏ nằm sẵn ở ô tên đăng nhập
        self.pass_entry.bind("<Return>", self.press_enter)   # bấm Enter = Đăng nhập
        self.user_entry.bind("<Return>", self.press_enter)

    def press_enter(self, event):
        self.do_login()

    def do_login(self):
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        if username == "" or password == "":
            self.message.config(text="Hãy nhập đủ tên đăng nhập và mật khẩu.")
            return

        self.login_button.config(state="disabled", text="Đang đăng nhập...")
        self.message.config(text="")
        self.app.set_status("Đang đăng nhập...")

        def task():                          # luồng nền
            return self.app.api.login(username, password)

        def done(result):                    # luồng chính
            if not self.winfo_exists():
                return
            self.app.on_login_ok(result)

        def fail(error):
            if not self.winfo_exists():
                return
            self.login_button.config(state="normal", text="Đăng nhập")
            self.pass_entry.delete(0, END)   # xóa mật khẩu đã gõ
            self.app.set_status("Sẵn sàng")
            if isinstance(error, ApiError):
                self.message.config(text=error.message)
            elif isinstance(error, UnknownResult):
                self.message.config(text="Mất kết nối tới server. Hãy kiểm tra mạng LAN.")
            else:
                messagebox.showerror("Lỗi", str(error))

        self.app.worker.run(task, done, fail)


class MfaScreen(Frame):
    def __init__(self, parent, app):
        Frame.__init__(self, parent, bg="white", padx=40, pady=30)
        self.app = app

        Label(self, text="Xác thực hai bước", bg="white", fg="#1F3A5F",
              font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=(0, 10))
        Label(self, text="Nhập mã 6 số từ ứng dụng xác thực của bạn:", bg="white",
              font=FONT).grid(row=1, column=0, pady=(0, 10))

        self.code_entry = Entry(self, font=("Segoe UI", 16), width=10, justify="center")
        self.code_entry.grid(row=2, column=0, pady=(0, 10))

        self.ok_button = Button(self, text="Xác nhận", command=self.do_verify,
                                bg="#2E7D32", fg="white", font=FONT, width=28,
                                relief="flat", cursor="hand2",
                                activebackground="#2E7D32", activeforeground="white")
        self.ok_button.grid(row=3, column=0, pady=5, ipady=4)

        Button(self, text="Quay lại đăng nhập", command=self.app.logout,
               bg="#757575", fg="white", font=FONT, width=28, relief="flat",
               cursor="hand2", activebackground="#757575",
               activeforeground="white").grid(row=4, column=0, pady=5, ipady=4)

        self.message = Label(self, text="", bg="white", fg="#C62828",
                             font=FONT, wraplength=300)
        self.message.grid(row=5, column=0, pady=(5, 0))

        Label(self, text="Thử với server giả: mã là 123456", bg="white",
              fg="#757575", font=("Segoe UI", 9)).grid(row=6, column=0, pady=(10, 0))

        self.code_entry.focus()
        self.code_entry.bind("<Return>", self.press_enter)

    def press_enter(self, event):
        self.do_verify()

    def do_verify(self):
        code = self.code_entry.get().strip()
        if len(code) != 6 or not code.isdigit():
            self.message.config(text="Mã gồm đúng 6 chữ số.")
            return

        self.ok_button.config(state="disabled", text="Đang kiểm tra...")
        self.message.config(text="")

        def task():
            return self.app.api.verify_mfa(code)

        def done(result):
            if not self.winfo_exists():
                return
            self.app.on_login_ok(result)

        def fail(error):
            if not self.winfo_exists():
                return
            self.ok_button.config(state="normal", text="Xác nhận")
            self.code_entry.delete(0, END)
            if isinstance(error, ApiError):
                self.message.config(text=error.message)
            elif isinstance(error, UnknownResult):
                self.message.config(text="Mất kết nối tới server. Hãy thử lại.")
            else:
                messagebox.showerror("Lỗi", str(error))

        self.app.worker.run(task, done, fail)