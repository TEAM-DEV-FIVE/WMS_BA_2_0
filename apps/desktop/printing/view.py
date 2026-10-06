import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from apps.desktop.printing.presenter import PrintPresenter

TEMPLATES = {
    "Phiếu nhập kho": "RECEIPT",
    "Phiếu xuất kho": "ISSUE",
    "Phiếu chuyển kho": "TRANSFER",
    "Phiếu kiểm kê (đếm mù)": "COUNT",
    "Tem hàng / serial": "PRODUCT_LABEL",
    "Tem vị trí": "LOCATION_LABEL",
}


class PrintView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=8)
        self.presenter = PrintPresenter(self, api)
        self.user = None
        self.warehouses = []
        self.sources = []
        self.devices = []
        self.image = None
        self.page = 0
        self.variables = {
            name: tk.StringVar(value=value)
            for name, value in [
                ("search", ""),
                ("serial", ""),
                ("reason", "In phục vụ nghiệp vụ"),
                ("copies", "1"),
                ("status", "Đăng nhập để in."),
            ]
        }
        self.price = tk.BooleanVar(value=False)
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.warehouse = ttk.Combobox(top, state="readonly", width=22)
        self.warehouse.pack(side="left")
        self.warehouse.bind("<<ComboboxSelected>>", lambda e: self.scope_changed())
        self.template = ttk.Combobox(top, state="readonly", values=list(TEMPLATES), width=25)
        self.template.current(0)
        self.template.pack(side="left", padx=5)
        self.template.bind("<<ComboboxSelected>>", lambda e: self.template_changed())
        self.paper = ttk.Combobox(top, state="readonly", values=["A4", "A5"], width=10)
        self.paper.current(0)
        self.paper.pack(side="left")
        find = ttk.Frame(self)
        find.pack(fill="x", pady=5)
        ttk.Label(find, text="Số phiếu / SKU / vị trí").pack(side="left")
        ttk.Entry(find, textvariable=self.variables["search"], width=20).pack(side="left", padx=4)
        ttk.Button(find, text="Tìm", command=self.search).pack(side="left")
        self.source = ttk.Combobox(find, state="readonly", width=40)
        self.source.pack(side="left", fill="x", expand=True, padx=4)
        options = ttk.Frame(self)
        options.pack(fill="x")
        ttk.Label(options, text="Serial (tem hàng, tùy chọn)").pack(side="left")
        ttk.Entry(options, textvariable=self.variables["serial"], width=22).pack(side="left", padx=4)
        ttk.Checkbutton(options, text="Có giá tham chiếu (cần quyền)", variable=self.price).pack(side="left")
        ttk.Button(options, text="Tạo bản PDF", command=self.create).pack(side="right")
        printer = ttk.Frame(self)
        printer.pack(fill="x", pady=5)
        ttk.Button(printer, text="Tìm máy in", command=self.presenter.devices).pack(side="left")
        self.device = ttk.Combobox(printer, state="readonly", width=38)
        self.device.pack(side="left", padx=4, fill="x", expand=True)
        ttk.Label(printer, text="Số bản").pack(side="left")
        ttk.Spinbox(printer, from_=1, to=20, textvariable=self.variables["copies"], width=4).pack(side="left")
        ttk.Button(printer, text="Gửi máy in", command=self.spool).pack(side="left", padx=5)
        reason = ttk.Frame(self)
        reason.pack(fill="x")
        ttk.Label(reason, text="Lý do in / in lại").pack(side="left")
        ttk.Entry(reason, textvariable=self.variables["reason"]).pack(
            side="left", fill="x", expand=True, padx=4
        )
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=4)
        for n, (label, command) in enumerate(
            [
                ("Trạng thái", self.presenter.refresh),
                ("Xem trước", lambda: self.preview(0)),
                ("Trang trước", lambda: self.preview(-1)),
                ("Trang sau", lambda: self.preview(1)),
                ("Lưu PDF", self.save),
                ("Chạy lại render lỗi", lambda: self.action("retry")),
                ("In lại", lambda: self.action("reprint")),
                ("Hủy", lambda: self.action("cancel")),
                ("Tra cùng key", self.presenter.recover),
            ]
        ):
            ttk.Button(buttons, text=label, command=command).grid(
                row=n // 5, column=n % 5, sticky="ew", padx=1, pady=1
            )
        for n in range(5):
            buttons.columnconfigure(n, weight=1)
        area = ttk.Frame(self)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, background="#d5dbe1", highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.variables["status"], wraplength=820).pack(fill="x", pady=4)

    def session_changed(self, user=None, warehouses=None):
        self.user = user
        self.warehouses = warehouses or []
        self.warehouse.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])
        self.warehouse.current(0) if self.warehouses else self.warehouse.set("")
        self.scope_changed()

    def scope_changed(self):
        index = self.warehouse.current()
        wh = self.warehouses[index].id if 0 <= index < len(self.warehouses) else None
        self.presenter.reset(self.user.id if self.user else None, wh)

    def template_changed(self):
        self.scope_changed()
        label = TEMPLATES[self.template.get()].endswith("LABEL")
        self.paper.configure(values=["100x50", "80x40"] if label else ["A4", "A5"])
        self.paper.current(0)
        self.price.set(False)

    def search(self):
        self.presenter.search(TEMPLATES[self.template.get()], self.variables["search"].get().strip())

    def create(self):
        index = self.source.current()
        if 0 <= index < len(self.sources):
            self.presenter.create(
                TEMPLATES[self.template.get()],
                self.sources[index],
                self.paper.get(),
                self.price.get(),
                self.variables["serial"].get().strip(),
            )

    def action(self, operation):
        if operation == "reprint" and not messagebox.askyesno(
            "In lại",
            "Lượt trước có thể đã ra giấy. Bạn đã kiểm tra và vẫn muốn tạo lượt in mới?",
            parent=self,
        ):
            return
        self.presenter.action(operation, self.variables["reason"].get().strip())

    def spool(self):
        index = self.device.current()
        try:
            if 0 <= index < len(self.devices):
                d = self.devices[index]
                self.presenter.spool(
                    d["name"],
                    d["driver"],
                    int(self.variables["copies"].get()),
                    self.variables["reason"].get().strip(),
                )
        except ValueError:
            self.print_error("Số bản phải là số nguyên từ 1 đến 20.")

    def preview(self, delta):
        self.page = max(0, self.page + delta) if delta else 0
        self.presenter.preview(self.page)

    def save(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf", initialfile="WMS.pdf", filetypes=[("PDF", "*.pdf")]
        )
        if path:
            self.presenter.download(path)

    def print_clear(self):
        self.sources = []
        self.source.set("")
        self.source.configure(values=[])
        self.clear_preview()
        self.variables["status"].set(
            "Chọn mẫu và dữ liệu. PDF có hiệu lực một giờ; máy in phải có driver đã cài."
        )

    def clear_preview(self):
        self.canvas.delete("all")
        self.image = None
        self.page = 0

    def print_busy(self):
        self.variables["status"].set("Đang xử lý…")

    def print_error(self, message):
        self.variables["status"].set(message + " · Nếu chưa rõ kết quả, Tra cùng key; không tự in lại.")

    def print_sources(self, items):
        self.sources = items
        self.source.configure(values=[f"{s['number']} · v{s['version']}" for s in items])
        if items:
            self.source.current(0)
        self.variables["status"].set(f"{len(items)} kết quả (tối đa 50); nhập mã để thu hẹp.")

    def print_devices(self, items):
        self.devices = items
        self.device.configure(values=[f"{d['name']} · {d['driver']}" for d in items])
        if items:
            self.device.current(0)
        self.variables["status"].set(f"Tìm thấy {len(items)} máy in.")

    def print_job(self, job):
        attempt = job["attempt"]
        state = attempt["status"] if attempt else job["status"]
        self.variables["status"].set(
            f"{state} · lượt {job['generation']} · {job['error_code'] or ''}. SUBMITTED: spooler đã nhận; chưa xác nhận giấy đã in."
        )

    def print_preview(self, result):
        from PIL import ImageTk

        image, total = result
        image.thumbnail((max(300, self.canvas.winfo_width() - 20), 1400))
        self.image = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(10, 10, image=self.image, anchor="nw")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.variables["status"].set(f"Xem trước trang {self.page + 1}/{total}.")

    def print_saved(self, path):
        self.variables["status"].set("Đã lưu PDF: " + path)

    def release_variables(self):
        self.image = None
        self.variables.clear()
        self.price = None
