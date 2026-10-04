import json
import tkinter as tk
from datetime import datetime, timezone
from tkinter import filedialog, ttk
from uuid import UUID

from apps.desktop.presenters.imports import ImportPresenter
from apps.desktop.views.document_review import ScrollPanel

LABELS = {
    "01_uom": "01 · Đơn vị tính", "02_categories": "02 · Nhóm hàng", "03_warehouses": "03 · Kho",
    "04_locations": "04 · Vị trí", "05_products": "05 · Sản phẩm", "06_product_uom": "06 · Quy đổi",
    "07_barcodes": "07 · Barcode", "08_partners": "08 · Đối tác", "09_lots": "09 · Lô",
    "10_serials": "10 · Serial", "11_opening": "11 · Tồn đầu kỳ", "12_open_orders": "12 · PO/SO còn mở",
    "14_prices": "14 · Giá tham chiếu",
}
STATUS = {"QUEUED": "Chờ máy chủ xử lý", "VALIDATING": "Đang kiểm tra",
          "VALIDATED": "Kiểm tra hợp lệ · chưa commit", "INVALID": "Có lỗi dữ liệu",
          "FAILED": "Xử lý job thất bại", "CANCELLED": "Đã hủy", "COMMITTED": "Đã commit import"}


class ImportView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=8)
        self.presenter = ImportPresenter(self, api)
        self.variables = {name: tk.StringVar() for name in
                          ["kind", "warehouse", "status", "source", "metadata", "job_id", "reason",
                           "reference", "limits", "progress", "uncertainty"]}
        self.confirm = tk.BooleanVar(value=False)
        self.user = None
        self.warehouses, self.permissions = [], []
        self.capabilities = None
        self.job = None
        self.rows = []
        self.cursors, self.page_index, self.next_after = [0], 0, None
        self.busy = self.trusted = False
        self.on_open_document = None
        self.buttons = {}

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.kind = ttk.Combobox(top, state="readonly", width=25, textvariable=self.variables["kind"],
                                 values=list(LABELS.values()))
        self.kind.pack(side="left")
        self.kind.current(0)
        self.selector = ttk.Combobox(top, state="readonly", width=30, textvariable=self.variables["warehouse"])
        self.selector.pack(side="left", padx=4)
        for combo in (self.kind, self.selector):
            combo.bind("<<ComboboxSelected>>", self.scope_changed)
        self.button(top, "load", "Tải quyền / mẫu", self.load)
        ttk.Label(self, textvariable=self.variables["status"], wraplength=750).pack(fill="x", pady=4)

        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        ttk.Checkbutton(footer, text="Tôi đã kiểm tra dữ liệu, SHA-256 và thời hạn dry-run",
                        variable=self.confirm, command=self.enable).pack(anchor="w")
        bar = ttk.Frame(footer)
        bar.pack(fill="x", pady=3)
        for name, label in [("create", "Tạo job / dry-run"), ("validate", "Kiểm tra lại"),
                            ("commit", "Xác nhận commit"), ("cancel", "Hủy job")]:
            self.button(bar, name, label, lambda a=name: self.action(a))
        recovery = ttk.Frame(footer)
        recovery.pack(fill="x")
        self.button(recovery, "lookup", "Tra yêu cầu chưa rõ", self.presenter.lookup)
        self.button(recovery, "retry", "Gửi lại đúng yêu cầu", self.presenter.retry)
        ttk.Label(footer, textvariable=self.variables["uncertainty"], wraplength=740).pack(fill="x")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)
        self.form = ScrollPanel(tabs)
        tabs.add(self.form, text="Tệp và job")
        body = self.form.inner
        ttk.Label(body, textvariable=self.variables["limits"], wraplength=710).pack(fill="x", pady=4)
        files = ttk.Frame(body)
        files.pack(fill="x")
        self.button(files, "template", "Lưu mẫu CSV", self.save_template)
        self.button(files, "choose", "Chọn tệp…", self.choose)
        self.button(files, "upload", "Upload tệp", self.presenter.upload)
        ttk.Label(body, textvariable=self.variables["source"], wraplength=710).pack(fill="x", pady=4)
        ttk.Label(body, textvariable=self.variables["metadata"], wraplength=710).pack(fill="x", pady=4)
        for name, label in [("reference", "Biên bản đã ký (tồn đầu kỳ)"), ("reason", "Lý do thao tác")]:
            row = ttk.Frame(body)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=28).pack(side="left")
            ttk.Entry(row, textvariable=self.variables[name]).pack(side="left", fill="x", expand=True)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Mã job").pack(side="left")
        entry = ttk.Entry(row, textvariable=self.variables["job_id"], width=40)
        entry.pack(side="left", fill="x", expand=True, padx=4)
        entry.bind("<Return>", lambda event: self.refresh())
        self.button(row, "refresh", "Đọc / tiếp tục", self.refresh)
        ttk.Label(body, textvariable=self.variables["progress"], wraplength=710).pack(fill="x", pady=4)
        self.progress = ttk.Progressbar(body, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=3)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=4)
        self.button(row, "source", "Tải tệp nguồn", lambda: self.download(False))
        self.button(row, "errors", "Tải CSV lỗi", lambda: self.download(True))
        ttk.Label(body, text="Import PO/SO/tồn đầu kỳ tạo NHÁP. Mở chứng từ để gửi duyệt và ghi sổ.\n"
                  "Mất LAN: giữ key và nội dung; tra trước, gửi lại khi bạn chủ động chọn.\n"
                  "Yêu cầu chưa rõ chỉ được giữ trong phiên chạy này; chưa hỗ trợ phục hồi sau khi thoát.",
                  wraplength=710).pack(fill="x", pady=4)

        table_page = ttk.Frame(tabs, padding=4)
        tabs.add(table_page, text="Dòng dữ liệu / lỗi")
        controls = ttk.Frame(table_page)
        controls.pack(fill="x")
        self.button(controls, "previous", "Trang trước", lambda: self.page(-1))
        self.button(controls, "next", "Trang sau", lambda: self.page(1))
        self.button(controls, "open", "Mở chứng từ đã tạo", self.open_target)
        frame = ttk.Frame(table_page)
        frame.pack(fill="both", expand=True, pady=3)
        self.table = ttk.Treeview(frame, columns=("row", "state", "owner", "agreement", "error"),
                                  show="headings", height=7, selectmode="browse")
        for key, label, width in [("row", "Dòng", 55), ("state", "Kết quả", 110),
                                   ("owner", "Chủ hàng", 130), ("agreement", "Hợp đồng", 140),
                                   ("error", "Lỗi / gợi ý", 330)]:
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=50)
        y = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        x = ttk.Scrollbar(frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        x.pack(side="bottom", fill="x")
        y.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.detail = tk.Text(table_page, height=5, wrap="word", state="disabled", takefocus=True)
        self.detail.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", self.show_row)
        self.table.bind("<Return>", lambda event: self.open_target())
        self.form.bind_scrolling()
        self.import_clear()

    def button(self, parent, name, label, command):
        button = ttk.Button(parent, text=label, command=command)
        button.pack(side="left", padx=2)
        self.buttons[name] = button
        return button

    def kind_id(self):
        index = self.kind.current()
        return list(LABELS)[max(0, index)]

    def warehouse_id(self):
        if self.kind_id() not in {"04_locations", "11_opening", "12_open_orders"}:
            return None
        index = self.selector.current()
        return str(self.warehouses[index].id) if index >= 0 else None

    def template(self):
        return next((t for t in (self.capabilities or {}).get("templates", []) if t["kind"] == self.kind_id()), None)

    def session_changed(self, user=None, warehouses=None):
        self.user, self.warehouses = user, warehouses or []
        self.selector.configure(values=[f"{w.code} · {w.name}" for w in self.warehouses])
        self.variables["warehouse"].set("")
        if self.warehouses:
            self.selector.current(0)
        self.scope_changed()

    def scope_changed(self, event=None):
        self.presenter.reset(self.user.id if self.user else None, self.kind_id(), self.warehouse_id())
        if self.user:
            self.load()

    def load(self):
        if self.user and not self.busy:
            self.presenter.load()

    def import_clear_data(self):
        self.job, self.rows = None, []
        self.trusted = False
        self.cursors, self.page_index, self.next_after = [0], 0, None
        for name in ("source", "metadata", "job_id", "progress", "reference", "reason"):
            self.variables[name].set("")
        self.confirm.set(False)
        self.progress["value"] = 0
        self.table.delete(*self.table.get_children())
        self.set_detail("")

    def import_clear(self):
        self.busy = False
        self.permissions, self.capabilities = [], None
        self.import_clear_data()
        self.variables["status"].set("Đăng nhập, chọn loại import và kho (nếu cần).")
        self.variables["limits"].set("Mỗi tệp một mẫu; tối đa 500 dòng, 200 dòng/chứng từ.\n"
                                    "Tồn đầu kỳ: một batch/kho, 200 dòng; kho chưa có lịch sử tồn.")
        self.enable()

    def enable(self):
        free = bool(self.user) and not self.busy
        template = self.template()
        allowed = bool(template and any(p in self.permissions for p in template["permissions"]))
        if template and template["warehouse_required"]:
            allowed = allowed and bool(self.warehouse_id()) and "document.read" in self.permissions
        uncertain = self.presenter.uncertain
        write = free and allowed and not uncertain
        job = self.job or {}
        token_valid = False
        if job.get("token_expires_at"):
            token_valid = datetime.fromisoformat(job["token_expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
        states = {
            "load": free, "choose": write, "template": free and bool(template),
            "upload": write and bool(self.presenter.source) and not self.presenter.file,
            "create": write and bool(self.presenter.file) and not job,
            "refresh": free, "lookup": free and bool(uncertain),
            "retry": free and bool(uncertain) and self.presenter.checked_key == uncertain.key if uncertain else False,
            "commit": write and self.trusted and job.get("status") == "VALIDATED" and token_valid and self.confirm.get(),
            "validate": write and bool(job) and job.get("status") not in {"COMMITTED", "VALIDATING"},
            "cancel": write and bool(job) and job.get("status") not in {"COMMITTED", "CANCELLED"},
            "source": free and bool(job), "errors": free and bool(job),
            "previous": free and self.page_index > 0, "next": free and self.next_after is not None,
            "open": free and job.get("status") == "COMMITTED" and self.kind_id() in {"11_opening", "12_open_orders"},
        }
        for name, button in self.buttons.items():
            button.configure(state="normal" if states.get(name, False) else "disabled")
        self.variables["uncertainty"].set(
            f"UNKNOWN · {uncertain.operation} · key {uncertain.key}" if uncertain else "")

    def import_busy(self):
        self.busy = True
        self.variables["status"].set("Đang xử lý…")
        self.enable()

    def import_loaded(self, capabilities, permissions):
        self.busy = False
        self.capabilities, self.permissions = capabilities, permissions
        self.variables["limits"].set(
            f"Hạn mức upload: {capabilities['max_file_bytes']:,} byte. CSV UTF-8/XLSX; một mẫu/tệp.\n"
            "Tối đa 500 dòng/tệp, 200 dòng/chứng từ. Tồn đầu kỳ: 200 dòng, một batch/kho chưa có lịch sử.\n"
            "Opening v2: owner_code bắt buộc; chủ ký gửi cần consignment_code đúng kho/ngày.\n"
            "PO/SO chỉ COMPANY. Không chia phiếu để vượt giới hạn; máy chủ kiểm tra lại điều kiện khởi tạo tồn.")
        self.variables["status"].set("Đã tải mẫu/quyền hiện hành. Chọn tệp hoặc nhập mã job để tiếp tục.")
        self.enable()

    def choose(self, path=None):
        if self.buttons["choose"].instate(["disabled"]):
            return
        path = path or filedialog.askopenfilename(parent=self, filetypes=[("CSV / XLSX", "*.csv *.xlsx")])
        if path:
            self.presenter.prepare(path, self.capabilities["max_file_bytes"], self.template()["max_rows"])

    def save_template(self):
        if self.buttons["template"].instate(["disabled"]):
            return
        path = filedialog.asksaveasfilename(parent=self, initialfile=self.kind_id() + ".csv", defaultextension=".csv")
        if path:
            self.presenter.template(path, self.template()["columns"])

    def import_source(self, source):
        self.busy = False
        self.variables["source"].set(f"{source.name} · {len(source.data):,} byte · {source.row_count} dòng\nSHA-256: {source.sha256}")
        self.variables["status"].set("Đã kiểm tra kích thước/số dòng; upload rồi chạy dry-run trên máy chủ.")
        self.enable()

    def import_saved(self, result, operation):
        self.busy = False
        self.confirm.set(False)
        if operation == "upload":
            self.variables["metadata"].set(f"File {result['id']} · SHA-256: {result['sha256']}")
            self.variables["status"].set("Upload hoàn tất. Nhập lý do/biên bản rồi tạo job.")
            self.enable()
        else:
            self.variables["job_id"].set(result["id"])
            self.presenter.read(result["id"])

    def refresh(self, after=0):
        if self.busy:
            return
        try:
            job_id = str(UUID(self.variables["job_id"].get().strip()))
        except ValueError:
            self.import_error("Nhập mã job UUID do máy chủ trả về.")
            return
        self.confirm.set(False)
        self.presenter.read(job_id, after)

    def import_read(self, job, file, page, after):
        previous = self.job
        self.busy, self.trusted = False, True
        self.job, self.rows = job, page["items"]
        if not previous or (previous["id"], previous["generation"], previous["version"]) != (job["id"], job["generation"], job["version"]):
            self.cursors, self.page_index = [0], 0
            self.confirm.set(False)
        self.next_after = page["next_after"]
        self.variables["job_id"].set(job["id"])
        self.variables["metadata"].set(f"{file['original_name']} · {file['size_bytes']:,} byte\nSHA-256: {job['file_hash']}\n"
                                        f"Mapping {job['mapping_version']} · v{job['version']} · lượt {job['generation']}\n"
                                        f"Hạn xác nhận: {job['token_expires_at'] or 'Chưa có token hợp lệ'}")
        self.variables["progress"].set(f"{STATUS[job['status']]} · {job['processed_rows']}/{job['total_rows']} dòng kiểm tra\n"
                                        f"{len(job['errors'])} lỗi · Trang {self.page_index + 1}; tối đa 50 dòng/trang.")
        self.progress["value"] = min(100, 100 * job["processed_rows"] / max(1, job["total_rows"]))
        self.table.delete(*self.table.get_children())
        for row in self.rows:
            payload = row["payload"]
            errors = "; ".join(f"{e['column']}: {e['message']}" for e in row["errors"])
            self.table.insert("", "end", iid=str(row["row_no"]), values=(row["row_no"], row["status"],
                              payload.get("owner_code", "COMPANY" if job["kind"] == "12_open_orders" else "—"),
                              payload.get("consignment_code") or "—", errors or "—"))
        # File/worker failures may have no staging rows. Keep these errors visible too.
        self.set_detail("\n".join(f"Dòng {e['row_no']} · {e['column']} · {e['code']}: {e['message']}\n{e['suggested_fix']}"
                                   for e in job["errors"][:50]))
        self.variables["status"].set(STATUS[job["status"]] + (". Chứng từ vẫn cần duyệt/ghi sổ." if job["status"] == "COMMITTED" else ""))
        self.enable()

    def page(self, step):
        index = self.page_index + step
        if self.busy or index < 0 or (step > 0 and self.next_after is None):
            return
        if index == len(self.cursors):
            self.cursors.append(self.next_after)
        self.page_index = index
        self.refresh(self.cursors[index])

    def action(self, action):
        self.enable()
        if self.buttons[action].instate(["disabled"]):
            return
        try:
            reason = self.variables["reason"].get().strip()
            if action == "create":
                self.presenter.create(reason, self.variables["reference"].get().strip())
            else:
                self.presenter.action(action, reason)
        except ValueError:
            self.import_error("Nhập lý do (3–2000 ký tự); tồn đầu kỳ cần biên bản kiểm đếm đã ký.")

    def import_checked(self):
        self.busy = False
        self.variables["status"].set("Chưa có ACK xác nhận. Có thể gửi lại đúng key/nội dung; không tạo yêu cầu mới.")
        self.enable()

    def import_error(self, message):
        self.busy = self.trusted = False
        self.confirm.set(False)
        self.variables["status"].set(message)
        self.enable()

    def download(self, errors=False, path=None):
        if self.buttons["errors" if errors else "source"].instate(["disabled"]):
            return
        initial = "import-errors.csv" if errors else self.presenter.file["original_name"]
        path = path or filedialog.asksaveasfilename(parent=self, initialfile=initial)
        if path:
            self.presenter.download(path, errors)

    def import_downloaded(self, path):
        self.busy = False
        self.variables["status"].set("Đã lưu tệp: " + path)
        self.enable()

    def set_detail(self, value):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", value)
        self.detail.configure(state="disabled")

    def selected_row(self):
        selected = self.table.selection()
        return next((r for r in self.rows if selected and str(r["row_no"]) == selected[0]), None)

    def show_row(self, event=None):
        row = self.selected_row()
        if row:
            self.set_detail(json.dumps(row, ensure_ascii=False, indent=2))

    def open_target(self):
        row = self.selected_row()
        if not self.buttons["open"].instate(["disabled"]) and row and row["target_id"] and self.on_open_document:
            kind = "OPENING" if self.kind_id() == "11_opening" else row["payload"].get("kind")
            self.on_open_document(dict(kind=kind, warehouse_id=self.warehouse_id(), id=row["target_id"]))

    def release_variables(self):
        self.variables.clear()
        self.confirm = None
        self.on_open_document = None
