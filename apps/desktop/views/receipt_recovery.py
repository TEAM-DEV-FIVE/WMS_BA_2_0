import tkinter as tk
from datetime import datetime
from tkinter import ttk

LABELS = {
    "READY": "Chờ gửi",
    "SENDING": "Chưa rõ kết quả",
    "UNKNOWN": "Chưa rõ kết quả",
    "COMMITTED": "Đã ghi sổ",
    "CONFLICT": "Bị từ chối",
}


class ReceiptRecoveryView(ttk.Frame):
    def __init__(self, parent, presenter):
        super().__init__(parent, padding=14)
        self.presenter = presenter
        presenter.recovery_view = self
        self.records = {}
        self.status = tk.StringVar(value="Đăng nhập để xem lệnh nhận hàng đã lưu trên máy này.")
        ttk.Label(self, text="Phục hồi lệnh nhận hàng", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            self,
            text="Mở lại ứng dụng chỉ tải danh sách đã lưu. Tra kết quả trước khi gửi lại; mỗi lần gửi lại giữ nguyên nội dung yêu cầu.",
            wraplength=810,
        ).pack(fill="x", pady=8)
        self.table = ttk.Treeview(
            self,
            columns=["document", "state", "lines", "updated"],
            show="headings",
            height=7,
            selectmode="browse",
        )
        for name, title, width in [
            ("document", "Phiếu nhận", 280),
            ("state", "Kết quả", 170),
            ("lines", "Số dòng", 80),
            ("updated", "Cập nhật trên máy", 190),
        ]:
            self.table.heading(name, text=title)
            self.table.column(name, width=width, minwidth=65)
        self.table.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", self.select)
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=8)
        self.refresh_button = ttk.Button(actions, text="Tải dữ liệu đã lưu", command=presenter.scan_recovery)
        self.refresh_button.pack(side="left")
        self.lookup_button = ttk.Button(
            actions, text="Tra kết quả máy chủ", command=lambda: self.action("lookup")
        )
        self.lookup_button.pack(side="left", padx=8)
        self.retry_button = ttk.Button(
            actions, text="Gửi lại đúng lệnh đã chọn", command=lambda: self.action("retry")
        )
        self.retry_button.pack(side="left")
        ttk.Label(self, textvariable=self.status, wraplength=810).pack(fill="x", pady=5)
        self.detail = tk.Text(self, height=9, wrap="word", state="disabled")
        self.detail.pack(fill="both", expand=True, pady=5)
        ttk.Label(
            self,
            text="Chỉ hiển thị dữ liệu của tài khoản và máy chủ hiện tại. Giữ thư mục dữ liệu WMS khi cập nhật ứng dụng.",
            wraplength=810,
        ).pack(fill="x", pady=5)
        self.enable()

    def selected(self):
        selected = self.table.selection()
        return self.records.get(selected[0]) if selected else None

    def enable(self):
        active = bool(self.presenter.user_id) and not self.presenter.recovery_busy
        record = self.selected()
        self.refresh_button.state(["!disabled"] if active else ["disabled"])
        ready = active and self.presenter.recovery_ready and record
        self.lookup_button.state(["!disabled"] if ready and record["state"] != "CONFLICT" else ["disabled"])
        self.retry_button.state(
            ["!disabled"] if ready and record["state"] in {"READY", "SENDING", "UNKNOWN"} else ["disabled"]
        )

    def text(self, content):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", content)
        self.detail.configure(state="disabled")

    def clear(self):
        self.records = {}
        self.table.delete(*self.table.get_children())
        self.text("")
        self.status.set("Đăng nhập để xem lệnh nhận hàng đã lưu trên máy này.")
        self.enable()

    def loading(self):
        self.status.set("Đang xử lý dữ liệu phục hồi…")
        self.enable()

    def loaded(self, records, error=None, result=None):
        selected = self.table.selection()
        self.records = {r["key"]: r for r in records}
        self.table.delete(*self.table.get_children())
        for record in records:
            try:
                updated = datetime.fromisoformat(record["updated_at"]).astimezone().strftime("%d/%m/%Y %H:%M")
            except ValueError:
                updated = "Không xác định"
            self.table.insert(
                "",
                "end",
                iid=record["key"],
                values=(
                    record["context"].get("document_number", record["endpoint"]),
                    LABELS[record["state"]],
                    len(record["payload"].get("lines", [])),
                    updated,
                ),
            )
        if selected and selected[0] in self.records:
            self.table.selection_set(selected[0])
        elif records:
            self.table.selection_set(records[0]["key"])
        self.select()
        if error:
            self.status.set(str(error))
        elif result:
            self.status.set(
                "Máy chủ xác nhận lệnh đã ghi sổ. Chi tiết phiếu hiện tại được tải ở tab Nhận hàng."
            )
        elif records:
            self.status.set(
                "Đã tải tối đa 200 lệnh, ưu tiên lệnh chưa rõ kết quả. Chọn lệnh để tra cứu; chưa tự gửi lệnh nào."
            )
        else:
            self.status.set("Chưa có lệnh ghi sổ nhận hàng được lưu cho tài khoản này.")
        self.enable()

    def select(self, event=None):
        record = self.selected()
        if not record:
            self.text("")
        else:
            body = record["payload"]
            lines = [
                f"Phiếu: {record['context'].get('document_number', record['endpoint'])}",
                f"Kết quả: {LABELS[record['state']]}",
                f"Lý do: {body.get('reason', '')}",
                "Số lượng theo đơn vị cơ sở:",
            ]
            lines += [
                f"  Dòng {i}: {line.get('quantity_base', '?')}"
                for i, line in enumerate(body.get("lines", []), 1)
            ]
            response = record["response"] or {}
            if record["state"] == "CONFLICT":
                lines += [
                    "Lệnh này bị máy chủ từ chối: " + response.get("message", ""),
                    "Tải lại phiếu ở tab Nhận hàng, xử lý nguyên nhân rồi tạo yêu cầu mới.",
                ]
            lines += [f"Mã tra cứu hỗ trợ: {record['key']}"]
            if response.get("request_id"):
                lines += [f"Mã phản hồi máy chủ: {response['request_id']}"]
            self.text("\n".join(lines))
        self.enable()

    def action(self, action):
        record = self.selected()
        if record:
            getattr(self.presenter, action)(record["key"])

    def release_variables(self):
        self.status = None
