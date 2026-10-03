import tkinter as tk
from tkinter import ttk

from apps.desktop.api.client import ApiClient, DesktopSettings
from apps.desktop.presenters.connection import ConnectionPresenter
from apps.desktop.views.master_data import MasterDataView
from apps.desktop.views.orders import OrderView
from apps.desktop.views.receipt_recovery import ReceiptRecoveryView
from apps.desktop.views.receipts import ReceiptView
from apps.desktop.views.serial_lookup import SerialLookupView
from apps.desktop.views.session import SessionView
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

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self.session_view = SessionView(notebook, settings)
        notebook.add(self.session_view, text="Đăng nhập và kho")
        self.master_view = MasterDataView(notebook, self.session_view.presenter.api)
        notebook.add(self.master_view, text="Danh mục")
        self.serial_view = SerialLookupView(notebook, self.session_view.presenter.api)
        self.session_view.on_session_change = self.session_changed
        notebook.add(self.serial_view, text="Tra serial / bảo hành")
        self.order_view = OrderView(notebook, self.session_view.presenter.api)
        notebook.add(self.order_view, text="PO/SO và duyệt")
        self.receipt_view = ReceiptView(notebook, self.session_view.presenter.api)
        notebook.add(self.receipt_view, text="Nhận hàng")
        self.receipt_recovery_view = ReceiptRecoveryView(notebook, self.receipt_view.presenter)
        notebook.add(self.receipt_recovery_view, text="Phục hồi nhận hàng")
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
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(50, self.poll)

    def show_loading(self) -> None:
        self.status.set("Đang kiểm tra… Bạn vẫn có thể thao tác hoặc đóng cửa sổ.")

    def session_changed(self, user=None, warehouses=None):
        self.master_view.session_changed(user)
        self.serial_view.session_changed(user, warehouses)
        self.order_view.session_changed(user, warehouses)
        self.receipt_view.session_changed(user, warehouses)

    def show_result(self, health: Health) -> None:
        self.status.set("Máy chủ và cơ sở dữ liệu đã sẵn sàng." if health.status == "ready" else "Đã kết nối máy chủ.")

    def show_error(self, message: str) -> None:
        self.status.set(message)

    def poll(self) -> None:
        if not self.closed:
            self.presenter.drain()
            self.session_view.presenter.drain()
            self.master_view.presenter.drain()
            self.serial_view.presenter.drain()
            self.order_view.presenter.drain()
            self.receipt_view.presenter.drain()
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
        self.serial_view.presenter.close()
        self.serial_view.release_variables()
        self.order_view.presenter.close()
        self.order_view.release_variables()
        self.receipt_view.presenter.close()
        self.receipt_view.release_variables()
        self.receipt_recovery_view.release_variables()
        self.session_view.release_variables()
        self.status = None
        self.root.destroy()

    def finish(self):
        self.presenter.finish()
        self.master_view.presenter.finish()
        self.serial_view.presenter.finish()
        self.order_view.presenter.finish()
        self.receipt_view.presenter.finish()
        self.session_view.presenter.finish()
        self.session_view.on_session_change = None
