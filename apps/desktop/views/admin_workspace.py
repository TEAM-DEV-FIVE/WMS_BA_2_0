"""Workspace navigation and actionable home, using the existing business screens."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

# Every section points to a real existing workflow, including recovery tools.
SECTIONS = [
    (
        "Không gian làm việc",
        "session_view",
        "Kho làm việc",
        "Chọn kho, quản lý phiên và bảo mật tài khoản",
    ),
    ("Dữ liệu", "master_container", "Danh mục sản phẩm", "Sản phẩm, ảnh, mô tả, đơn vị, kho và đối tác"),
    ("Dữ liệu", "serial_view", "Serial & bảo hành", "Tra cứu nguồn gốc và lịch sử từng thiết bị"),
    ("Dữ liệu", "custom_fields_view", "Trường mở rộng", "Thông tin bổ sung cho sản phẩm và chứng từ"),
    ("Nhập hàng", "order_view", "Đơn mua / đơn bán", "Lập và theo dõi đơn hàng theo kho"),
    ("Nhập hàng", "approval_view", "Hộp thư phê duyệt", "Rà soát chứng từ và quyết định theo thẩm quyền"),
    ("Nhập hàng", "receipt_view", "Nhận hàng", "Ghi nhận hàng nhận và đối chiếu đơn mua"),
    ("Nhập hàng", "opening_view", "Tồn đầu kỳ", "Khởi tạo tồn kho có kiểm đếm và phê duyệt"),
    ("Nhập hàng", "consignment_view", "Nhận ký gửi", "Tiếp nhận hàng theo chủ hàng và hợp đồng"),
    (
        "Vận hành kho",
        "issue_view",
        "Giữ hàng & xuất kho",
        "Giữ chỗ, kiểm tra khả dụng và ghi nhận xuất hàng",
    ),
    ("Vận hành kho", "fulfillment_view", "Soạn & đóng kiện", "Xử lý danh sách lấy hàng và đóng gói"),
    ("Vận hành kho", "quality_view", "Kiểm định chất lượng", "Kiểm tra và phân loại hàng cần xử lý"),
    ("Vận hành kho", "move_view", "Cất & di chuyển hàng", "Chuyển hàng giữa các vị trí trong kho"),
    ("Vận hành kho", "transfer_view", "Chuyển kho", "Theo dõi gửi, nhận và hàng đang vận chuyển"),
    ("Vận hành kho", "customer_return_view", "Khách trả hàng", "Tiếp nhận hàng trả và đối chiếu phiếu xuất"),
    ("Vận hành kho", "supplier_return_view", "Trả nhà cung cấp", "Xử lý hàng trả về nhà cung cấp"),
    ("Kiểm soát", "report_view", "Tồn kho & báo cáo", "Tra cứu tồn, thẻ kho và xuất dữ liệu"),
    ("Kiểm soát", "count_view", "Kiểm kê & điều chỉnh", "Chốt vị trí, đếm hàng và đối soát chênh lệch"),
    ("Kiểm soát", "period_view", "Kỳ kho", "Quản lý thời gian ghi sổ của từng kho"),
    ("Kiểm soát", "reversal_view", "Đảo giao dịch", "Xử lý giao dịch bù theo quy trình có phê duyệt"),
    ("Công cụ & hệ thống", "import_view", "Nhập dữ liệu từ tệp", "Kiểm tra và nhập bộ dữ liệu theo mẫu"),
    ("Công cụ & hệ thống", "print_view", "In chứng từ & tem", "Xem trước, tạo phiếu và nhãn hàng hóa"),
    (
        "Công cụ & hệ thống",
        "admin_view",
        "Tài khoản & phân quyền",
        "Quản lý người dùng, vai trò và phạm vi kho",
    ),
    (
        "Công cụ & hệ thống",
        "recovery_view",
        "Nháp & phục hồi lệnh",
        "Kiểm tra lệnh chưa rõ kết quả trước khi thao tác lại",
    ),
    (
        "Công cụ & hệ thống",
        "receipt_recovery_view",
        "Phục hồi nhận hàng",
        "Tra kết quả và tiếp tục phiếu nhận gián đoạn",
    ),
    (
        "Công cụ & hệ thống",
        "connection_view",
        "Kết nối máy chủ",
        "Kiểm tra kết nối và trạng thái sẵn sàng của máy chủ",
    ),
]


class _NavigationHighlight(tk.Canvas):
    """Rounded active-page surface; the native tree still owns navigation."""

    def __init__(self, tree, command):
        super().__init__(tree, highlightthickness=0, borderwidth=0, cursor="hand2", takefocus=False)
        self.tree, self.command = tree, command
        self.key = None
        self.photo = None
        self.photo_size = None
        self.job = None
        self.closed = False
        self.label_font = tkfont.Font(self, family="Arial", size=10, weight="bold")
        self.bind("<Button-1>", self.activate)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, self.scroll)
        for sequence in ("<Configure>", "<Map>", "<<ThemeChanged>>", "<<TreeviewOpen>>",
                         "<<TreeviewClose>>", "<KeyRelease>", "<ButtonRelease-1>"):
            tree.bind(sequence, lambda event: self.redraw(), add="+")

    def activate(self, event=None):
        self.tree.focus_set()
        if self.key:
            self.tree.selection_set(self.key)
            self.tree.focus(self.key)
            self.command(self.key)
        return "break"

    def scroll(self, event):
        upward = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
        self.tree.yview_scroll(-3 if upward else 3, "units")
        return "break"

    def redraw(self):
        if not self.closed and self.job is None:
            self.job = self.after_idle(self.paint)

    def paint(self):
        self.job = None
        bounds = self.tree.bbox(self.key) if self.key and self.tree.exists(self.key) else ()
        if not bounds:
            self.place_forget()
            return
        _, y, _, height = bounds
        width = max(1, self.tree.winfo_width() - 4)
        self.place(x=2, y=y, width=width, height=height)
        background = ttk.Style(self).lookup("Nav.Treeview", "background") or "#ffffff"
        self.configure(background=background)
        if self.photo_size != (width, height):
            # This is a UI selection background, not a hand-drawn icon.
            scale = 3
            image = Image.new("RGBA", (width * scale, height * scale))
            draw = ImageDraw.Draw(image)
            for x in range(image.width):
                ratio = x / max(1, image.width - 1)
                color = tuple(round(a + (b - a) * ratio) for a, b in zip((0, 91, 158), (55, 133, 184)))
                draw.line((x, 0, x, image.height), fill=(*color, 255))
            mask = Image.new("L", image.size)
            ImageDraw.Draw(mask).rounded_rectangle((0, 3, image.width - 1, image.height - 4),
                                                   radius=image.height // 2, fill=255)
            image.putalpha(mask)
            self.photo = ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=self)
            self.photo_size = (width, height)
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        title = self.tree.item(self.key, "text")
        if self.label_font.measure(title) > width - 26:
            while title and self.label_font.measure(title + "…") > width - 26:
                title = title[:-1]
            title += "…"
        self.create_text(13, height / 2, text=title, anchor="w", fill="#ffffff", font=self.label_font)

    def destroy(self):
        self.closed = True
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.photo = self.label_font = self.command = None
        super().destroy()


class AdminNavigation(ttk.Frame):
    def __init__(self, parent, command):
        super().__init__(parent, padding=(8, 12, 6, 8), width=254)
        self.command = command
        ttk.Label(self, text="KHÔNG GIAN QUẢN TRỊ", style="Muted.TLabel", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=8, pady=(0, 16)
        )
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse", style="Nav.Treeview", takefocus=True)
        self.tree.column("#0", width=234, minwidth=214, stretch=True)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        groups = {}
        for group, key, title, _ in SECTIONS:
            if group not in groups:
                groups[group] = "group_" + str(len(groups))
                self.tree.insert("", "end", iid=groups[group], text=group, open=True, tags=("group",))
            self.tree.insert(groups[group], "end", iid=key, text=title)
        self.tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        self.tree.bind("<ButtonRelease-1>", self.activate)
        self.tree.bind("<Return>", self.activate)
        self.tree.bind("<space>", self.activate)
        self.highlight = _NavigationHighlight(self.tree, command)

        def scrolled(first, last):
            scroll.set(first, last)
            self.highlight.redraw()

        self.tree.configure(yscrollcommand=scrolled)

    def activate(self, event=None):
        if event is not None and getattr(event, "num", None) == 1:
            clicked = self.tree.identify_row(event.y)
            # Clicking a group's disclosure arrow may leave the old leaf selected.
            # Let Treeview collapse it without reopening that leaf's screen.
            if not clicked or clicked.startswith("group_"):
                return
        selection = self.tree.selection()
        if selection and not selection[0].startswith("group_"):
            self.command(selection[0])

    def select(self, key):
        if self.tree.exists(key):
            self.highlight.key = key
            self.tree.selection_set(key)
            self.tree.see(key)
            self.highlight.redraw()
