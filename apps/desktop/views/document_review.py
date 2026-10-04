import json
import tkinter as tk
from tkinter import ttk


def flattened(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flattened(child, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list) and prefix == "lines":
        for line in value:
            result.update(flattened(line, f"Dòng {line['line_no']}"))
    else:
        result[prefix] = "—" if value is None else (
            json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value))
    return result


def snapshot_diff(before, after):
    left, right = flattened(before), flattened(after)
    return [(key, left.get(key, "—"), right.get(key, "—"))
            for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]


FIELD_LABELS = {
    "kind": "Loại", "warehouse_id": "Kho", "partner_id": "Đối tác", "business_date": "Ngày",
    "product_id": "Sản phẩm", "uom_id": "Đơn vị", "quantity": "Số lượng", "factor_snapshot": "Hệ số",
    "base_quantity": "Lượng cơ sở", "owner_id": "Chủ sở hữu", "consignment_id": "Hợp đồng ký gửi",
    "source_line_id": "Dòng nguồn", "closed_base_quantity": "Lượng đóng", "line_no": "Số dòng",
    "assigned_user_ids": "Người được phân công", "source_order_id": "PO nguồn",
    "destination_location_id": "Vị trí nhận", "lot_code": "Lô", "serial_code": "Serial",
    "manufactured_on": "Ngày sản xuất", "expires_on": "Hạn dùng",
}


def field_label(path):
    return " · ".join(FIELD_LABELS.get(p, p) for p in path.split(".") if p not in {"header", "receipt_plan"})


class ScrollPanel(ttk.Frame):
    """Keep form fields reachable at the shell's minimum size, including by Tab."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=150)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.inner = ttk.Frame(self.canvas, padding=4)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.inner)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.inner.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def bind_scrolling(self):
        def focus(event):
            widget = event.widget
            top = widget.winfo_rooty() - self.inner.winfo_rooty()
            height = max(self.inner.winfo_height(), 1)
            low, high = self.canvas.yview()
            bottom = top + widget.winfo_height()
            if top < low * height:
                self.canvas.yview_moveto(top / height)
            elif bottom > high * height:
                self.canvas.yview_moveto((bottom - self.canvas.winfo_height()) / height)

        def bind_children(widget):
            widget.bind("<FocusIn>", focus, add="+")
            for child in widget.winfo_children():
                bind_children(child)

        bind_children(self.inner)
        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda event: self.canvas.yview_scroll(1, "units"))


class ReviewPanel(ScrollPanel):
    def __init__(self, parent, load):
        super().__init__(parent)
        self.left, self.right, self.message = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.records = []
        bar = ttk.Frame(self.inner)
        bar.pack(fill="x")
        self.load_button = ttk.Button(bar, text="Tải snapshot duyệt", command=load)
        self.load_button.pack(side="left")
        self.before = ttk.Combobox(bar, state="readonly", textvariable=self.left, width=26)
        self.before.pack(side="left", padx=4)
        self.after = ttk.Combobox(bar, state="readonly", textvariable=self.right, width=26)
        self.after.pack(side="left")
        for box in (self.before, self.after):
            box.bind("<<ComboboxSelected>>", lambda event: self.compare())
        ttk.Label(self.inner, textvariable=self.message, wraplength=700).pack(fill="x", pady=4)
        frame = ttk.Frame(self.inner)
        frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(frame, columns=("field", "before", "after"), show="headings", height=5)
        for key, title, width in [("field", "Trường thay đổi", 210), ("before", "Bản trước", 280),
                                  ("after", "Bản sau", 280)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=100)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.detail = tk.Text(self.inner, height=3, wrap="word", state="disabled", takefocus=True)
        self.detail.pack(fill="x", pady=3)
        self.table.bind("<<TreeviewSelect>>", self.show_detail)
        ttk.Label(self.inner, text="Chỉ có bản lưu lúc gửi duyệt và nội dung hiện tại; không phải lịch sử mọi lần sửa.\n"
                  "Đối chiếu trường nghiệp vụ được hỗ trợ; không bao gồm giá hoặc thuộc tính tùy biến.",
                  wraplength=740).pack(fill="x")
        self.clear()
        self.bind_scrolling()

    def clear(self):
        self.records = []
        self.unavailable = 0
        self.left.set("")
        self.right.set("")
        self.before.configure(values=[])
        self.after.configure(values=[])
        self.table.delete(*self.table.get_children())
        self.message.set("Chọn phiếu rồi tải các bản lưu để so sánh.")
        self.set_detail("")

    def set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def show_detail(self, event=None):
        selected = self.table.selection()
        if selected:
            field, left, right = self.table.item(selected[0], "values")
            self.set_detail(f"{field}\nTrước: {left}\nSau: {right}")

    def loaded(self, result):
        available = [r for r in result["snapshots"] if r["content"] is not None]
        self.unavailable = len(result["snapshots"]) - len(available)
        self.records = [r["content"] for r in available] + [result["current"]]
        labels = [f"Gửi duyệt v{r['document_version']} · {r['status']}" for r in available]
        labels += [f"Hiện tại v{result['current_version']}"]
        self.before.configure(values=labels)
        self.after.configure(values=labels)
        self.before.current(max(0, len(labels) - 2))
        self.after.current(len(labels) - 1)
        self.compare()

    def compare(self):
        if not self.records or min(self.before.current(), self.after.current()) < 0:
            return
        self.table.delete(*self.table.get_children())
        self.set_detail("")
        changes = snapshot_diff(self.records[self.before.current()], self.records[self.after.current()])
        for field, left, right in changes:
            self.table.insert("", "end", values=(field_label(field), left, right))
        self.message.set(f"{len(changes)} trường thay đổi trong nội dung đối chiếu." if changes else
                         "Không có khác biệt trong các trường được hiển thị của hai bản đã chọn.")
        if self.unavailable:
            self.message.set(f"{self.unavailable} lần gửi cũ không có bản lưu; không thể so sánh các lần đó. "
                             + self.message.get())

    def release_variables(self):
        self.left = self.right = self.message = None


def fulfillment_label(doc):
    from decimal import Decimal

    if doc["status"] == "COMPLETED" and any(Decimal(line["closed_base"]) > 0 for line in doc["lines"]):
        return "Đã đóng phần còn lại (chưa thực hiện đủ)"
    return {"DRAFT": "Nháp", "SUBMITTED": "Chờ duyệt", "APPROVED": "Đã duyệt",
            "REJECTED": "Từ chối", "PARTIAL": "Thực hiện một phần", "COMPLETED": "Hoàn tất",
            "CANCELLED": "Đã hủy"}.get(doc["status"], doc["status"])
