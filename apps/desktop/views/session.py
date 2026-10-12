import tkinter as tk
import webbrowser
from importlib.resources import as_file, files
from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.session import SessionPresenter
from apps.desktop.views.auth_controls import RoundedButton, RoundedField, avatar_photo, ui_icon
from apps.desktop.views.data_table import DataTable
from apps.desktop.views.image_picker import ImagePicker
from apps.desktop.views.mfa_qr import enrollment_qr
from apps.desktop.views.password_recovery import PasswordRecovery
from packages.contracts.identity import Enrollment, RecoveryCodes

ZALO_URL = "https://zalo.me/0869233973"


class SessionView(ttk.Frame):
    def __init__(self, parent, settings):
        super().__init__(parent, padding=20)
        self.presenter = SessionPresenter(self, IdentityClient(settings))
        self.on_session_change = lambda user=None, warehouses=None: None
        self.on_profile_change = lambda user: None
        self.current_user = None
        self.profile_dialog = None
        self.avatar_picker = None
        self.permission_codes = []
        self.permissions_dialog = None
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.remember_session = tk.BooleanVar(value=True)
        self.password_visible = tk.BooleanVar(value=False)
        self.code = tk.StringVar()
        self.status = tk.StringVar()
        self.secret = tk.StringVar()
        self.warehouse = tk.StringVar()
        self.permissions = tk.StringVar()
        self.factor_id = None
        self.enrollment_timer = None
        self.enrollment_qr_image = None
        self.warehouses = []
        self.buttons = []
        self.lifecycle_dialog = None
        self.secret_dialog = None
        self.secret_timer = None
        self.lifecycle_variables = {}

        self.screen = "login"
        self.dark_mode = False
        self.capabilities = {}
        self.inputs = []
        self.configure(style="Auth.Page.TFrame", padding=0)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Auth.Page.TFrame", background="#ffffff")
        style.configure("Auth.Card.TFrame", background="#ffffff")
        style.configure("Auth.TLabel", background="#ffffff", foreground="#263449", font=("Segoe UI", 10))
        style.configure("Auth.Title.TLabel", background="#ffffff", foreground="#102a43", font=("Segoe UI", 22))
        style.configure("Auth.Muted.TLabel", background="#ffffff", foreground="#53657a", font=("Segoe UI", 10))
        style.configure("Auth.TEntry", padding=9, fieldbackground="#ffffff", foreground="#102a43", font=("Segoe UI", 11))
        style.configure("Auth.Primary.TButton", padding=(14, 10), background="#145dcc", foreground="#ffffff", font=("Segoe UI", 11, "bold"))
        style.map("Auth.Primary.TButton", background=[("disabled", "#9aaac0"), ("active", "#104ba8")], foreground=[("disabled", "#ffffff")])
        style.configure("Auth.Secondary.TButton", padding=(10, 7), font=("Segoe UI", 10))
        style.configure("Auth.Link.TButton", padding=(3, 5), background="#ffffff", foreground="#145dcc", borderwidth=0, font=("Segoe UI", 10))
        style.map("Auth.Link.TButton", background=[("active", "#eef5ff")])
        style.configure("Auth.TCombobox", padding=7, font=("Segoe UI", 11))
        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        scroll = self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(fill="both", expand=True)
        self.page = ttk.Frame(self.canvas, style="Auth.Page.TFrame")
        self.page_window = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_card)
        self.breadcrumb = ttk.Frame(self.page, style="Auth.Page.TFrame", padding=(24, 8))
        self.button(self.breadcrumb, "Đăng nhập", self.return_from_recovery, link=True).pack(side="left")
        ttk.Label(self.breadcrumb, text="›  Khôi phục mật khẩu", style="Auth.Muted.TLabel").pack(side="left")
        self.content = ttk.Frame(self.page, style="Auth.Card.TFrame", padding=(24, 68))
        self.content.pack(fill="x")
        self.content.columnconfigure(0, weight=6, uniform="auth")
        self.content.columnconfigure(1, weight=5, uniform="auth")
        self.visual = ttk.Frame(self.content, style="Auth.Card.TFrame", padding=(12, 48))
        self.visual.grid(row=0, column=0, sticky="nsew")
        with as_file(files("apps.desktop.assets").joinpath("login-security-transparent.png")) as path:
            with Image.open(path) as illustration:
                self.hero_source = illustration.copy()
                self.hero_icon = ImageTk.PhotoImage(ImageOps.contain(illustration, (530, 287), Image.Resampling.LANCZOS), master=self)
        self.hero_width = 530
        self.hero_sources = {"login": self.hero_source}
        with as_file(files("apps.desktop.assets").joinpath("recovery-security-transparent.png")) as path:
            with Image.open(path) as illustration:
                self.hero_sources["recovery"] = illustration.copy()
        self.hero_label = ttk.Label(self.visual, image=self.hero_icon, style="Auth.TLabel")
        self.hero_label.pack(pady=(12, 20))
        self.card = ttk.Frame(self.content, style="Auth.Card.TFrame", padding=(28, 8))
        self.card.grid(row=0, column=1, sticky="nsew")
        brand = ttk.Frame(self.card, style="Auth.Card.TFrame")
        # Header carries the brand; keep the form aligned like the supplied reference.
        with as_file(files("apps.desktop.assets").joinpath("wms-logo-transparent.png")) as path:
            with Image.open(path) as logo:
                self.brand_icon = ImageTk.PhotoImage(logo.resize((52, 52), Image.Resampling.LANCZOS), master=self)
        ttk.Label(brand, image=self.brand_icon, style="Auth.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(brand, text="WMS  /  InternTechLead", style="Auth.Muted.TLabel").pack(side="left")
        self.title_label = ttk.Label(self.card, text="Chào mừng trở lại", style="Auth.Title.TLabel")
        self.title_label.pack(anchor="w")
        self.subtitle = ttk.Label(self.card, text="Đăng nhập để quản lý kho của bạn", style="Auth.Muted.TLabel", wraplength=420)
        self.subtitle.pack(anchor="w", pady=(8, 22))
        self.credentials = ttk.Frame(self.card, style="Auth.Card.TFrame")
        self.username_label = ttk.Label(self.credentials, text="Tên đăng nhập hoặc email:", style="Auth.TLabel")
        self.username_label.pack(anchor="w", pady=(0, 5))
        self.username_entry = RoundedField(self.credentials, textvariable=self.username)
        self.username_entry.pack(fill="x", pady=(0, 12))
        self.password_label = ttk.Label(self.credentials, text="Mật khẩu:", style="Auth.TLabel")
        self.password_label.pack(anchor="w", pady=(0, 5))
        self.password_entry = RoundedField(self.credentials, textvariable=self.password, show="•")
        self.password_entry.pack(fill="x")
        self.show_password_button = RoundedButton(self.password_entry, "", self.toggle_password, link=True, glyph="eye")
        self.password_entry.trailing = self.show_password_button
        self.buttons.append(self.show_password_button)
        self.inputs += [self.username_entry, self.password_entry]
        self.mfa_panel = ttk.Frame(self.card, style="Auth.Card.TFrame")
        self.enrollment_qr_label = ttk.Label(self.mfa_panel, style="Auth.TLabel")
        self.secret_label = ttk.Label(self.mfa_panel, textvariable=self.secret, style="Auth.Muted.TLabel", wraplength=420)
        self.secret_label.pack(anchor="w", pady=(0, 8))
        ttk.Label(self.mfa_panel, text="Mã xác thực (6 số)", style="Auth.TLabel").pack(anchor="w", pady=(0, 5))
        self.code_entry = RoundedField(self.mfa_panel, textvariable=self.code, justify="center")
        self.code_entry.pack(fill="x")
        self.inputs.append(self.code_entry)
        self.primary = self.button(self.card, "Đăng nhập", self.next_step, primary=True)
        self.primary.pack(fill="x", pady=(16, 0))
        self.login_options = ttk.Frame(self.card, style="Auth.Card.TFrame")
        self.remember_button = ttk.Checkbutton(self.login_options, text="Giữ đăng nhập trên máy này", variable=self.remember_session)
        self.remember_button.pack(side="left")
        self.buttons.append(self.remember_button)
        self.forgot_button = self.button(self.login_options, "Quên mật khẩu?", self.open_recovery, link=True)
        self.forgot_button.pack(side="right")
        self.alternatives = ttk.Frame(self.card, style="Auth.Card.TFrame")
        self.social_label = ttk.Label(self.alternatives, text="Hoặc đăng nhập với", style="Auth.Muted.TLabel", anchor="center")
        self.social_label.pack(fill="x", pady=(20, 12))
        self.register_row = ttk.Frame(self.alternatives, style="Auth.Card.TFrame")
        ttk.Label(self.register_row, text="Chưa có tài khoản?", style="Auth.TLabel").pack(side="left")
        self.register_button = self.button(self.register_row, "Liên hệ quản trị viên", self.request_account, link=True)
        self.register_button.pack(side="left", padx=(4, 0))
        self.social_row = ttk.Frame(self.alternatives, style="Auth.Card.TFrame")
        self.social_row.pack(fill="x")
        self.social_row.columnconfigure(0, weight=1)
        with as_file(files("apps.desktop.assets").joinpath("google-g.png")) as path:
            with Image.open(path) as icon:
                self.google_icon = ImageTk.PhotoImage(ImageOps.contain(icon,(22,22),Image.Resampling.LANCZOS), master=self)
        self.google_button = self.button(self.social_row, "", self.google)
        self.google_button.configure(image=self.google_icon, compound="left")
        self.google_button.grid(row=0, column=0, sticky="ew")
        self.register_row.pack(fill="x", pady=(16, 0))
        self.google_hint = ttk.Label(self.alternatives, text="Google và gửi mã cần được máy chủ cấu hình", style="Auth.Muted.TLabel", wraplength=420)
        self.back_button = self.button(self.card, "Quay lại đăng nhập", self.logout, link=True)
        self.status_label = ttk.Label(self.card, textvariable=self.status, style="Auth.Muted.TLabel", wraplength=420)
        self.status_label.pack(fill="x", pady=(12, 0))
        self.workspace = ttk.Frame(self.card, style="Auth.Card.TFrame")
        ttk.Label(self.workspace, text="Kho làm việc", style="Auth.TLabel").pack(anchor="w", pady=(8, 5))
        self.selector = ttk.Combobox(self.workspace, textvariable=self.warehouse, state="readonly", style="Auth.TCombobox")
        self.selector.pack(fill="x")
        self.selector.bind("<<ComboboxSelected>>", self.select_warehouse)
        permissions_row = ttk.Frame(self.workspace, style="Auth.Card.TFrame")
        permissions_row.pack(fill="x", pady=8)
        ttk.Label(permissions_row, textvariable=self.permissions, style="Auth.Muted.TLabel").pack(side="left")
        self.button(permissions_row, "Xem quyền", self.show_permissions, link=True).pack(side="right")
        actions = ttk.Frame(self.workspace, style="Auth.Card.TFrame")
        actions.pack(fill="x")
        for text, command in [("Tải lại", self.reload), ("Bảo mật", self.open_security), ("Liên hệ", self.open_contacts), ("Đăng xuất", self.logout)]:
            self.button(actions, text, command).pack(side="left", padx=(0, 6))
        self.recovery_ui = PasswordRecovery(self)
        self.recovery_return_screen = "login"
        self.build_footer()
        self.set_screen("login")
        self.username_entry.bind("<Return>", lambda event: self.password_entry.focus_set())
        self.password_entry.bind("<Return>", lambda event: self.next_step())
        self.code_entry.bind("<Return>", lambda event: self.next_step())
        self.after_idle(self.username_entry.focus_set)
        self.after_idle(lambda: self.presenter.submit("startup"))
        self.bind_scrolling(self.page)

    def show_permissions(self):
        if not self.permission_codes:
            messagebox.showinfo("Quyền tại kho", "Chọn kho để xem quyền được cấp", parent=self)
            return
        if self.permissions_dialog and self.permissions_dialog.winfo_exists():
            self.permissions_dialog.destroy()
        dialog = self.permissions_dialog = tk.Toplevel(self)
        dialog.title("Quyền tại kho")
        dialog.transient(self.winfo_toplevel())
        dialog.geometry("470x460")
        ttk.Label(dialog, text=self.warehouse.get(), padding=12).pack(anchor="w")
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        table = DataTable(body, columns=("permission",), show="headings")
        table.heading("permission", text="Quyền được cấp")
        scroll = ttk.Scrollbar(body, command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        for code in self.permission_codes:
            table.insert("", "end", values=(code,))
        ttk.Button(dialog, text="Đóng", command=dialog.destroy).pack(pady=12)
        dialog.bind("<Escape>", lambda event: dialog.destroy())

    def open_profile(self):
        if not self.current_user or not self.current_user.mfa_verified or self.presenter.pending:
            return
        if self.profile_dialog:
            self.profile_dialog.lift()
            return
        dialog = self.profile_dialog = tk.Toplevel(self)
        dialog.title("Chỉnh sửa hồ sơ")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Hồ sơ của bạn", style="Card.Title.TLabel").pack(anchor="w", pady=(0, 18))
        self.profile_avatar = self.current_user.avatar_base64
        self.profile_avatar_changed = False
        avatar_row = ttk.Frame(body)
        avatar_row.pack(fill="x", pady=(0, 18))
        self.profile_avatar_label = ttk.Label(avatar_row)
        self.profile_avatar_label.pack(side="left", padx=(0, 18))
        avatar_actions = ttk.Frame(avatar_row)
        avatar_actions.pack(side="left")
        ttk.Label(avatar_actions, text="Ảnh đại diện").pack(anchor="w", pady=(0, 6))
        self.profile_choose = ttk.Button(avatar_actions, text="Chọn ảnh", command=self.choose_avatar)
        self.profile_choose.pack(anchor="w")
        self.profile_remove = ttk.Button(avatar_actions, text="Xóa ảnh", command=self.remove_avatar)
        self.profile_remove.pack(anchor="w", pady=5)
        ttk.Label(avatar_actions, text="JPG, PNG hoặc WebP   Tối đa 5 MB").pack(anchor="w")
        self.render_profile_avatar()
        ttk.Label(body, text="Tên đăng nhập").pack(anchor="w")
        ttk.Label(body, text=self.current_user.username).pack(anchor="w", pady=(4, 14))
        ttk.Label(body, text="Tên hiển thị").pack(anchor="w")
        self.profile_name = tk.StringVar(value=self.current_user.display_name)
        self.profile_expected_name = self.current_user.display_name
        self.profile_entry = ttk.Entry(body, textvariable=self.profile_name, width=42)
        self.profile_entry.pack(fill="x", pady=(5, 12))
        self.profile_status = tk.StringVar()
        ttk.Label(body, textvariable=self.profile_status, wraplength=350).pack(fill="x", pady=(0, 8))
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        ttk.Button(actions, text="Hủy", command=self.close_profile).pack(side="right")
        self.profile_save = ttk.Button(actions, text="Lưu thay đổi", command=self.save_profile)
        self.profile_save.pack(side="right", padx=8)
        ttk.Button(body, text="Email và số điện thoại", command=self.profile_contacts).pack(anchor="w", pady=(16, 0))
        dialog.protocol("WM_DELETE_WINDOW", self.close_profile)
        dialog.bind("<Escape>", lambda event: self.close_profile())
        self.profile_entry.bind("<Return>", lambda event: self.save_profile())
        dialog.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.profile_entry.focus_set()

    def render_profile_avatar(self):
        self.profile_avatar_photo = (avatar_photo(self, self.profile_avatar, 80) if self.profile_avatar
                                     else ui_icon(self, "account", "blue", 80))
        self.profile_avatar_label.configure(image=self.profile_avatar_photo)
        self.profile_remove.state(["!disabled"] if self.profile_avatar else ["disabled"])

    def choose_avatar(self):
        if self.presenter.pending or self.avatar_picker:
            return
        self.set_profile_busy(True)
        self.avatar_picker = ImagePicker(self.profile_dialog, self.avatar_selected)
        self.avatar_picker.start()

    def avatar_selected(self, path):
        self.avatar_picker = None
        if not self.profile_dialog:
            return
        if path:
            self.profile_status.set("Đang đọc ảnh…")
            self.presenter.submit("avatar_preview", path)
        else:
            self.set_profile_busy(False)

    def remove_avatar(self):
        if self.presenter.pending:
            return
        self.profile_avatar = None
        self.profile_avatar_changed = True
        self.render_profile_avatar()
        self.profile_status.set("Bấm Lưu thay đổi để dùng avatar mặc định")

    def set_profile_busy(self, busy):
        for control in (self.profile_save, self.profile_entry, self.profile_choose, self.profile_remove):
            control.state(["disabled"] if busy else ["!disabled"])
        if not busy and not self.profile_avatar:
            self.profile_remove.state(["disabled"])

    def profile_contacts(self):
        self.close_profile()
        self.open_contacts()

    def close_profile(self):
        if self.avatar_picker:
            self.avatar_picker.cancel()
            self.avatar_picker = None
        if self.profile_dialog:
            self.profile_dialog.destroy()
            self.profile_dialog = None
        self.profile_name = self.profile_status = None
        self.profile_avatar_photo = None
        self.profile_avatar = None

    def save_profile(self):
        if self.presenter.pending or not self.profile_dialog:
            return
        name = self.profile_name.get().strip()
        if not name or len(name) > 200 or any(c in name for c in "\r\n\t"):
            self.profile_status.set("Nhập tên từ 1 đến 200 ký tự")
            return
        self.profile_status.set("Đang lưu…")
        self.set_profile_busy(True)
        payload = {"display_name": name, "expected_display_name": self.profile_expected_name}
        if self.profile_avatar_changed:
            payload.update(avatar_base64=self.profile_avatar, expected_avatar_version=self.current_user.avatar_version)
        self.presenter.submit("profile", payload)

    def open_zalo(self):
        try:
            opened = webbrowser.open(ZALO_URL, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            messagebox.showinfo("Liên hệ Zalo", "Mở Zalo và tìm số 0869233973, hoặc truy cập:\n" + ZALO_URL,
                                parent=self.winfo_toplevel())

    def bind_scrolling(self, widget):
        widget.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"), add=True)
        widget.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-1, "units"), add=True)
        widget.bind("<Button-5>", lambda event: self.canvas.yview_scroll(1, "units"), add=True)
        for child in widget.winfo_children():
            self.bind_scrolling(child)

    def resize_card(self, event=None):
        width = max(320, self.canvas.winfo_width())
        compact = width < 1020
        self.content.configure(padding=(max(20,(width-(540 if compact else 1180))//2), 40))
        self.canvas.itemconfigure(self.page_window, width=width)
        self.breadcrumb.configure(padding=(max(24, (width-1200)//2), 16))
        if compact:
            self.visual.grid_remove()
            self.card.grid_configure(column=0, columnspan=2)
        else:
            self.visual.grid()
            self.card.grid_configure(column=1, columnspan=1)
            hero_width = min(560, max(280, int((min(width,1180)-48)*6/11)-24))
            if hero_width != self.hero_width:
                self.hero_icon = ImageTk.PhotoImage(ImageOps.contain(self.hero_source, (hero_width, round(hero_width*self.hero_source.height/self.hero_source.width)), Image.Resampling.LANCZOS), master=self)
                self.hero_label.configure(image=self.hero_icon)
                self.hero_width = hero_width
        wrap = 420 if compact else min(440,max(280,int(min(width,1100)/2)-72))
        for label in (self.subtitle, self.status_label, self.secret_label, self.google_hint):
            label.configure(wraplength=wrap)

    def build_footer(self):
        self.footer = tk.Frame(self.page, background="#1d1d1f")
        self.footer.pack(fill="x")
        inner = self.footer_inner = tk.Frame(self.footer, background="#1d1d1f", padx=24, pady=48)
        inner.pack(fill="x")
        self.footer_blocks = []
        self.footer_bodies = []
        for col in range(4):
            block = tk.Frame(inner, background="#1d1d1f")
            block.grid(row=0, column=col, sticky="new", padx=(0, 28))
            self.footer_blocks.append(block)
        brand = tk.Frame(self.footer_blocks[0], background="#1d1d1f")
        brand.pack(anchor="w", pady=(0, 20))
        tk.Label(brand, image=self.brand_icon, background="#1d1d1f").pack(side="left", padx=(0, 12))
        tk.Label(brand, text="WMS\nInternTechLead", background="#1d1d1f", foreground="#ffffff",
                 justify="left", font=("Segoe UI", 15, "bold")).pack(side="left")
        self.footer_text(0, "Quản lý hàng hóa và vận hành kho; Theo dõi nhập, xuất, tồn kho và chứng từ trong một hệ thống")
        self.footer_link(0, "Hỗ trợ: 0329 511 628", self.request_account, accent=True, pady=(18, 6))
        self.footer_link(0, "Zalo: 0869 233 973", self.open_zalo, accent=True)
        icons = tk.Frame(self.footer_blocks[0], background="#1d1d1f")
        icons.pack(anchor="w", pady=(24, 0))
        with as_file(files("apps.desktop.assets").joinpath("zalo.png")) as path:
            with Image.open(path) as source:
                self.footer_zalo_icon = ImageTk.PhotoImage(ImageOps.contain(source, (36, 24), Image.Resampling.LANCZOS), master=self)
        self.footer_icon_buttons = []
        for glyph, action in ((None, self.open_zalo), ("phone", self.request_account), ("book-open", self.help)):
            button = RoundedButton(icons, "", action, glyph=glyph, circular=True)
            button.set_dark(True, background="#1d1d1f")
            button.configure(width=52, height=52)
            if glyph is None:
                button.configure(image=self.footer_zalo_icon)
            button.pack(side="left", padx=(0, 10))
            self.footer_icon_buttons.append(button)
        for col, title in ((1, "Thông tin"), (2, "Bảo mật"), (3, "Địa chỉ & Liên hệ")):
            tk.Label(self.footer_blocks[col], text=title, background="#1d1d1f", foreground="#f5f5f7",
                     font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 24))
        self.footer_link(1, "Giới thiệu hệ thống", lambda: self.footer_info("Giới thiệu WMS", "WMS của InternTechLead hỗ trợ quản lý nhập kho, xuất kho, tồn kho và chứng từ hàng hóa"))
        self.footer_link(1, "Hướng dẫn sử dụng", self.help)
        self.footer_link(1, "Nhập  Xuất  Tồn kho", lambda: self.footer_info("Nghiệp vụ kho", "Đăng nhập, xác thực MFA và chọn kho được cấp quyền để sử dụng các chức năng nhập, xuất và tồn kho"))
        self.footer_link(1, "Báo cáo & chứng từ", lambda: self.footer_info("Báo cáo & chứng từ", "Sau khi đăng nhập, mở Báo cáo / xuất dữ liệu hoặc In chứng từ / tem trong danh sách chức năng"))
        self.footer_link(2, "Xác thực hai bước", self.help)
        self.footer_link(2, "Quyền truy cập theo kho", self.request_account)
        self.footer_link(2, "Khôi phục tài khoản", self.open_recovery)
        self.footer_link(2, "Bảo vệ tài khoản", lambda: self.footer_info("Bảo vệ tài khoản", "Không chia sẻ mật khẩu, mã MFA hoặc mã khôi phục; Đăng xuất khi kết thúc công việc trên máy dùng chung; Liên hệ quản trị viên nếu nghi ngờ tài khoản bị truy cập trái phép"))
        self.footer_text(3, "Đông Thạnh, Hóc Môn, TP HCM\n\nPhụ trách: Trần Trung Kiên")
        self.footer_link(3, "Điện thoại: 0329 511 628", self.request_account, pady=(16, 6))
        self.footer_link(3, "Chat qua Zalo", self.open_zalo, accent=True)
        self.footer_link(3, "Yêu cầu cấp tài khoản", self.request_account)
        tk.Frame(inner, height=1, background="#424245").grid(row=3, column=0, columnspan=4, sticky="ew", pady=(36, 18))
        self.footer_legal = tk.Label(inner, text="© InternTechLead  WMS  Quản lý kho\nMã số thuế: 0869233973  |  Đại diện: Trần Trung Kiên",
                 background="#1d1d1f", foreground="#a0a0a8", justify="left", font=("Segoe UI", 9))
        self.footer_legal.grid(row=4, column=0, columnspan=4, sticky="w")
        self.footer.bind("<Configure>", self.resize_footer)

    def footer_info(self, title, text):
        messagebox.showinfo(title, text, parent=self.winfo_toplevel())

    def footer_text(self, column, text):
        label = tk.Label(self.footer_blocks[column], text=text, background="#1d1d1f", foreground="#b5b5bd",
                         font=("Segoe UI", 10), justify="left", anchor="w", wraplength=240)
        label.pack(fill="x", anchor="w")
        self.footer_bodies.append((column, label))

    def footer_link(self, column, text, command, *, accent=False, pady=(0, 10)):
        color = "#55a6ff" if accent else "#a0a0a8"
        link = tk.Label(self.footer_blocks[column], text=text, background="#1d1d1f", foreground=color,
                        font=("Segoe UI", 10, "bold") if accent else ("Segoe UI", 10), anchor="w", justify="left",
                        cursor="hand2", takefocus=True, wraplength=220)
        link.pack(fill="x", pady=pady)
        for event in ("<Enter>", "<FocusIn>"):
            link.bind(event, lambda event, item=link: item.configure(foreground="#ffffff"))
        for event in ("<Leave>", "<FocusOut>"):
            link.bind(event, lambda event, item=link: item.configure(foreground=color))
        def invoke(event):
            command()
            return "break"
        for event in ("<Button-1>", "<Return>", "<space>"):
            link.bind(event, invoke)
        self.footer_bodies.append((column, link))

    def resize_footer(self, event):
        padding = max(24, (event.width-1180)//2)
        self.footer_inner.configure(padx=padding)
        columns = 4 if event.width >= 1120 else 2
        weights = (4, 2, 2, 3) if columns == 4 else (1, 1, 0, 0)
        for i in range(4):
            self.footer_inner.columnconfigure(i, weight=weights[i], uniform="footer" if i < columns else "")
            self.footer_blocks[i].grid_configure(row=i//columns, column=i%columns, pady=(0, 32) if columns == 2 else 0)
        available = event.width-padding*2
        for column, label in self.footer_bodies:
            label.configure(wraplength=max(130, int(available*weights[column%columns]/sum(weights))-32))
        self.footer_legal.configure(wraplength=available)

    def help(self):
        messagebox.showinfo("Hướng dẫn đăng nhập WMS", "1) Dùng tài khoản hoặc email đã xác minh và mật khẩu\n"
            "2) Lần đầu bật MFA trong ứng dụng Authenticator\n"
            "3) Những lần sau nhập mã 6 số khi được yêu cầu\n"
            "4) Đăng nhập xong, xác minh email/điện thoại trong mục Liên hệ\n\n"
            "Tài khoản mới do quản trị viên cấp; quyền kho cần được phê duyệt\n"
            "Google và gửi mã chỉ hoạt động sau khi máy chủ cấu hình dịch vụ", parent=self.winfo_toplevel())

    def button(self, parent, text, command, *, primary=False, link=False):
        button = RoundedButton(parent, text, command, primary=primary, link=link)
        button.set_dark(self.dark_mode)
        self.buttons.append(button)
        return button

    def set_dark(self, enabled):
        self.dark_mode = enabled
        background = "#171b24" if enabled else "#ffffff"
        foreground = "#edf2f7" if enabled else "#263449"
        muted = "#b2bdcc" if enabled else "#53657a"
        style = ttk.Style(self)
        for name in ("Auth.Page.TFrame", "Auth.Card.TFrame"):
            style.configure(name, background=background)
        for name, color in (("Auth.TLabel", foreground), ("Auth.Title.TLabel", foreground), ("Auth.Muted.TLabel", muted)):
            style.configure(name, background=background, foreground=color)
        self.canvas.configure(background=background)
        def recolor(widget):
            if widget is self.footer:
                return
            if isinstance(widget, (RoundedField, RoundedButton)):
                widget.set_dark(enabled)
                return
            for child in widget.winfo_children():
                recolor(child)
        recolor(self.page)

    def toggle_password(self):
        self.password_visible.set(not self.password_visible.get())
        self.update_password_visibility()

    def update_password_visibility(self):
        visible = self.password_visible.get()
        self.password_entry.configure(show="" if visible else "•")
        self.show_password_button.glyph = "eye-hidden" if visible else "eye"
        self.show_password_button.draw()

    def request_account(self):
        messagebox.showinfo("Cấp tài khoản WMS", "Liên hệ quản trị viên để tạo tài khoản và được cấp quyền kho\n\n"
                            "InternTechLead  Trần Trung Kiên\nĐiện thoại: 0329511628", parent=self.winfo_toplevel())

    def set_screen(self, screen):
        self.screen = screen
        recovering = screen in {"recovery", "recovery_reset"}
        for panel in (self.subtitle, self.credentials, self.mfa_panel, self.login_options, self.primary, self.alternatives, self.back_button, self.status_label, self.workspace,
                      self.recovery_ui.request_panel, self.recovery_ui.reset_panel):
            panel.pack_forget()
        self.breadcrumb.pack_forget()
        self.content.rowconfigure(0, minsize=500 if recovering else 0)
        source = self.hero_sources["recovery" if recovering else "login"]
        if self.hero_source is not source:
            self.hero_source = source
            self.hero_width = 0
        if recovering:
            self.breadcrumb.pack(fill="x", before=self.content)
        self.username_label.pack_forget()
        self.username_entry.pack_forget()
        titles = {"login": ("Đăng nhập", "Email hoặc tài khoản WMS của bạn"),
                  "mfa": ("Xác minh danh tính", "Nhập mã trong ứng dụng xác thực của bạn"),
                  "enroll": ("Bảo vệ tài khoản", "Mở Authenticator → Thêm tài khoản → Quét mã QR, rồi nhập mã 6 số để xác nhận"),
                  "recovery": ("Khôi phục mật khẩu", "Nhập " + ("email" if self.recovery_ui.channel == "email" else "số điện thoại") + " đã xác minh trên tài khoản WMS của bạn để nhận hướng dẫn khôi phục"),
                  "recovery_reset": ("Đặt mật khẩu mới", "Nhập tên tài khoản và mã trong email/SMS; Sau khi đổi mật khẩu, bạn vẫn cần xác thực MFA để vào kho"),
                  "workspace": ("Bạn đã đăng nhập", "Chọn kho và mở chức năng bạn cần")}
        title, subtitle = titles[screen]
        self.title_label.configure(text=title)
        self.subtitle.configure(text=subtitle)
        if screen == "login":
            self.title_label.pack_configure(pady=(0, 34))
        else:
            self.title_label.pack_configure(pady=0)
            self.subtitle.pack(anchor="w", pady=(8, 22))
        if screen in {"login", "enroll"} and not self.factor_id:
            if screen == "login":
                self.username_label.pack(anchor="w", pady=(0, 5), before=self.password_label)
                self.username_entry.pack(fill="x", pady=(0, 18), before=self.password_label)
            self.password_label.configure(text="Mật khẩu:" if screen == "login" else "Nhập lại mật khẩu để bật MFA")
            self.credentials.pack(fill="x")
        if screen == "login":
            self.login_options.pack(fill="x", pady=(12, 8))
        if screen == "mfa" or (screen == "enroll" and self.factor_id):
            self.mfa_panel.pack(fill="x")
            self.code_entry.focus_set()
        if screen != "workspace" and not recovering:
            label = "Đăng nhập" if screen == "login" else "Xác nhận MFA" if screen == "mfa" else "Xác nhận bật MFA" if self.factor_id else "Thiết lập MFA"
            self.primary.configure(text=label)
            self.primary.pack(fill="x", pady=(4 if screen == "login" else 16, 0))
        if screen == "login":
            self.alternatives.pack(fill="x")
        else:
            if recovering:
                panel = self.recovery_ui.request_panel if screen == "recovery" else self.recovery_ui.reset_panel
                panel.pack(fill="x")
            self.back_button.command = self.return_from_recovery if recovering else self.logout
            self.back_button.configure(text="Quay lại" if recovering and self.recovery_return_screen != "login" else "Quay lại đăng nhập")
            self.back_button.pack(anchor="w", pady=(6, 0))
        self.status_label.pack(fill="x", pady=(12, 0))
        if screen == "workspace":
            self.back_button.pack_forget()
            self.workspace.pack(fill="x")
        self.resize_card()

    def next_step(self):
        if self.presenter.pending:
            return
        if self.screen == "login":
            if not self.username.get().strip() or not self.password.get():
                self.status.set("Nhập email/tài khoản và mật khẩu để tiếp tục")
                return
            self.login()
        elif self.screen == "enroll" and not self.factor_id:
            if not self.password.get():
                self.status.set("Nhập lại mật khẩu để thiết lập MFA")
                return
            self.enroll()
        elif len(self.code.get().strip()) != 6 or not self.code.get().strip().isascii() or not self.code.get().strip().isdigit():
            self.status.set("Mã xác thực phải gồm 6 chữ số")
        elif self.screen == "enroll":
            self.confirm()
        else:
            self.mfa()

    def google(self):
        if not self.capabilities.get("google"):
            self.status.set("Google cần cấu hình OAuth trên máy chủ; Xem hướng dẫn thiết lập đăng nhập")
            return
        self.presenter.submit("google", None, self.remember_session.get())

    def open_recovery(self):
        if self.presenter.pending:
            return
        if self.screen not in {"recovery", "recovery_reset"}:
            self.recovery_return_screen = self.screen
        self.close_security()
        self.password.set("")
        self.password_visible.set(False)
        self.update_password_visibility()
        self.code.set("")
        self.recovery_ui.clear()
        self.recovery_ui.show_request()
        self.canvas.yview_moveto(0)

    def return_from_recovery(self):
        if self.presenter.pending:
            return
        self.recovery_ui.clear()
        self.status.set("")
        self.set_screen(self.recovery_return_screen)
        self.canvas.yview_moveto(0)
        if self.screen == "login":
            self.username_entry.focus_set()

    def open_contacts(self):
        self.open_account_dialog("contacts")

    def open_account_dialog(self, kind):
        self.close_security()
        dialog = self.lifecycle_dialog = tk.Toplevel(self)
        dialog.title("Khôi phục đăng nhập" if kind == "recovery" else "Email / điện thoại khôi phục")
        dialog.transient(self.winfo_toplevel())
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        variables = self.lifecycle_variables = {key: tk.StringVar() for key in
            ("kind", "value", "purpose", "password", "code", "username", "reset_token", "new_password", "verify_code")}
        variables["kind"].set("Email")
        variables["purpose"].set("Quên mật khẩu")
        variables["username"].set(self.username.get() if "@" not in self.username.get() else "")
        self.contact_challenge = None
        ttk.Label(body, text="Chọn liên hệ đã xác minh trên tài khoản" if kind == "recovery" else
                  "Xác minh liên hệ để đăng nhập bằng email và khôi phục tài khoản", wraplength=460).pack(anchor="w", pady=(0, 12))
        ttk.Combobox(body, textvariable=variables["kind"], values=["Email", "Điện thoại"], state="readonly").pack(fill="x")
        ttk.Entry(body, textvariable=variables["value"], width=45).pack(fill="x", pady=8)
        if kind == "recovery":
            ttk.Combobox(body, textvariable=variables["purpose"], values=["Quên mật khẩu", "Quên tài khoản"], state="readonly").pack(fill="x")
        else:
            for key, label in [("password", "Mật khẩu hiện tại"), ("code", "Mã MFA mới (6 số)")]:
                ttk.Label(body, text=label).pack(anchor="w", pady=(8, 3))
                ttk.Entry(body, textvariable=variables[key], show="•").pack(fill="x")
        def request():
            if self.presenter.pending:
                return
            channel = "email" if variables["kind"].get() == "Email" else "sms"
            if not self.capabilities.get(channel):
                self.status.set("Dịch vụ gửi mã này chưa được cấu hình; Liên hệ quản trị; bạn vẫn có thể dùng mã reset do quản trị cấp")
                return
            payload = {"kind": channel, "value": variables["value"].get()}
            if kind == "recovery":
                payload["purpose"] = "password" if variables["purpose"].get() == "Quên mật khẩu" else "account"
                self.presenter.submit("forgot", payload)
            else:
                payload.update(password=self.take(variables["password"]), code=self.take(variables["code"]))
                self.presenter.submit("contact_start", payload)
        ttk.Button(body, text="Gửi hướng dẫn" if kind == "recovery" else "Gửi mã xác minh", command=request).pack(fill="x", pady=12)
        if kind == "recovery":
            ttk.Separator(body).pack(fill="x", pady=8)
            for key, label in [("username", "Tài khoản (ghi trong email/SMS)"), ("reset_token", "Mã đặt lại mật khẩu"), ("new_password", "Mật khẩu mới (12–128 ký tự)")]:
                ttk.Label(body, text=label).pack(anchor="w", pady=(8, 3))
                ttk.Entry(body, textvariable=variables[key], show="" if key == "username" else "•").pack(fill="x")
            def reset():
                if self.presenter.pending:
                    return
                payload = {k: v.get() for k, v in variables.items() if k in {"username", "reset_token", "new_password"}}
                self.close_security()
                self.presenter.submit("self_reset", payload)
            ttk.Button(body, text="Đặt lại mật khẩu", command=reset).pack(fill="x", pady=12)
            ttk.Button(body, text="Dùng mã reset do quản trị cấp", command=self.open_security).pack(anchor="w")
        else:
            ttk.Label(body, text="Mã xác minh liên hệ (6 số)").pack(anchor="w")
            ttk.Entry(body, textvariable=variables["verify_code"]).pack(fill="x", pady=6)
            def confirm():
                if self.presenter.pending:
                    return
                if self.contact_challenge:
                    payload = dict(challenge_id=self.contact_challenge, code=self.take(variables["verify_code"]))
                    self.close_security()
                    self.presenter.submit("contact_confirm", payload)
                else:
                    self.status.set("Gửi mã xác minh liên hệ trước")
            ttk.Button(body, text="Xác minh liên hệ", command=confirm).pack(fill="x", pady=8)
        ttk.Label(body, textvariable=self.status, wraplength=460).pack(anchor="w", pady=6)
        dialog.protocol("WM_DELETE_WINDOW", self.close_security)


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
        ttk.Label(body, text="Đổi/reset sẽ đăng xuất mọi phiên; Reset mật khẩu giữ MFA hiện có\n"
                  "Mất TOTP: đăng nhập bằng mật khẩu để nhận yêu cầu MFA trước\n"
                  "Sau reset MFA, đăng nhập và bật MFA mới; quyền quản trị vẫn cần MFA",
                  wraplength=610).grid(row=6, columnspan=2, pady=10)
        def send():
            if self.presenter.pending:
                return
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
        def link_google():
            if self.presenter.pending:
                return
            if not self.capabilities.get("google"):
                self.status.set("Đăng nhập Google chưa được quản trị viên cấu hình")
                return
            payload = {"password": self.take(self.lifecycle_variables["password"]),
                       "code": self.take(self.lifecycle_variables["code"])}
            self.close_security()
            self.presenter.submit("google_link", payload)
        ttk.Button(body, text="Liên kết tài khoản Google", command=link_google).grid(row=8, columnspan=2, pady=8)
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
        dialog.title("Mã khôi phục  chỉ hiển thị một lần")
        ttk.Label(dialog, padding=12, text="Lưu ở nơi riêng an toàn; Bộ mã cũ đã bị thu hồi\n"
                  "Sau khôi phục, toàn bộ bộ mã này hết hiệu lực; Cửa sổ đóng sau 60 giây").pack()
        text = tk.Text(dialog, height=9, width=50)
        text.insert("1.0", "\n".join(codes))
        text.configure(state="disabled")
        text.pack(padx=12)
        ttk.Button(dialog, text="Đã lưu  đóng", command=self.hide_codes).pack(pady=12)
        dialog.protocol("WM_DELETE_WINDOW", self.hide_codes)
        self.secret_timer = self.after(60000, self.hide_codes)

    def take(self, variable):
        value = variable.get()
        variable.set("")
        if variable is self.password:
            self.password_visible.set(False)
            self.update_password_visibility()
        return value

    def login(self):
        password = self.take(self.password)
        self.clear_scope()
        self.presenter.submit("login", self.username.get(), password, self.remember_session.get())

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
            self.status.set("Lấy khóa MFA trước khi xác nhận")

    def select_warehouse(self, event=None):
        self.permissions.set("")
        self.permission_codes = []
        index = self.selector.current()
        if index >= 0:
            self.presenter.submit("warehouse", self.warehouses[index].id)

    def hide_enrollment(self):
        if self.enrollment_timer:
            self.after_cancel(self.enrollment_timer)
            self.enrollment_timer = None
        self.enrollment_qr_label.configure(image="")
        self.enrollment_qr_label.pack_forget()
        self.enrollment_qr_image = None
        self.secret.set("")
        self.code.set("")
        self.factor_id = None
        if self.screen == "enroll":
            self.set_screen("enroll")
            self.status.set("Mã thiết lập đã hết hạn hoặc bị hủy; Nhập lại mật khẩu để tạo mã QR mới")

    def clear_scope(self):
        self.close_profile()
        if self.permissions_dialog and self.permissions_dialog.winfo_exists():
            self.permissions_dialog.destroy()
        self.permissions_dialog = None
        self.current_user = None
        self.permission_codes = []
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
        self.code.set("")
        self.password.set("")
        self.recovery_ui.clear()
        self.password_visible.set(False)
        self.update_password_visibility()
        self.set_screen("login")

    def release_variables(self):
        self.close_profile()
        self.hide_enrollment()
        self.close_security()
        self.hide_codes()
        self.brand_icon = None
        self.google_icon = None
        self.footer_zalo_icon = None
        self.hero_icon = None
        self.hero_source = None
        self.hero_sources.clear()
        self.recovery_ui.release()
        # Run on the UI thread before destroying Tk. Worker-side cyclic GC must
        # never become responsible for finalizing Tk variables/interpreters.
        for name in ("username", "password", "remember_session", "password_visible", "code", "status", "secret", "warehouse", "permissions"):
            setattr(self, name, None)

    def session_busy(self):
        for button in self.buttons:
            button.state(["disabled"])
        for entry in self.inputs:
            entry.state(["disabled"])
        self.selector.state(["disabled"])
        self.status.set("Đang xử lý…")

    def enable(self):
        for button in self.buttons:
            button.state(["!disabled"])
        for entry in self.inputs:
            entry.state(["!disabled"])
        self.selector.state(["!disabled", "readonly"])

    def session_error(self, message, *, signed_out):
        self.enable()
        recovery_screen = self.screen if self.screen in {"recovery", "recovery_reset"} else None
        if signed_out:
            self.clear_scope()
            if recovery_screen:
                self.recovery_return_screen = "login"
                self.set_screen(recovery_screen)
        self.status.set(message)
        if self.profile_dialog:
            self.profile_status.set(message)
            self.set_profile_busy(False)

    def session_result(self, action, result):
        self.enable()
        if action == "avatar_preview":
            if self.profile_dialog:
                self.profile_avatar = result
                self.profile_avatar_changed = True
                self.render_profile_avatar()
                self.set_profile_busy(False)
                self.profile_status.set("Bấm Lưu thay đổi để cập nhật ảnh đại diện")
            return
        if action == "profile":
            self.current_user = result
            self.on_profile_change(result)
            self.close_profile()
            self.status.set("Đã cập nhật hồ sơ")
            return
        if action == "startup":
            self.session_result("options", result["options"])
            if result["session"]:
                self.session_result("restore", result["session"])
            if result["notice"]:
                self.status.set(result["notice"])
            return
        if action == "options":
            self.capabilities = result
            self.google_hint.configure(text="" if result.get("google") else "Google cần được cấu hình để đăng nhập")
            self.enable()
            self.status.set("")
            return
        if action in {"forgot", "contact_start", "contact_confirm", "google_link"}:
            self.status.set(result.get("message", "Đã cập nhật"))
            if action == "contact_start":
                self.contact_challenge = result["challenge_id"]
            return
        if result == "MFA_REQUIRED":
            self.set_screen("mfa")
            self.status.set("Nhập mã trong ứng dụng xác thực rồi bấm Xác nhận MFA")
        elif result == "SIGNED_OUT":
            self.clear_scope()
            self.status.set("Đã đổi mật khẩu; Hãy đăng nhập lại và xác thực MFA để vào kho" if action == "self_reset" else "Đã đăng xuất" if action == "logout" else
                            "Đã đăng xuất; Đăng nhập lại; sau reset MFA hãy bật MFA mới")
        elif isinstance(result, RecoveryCodes):
            self.show_codes(result.codes)
            self.status.set("Mã khôi phục mới chỉ hiển thị một lần trong cửa sổ riêng")
        elif isinstance(result, Enrollment):
            self.hide_enrollment()
            self.enrollment_timer = self.after(result.expires_in * 1000, self.hide_enrollment)
            self.factor_id = result.factor_id
            self.enrollment_qr_image = ImageTk.PhotoImage(enrollment_qr(result.provisioning_uri), master=self)
            self.enrollment_qr_label.configure(image=self.enrollment_qr_image)
            self.enrollment_qr_label.pack(anchor="center", pady=(0, 12), before=self.secret_label)
            self.secret.set("Không quét được? Nhập khóa này trong Authenticator:\n" + result.secret)
            self.set_screen("enroll")
            self.status.set("Quét mã QR bằng ứng dụng xác thực; nhập mã 6 số rồi bấm Xác nhận bật MFA trong 5 phút")
        elif action == "warehouse":
            self.permission_codes = list(result)
            self.permissions.set(f"Được cấp {len(result)} quyền tại kho")
            self.status.set("Đã chọn kho")
        else:
            self.clear_scope()
            self.warehouses = result["warehouses"]
            user = self.current_user = result["user"]
            self.on_session_change(user, result["warehouses"])
            self.selector.configure(values=[f"{item.code}  {item.name}" for item in self.warehouses])
            self.set_screen("workspace" if user.mfa_verified else "enroll")
            state = "MFA đã xác thực" if user.mfa_verified else "Chưa bật/xác thực MFA"
            self.status.set(state if self.warehouses else "Chưa được cấp quyền kho")
            if self.presenter.api.persistence_notice:
                self.status.set(self.status.get() + "  " + self.presenter.api.persistence_notice)
