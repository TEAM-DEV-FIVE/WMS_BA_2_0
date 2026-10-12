import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from apps.desktop.printing.presenter import PrintPresenter
from apps.desktop.views.action_menu import ActionMenu
from apps.desktop.views.document_review import ScrollPanel
from apps.desktop.views.ui_help import HelpButton, StatusButton

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
                ("status", "Đăng nhập để in"),
            ]
        }
        self.price = tk.BooleanVar(value=False)
        self.workspace = ttk.Frame(self)
        self.form = ScrollPanel(self.workspace)
        self.form.canvas.configure(width=420, height=300)
        body = self.form.inner
        self.document_fields = ttk.LabelFrame(body, text="Chứng từ", padding=16)
        self.printer_fields = ttk.LabelFrame(body, text="Máy in", padding=16)
        self.layout_mode = None

        def field(parent, label, widget):
            ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 4))
            widget.pack(anchor="w", pady=(0, 5))
            return widget

        document = self.document_fields
        self.warehouse = field(document, "Kho", ttk.Combobox(document, state="readonly", width=40))
        self.warehouse.bind("<<ComboboxSelected>>", lambda e: self.scope_changed())
        self.template = field(document, "Mẫu in", ttk.Combobox(document, state="readonly", values=list(TEMPLATES), width=40))
        self.template.current(0)
        self.template.bind("<<ComboboxSelected>>", lambda e: self.template_changed())
        self.paper = field(document, "Khổ giấy", ttk.Combobox(document, state="readonly", values=["A4", "A5"], width=14))
        self.paper.current(0)
        ttk.Label(document, text="Số phiếu / mã hàng / vị trí").pack(anchor="w", pady=(8, 4))
        find = ttk.Frame(document)
        find.pack(anchor="w", pady=(0, 5))
        self.search_entry = ttk.Entry(find, textvariable=self.variables["search"], width=24)
        self.search_entry.pack(side="left")
        ttk.Button(find, text="Tìm", command=self.search, style="Primary.TButton").pack(side="left", padx=(8, 0))
        self.source = field(document, "Chứng từ hoặc mặt hàng", ttk.Combobox(document, state="readonly", width=40))
        field(document, "Serial (nếu có)", ttk.Entry(document, textvariable=self.variables["serial"], width=42))
        ttk.Checkbutton(document, text="Có giá tham chiếu", variable=self.price).pack(anchor="w", pady=8)
        printer = self.printer_fields
        self.device = field(printer, "Máy in", ttk.Combobox(printer, state="readonly", width=40))
        ttk.Button(printer, text="Tìm máy in", command=self.presenter.devices).pack(anchor="w", pady=4)
        field(printer, "Số bản", ttk.Spinbox(printer, from_=1, to=20, textvariable=self.variables["copies"], width=8))
        self.reason_entry = field(printer, "Lý do in / in lại", ttk.Entry(printer, textvariable=self.variables["reason"], width=42))
        self.form.canvas.bind("<Configure>", self.arrange_fields, add=True)
        self.arrange_fields()
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        self.actions = ActionMenu(toolbar, [
            ("In / xem trước", lambda: self.preview(0)),
            ("Gửi máy in", self.spool),
            ("Lưu PDF", self.save),
            ("Cập nhật trạng thái", self.presenter.refresh),
            ("In lại", lambda: self.action("reprint")),
            ("Chạy lại khi lỗi", lambda: self.action("retry")),
            ("Hủy", lambda: self.action("cancel")),
            ("Kiểm tra yêu cầu", self.presenter.recover),
        ], title="Thao tác in")
        self.actions.pack(side="right")
        footer_actions = ttk.Frame(self)
        footer_actions.pack(side="bottom", fill="x", pady=(8, 0))
        self.create_button = ttk.Button(footer_actions, text="Tạo bản PDF", command=self.create, style="Primary.TButton")
        self.create_button.pack(side="right")
        HelpButton(footer_actions, "Chọn mẫu và dữ liệu, sau đó tạo PDF. PDF có hiệu lực một giờ. Máy in cần được cài driver. Khi chưa rõ kết quả, kiểm tra yêu cầu trước khi in lại.").pack(side="left")
        self.preview_window = tk.Toplevel(self)
        self.preview_window.withdraw()
        self.preview_window.title("In / xem trước")
        self.preview_window.transient(self.winfo_toplevel())
        self.preview_window.geometry("900x700")
        self.preview_window.protocol("WM_DELETE_WINDOW", self.preview_window.withdraw)
        self.preview_window.bind("<Escape>", lambda event: self.preview_window.withdraw())
        self.preview_area = ttk.Frame(self.preview_window, padding=12)
        self.preview_area.pack(fill="both", expand=True)
        head = ttk.Frame(self.preview_area)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Bản xem trước", style="Card.Title.TLabel").pack(side="left")
        ttk.Button(head, text="Gửi máy in", command=self.spool, style="Primary.TButton").pack(side="right")
        self.preview_position = tk.StringVar(value="Chưa có bản xem trước")
        footer = ttk.Frame(self.preview_area)
        footer.pack(side="bottom", fill="x", pady=6)
        navigation = ttk.Frame(footer)
        navigation.pack(anchor="center")
        ttk.Button(navigation, text="‹ Trước", command=lambda: self.preview(-1)).pack(side="left")
        ttk.Label(navigation, textvariable=self.preview_position, width=26, anchor="center").pack(side="left", padx=6)
        ttk.Button(navigation, text="Sau ›", command=lambda: self.preview(1)).pack(side="left")
        area = ttk.Frame(self.preview_area)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, background="#d5dbe1", highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        StatusButton(footer_actions, self.variables["status"]).pack(side="right", padx=8)
        self.workspace.pack(fill="both", expand=True)
        self.form.pack(fill="both", expand=True)
        self.form.bind_scrolling()

    def arrange_fields(self, event=None):
        body = self.form.inner
        wide = self.form.canvas.winfo_width() >= 1000
        if wide == self.layout_mode:
            return
        self.layout_mode = wide
        self.document_fields.grid_forget()
        self.printer_fields.grid_forget()
        body.columnconfigure(0, weight=1, uniform="print-sections")
        body.columnconfigure(1, weight=1 if wide else 0, uniform="print-sections" if wide else "")
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0 if wide else 1)
        self.document_fields.grid(row=0, column=0, sticky="nsew", padx=(0, 8 if wide else 0))
        self.printer_fields.grid(row=0 if wide else 1, column=1 if wide else 0, sticky="nsew", pady=(0 if wide else 8, 0))

    def session_changed(self, user=None, warehouses=None):
        self.user = user
        self.warehouses = warehouses or []
        self.warehouse.configure(values=[f"{w.code}  {w.name}" for w in self.warehouses])
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
            "Lượt trước có thể đã ra giấy; Bạn đã kiểm tra và vẫn muốn tạo lượt in mới?",
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
            self.print_error("Số bản phải là số nguyên từ 1 đến 20")

    def preview(self, delta):
        if not self.presenter.job or self.presenter.job["status"] != "READY":
            self.variables["status"].set("Chưa có PDF sẵn sàng. Tạo bản PDF và cập nhật trạng thái trước khi in.")
            return
        self.preview_window.deiconify()
        self.preview_window.lift()
        self.preview_window.update_idletasks()
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
            "Chọn mẫu và dữ liệu; PDF có hiệu lực một giờ; máy in phải có driver đã cài"
        )

    def clear_preview(self):
        self.preview_window.withdraw()
        self.canvas.delete("all")
        self.image = None
        self.page = 0
        self.preview_position.set("Chưa có bản xem trước")

    def print_busy(self):
        self.variables["status"].set("Đang xử lý…")

    def print_error(self, message):
        self.variables["status"].set(message + "  Nếu chưa rõ kết quả, Tra cùng key; không tự in lại")

    def print_sources(self, items):
        self.sources = items
        self.source.configure(values=[f"{s['number']}  v{s['version']}" for s in items])
        if items:
            self.source.current(0)
        self.variables["status"].set(f"{len(items)} kết quả (tối đa 50); nhập mã để thu hẹp")

    def print_devices(self, items):
        self.devices = items
        self.device.configure(values=[f"{d['name']}  {d['driver']}" for d in items])
        if items:
            self.device.current(0)
        self.variables["status"].set(f"Tìm thấy {len(items)} máy in")

    def print_job(self, job):
        attempt = job["attempt"]
        state = attempt["status"] if attempt else job["status"]
        self.variables["status"].set(
            f"{state}  lượt {job['generation']}  {job['error_code'] or ''}; SUBMITTED: spooler đã nhận; chưa xác nhận giấy đã in"
        )

    def print_preview(self, result):
        from PIL import ImageTk

        image, total = result
        image.thumbnail((max(300, self.canvas.winfo_width() - 20), 1400))
        self.image = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(10, 10, image=self.image, anchor="nw")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.preview_position.set(f"Trang {self.page + 1} / {total}")
        self.variables["status"].set(f"Xem trước trang {self.page + 1}/{total}  ")

    def print_saved(self, path):
        self.variables["status"].set("Đã lưu PDF: " + path)

    def release_variables(self):
        self.image = None
        self.variables.clear()
        self.price = self.preview_position = None
