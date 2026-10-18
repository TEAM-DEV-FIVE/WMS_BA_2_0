import tkinter as tk
from importlib.resources import as_file, files
from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from apps.desktop.api.client import ApiClient, DesktopSettings
from apps.desktop.application_icon import install_application_icon
from apps.desktop.lifecycle import await_workers
from apps.desktop.presenters.connection import ConnectionPresenter
from apps.desktop.printing.view import PrintView
from apps.desktop.views.admin import AdminView
from apps.desktop.views.admin_theme import AdminTheme
from apps.desktop.views.admin_workspace import SECTIONS, AdminNavigation
from apps.desktop.views.approvals import ApprovalView
from apps.desktop.views.auth_controls import RoundedButton, RoundedField, ThemeSwitch, avatar_photo, ui_icon
from apps.desktop.views.counting import CountView
from apps.desktop.views.custom_fields import CustomFieldView
from apps.desktop.views.fulfillment import FulfillmentView
from apps.desktop.views.imports import ImportView
from apps.desktop.views.issues import IssueView
from apps.desktop.views.master_data import MasterDataView
from apps.desktop.views.master_details import ProductDetailsView
from apps.desktop.views.moves import MoveView
from apps.desktop.views.navigation import NavigationStrip
from apps.desktop.views.openings import OpeningView
from apps.desktop.views.orders import OrderView
from apps.desktop.views.ownership import OwnershipView
from apps.desktop.views.periods import PeriodView
from apps.desktop.views.quality import QualityView
from apps.desktop.views.receipt_recovery import ReceiptRecoveryView
from apps.desktop.views.receipts import ReceiptView
from apps.desktop.views.recovery import RecoveryView
from apps.desktop.views.reports import ReportView
from apps.desktop.views.returns import ReturnView
from apps.desktop.views.reversals import ReversalView
from apps.desktop.views.serial_lookup import SerialLookupView
from apps.desktop.views.session import SessionView
from apps.desktop.views.transfers import TransferView
from apps.desktop.views.workspace_loading import WorkspaceLoading
from packages.contracts import Health


class DesktopShell:
    def __init__(self, root: tk.Tk, settings: DesktopSettings):
        self.root = root
        self.settings = settings
        self.root.title("WMS  Quản lý kho")
        self.application_icons = install_application_icon(root)
        self.root.update_idletasks()
        if self.root.winfo_width() <= 200 and self.root.winfo_height() <= 200:
            self.root.geometry(f"{min(1366, self.root.winfo_screenwidth()-60)}x{max(690, min(900, self.root.winfo_screenheight()-80))}")
        self.root.minsize(800, 620)
        self.closed = False
        self.closing = False
        self.workers_stopped = False
        self.restart_requested = False
        self.exit_dialog = None
        self.dark_mode = False
        self.authenticated = False
        self.current_user = None
        self.work_history = []
        self.destroyed_widgets = []
        self.status = tk.StringVar(value="Chưa kiểm tra kết nối")
        self.presenter = ConnectionPresenter(self, ApiClient(settings))

        self.root.configure(background="#ffffff")
        header = self.header = tk.Frame(root, background="#515154", height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        self.header_inner = tk.Frame(header, background="#515154")
        self.header_inner.place(relx=.5, y=8, anchor="n", width=1180)
        self.header_inner.columnconfigure(1, weight=1)
        brand = self.brand = tk.Frame(self.header_inner, background="#515154")
        brand.grid(row=0, column=0, sticky="w", padx=(0, 24))
        with as_file(files("apps.desktop.assets").joinpath("wms-logo-transparent.png")) as logo:
            with Image.open(logo) as source:
                self.header_icon = ImageTk.PhotoImage(ImageOps.contain(source,(64,64),Image.Resampling.LANCZOS), master=root)
                self.compact_header_icon = ImageTk.PhotoImage(ImageOps.contain(source,(42,42),Image.Resampling.LANCZOS), master=root)
        with as_file(files("apps.desktop.assets").joinpath("wms-logo-navy.png")) as logo:
            with Image.open(logo) as source:
                self.light_header_icon = ImageTk.PhotoImage(ImageOps.contain(source, (48, 48), Image.Resampling.LANCZOS), master=root)
        self.brand_label = tk.Label(brand, image=self.header_icon, background="#515154")
        self.brand_label.pack(side="left", padx=(0, 8))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Search.TCombobox", padding=8, foreground="#515154", fieldbackground="#ffffff", font=("Segoe UI", 10))
        self.function_search = RoundedField(self.header_inner, combo=True, leading="search")
        self.function_search.set("Bạn cần chức năng gì…")
        self.function_search.grid(row=0, column=1, sticky="ew", padx=(0, 24))
        self.function_search.bind("<Return>", self.search_function)
        self.function_search.bind("<<ComboboxSelected>>", self.search_function)
        self.function_search.bind("<FocusIn>", lambda event: self.function_search.set("") if self.function_search.get() == "Bạn cần chức năng gì…" else None)
        self.header_controls = []
        for col, title, glyph, action in [(2, "Hỗ trợ", "help", self.support), (3, "Tài khoản", "account", self.open_account_menu)]:
            control = RoundedButton(self.header_inner,title,action,glyph=glyph,header=True)
            self.header_controls.append(control)
            control.grid(row=0,column=col,padx=4)
            if col == 3:
                self.account_button = control
        self.account_button.avatar = True
        self.account_menu = tk.Menu(root, tearoff=False)
        self.account_menu.add_command(label="Chỉnh sửa hồ sơ", command=lambda: self.session_view.open_profile())
        self.account_menu.add_command(label="Đăng xuất", command=lambda: self.session_view.logout())
        self.theme_button = ThemeSwitch(self.header_inner, self.toggle_theme)
        self.reload_button = RoundedButton(self.header_inner, "Tải lại", self.request_reload,
                                           glyph="action-refresh-cw", header=True)
        self.reload_button.grid(row=0, column=4, padx=4)
        self.header_controls.append(self.reload_button)
        self.theme_button.grid(row=0, column=5, padx=(12, 0))
        labels = [("Kho làm việc", "session_view"), ("Danh mục", "master_container"),
                  ("Nhập kho", "receipt_view"), ("Xuất kho", "issue_view"), ("Tồn kho", "report_view"),
                  ("Báo cáo", "report_view"), ("Quản trị", "admin_view"), ("Hướng dẫn", None)]
        self.menu_items = [(title, (lambda key=name: self.open_section(getattr(self, key))) if name
                            else lambda: self.session_view.help()) for title, name in labels]
        menu = self.header_menu = NavigationStrip(header, self.menu_items, self.select_menu)
        menu.place(relx=.5, y=72, anchor="n", width=1100)
        header.bind("<Configure>", self.resize_header)
        self.erp_bar = tk.Frame(root, background="#005b9e")
        self.group_buttons = {}
        for index, group in enumerate(dict.fromkeys(row[0] for row in SECTIONS)):
            button = ttk.Button(self.erp_bar, text=group, width=1, style="ERP.Nav.TButton", command=lambda name=group: self.open_group(name))
            self.erp_bar.columnconfigure(index, weight=len(group))
            button.grid(row=0, column=index, sticky="ew")
            self.group_buttons[group] = button
        self.work_area = ttk.Frame(root, style="Page.TFrame")
        self.work_area.pack(fill="both", expand=True)
        self.sidebar = AdminNavigation(self.work_area, self.open_key)
        self.main_area = ttk.Frame(self.work_area, style="Page.TFrame")
        self.main_area.pack(side="right", fill="both", expand=True)
        self.page_heading = ttk.Frame(self.main_area, padding=(10, 5), style="Page.TFrame")
        self.page_title = ttk.Label(self.page_heading, text="Danh mục sản phẩm", style="Title.TLabel")
        self.page_title.pack(side="left")
        self.page_description = ttk.Label(self.page_heading, style="Page.TLabel", wraplength=500)
        self.page_description.pack(side="left", padx=16)
        navigation = self.navigation_bar = ttk.Frame(self.main_area, padding=(16, 6))
        navigation.pack(fill="x")
        ttk.Label(navigation, text="Chức năng").pack(side="left", padx=(0, 8))
        self.navigation = ttk.Combobox(navigation, state="readonly", width=34)
        self.navigation.pack(side="left")
        # A single selector keeps every section reachable at 900×690 even when
        # the combined notebook tab labels exceed the window width.
        style = ttk.Style(root)
        style.layout("WMS.TNotebook.Tab", [])
        notebook = self.notebook = ttk.Notebook(self.main_area, style="WMS.TNotebook")
        notebook.pack(fill="both", expand=True)
        self.session_view = SessionView(notebook, settings)
        self.session_view.on_profile_change = self.update_account
        self.session_view.presenter.api.enable_recovery()
        self.draft_only = tk.BooleanVar(value=False)
        self.draft_secondary = ttk.Checkbutton(self.page_heading, text="Lưu nháp nghiệp vụ", variable=self.draft_only, command=self.set_draft_mode)
        ttk.Checkbutton(navigation, text="Chỉ lưu nháp nghiệp vụ (trừ IAM/tệp)", variable=self.draft_only,
                        command=self.set_draft_mode).pack(side="left", padx=12)
        notebook.add(self.session_view, text="Đăng nhập và kho")
        self.master_container = ttk.Notebook(notebook)
        notebook.add(self.master_container, text="Danh mục")
        self.master_view = MasterDataView(self.master_container, self.session_view.presenter.api)
        self.master_container.add(self.master_view, text="Danh mục cơ sở")
        self.product_details_view = ProductDetailsView(self.master_container, self.session_view.presenter.api)
        self.master_container.add(self.product_details_view, text="Quy đổi / barcode / giá")
        self.ownership_view = OwnershipView(self.master_container, self.session_view.presenter.api)
        self.master_container.add(self.ownership_view, text="Chủ hàng / ký gửi")
        self.serial_view = SerialLookupView(notebook, self.session_view.presenter.api)
        self.session_view.on_session_change = self.session_changed
        notebook.add(self.serial_view, text="Tra serial / bảo hành")
        self.order_view = OrderView(notebook, self.session_view.presenter.api)
        notebook.add(self.order_view, text="PO/SO và duyệt")
        self.approval_view = ApprovalView(notebook, self.session_view.presenter.api)
        notebook.add(self.approval_view, text="Hộp thư duyệt PO/SO/nhận")
        self.receipt_view = ReceiptView(notebook, self.session_view.presenter.api)
        notebook.add(self.receipt_view, text="Nhận hàng")
        self.opening_view = OpeningView(notebook, self.session_view.presenter.api)
        notebook.add(self.opening_view, text="Tồn đầu kỳ")
        self.consignment_view = OpeningView(notebook, self.session_view.presenter.api, consignment=True)
        notebook.add(self.consignment_view, text="Nhận ký gửi")
        self.import_view = ImportView(notebook, self.session_view.presenter.api)
        self.import_view.on_open_document = self.open_imported_document
        notebook.add(self.import_view, text="Import tệp / tồn đầu kỳ")
        self.order_view.on_open_receipt = self.open_receipt
        self.order_view.on_open_approvals = self.open_approvals
        self.approval_view.on_open_document = self.open_document
        self.receipt_recovery_view = ReceiptRecoveryView(notebook, self.receipt_view.presenter)
        notebook.add(self.receipt_recovery_view, text="Phục hồi nhận hàng")
        self.recovery_view = RecoveryView(notebook, self.session_view.presenter.api)
        notebook.add(self.recovery_view, text="Nháp / phục hồi lệnh")
        self.issue_view = IssueView(notebook, self.session_view.presenter.api)
        notebook.add(self.issue_view, text="Giữ hàng / xuất kho")
        self.fulfillment_view = FulfillmentView(notebook, self.session_view.presenter.api)
        self.fulfillment_view.on_signed_out = self.admin_signed_out
        notebook.add(self.fulfillment_view, text="Soạn hàng / đóng kiện")
        self.admin_view = AdminView(notebook, self.session_view.presenter.api)
        self.admin_view.on_signed_out = self.admin_signed_out
        notebook.add(self.admin_view, text="Quản trị tài khoản / quyền")
        self.quality_view = QualityView(notebook, self.session_view.presenter.api)
        self.move_view = MoveView(notebook, self.session_view.presenter.api)
        for view, title in [(self.quality_view, "Kiểm định chất lượng"), (self.move_view, "Cất hàng / di chuyển")]:
            view.on_signed_out = self.admin_signed_out
            notebook.add(view, text=title)
        self.customer_return_view = ReturnView(notebook, self.session_view.presenter.api, "CUSTOMER_RETURN")
        self.supplier_return_view = ReturnView(notebook, self.session_view.presenter.api, "SUPPLIER_RETURN")
        self.return_views = [self.customer_return_view, self.supplier_return_view]
        for view, title in zip(self.return_views, ["Khách trả hàng", "Trả nhà cung cấp"]):
            view.on_signed_out = self.admin_signed_out
            notebook.add(view, text=title)
        self.transfer_view = TransferView(notebook, self.session_view.presenter.api)
        self.transfer_view.on_signed_out = self.admin_signed_out
        notebook.add(self.transfer_view, text="Chuyển kho / transit")
        self.reversal_view = ReversalView(notebook, self.session_view.presenter.api)
        self.reversal_view.on_signed_out = self.admin_signed_out
        notebook.add(self.reversal_view, text="Đảo giao dịch")
        self.count_view = CountView(notebook, self.session_view.presenter.api)
        self.period_view = PeriodView(notebook, self.session_view.presenter.api)
        for view, title in [(self.count_view, "Kiểm kê / điều chỉnh"), (self.period_view, "Kỳ kho")]:
            view.on_signed_out = self.admin_signed_out
            notebook.add(view, text=title)
        self.print_view = PrintView(notebook, self.session_view.presenter.api)
        notebook.add(self.print_view, text="In chứng từ / tem")
        self.report_view = ReportView(notebook, self.session_view.presenter.api)
        notebook.add(self.report_view, text="Báo cáo / xuất dữ liệu")
        self.custom_fields_view = CustomFieldView(notebook, self.session_view.presenter.api)
        self.custom_fields_view.on_signed_out = self.admin_signed_out
        notebook.add(self.custom_fields_view, text="Trường mở rộng")
        container = self.connection_view = ttk.Frame(notebook, padding=24)
        notebook.add(container, text="Kết nối")
        ttk.Label(container, text="WMS  Quản lý kho", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(container, text="Kết nối máy chủ", font=("Segoe UI", 14)).pack(anchor="w", pady=(24, 8))
        ttk.Label(container, text=settings.api_url, wraplength=720).pack(anchor="w")
        ttk.Label(container, textvariable=self.status, wraplength=720).pack(anchor="w", pady=16)
        actions = ttk.Frame(container)
        actions.pack(anchor="w")
        ttk.Button(actions, text="Kiểm tra kết nối", command=self.presenter.check).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Kiểm tra sẵn sàng", command=lambda: self.presenter.check(readiness=True)).pack(side="left")
        ttk.Separator(container).pack(fill="x", pady=24)
        ttk.Label(container, text="Quyền thao tác được kiểm tra theo tài khoản và từng kho;\nNếu kết nối bị gián đoạn, mở Nháp / phục hồi lệnh để kiểm tra kết quả",
                  wraplength=720).pack(anchor="w")
        self.work_tabs = ttk.Frame(self.main_area)
        self.navigation.configure(values=[notebook.tab(tab, "text") for tab in notebook.tabs()])
        self.function_search.configure(values=[notebook.tab(tab, "text") for tab in notebook.tabs()])
        self.navigation.current(0)
        self.navigation.bind("<<ComboboxSelected>>", lambda event: self.open_section(root.nametowidget(notebook.tabs()[self.navigation.current()])))
        notebook.bind("<<NotebookTabChanged>>", self.section_changed)
        self.admin_theme = AdminTheme(root)
        self.admin_theme.apply()
        self.root.bind("<Configure>", self.resize_workspace, add="+")
        self.root.bind("<Map>", self.style_mapped_widget, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.workspace_loading = WorkspaceLoading()
        self.workspace_loaders = {
            self.opening_view: self.opening_view.open_workspace, self.quality_view: self.quality_view.open_workspace,
            self.order_view: self.order_view.load, self.approval_view: self.approval_view.load,
            self.receipt_view: self.receipt_view.load, self.consignment_view: self.consignment_view.open_workspace,
            self.issue_view: self.issue_view.load, self.fulfillment_view: self.fulfillment_view.presenter.load,
            self.move_view: self.move_view.presenter.load, self.transfer_view: self.transfer_view.presenter.load,
            self.customer_return_view: self.customer_return_view.presenter.load,
            self.supplier_return_view: self.supplier_return_view.presenter.load,
            self.count_view: self.count_view.presenter.load, self.period_view: self.period_view.presenter.load,
            self.reversal_view: self.reversal_view.presenter.load,
            self.custom_fields_view: self.custom_fields_view.open_workspace,
            self.report_view: self.report_view.create,
            self.serial_view: self.serial_view.browse,
        }
        for view in self.workspace_loaders:
            for name in ("selector", "kind", "filter"):
                widget = getattr(view, name, None)
                if hasattr(widget, "bind"):
                    widget.bind("<<ComboboxSelected>>", lambda event, target=view: self.root.after_idle(lambda: self.load_workspace(target)), add="+")
        self.poll_id = self.root.after(50, self.poll)
        self.navigation_bar.pack_forget()
        self.show_authenticated_header(False)

    def resize_header(self, event):
        width = max(740,event.width-24) if self.authenticated else min(1100,max(740,event.width-48))
        self.header_inner.place_configure(width=width, y=3 if self.authenticated else 8)
        if self.header_menu.winfo_manager():
            self.header_menu.place_configure(width=width)

    def toggle_theme(self, enabled=None):
        self.dark_mode = not self.dark_mode if enabled is None else enabled
        self.theme_button.set_dark(self.dark_mode)
        self.root.configure(background="#171b24" if self.dark_mode else "#ffffff")
        self.session_view.set_dark(self.dark_mode)
        self.admin_theme.apply(self.dark_mode)
        self.header_palette()
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if not str(widget).startswith(str(self.session_view)):
                self.admin_theme.native(widget)

    def style_mapped_widget(self, event):
        if not str(event.widget).startswith(str(self.session_view)):
            self.admin_theme.native(event.widget)

    def resize_workspace(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        if not self.authenticated:
            self.sidebar.pack_forget()
            self.page_heading.pack_forget()
            self.navigation_bar.pack_forget()
            self.work_tabs.pack_forget()
            return
        self.page_heading.pack(fill="x", before=self.notebook)
        # Keep all form width on smaller laptop displays; the selector remains usable.
        if self.root.winfo_width() >= 1250:
            self.sidebar.pack(side="left", fill="y", before=self.main_area)
            self.navigation_bar.pack_forget()
            self.draft_secondary.pack(side="right")
        else:
            self.sidebar.pack_forget()
            self.navigation_bar.pack(fill="x", before=self.notebook)
            self.draft_secondary.pack_forget()
        self.work_tabs.pack(fill="x", before=self.page_heading)

    def load_workspace(self, view):
        if self.authenticated and str(view) == self.notebook.select() and view in self.workspace_loaders:
            self.workspace_loading.open(view, self.workspace_loaders[view])

    def open_key(self, key):
        view = getattr(self, key, None)
        return self.open_section(view) if view is not None else False

    def open_group(self, group):
        key = next(row[1] for row in SECTIONS if row[0] == group)
        self.open_key(key)

    def update_work_tabs(self, key):
        if not self.authenticated:
            return
        if key not in self.work_history:
            self.work_history.append(key)
            self.work_history = self.work_history[-4:]
        for child in self.work_tabs.winfo_children():
            child.destroy()
        titles = {row[1]: row[2] for row in SECTIONS}
        for item in self.work_history:
            label = titles[item] if len(titles[item]) <= 24 else titles[item][:22] + "…"
            button = ttk.Button(self.work_tabs, text=label, style="ERP.WorkTab.TButton", command=lambda target=item: self.open_key(target))
            button.pack(side="left", padx=(0, 2), pady=(4, 0))
            button.state(["selected"] if item == key else ["!selected"])

    def section_changed(self, event=None):
        if self.closed:
            return
        self.navigation.current(self.notebook.index("current"))
        selected = self.notebook.select()
        for group, key, title, description in SECTIONS:
            if str(getattr(self, key)) == selected:
                self.sidebar.select(key)
                self.page_title.configure(text=title)
                self.page_description.configure(text=group)
                for name, button in self.group_buttons.items():
                    button.state(["selected"] if name == group else ["!selected"])
                self.update_work_tabs(key)
                if hasattr(self, "workspace_loaders"):
                    self.load_workspace(getattr(self, key))
                break

    def update_account(self, user):
        self.current_user = user
        name = user.display_name if user else "Tài khoản"
        caption = name if len(name) <= 26 else name[:25] + "…"
        encoded = getattr(user, "avatar_base64", None) if user else None
        photo = avatar_photo(self.root, encoded, 32) if encoded else None
        self.account_button.configure(image=photo, text=caption + "  ▾", width=min(280, max(140, len(caption) * 9 + 64)))

    def open_account_menu(self):
        if not self.authenticated or self.session_view.presenter.pending:
            return
        button = self.account_button
        try:
            self.account_menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            self.account_menu.grab_release()

    def show_authenticated_header(self, authenticated):
        self.header.configure(height=64 if authenticated else 80)
        if authenticated:
            self.function_search.grid()
            self.account_button.grid()
            self.header_menu.place_forget()
            self.erp_bar.pack(fill="x", after=self.header)
        else:
            self.function_search.grid_remove()
            self.account_button.grid_remove()
            self.header_menu.place_forget()
            self.header_menu.select(None)
            self.function_search.set("Bạn cần chức năng gì…")
            self.erp_bar.pack_forget()
            self.work_history.clear()
        self.header_palette()

    def header_palette(self):
        light = self.authenticated and not self.dark_mode
        background = "#ffffff" if light else "#1d2635" if self.authenticated else "#515154"
        self.header.configure(background=background)
        self.header_inner.configure(background=background)
        self.brand.configure(background=background)
        self.brand_label.configure(image=self.light_header_icon if light else self.compact_header_icon if self.authenticated else self.header_icon,
                                   background=background)
        self.erp_bar.configure(background="#005b9e")
        for control in self.header_controls:
            control.header_surface = background
            control.header_tone = "blue" if light else "white"
            control.configure(background=background)
        self.theme_button.light_surface = light
        self.theme_button.icons = [ui_icon(self.root, name, "blue" if light else "white") for name in ("sun", "moon")]
        self.theme_button.configure(background=background)
        self.theme_button.draw()
        self.function_search.set_dark(self.dark_mode)
        self.function_search.configure(background=background, height=40 if self.authenticated else 46)

    def open_section(self, view):
        if view is not self.session_view and not self.authenticated:
            self.notebook.select(self.session_view)
            self.session_view.status.set("Đăng nhập và hoàn tất MFA để mở chức năng này")
            self.session_view.canvas.yview_moveto(0)
            return False
        self.notebook.select(view)
        if view is self.master_container:
            self.master_container.select(self.master_view)
            self.master_view.open_products()
        if view is self.quality_view:
            self.quality_view.open_workspace()
        if view is self.opening_view:
            self.opening_view.open_workspace()
        self.load_workspace(view)
        return True

    def select_menu(self, index):
        self.header_menu.select(index)

    def search_function(self, event=None):
        query = self.function_search.get().strip().casefold()
        aliases = {"nhập kho": self.receipt_view, "xuất kho": self.issue_view, "tồn kho": self.report_view}
        if query in aliases:
            self.open_section(aliases[query])
            return
        matches = [tab for tab in self.notebook.tabs() if query and query in self.notebook.tab(tab, "text").casefold()]
        if matches:
            self.open_section(self.root.nametowidget(matches[0]))
        else:
            messagebox.showinfo("Tìm chức năng", "Chọn một chức năng trong danh sách hoặc nhập tên chức năng", parent=self.root)

    def support(self):
        messagebox.showinfo("Hỗ trợ WMS", "InternTechLead\nĐiện thoại: 0329511628\nĐông Thạnh, Hóc Môn, TP HCM", parent=self.root)

    def show_loading(self) -> None:
        self.status.set("Đang kiểm tra… Bạn vẫn có thể thao tác hoặc đóng cửa sổ")

    def session_changed(self, user=None, warehouses=None):
        if hasattr(self, "workspace_loading"):
            self.workspace_loading.clear()
        self.account_menu.unpost()
        self.update_account(user)
        previously_authenticated = self.authenticated
        self.authenticated = bool(user and user.mfa_verified)
        self.show_authenticated_header(self.authenticated)
        self.resize_workspace()
        if not self.authenticated:
            self.notebook.select(self.session_view)
        self.draft_only.set(self.session_view.presenter.api.draft_only)
        self.recovery_view.session_changed(user, warehouses)
        self.master_view.session_changed(user)
        self.product_details_view.session_changed(user, warehouses)
        self.ownership_view.session_changed(user, warehouses)
        self.serial_view.session_changed(user, warehouses)
        self.order_view.session_changed(user, warehouses)
        self.approval_view.session_changed(user, warehouses)
        self.receipt_view.session_changed(user, warehouses)
        self.issue_view.session_changed(user, warehouses)
        self.fulfillment_view.session_changed(user, warehouses)
        self.opening_view.session_changed(user, warehouses)
        self.consignment_view.session_changed(user, warehouses)
        self.import_view.session_changed(user, warehouses)
        self.admin_view.session_changed(user, warehouses)
        self.quality_view.session_changed(user, warehouses)
        self.move_view.session_changed(user, warehouses)
        for view in self.return_views:
            view.session_changed(user, warehouses)
        self.transfer_view.session_changed(user, warehouses)
        self.count_view.session_changed(user, warehouses)
        self.period_view.session_changed(user, warehouses)
        self.reversal_view.session_changed(user, warehouses)
        self.print_view.session_changed(user, warehouses)
        self.report_view.session_changed(user, warehouses)
        self.custom_fields_view.session_changed(user, warehouses)
        if self.authenticated and not previously_authenticated:
            self.open_key("master_container")

    def set_draft_mode(self):
        self.session_view.presenter.api.draft_only = bool(self.draft_only.get())

    def admin_signed_out(self, message):
        # A queued session snapshot/warehouse response must not restore the
        # scope just invalidated by the admin worker.
        session = self.session_view.presenter
        session.sequence += 1
        if session.pending:
            session.pending.cancel()
        session.pending = None
        self.session_view.password.set("")
        self.session_view.code.set("")
        self.session_view.session_error(message, signed_out=True)

    def open_approvals(self, kind, warehouse_id):
        view = self.approval_view
        self.notebook.select(view)
        if view.busy or view.presenter.uncertain:
            return
        view.variables["kind"].set(kind)
        for index, warehouse in enumerate(view.warehouses):
            if str(warehouse.id) == warehouse_id:
                view.selector.current(index)
                view.scope_changed()
                view.load()
                break

    def open_receipt(self, source):
        # The receiving agent owns the form. Keep its in-progress draft/recovery context intact.
        self.notebook.select(self.receipt_view)
        if not self.receipt_view.busy and not self.receipt_view.presenter.uncertain:
            self.receipt_view.variables["status"].set(
                f"Từ PO {source['number']}: chọn kho, tải danh sách rồi tạo phiếu nhận và chọn PO nguồn này")

    def open_document(self, doc):
        view = self.receipt_view if doc["kind"] == "RECEIPT" else self.order_view
        self.notebook.select(view)
        if view.busy or view.presenter.uncertain:
            return
        if doc["kind"] != "RECEIPT":
            view.variables["kind"].set(doc["kind"])
        for index, warehouse in enumerate(view.warehouses):
            if str(warehouse.id) == doc["warehouse_id"]:
                view.selector.current(index)
                view.presenter.read(view.path, doc["id"])
                view.document_pages.show_detail()
                break

    def open_imported_document(self, doc):
        view = self.opening_view if doc["kind"] == "OPENING" else self.order_view
        if view.busy or view.presenter.uncertain:
            self.import_view.import_error("Màn chứng từ đang xử lý/chờ tra kết quả; hoàn tất trước khi mở phiếu import")
            return
        if (view.doc or view.lines) and not messagebox.askyesno(
                "Mở chứng từ import", "Thay nội dung đang xem/nhập bằng chứng từ đã import?", parent=self.root):
            return
        index = next((i for i, w in enumerate(view.warehouses) if str(w.id) == doc["warehouse_id"]), None)
        if index is None:
            self.import_view.import_error("Kho không còn trong phiên hiện tại; Tải lại quyền trước khi mở phiếu")
            return
        view.selector.current(index)
        if doc["kind"] != "OPENING":
            view.variables["kind"].set(doc["kind"])
        view.scope_changed()
        self.notebook.select(view)
        view.document_pages.show_detail()
        if doc["kind"] == "OPENING":
            view.presenter.read(doc["id"])
        else:
            view.presenter.read(view.path, doc["id"])

    def show_result(self, health: Health) -> None:
        self.status.set("Máy chủ và cơ sở dữ liệu đã sẵn sàng" if health.status == "ready" else "Đã kết nối máy chủ")

    def show_error(self, message: str) -> None:
        self.status.set(message)

    def poll(self) -> None:
        if not self.closed and not self.closing:
            self.presenter.drain()
            self.session_view.presenter.drain()
            self.master_view.presenter.drain()
            self.product_details_view.presenter.drain()
            self.ownership_view.drain()
            self.serial_view.presenter.drain()
            self.order_view.presenter.drain()
            self.approval_view.presenter.drain()
            self.receipt_view.presenter.drain()
            self.issue_view.presenter.drain()
            self.fulfillment_view.presenter.drain()
            self.opening_view.presenter.drain()
            self.consignment_view.presenter.drain()
            self.import_view.presenter.drain()
            self.admin_view.presenter.drain()
            self.quality_view.presenter.drain()
            self.move_view.presenter.drain()
            for view in self.return_views:
                view.presenter.drain()
            self.transfer_view.presenter.drain()
            self.count_view.presenter.drain()
            self.period_view.presenter.drain()
            self.reversal_view.presenter.drain()
            self.print_view.presenter.drain()
            self.report_view.presenter.drain()
            self.custom_fields_view.presenter.drain()
            self.recovery_view.drain()
            self.workspace_loading.drain()
            self.poll_id = self.root.after(50, self.poll)

    def request_reload(self):
        self.request_close(restart=True)

    def request_close(self, *, restart=False):
        if self.closed or self.closing:
            return
        self.closing = True
        title = "Tải lại" if restart else "Thoát ứng dụng"
        question = ("Ứng dụng sẽ khởi động lại để nhận giao diện mới."
                    if restart else "Bạn muốn thoát ứng dụng?")
        if not messagebox.askokcancel(title, question + "\n\nPhần đang nhập chưa lưu sẽ mất. "
                                      "Hãy chọn Hủy để quay lại lưu trước.\n"
                                      "Các tác vụ đang chạy sẽ được chờ kết thúc.",
                                      parent=self.root, default=messagebox.CANCEL):
            self.closing = False
            # The regular poll may have fired during the modal confirmation.
            self.root.after_cancel(self.poll_id)
            self.poll_id = self.root.after(50, self.poll)
            return
        self.restart_requested = restart
        dialog = self.exit_dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Đang tải lại giao diện…" if restart else "Đang đóng ứng dụng…",
                  font=("Arial", 12, "bold")).pack(anchor="w")
        ttk.Label(body, text="Đang chờ tác vụ hoàn tất. Vui lòng giữ ứng dụng mở.").pack(pady=(12, 16))
        self.exit_progress = ttk.Progressbar(body, mode="indeterminate", length=400)
        self.exit_progress.pack(fill="x")
        self.exit_progress.start(15)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.focus_set()
        self.stop_workers()
        self.shutdown_done = await_workers(self.worker_executors)
        self.root.after(100, self.wait_for_close)

    def worker_owners(self):
        views = [self.session_view, self.master_view, self.product_details_view,
                 self.ownership_view.catalog, self.ownership_view.stock, self.serial_view,
                 self.order_view, self.approval_view, self.receipt_view, self.opening_view,
                 self.consignment_view, self.import_view, self.issue_view, self.admin_view,
                 self.quality_view, self.move_view, self.transfer_view, self.fulfillment_view,
                 self.count_view, self.period_view, self.reversal_view, self.print_view,
                 self.report_view, self.custom_fields_view, *self.return_views]
        scanners = [view.scan_bar for view in (self.receipt_view, self.issue_view,
                    self.transfer_view, self.fulfillment_view, self.count_view)]
        profiles = [view.profile for view in (self.master_view, self.ownership_view.catalog)
                    if view.profile is not None]
        return [self.presenter, *(view.presenter for view in views), self.recovery_view, *scanners, *profiles]

    def stop_workers(self):
        if self.workers_stopped:
            return
        self.workers_stopped = True
        self.root.after_cancel(self.poll_id)
        self.workspace_loading.clear()
        owners = self.worker_owners()
        self.worker_executors = tuple(owner.executor for owner in owners)
        for owner in owners:
            owner.close()

    def wait_for_close(self):
        if self.closed:
            return
        if not self.shutdown_done.is_set():
            self.root.after(100, self.wait_for_close)
            return
        self.exit_progress.stop()
        self.close()

    def close(self) -> None:
        """Final Tk teardown; user actions enter through request_close()."""
        if self.closed:
            return
        self.closed = True
        self.stop_workers()
        self.master_view.release_variables()
        self.product_details_view.release_variables()
        self.ownership_view.catalog.release_variables()
        self.ownership_view.stock.release_variables()
        self.serial_view.release_variables()
        self.order_view.release_variables()
        self.approval_view.release_variables()
        self.receipt_view.release_variables()
        self.opening_view.release_variables()
        self.consignment_view.release_variables()
        self.import_view.release_variables()
        self.receipt_recovery_view.release_variables()
        self.recovery_view.release_variables()
        self.draft_only = None
        self.issue_view.release_variables()
        self.admin_view.release_variables()
        for view in [self.quality_view, self.move_view, self.transfer_view, self.fulfillment_view, self.count_view, self.period_view, self.reversal_view, self.print_view, self.report_view, self.custom_fields_view, *self.return_views]:
            view.release_variables()
        self.session_view.release_variables()
        self.status = None
        self.application_icon = None
        self.header_icon = None
        self.compact_header_icon = None
        self.light_header_icon = None
        self.admin_theme.close()
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            self.destroyed_widgets.append(widget)
        self.root.destroy()

    def finish(self):
        for executor in getattr(self, "worker_executors", ()):
            executor.shutdown(wait=True)
        self.worker_executors = ()
        for view in [self.receipt_view, self.issue_view, self.transfer_view, self.fulfillment_view, self.count_view]:
            view.scan_bar.executor.shutdown(wait=True, cancel_futures=True)
            view.scan_bar.view = None
        self.presenter.finish()
        self.master_view.presenter.finish()
        self.product_details_view.presenter.finish()
        self.ownership_view.finish()
        self.serial_view.presenter.finish()
        self.order_view.presenter.finish()
        self.approval_view.presenter.finish()
        self.receipt_view.presenter.finish()
        self.issue_view.presenter.finish()
        self.fulfillment_view.presenter.finish()
        self.opening_view.presenter.finish()
        self.consignment_view.presenter.finish()
        self.import_view.presenter.finish()
        self.admin_view.presenter.finish()
        self.quality_view.presenter.finish()
        self.move_view.presenter.finish()
        for view in self.return_views:
            view.presenter.finish()
        self.transfer_view.presenter.finish()
        self.count_view.presenter.finish()
        self.period_view.presenter.finish()
        self.print_view.presenter.finish()
        self.report_view.presenter.finish()
        self.reversal_view.presenter.finish()
        self.custom_fields_view.presenter.finish()
        self.recovery_view.finish()
        self.session_view.presenter.finish()
        self.session_view.on_session_change = None
        # Destroy removes Tcl commands but Python widget cycles may outlive this
        # window (queued callbacks, callers, test fixtures). Drop their native
        # interpreter references here, on the Tk thread, before a HTTP worker's
        # cyclic GC can become the last owner of the destroyed Tcl interpreter.
        for widget in self.destroyed_widgets:
            widget.tk = None
        self.destroyed_widgets.clear()
