import json
import tkinter as tk
from tkinter import filedialog, ttk

from apps.desktop.presenters.reports import ReportPresenter
from apps.desktop.views.job_history import JobHistoryPanel

LABELS = [
    "R01 · Tồn theo vị trí",
    "R02 · Nhập / xuất qua ranh giới",
    "R03 · Thẻ kho",
    "R04 · Giữ hàng / nhu cầu mở",
    "R05 · Chuyển kho / transit",
    "R06 · Hạn dùng / tồn lâu",
    "R07 · Kiểm kê",
    "R08 · Hoạt động / giá tham chiếu",
]
SORTS = {"Mặc định": "default", "SKU": "sku", "Vị trí": "location_code", "Chủ hàng": "owner_code"}
COLUMNS = {
    "sku": "SKU",
    "product_name": "Tên hàng",
    "base_uom": "ĐVT cơ sở",
    "owner_code": "Chủ hàng",
    "owner_kind": "Loại sở hữu",
    "lot_code": "Lô",
    "serial_code": "Serial",
    "location_code": "Vị trí",
    "location_kind": "Loại vị trí",
    "physical": "Tồn vật lý",
    "transit": "Đang chuyển",
    "eligible": "Đủ điều kiện",
    "reserved": "Đang giữ",
    "available": "Khả dụng",
    "balance_reserved": "Giữ trên số dư",
    "reservation_reconciled": "Khớp giữ chỗ",
    "opening": "Tồn đầu",
    "inbound": "Nhập",
    "outbound": "Xuất",
    "net": "Chênh lệch",
    "closing": "Tồn cuối",
    "posted_at": "Thời điểm ghi sổ",
    "business_date": "Ngày nghiệp vụ",
    "operation": "Nghiệp vụ",
    "posted_by": "Người ghi sổ",
    "source_inside": "Nguồn trong ranh giới",
    "destination_inside": "Đích trong ranh giới",
    "quantity_base": "Số lượng cơ sở",
    "number": "Số phiếu / phiên",
    "kind": "Loại",
    "status": "Trạng thái",
    "requested": "Yêu cầu",
    "closed": "Đã đóng",
    "demand_scope": "Phạm vi nhu cầu",
    "open_demand": "Nhu cầu mở",
    "reservations": "Chi tiết giữ chỗ",
    "dispatched": "Đã gửi",
    "received_good": "Nhận tốt",
    "received_damaged": "Nhận hỏng",
    "loss": "Đã xử lý mất",
    "dispatch_evidence": "Chứng cứ gửi",
    "receipt_evidence": "Chứng cứ nhận",
    "discrepancy_evidence": "Biên bản chênh lệch",
    "reported_missing": "Báo thiếu",
    "on_hand": "Tồn hiện tại",
    "expires_on": "Hết hạn",
    "days_to_expiry": "Ngày còn đến hạn",
    "last_movement_at": "Dịch chuyển gần nhất",
    "movement_age_days": "Ngày từ lần dịch chuyển",
    "age_basis": "Cơ sở tuổi",
    "frozen_at": "Thời điểm chốt",
    "snapshot_quantity": "Số lượng chốt",
    "approved_quantity": "Số duyệt",
    "delta": "Chênh lệch",
    "rounds": "Các vòng đếm",
    "decisions": "Quyết định duyệt",
    "empty_confirmations": "Xác nhận vị trí trống",
    "movement_count": "Số phát sinh",
    "last_posted_at": "Ghi sổ gần nhất",
    "reference_price": "Giá tham chiếu",
    "currency": "Tiền tệ",
    "price_effective_on": "Giá hiệu lực từ",
    "valuation_label": "Loại giá trị",
    "inbound_reference_value": "Giá trị nhập tham chiếu",
    "outbound_reference_value": "Giá trị xuất tham chiếu",
}
VALUES = {
    "WAREHOUSE_ORDER_LINE": "Dòng đơn hàng toàn kho",
    "LAST_MOVEMENT_AT_LOCATION": "Lần dịch chuyển tại vị trí",
    "UNKNOWN": "Chưa xác định",
    "COMPANY": "Doanh nghiệp",
    "CONSIGNOR": "Ký gửi",
    "UNCLASSIFIED": "Chưa phân loại",
}


class ReportView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=10)
        self.presenter = ReportPresenter(self, api)
        self.user = None
        self.warehouses = []
        self.variables = {}
        self.status = tk.StringVar(value="Đăng nhập để xem báo cáo.")
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.selector = ttk.Combobox(top, state="readonly", width=22)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", lambda event: self.scope_changed())
        self.report = ttk.Combobox(top, state="readonly", values=LABELS, width=36)
        self.report.current(0)
        self.report.pack(side="left", padx=8)
        self.report.bind("<<ComboboxSelected>>", lambda event: self.scope_changed())
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=6)
        fields = [
            ("product", "SKU"),
            ("owner", "Mã chủ hàng"),
            ("locations", "Mã vị trí (phân cách dấu phẩy)"),
            ("business_from", "Ngày nghiệp vụ từ"),
            ("business_to", "Đến ngày"),
            ("effective_on", "Ngày giá tham chiếu"),
            ("posted_from", "Ghi sổ từ (ISO + múi giờ)"),
            ("posted_to", "Ghi sổ đến (ISO + múi giờ)"),
        ]
        for n, (key, label) in enumerate(fields):
            row, col = divmod(n, 3)
            box = ttk.Frame(filters)
            box.grid(row=row, column=col, sticky="ew", padx=3, pady=2)
            ttk.Label(box, text=label).pack(anchor="w")
            self.variables[key] = tk.StringVar()
            ttk.Entry(box, textvariable=self.variables[key], width=25).pack(fill="x")
        for col in range(3):
            filters.columnconfigure(col, weight=1)
        options = ttk.Frame(self)
        options.pack(fill="x")
        self.sort = ttk.Combobox(options, state="readonly", values=list(SORTS), width=16)
        self.sort.current(0)
        self.sort.pack(side="left")
        self.desc = tk.BooleanVar(value=False)
        self.price = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Giảm dần", variable=self.desc).pack(side="left")
        ttk.Checkbutton(options, text="Giá quản trị (R08, cần quyền giá)", variable=self.price).pack(
            side="left"
        )
        ttk.Button(options, text="Tạo báo cáo", command=self.create).pack(side="right")
        ttk.Label(
            self,
            text="R01/R06: tồn hiện tại. R03: thứ tự ghi sổ cố định. R05: cần quyền cả hai kho. Ngày: YYYY-MM-DD.",
        ).pack(anchor="w", pady=3)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        grid = ttk.Frame(self.tabs)
        self.tabs.add(grid, text="Dữ liệu báo cáo")
        self.history = JobHistoryPanel(self.tabs,
            lambda filters: self.presenter.history(filters, self.report.get()[:3]), self.presenter.open_history,
            ["QUEUED", "RUNNING", "READY", "FAILED", "CANCELLED"])
        self.tabs.add(self.history, text="Lịch sử export")
        self.tree = ttk.Treeview(grid, show="headings", height=8)
        self.tree.grid(row=0, column=0, sticky="nsew")
        x = ttk.Scrollbar(grid, orient="horizontal", command=self.tree.xview)
        y = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        self.tree.configure(xscrollcommand=x.set, yscrollcommand=y.set)
        x.grid(row=1, column=0, sticky="ew")
        y.grid(row=0, column=1, sticky="ns")
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=5)
        for n, (label, fn) in enumerate(
            [
                ("Trang đầu", lambda: self.presenter.read()),
                ("Trang sau", self.next_page),
                ("Xuất CSV", lambda: self.presenter.export("csv")),
                ("Xuất XLSX", lambda: self.presenter.export("xlsx")),
                ("Trạng thái", self.presenter.refresh),
                ("Tải tệp", self.download),
                ("Hủy", lambda: self.presenter.action("cancel")),
                ("Chạy lại job lỗi", lambda: self.presenter.action("retry")),
                ("Tra / gửi lại cùng key", self.presenter.recover),
            ]
        ):
            ttk.Button(buttons, text=label, command=fn).grid(
                row=n // 5, column=n % 5, sticky="ew", padx=1, pady=1
            )
        ttk.Label(self, textvariable=self.status, wraplength=820).pack(anchor="w")

    def session_changed(self, user=None, warehouses=None):
        self.user = user
        self.warehouses = warehouses or []
        self.selector.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])
        if self.warehouses:
            self.selector.current(0)
        else:
            self.selector.set("")
        self.scope_changed()

    def scope_changed(self):
        index = self.selector.current()
        warehouse = self.warehouses[index].id if 0 <= index < len(self.warehouses) else None
        self.presenter.reset(self.user.id if self.user else None, warehouse)

    def create(self):
        values = {k: v.get().strip() for k, v in self.variables.items()}
        filters = {k: v for k, v in values.items() if v and k not in {"product", "owner", "locations"}}
        filters.update(
            sort_by=SORTS[self.sort.get()], descending=self.desc.get(), include_price=self.price.get()
        )
        self.presenter.create(
            self.report.get()[:3], filters, values["product"], values["owner"], values["locations"]
        )

    def next_page(self):
        if self.presenter.next_after is not None:
            self.presenter.read(self.presenter.next_after)

    def download(self):
        job = self.presenter.job
        if not job or job["status"] != "READY":
            self.status.set("Đọc trạng thái đến khi tệp READY trước khi tải.")
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension="." + job["format"],
            initialfile=job["report_code"] + "." + job["format"],
        )
        if path:
            self.presenter.download(path)

    def report_clear(self):
        self.tree.delete(*self.tree.get_children())
        self.history.clear()
        self.status.set("Chọn báo cáo và bộ lọc; snapshot có hiệu lực một giờ.")

    def report_busy(self):
        self.status.set("Đang xử lý…")

    def report_error(self, message):
        self.status.set(message + " Nếu chưa rõ kết quả, dùng Tra / gửi lại cùng key.")

    def report_page(self, page):
        self.tree.delete(*self.tree.get_children())
        columns = [c for c in page["snapshot"]["columns"] if c in COLUMNS]
        self.tree.configure(columns=columns)
        for c in columns:
            self.tree.heading(c, text=COLUMNS[c])
            self.tree.column(c, width=150, stretch=False)
        for row in page["items"]:
            self.tree.insert(
                "",
                "end",
                values=[
                    json.dumps(row[c], ensure_ascii=False)
                    if isinstance(row.get(c), (dict, list))
                    else VALUES.get(str(row.get(c)), row.get(c, ""))
                    for c in columns
                ],
            )
        self.status.set(
            f"{page['snapshot']['report_code']} · {page['snapshot']['row_count']} dòng · snapshot {page['snapshot']['created_at']} · còn trang: {'có' if page['next_after'] else 'không'}"
        )

    def report_job(self, job):
        self.status.set(
            f"Xuất {job['format'].upper()}: {job['status']} · {job['error_code'] or ''}. Bấm Trạng thái để cập nhật."
        )

    def report_history(self, result):
        self.history.show(result)
        self.status.set("Chọn job trong lịch sử để đọc trạng thái, tải tệp, hủy hoặc retry theo quyền hiện tại.")

    def report_saved(self, path):
        self.status.set("Đã lưu: " + path)

    def release_variables(self):
        self.history.release_variables()
        self.variables.clear()
        self.status = self.desc = self.price = None
