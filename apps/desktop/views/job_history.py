"""Read-only history panel. Its owner performs HTTP on the existing fenced worker."""

import tkinter as tk
from datetime import UTC, datetime, timedelta
from tkinter import ttk


class JobHistoryPanel(ttk.Frame):
    def __init__(self, parent, load, open_job, statuses):
        super().__init__(parent, padding=4)
        self.load_callback, self.open_callback = load, open_job
        self.rows, self.cursors, self.next_after = {}, [None], None
        self.last_filters = None
        self.since, self.until, self.state = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.message = tk.StringVar(value="Chọn loại/kho ở màn chính rồi tải lịch sử của bạn.")
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        for label, variable in (("Từ ngày UTC", self.since), ("Đến ngày UTC", self.until)):
            ttk.Label(toolbar, text=label).pack(side="left")
            ttk.Entry(toolbar, textvariable=variable, width=11).pack(side="left", padx=3)
        ttk.Combobox(
            toolbar, textvariable=self.state, values=["", *statuses], state="readonly", width=12
        ).pack(side="left")
        ttk.Button(toolbar, text="Tải lịch sử", command=self.load).pack(side="left", padx=3)
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        columns = ("time", "kind", "status", "error", "id")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=6, selectmode="browse")
        for name, label, width in zip(
            columns,
            ("Tạo lúc", "Loại", "Trạng thái", "Lỗi / hết hạn", "Mã job"),
            (180, 100, 100, 190, 290),
            strict=True,
        ):
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, stretch=False)
        x = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        y = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(xscrollcommand=x.set, yscrollcommand=y.set)
        x.pack(side="bottom", fill="x")
        y.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Trang trước", command=lambda: self.page(-1)).pack(side="left")
        ttk.Button(buttons, text="Trang sau", command=lambda: self.page(1)).pack(side="left")
        ttk.Button(buttons, text="Mở job đã chọn", command=self.open_selected).pack(side="left")
        self.tree.bind("<Return>", lambda event: self.open_selected())
        self.tree.bind("<Double-1>", lambda event: self.open_selected())
        ttk.Label(self, textvariable=self.message, wraplength=750).pack(fill="x")

    def filters(self):
        result = {}
        for name, variable in (("since", self.since), ("until", self.until)):
            if variable.get().strip():
                day = datetime.strptime(variable.get().strip(), "%Y-%m-%d").replace(tzinfo=UTC)
                result[name] = (day + (timedelta(days=1) if name == "until" else timedelta())).isoformat()
        if self.state.get():
            result["status"] = self.state.get()
        return result

    def load(self, cursor=None):
        try:
            filters = self.filters()
        except ValueError:
            self.message.set("Ngày cần dạng YYYY-MM-DD.")
            return False
        if filters != self.last_filters:
            cursor = None
        query = dict(filters, limit=25)
        if cursor:
            query["after"] = cursor
        if not self.load_callback(query):
            return False
        if cursor is None:
            self.cursors = [None]
        self.last_filters = filters
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.next_after = None
        self.message.set("Đang tải lịch sử…")
        return True

    def page(self, step):
        try:
            changed = self.filters() != self.last_filters
        except ValueError:
            changed = True
        if changed:
            self.load()
            return
        if step > 0 and self.next_after:
            cursor = self.next_after
            if self.load(cursor) and self.cursors[-1] != cursor:
                self.cursors.append(cursor)
        elif step < 0 and len(self.cursors) > 1:
            cursors = self.cursors[:-1]
            if self.load(cursors[-1]):
                self.cursors = cursors

    def show(self, result):
        self.rows = {row["id"]: row for row in result["items"]}
        self.tree.delete(*self.tree.get_children())
        for row in result["items"]:
            self.tree.insert(
                "",
                "end",
                iid=row["id"],
                values=(
                    row["created_at"],
                    row["kind"],
                    row["status"],
                    "Đã hết hạn; chỉ xem lịch sử" if row["expired"] else row["error_code"] or "",
                    row["id"],
                ),
            )
        self.next_after = result["next_after"]
        self.message.set(
            f"{len(self.rows)} job của bạn; chỉ hiện các job còn đủ quyền. Hết hạn không tải lại file."
        )

    def open_selected(self):
        selected = self.tree.selection()
        row = self.rows.get(selected[0]) if selected else None
        if row and not row["expired"]:
            self.open_callback(row["id"])
        elif row:
            self.message.set("Job hết hạn. Tạo snapshot mới để xuất dữ liệu hiện tại.")

    def clear(self):
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.cursors, self.next_after, self.last_filters = [None], None, None
        self.message.set("Tải lại lịch sử theo tài khoản, loại và kho hiện tại.")

    def release_variables(self):
        self.since = self.until = self.state = self.message = None
