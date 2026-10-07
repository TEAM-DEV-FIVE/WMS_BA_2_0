# apps/desktop/views/admin_screen.py
# SC04 Quản lý người dùng và cấp vai trò theo kho (chỉ SYSADMIN).
from tkinter import *
from tkinter import messagebox

from api.client import ApiError, UnknownResult

FONT = ("Segoe UI", 10)
ROLES = ["SYSADMIN", "MASTER_DATA", "BUYER", "SELLER", "RECEIVER", "PICKER",
         "WAREHOUSE_MANAGER", "CONTROLLER", "DIRECTOR", "AUDITOR"]


class AdminScreen(Frame):
    def __init__(self, parent, app):
        Frame.__init__(self, parent, bg="white", padx=25, pady=15)
        self.app = app
        self.users = []          # danh sách user, cùng thứ tự với Listbox

        Label(self, text="Quản trị người dùng và cấp vai trò", bg="white",
              fg="#1F3A5F", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 8))

        # ----- Danh sách người dùng -----
        # exportselection=False: để dòng đã chọn không bị mất khi bấm sang ô khác
        self.user_list = Listbox(self, width=75, height=6, font=("Consolas", 10),
                                 exportselection=False)
        self.user_list.grid(row=1, column=0, columnspan=2)

        Button(self, text="Tải lại danh sách", command=self.load_users,
               bg="#1565C0", fg="white", font=FONT, relief="flat", cursor="hand2",
               activebackground="#1565C0", activeforeground="white").grid(
            row=2, column=0, pady=8, ipadx=6, ipady=2)
        Button(self, text="Khóa / mở khóa người đã chọn", command=self.toggle_lock,
               bg="#E65100", fg="white", font=FONT, relief="flat", cursor="hand2",
               activebackground="#E65100", activeforeground="white").grid(
            row=2, column=1, pady=8, ipadx=6, ipady=2)

        # ----- Form cấp vai trò -----
        Label(self, text="Cấp vai trò cho người đã chọn", bg="white", fg="#1F3A5F",
              font=("Segoe UI", 11, "bold")).grid(
            row=3, column=0, columnspan=2, pady=(8, 4))

        Label(self, text="Vai trò:", bg="white", font=FONT).grid(
            row=4, column=0, sticky="e", padx=5, pady=3)
        self.role_var = StringVar(value="RECEIVER")
        OptionMenu(self, self.role_var, *ROLES).grid(row=4, column=1, sticky="w")

        Label(self, text="Phạm vi:", bg="white", font=FONT).grid(
            row=5, column=0, sticky="e", padx=5, pady=3)
        scope_frame = Frame(self, bg="white")
        scope_frame.grid(row=5, column=1, sticky="w")
        self.scope_var = StringVar(value="WAREHOUSE")
        Radiobutton(scope_frame, text="Một kho", variable=self.scope_var,
                    value="WAREHOUSE", command=self.scope_changed,
                    bg="white", font=FONT).grid(row=0, column=0)
        Radiobutton(scope_frame, text="Mọi kho", variable=self.scope_var,
                    value="ALL_WAREHOUSES", command=self.scope_changed,
                    bg="white", font=FONT).grid(row=0, column=1)
        Radiobutton(scope_frame, text="Toàn hệ thống", variable=self.scope_var,
                    value="GLOBAL", command=self.scope_changed,
                    bg="white", font=FONT).grid(row=0, column=2)

        Label(self, text="Mã kho:", bg="white", font=FONT).grid(
            row=6, column=0, sticky="e", padx=5, pady=3)
        self.warehouse_entry = Entry(self, font=FONT, width=20)
        self.warehouse_entry.grid(row=6, column=1, sticky="w")

        Label(self, text="Mã biên bản phê chuẩn:", bg="white", font=FONT).grid(
            row=7, column=0, sticky="e", padx=5, pady=3)
        self.ref_entry = Entry(self, font=FONT, width=30)
        self.ref_entry.grid(row=7, column=1, sticky="w")

        self.grant_button = Button(self, text="Cấp vai trò", command=self.do_grant,
                                   bg="#2E7D32", fg="white", font=FONT, relief="flat",
                                   cursor="hand2", activebackground="#2E7D32",
                                   activeforeground="white")
        self.grant_button.grid(row=8, column=0, columnspan=2, pady=10, ipadx=20, ipady=3)

        self.result_label = Label(self, text="", bg="white", font=("Segoe UI", 10, "bold"),
                                  wraplength=520)
        self.result_label.grid(row=9, column=0, columnspan=2)

        self.load_users()

    # ---------- Tiện ích ----------
    def scope_changed(self):
        # Chỉ phạm vi "Một kho" mới cần nhập mã kho
        if self.scope_var.get() == "WAREHOUSE":
            self.warehouse_entry.config(state="normal")
        else:
            self.warehouse_entry.delete(0, END)
            self.warehouse_entry.config(state="disabled")

    def selected_user(self):
        pick = self.user_list.curselection()
        if len(pick) == 0:
            messagebox.showwarning("Chưa chọn", "Hãy bấm chọn một người trong danh sách.")
            return None
        return self.users[pick[0]]

    def show_error(self, error):
        if isinstance(error, ApiError):
            text = "Bị từ chối: " + error.code + " - " + error.message
        elif isinstance(error, UnknownResult):
            text = "Mất kết nối. Hãy bấm 'Tải lại danh sách' để kiểm tra trước khi thử lại."
        else:
            text = str(error)
        self.result_label.config(text=text, fg="#C62828")
        self.app.set_status("Lỗi")

    # ---------- Tải danh sách ----------
    def load_users(self):
        self.app.set_status("Đang tải danh sách người dùng...")

        def task():
            return self.app.api.list_users()

        def done(users):
            if not self.winfo_exists():
                return
            self.users = users
            self.user_list.delete(0, END)
            for u in users:
                if u["is_active"]:
                    state = "Hoạt động"
                else:
                    state = "ĐÃ KHÓA"
                line = (u["username"].ljust(9) + u["display_name"].ljust(20)
                        + state.ljust(11) + ", ".join(u["roles"]))
                self.user_list.insert(END, line)
            self.app.set_status("Đã tải " + str(len(users)) + " người dùng")

        def fail(error):
            if not self.winfo_exists():
                return
            self.show_error(error)

        self.app.worker.run(task, done, fail)

    # ---------- Khóa / mở khóa ----------
    def toggle_lock(self):
        user = self.selected_user()
        if user is None:
            return
        new_active = not user["is_active"]
        if new_active:
            question = "Mở khóa tài khoản " + user["username"] + "?"
        else:
            question = ("Khóa tài khoản " + user["username"] +
                        "?\nCác phiên đang đăng nhập của người này sẽ bị thu hồi.")
        if not messagebox.askyesno("Xác nhận", question):
            return

        self.app.set_status("Đang gửi...")

        def task():
            return self.app.api.set_user_active(user["username"], new_active)

        def done(result):
            if not self.winfo_exists():
                return
            self.result_label.config(text="Đã cập nhật " + user["username"], fg="#2E7D32")
            self.load_users()

        def fail(error):
            if not self.winfo_exists():
                return
            self.show_error(error)

        self.app.worker.run(task, done, fail)

    # ---------- Cấp vai trò ----------
    def do_grant(self):
        user = self.selected_user()
        if user is None:
            return
        role = self.role_var.get()
        scope = self.scope_var.get()
        warehouse = self.warehouse_entry.get().strip()
        reference = self.ref_entry.get().strip()

        if scope == "WAREHOUSE" and warehouse == "":
            self.result_label.config(text="Chọn 'Một kho' thì phải nhập mã kho.", fg="#C62828")
            return
        if reference == "":
            self.result_label.config(
                text="Phải nhập mã biên bản có người thứ hai phê chuẩn.", fg="#C62828")
            return

        where = warehouse if scope == "WAREHOUSE" else scope
        question = ("Cấp vai trò " + role + " (" + where + ") cho " +
                    user["username"] + "?")
        if not messagebox.askyesno("Xác nhận cấp quyền", question):
            return

        self.grant_button.config(state="disabled")
        self.result_label.config(text="")
        self.app.set_status("Đang gửi...")

        def task():
            return self.app.api.add_grant(user["username"], role, scope,
                                          warehouse, reference)

        def done(result):
            if not self.winfo_exists():
                return
            self.grant_button.config(state="normal")
            self.result_label.config(text="Đã cấp " + role + " cho " + user["username"],
                                     fg="#2E7D32")
            self.ref_entry.delete(0, END)
            self.load_users()

        def fail(error):
            if not self.winfo_exists():
                return
            self.grant_button.config(state="normal")
            self.show_error(error)

        self.app.worker.run(task, done, fail)