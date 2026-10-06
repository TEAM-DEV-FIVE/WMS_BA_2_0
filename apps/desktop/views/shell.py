import tkinter as tk
from importlib.resources import as_file, files
from tkinter import messagebox, ttk

from apps.desktop.api.client import ApiClient, DesktopSettings
from apps.desktop.presenters.connection import ConnectionPresenter
from apps.desktop.printing.view import PrintView
from apps.desktop.views.admin import AdminView
from apps.desktop.views.approvals import ApprovalView
from apps.desktop.views.counting import CountView
from apps.desktop.views.custom_fields import CustomFieldView
from apps.desktop.views.fulfillment import FulfillmentView
from apps.desktop.views.imports import ImportView
from apps.desktop.views.issues import IssueView
from apps.desktop.views.master_data import MasterDataView
from apps.desktop.views.master_details import ProductDetailsView
from apps.desktop.views.moves import MoveView
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
from packages.contracts import Health


class DesktopShell:
    def __init__(self, root: tk.Tk, settings: DesktopSettings):
        self.root = root
        self.settings = settings
        self.root.title("WMS — Quản lý kho")
        with as_file(files("apps.desktop.assets").joinpath("wms-logo.png")) as logo:
            self.application_icon = tk.PhotoImage(master=root, file=str(logo))
        self.root.iconphoto(True, self.application_icon)
        self.root.geometry("900x690")
        self.root.minsize(800, 620)
        self.closed = False
        self.destroyed_widgets = []
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
        self.session_view.presenter.api.enable_recovery()
        self.draft_only = tk.BooleanVar(value=False)
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
                f"Từ PO {source['number']}: chọn kho, tải danh sách rồi tạo phiếu nhận và chọn PO nguồn này.")

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
                break

    def open_imported_document(self, doc):
        view = self.opening_view if doc["kind"] == "OPENING" else self.order_view
        if view.busy or view.presenter.uncertain:
            self.import_view.import_error("Màn chứng từ đang xử lý/chờ tra kết quả; hoàn tất trước khi mở phiếu import.")
            return
        if (view.doc or view.lines) and not messagebox.askyesno(
                "Mở chứng từ import", "Thay nội dung đang xem/nhập bằng chứng từ đã import?", parent=self.root):
            return
        index = next((i for i, w in enumerate(view.warehouses) if str(w.id) == doc["warehouse_id"]), None)
        if index is None:
            self.import_view.import_error("Kho không còn trong phiên hiện tại. Tải lại quyền trước khi mở phiếu.")
            return
        view.selector.current(index)
        if doc["kind"] != "OPENING":
            view.variables["kind"].set(doc["kind"])
        view.scope_changed()
        self.notebook.select(view)
        if doc["kind"] == "OPENING":
            view.presenter.read(doc["id"])
        else:
            view.presenter.read(view.path, doc["id"])

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
        self.approval_view.presenter.close()
        self.approval_view.release_variables()
        self.receipt_view.presenter.close()
        self.receipt_view.release_variables()
        self.opening_view.presenter.close()
        self.consignment_view.presenter.close()
        self.opening_view.release_variables()
        self.consignment_view.release_variables()
        self.import_view.presenter.close()
        self.import_view.release_variables()
        self.receipt_recovery_view.release_variables()
        self.recovery_view.close()
        self.recovery_view.release_variables()
        self.draft_only = None
        self.issue_view.presenter.close()
        self.issue_view.release_variables()
        self.admin_view.presenter.close()
        self.admin_view.release_variables()
        for view in [self.quality_view, self.move_view, self.transfer_view, self.fulfillment_view, self.count_view, self.period_view, self.reversal_view, self.print_view, self.report_view, self.custom_fields_view, *self.return_views]:
            view.presenter.close()
            view.release_variables()
        self.session_view.release_variables()
        self.status = None
        self.application_icon = None
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            self.destroyed_widgets.append(widget)
        self.root.destroy()

    def finish(self):
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
