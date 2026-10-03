import tkinter as tk
from tkinter import ttk

from apps.desktop.api.client import ApiClient, DesktopSettings
from apps.desktop.presenters.connection import ConnectionPresenter
from apps.desktop.views.admin import AdminView
from apps.desktop.views.issues import IssueView
from apps.desktop.views.master_data import MasterDataView
from apps.desktop.views.master_details import ProductDetailsView
from apps.desktop.views.moves import MoveView
from apps.desktop.views.openings import OpeningView
from apps.desktop.views.orders import OrderView
from apps.desktop.views.ownership import OwnershipView
from apps.desktop.views.quality import QualityView
from apps.desktop.views.receipt_recovery import ReceiptRecoveryView
from apps.desktop.views.receipts import ReceiptView
from apps.desktop.views.serial_lookup import SerialLookupView
from apps.desktop.views.session import SessionView
from apps.desktop.views.transfers import TransferView
from packages.contracts import Health


class DesktopShell:
    def __init__(self, root: tk.Tk, settings: DesktopSettings):
        self.root = root
        self.settings = settings
        self.root.title("WMS — Quản lý kho")
        self.root.geometry("900x690")
        self.root.minsize(800, 620)
        self.closed = False
        self.status = tk.StringVar(value="Chưa kiểm tra kết nối.")
        self.presenter = ConnectionPresenter(self, ApiClient(settings))

        navigation = ttk.Frame(root, padding=(12, 8, 12, 0))
        navigation.pack(fill="x")
        ttk.Label(navigation, text="Chức năng").pack(side="left", padx=(0, 8))
        self.navigation = ttk.Combobox(navigation, state="readonly", width=34)
        self.navigation.pack(side="left")
        # A single selector keeps every section reachable at 900×690 even when
        # the combined notebook tab labels exceed the window width.
        style = ttk.Style(root)
        style.layout("WMS.TNotebook.Tab", [])
        notebook = self.notebook = ttk.Notebook(root, style="WMS.TNotebook")
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self.session_view = SessionView(notebook, settings)
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
        self.receipt_view = ReceiptView(notebook, self.session_view.presenter.api)
        notebook.add(self.receipt_view, text="Nhận hàng")
        self.opening_view = OpeningView(notebook, self.session_view.presenter.api)
        notebook.add(self.opening_view, text="Tồn đầu kỳ")
        self.consignment_view = OpeningView(notebook, self.session_view.presenter.api, consignment=True)
        notebook.add(self.consignment_view, text="Nhận ký gửi")
        self.receipt_recovery_view = ReceiptRecoveryView(notebook, self.receipt_view.presenter)
        notebook.add(self.receipt_recovery_view, text="Phục hồi nhận hàng")
        self.issue_view = IssueView(notebook, self.session_view.presenter.api)
        notebook.add(self.issue_view, text="Giữ hàng / xuất kho")
        self.admin_view = AdminView(notebook, self.session_view.presenter.api)
        self.admin_view.on_signed_out = self.admin_signed_out
        notebook.add(self.admin_view, text="Quản trị tài khoản / quyền")
        self.quality_view = QualityView(notebook, self.session_view.presenter.api)
        self.move_view = MoveView(notebook, self.session_view.presenter.api)
        for view, title in [(self.quality_view, "Kiểm định chất lượng"), (self.move_view, "Cất hàng / di chuyển")]:
            view.on_signed_out = self.admin_signed_out
            notebook.add(view, text=title)
        self.transfer_view = TransferView(notebook, self.session_view.presenter.api)
        self.transfer_view.on_signed_out = self.admin_signed_out
        notebook.add(self.transfer_view, text="Chuyển kho / transit")
        container = ttk.Frame(notebook, padding=24)
        notebook.add(container, text="Kết nối")
        ttk.Label(container, text="WMS · Quản lý kho", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(container, text="Kết nối máy chủ", font=("Segoe UI", 14)).pack(anchor="w", pady=(24, 8))
        ttk.Label(container, text=settings.api_url, wraplength=720).pack(anchor="w")
        ttk.Label(container, textvariable=self.status, wraplength=720).pack(anchor="w", pady=16)
        actions = ttk.Frame(container)
        actions.pack(anchor="w")
        ttk.Button(actions, text="Kiểm tra kết nối", command=self.presenter.check).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Kiểm tra sẵn sàng", command=lambda: self.presenter.check(readiness=True)).pack(side="left")
        ttk.Separator(container).pack(fill="x", pady=24)
        ttk.Label(container, text="Đã có đăng nhập, MFA và quyền theo kho.\nCác nghiệp vụ nhập/xuất kho đang được phát triển.",
                  wraplength=720).pack(anchor="w")
        self.navigation.configure(values=[notebook.tab(tab, "text") for tab in notebook.tabs()])
        self.navigation.current(0)
        self.navigation.bind("<<ComboboxSelected>>", lambda event: notebook.select(self.navigation.current()))
        notebook.bind("<<NotebookTabChanged>>", lambda event: self.navigation.current(notebook.index("current")))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(50, self.poll)

    def show_loading(self) -> None:
        self.status.set("Đang kiểm tra… Bạn vẫn có thể thao tác hoặc đóng cửa sổ.")

    def session_changed(self, user=None, warehouses=None):
        self.master_view.session_changed(user)
        self.product_details_view.session_changed(user, warehouses)
        self.ownership_view.session_changed(user, warehouses)
        self.serial_view.session_changed(user, warehouses)
        self.order_view.session_changed(user, warehouses)
        self.receipt_view.session_changed(user, warehouses)
        self.issue_view.session_changed(user, warehouses)
        self.opening_view.session_changed(user, warehouses)
        self.consignment_view.session_changed(user, warehouses)
        self.admin_view.session_changed(user, warehouses)
        self.quality_view.session_changed(user, warehouses)
        self.move_view.session_changed(user, warehouses)
        self.transfer_view.session_changed(user, warehouses)

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

    def show_result(self, health: Health) -> None:
        self.status.set("Máy chủ và cơ sở dữ liệu đã sẵn sàng." if health.status == "ready" else "Đã kết nối máy chủ.")

    def show_error(self, message: str) -> None:
        self.status.set(message)

    def poll(self) -> None:
        if not self.closed:
            self.presenter.drain()
            self.session_view.presenter.drain()
            self.master_view.presenter.drain()
            self.product_details_view.presenter.drain()
            self.ownership_view.drain()
            self.serial_view.presenter.drain()
            self.order_view.presenter.drain()
            self.receipt_view.presenter.drain()
            self.issue_view.presenter.drain()
            self.opening_view.presenter.drain()
            self.consignment_view.presenter.drain()
            self.admin_view.presenter.drain()
            self.quality_view.presenter.drain()
            self.move_view.presenter.drain()
            self.transfer_view.presenter.drain()
            self.poll_id = self.root.after(50, self.poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.presenter.close()
        self.session_view.presenter.close()
        self.master_view.presenter.close()
        self.master_view.release_variables()
        self.product_details_view.presenter.close()
        self.product_details_view.release_variables()
        self.ownership_view.close()
        self.serial_view.presenter.close()
        self.serial_view.release_variables()
        self.order_view.presenter.close()
        self.order_view.release_variables()
        self.receipt_view.presenter.close()
        self.receipt_view.release_variables()
        self.opening_view.presenter.close()
        self.consignment_view.presenter.close()
        self.opening_view.release_variables()
        self.consignment_view.release_variables()
        self.receipt_recovery_view.release_variables()
        self.issue_view.presenter.close()
        self.issue_view.release_variables()
        self.admin_view.presenter.close()
        self.admin_view.release_variables()
        for view in [self.quality_view, self.move_view, self.transfer_view]:
            view.presenter.close()
            view.release_variables()
        self.session_view.release_variables()
        self.status = None
        self.root.destroy()

    def finish(self):
        self.presenter.finish()
        self.master_view.presenter.finish()
        self.product_details_view.presenter.finish()
        self.ownership_view.finish()
        self.serial_view.presenter.finish()
        self.order_view.presenter.finish()
        self.receipt_view.presenter.finish()
        self.issue_view.presenter.finish()
        self.opening_view.presenter.finish()
        self.consignment_view.presenter.finish()
        self.admin_view.presenter.finish()
        self.quality_view.presenter.finish()
        self.move_view.presenter.finish()
        self.transfer_view.presenter.finish()
        self.session_view.presenter.finish()
        self.session_view.on_session_change = None
