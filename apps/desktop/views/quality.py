from tkinter import ttk

from apps.desktop.catalog_display import display_sku
from apps.desktop.presenters.quality import QualityPresenter
from apps.desktop.views.document_pages import DocumentPages, reset_document_page
from apps.desktop.views.document_review import ScrollPanel
from apps.desktop.views.moves import WorkflowView
from apps.desktop.views.pagination import install_pagination
from apps.desktop.views.ui_help import HelpButton
from packages.contracts.quality import QualityInput


class QualityView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, QualityPresenter)
        self.source = None
        self.sources, self.decisions = {}, {}
        self.next_after = self.history_after = None
        self.load_button = ttk.Button(self.top, text="Tải lần nhận", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.next_after))
        self.next_button.pack(side="left", padx=6)
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x")
        self.detail_scroll = ScrollPanel(self)
        self.detail_scroll.pack(fill="both", expand=True)
        body = self.detail_scroll.inner
        self.table = self.tree(body, ["number", "sku", "trace", "location", "left"],
            ["Phiếu nhận", "SKU / owner", "Lô / serial", "Nguồn", "Còn kiểm định"], [200, 210, 170, 100, 130])
        self.table.bind("<<TreeviewSelect>>", self.select)
        ttk.Label(body, textvariable=self.variables["detail"], wraplength=820).pack(fill="x", pady=6)
        form = ttk.Frame(body)
        form.pack(fill="x", pady=6)
        self.entries = []
        for name, label in [("accepted", "Số lượng đạt"), ("rejected", "Số lượng lỗi")]:
            ttk.Label(form, text=label).pack(side="left", padx=(0, 6))
            entry = ttk.Entry(form, textvariable=self.variable(name, "0"), width=18)
            entry.pack(side="left", padx=(0, 12))
            self.entries.append(entry)
        self.reason_form(parent=body)
        self.decide_button = ttk.Button(body, text="Ghi quyết định chất lượng", command=self.decide)
        self.decide_button.pack(anchor="w", pady=4)
        HelpButton(body, "Quyết định không tăng hoặc giảm tồn. Dùng mã quyết định trong Cất và di chuyển hàng để lập phiếu.").pack(anchor="e", pady=5)
        self.history = self.tree(body, ["id", "result", "quantity", "remaining", "reason"],
            ["UUID quyết định", "Kết quả", "Lượng", "Còn chuyển", "Lý do"], [285, 100, 90, 90, 230])
        self.history.bind("<<TreeviewSelect>>", self.decision_selected)
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=4)
        self.history_button = ttk.Button(bar, text="Lịch sử từ đầu", command=lambda: self.presenter.read(self.source["id"]) if self.source else None)
        self.history_button.pack(side="left")
        self.history_next = ttk.Button(bar, text="Lịch sử tiếp", command=lambda: self.presenter.read(self.source["id"], self.history_after) if self.source else None)
        self.history_next.pack(side="left", padx=6)
        ttk.Entry(body, textvariable=self.variable("decision_detail"), state="readonly").pack(fill="x", pady=4)
        self.retry_form(parent=footer)
        self.document_pages = DocumentPages(self.table, footer=footer)
        self.align_document_toolbar()
        self.detail_scroll.bind_scrolling()
        self.session_changed()
        install_pagination(self, lambda after: self.presenter.load(after=after), limit=50, resource='quality/sources')
        self.enable()

    def open_workspace(self):
        if self.presenter.user_id and self.warehouse_id() and not self.busy and not self.presenter.uncertain and not self.loaded:
            self.presenter.load()

    def scope_changed(self, event=None):
        if hasattr(self, "pagination"):
            self.pagination.reset()
        super().scope_changed(event)
        self.open_workspace()

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain and self.source and "quality.decide" in self.permissions
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.next_after)
        for widget in [*self.entries, self.reason_entry, self.decide_button]:
            self.set_enabled(widget, writable)
        self.set_enabled(self.history_button, free and self.source)
        self.set_enabled(self.history_next, free and self.source and self.history_after)
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        if hasattr(self, "pagination"):
            self.pagination.set_enabled(self.load_button.instate(["!disabled"]) and not self.presenter.uncertain)

    def workflow_clear(self):
        reset_document_page(self)
        self.loaded = False
        self.source, self.sources, self.decisions, self.permissions = None, {}, {}, []
        self.next_after = self.history_after = None
        self.busy = False
        self.table.delete(*self.table.get_children())
        self.history.delete(*self.history.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status"}:
                self.variables[name].set("")

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def decision_selected(self, event=None):
        selected = self.history.selection()
        if selected and selected[0] in self.decisions:
            row = self.decisions[selected[0]]
            self.variables["decision_detail"].set(f"{row['id']}  {row['result']}  {row['decided_at']}"
                f"  người quyết định {row['decided_by']}  {row['reason']}")

    def workflow_loaded(self, action, result, permissions):
        if action == 'quality/sources':
            self.pagination.loaded(result)
        self.busy, self.permissions = False, permissions
        if action == "quality/sources":
            self.loaded = True
            self.source = None
            self.history.delete(*self.history.get_children())
            self.decisions = {}
            self.history_after = None
            self.variables["detail"].set("")
            self.variables["decision_detail"].set("")
            for field in ("accepted", "rejected", "reason"):
                self.variables[field].set("")
            self.sources = {r["id"]: r for r in result["items"]}
            self.next_after = result["next_after"]
            self.table.delete(*self.table.get_children())
            for row in result["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["receipt_number"], f"{display_sku(row['sku'])} / {row['owner_code']}",
                    row["lot_code"] or row["serial_code"] or "", row["location_code"], row["remaining_base"]))
        else:
            self.source = result["source"]
            row = self.source
            self.variables["detail"].set(f"{row['receipt_number']}  v{row['version']}  nhận {row['received_base']}"
                f"  còn kiểm định {row['remaining_base']}  {display_sku(row['sku'])} / {row['owner_code']}  nguồn {row['location_code']}")
            self.variables["accepted"].set(row["remaining_base"])
            self.variables["rejected"].set("0")
            self.variables["reason"].set("")
            self.decisions = {q["id"]: q for q in result["items"]}
            self.history_after = result["next_after"]
            self.history.delete(*self.history.get_children())
            for q in result["items"]:
                self.history.insert("", "end", iid=q["id"], values=(q["id"], {"ACCEPT": "Đạt", "REJECT": "Không đạt"}.get(q["result"], q["result"]), q["quantity"], q["remaining_base"], q["reason"]))
        self.variables["status"].set("Đã tải dữ liệu" + (" Còn trang sau" if result["next_after"] else ""))
        self.enable()
        if action == "quality/sources":
            if self.sources:
                first = next(iter(self.sources))
                self.table.selection_set(first)
                self.table.focus(first)
            else:
                self.variables["status"].set("Chưa có phiếu nhận hàng đủ điều kiện kiểm định tại kho này")

    def decide(self):
        if self.busy or not self.source or self.presenter.uncertain:
            return
        try:
            body = QualityInput(expected_version=self.source["version"], accepted_base=self.variables["accepted"].get(),
                                rejected_base=self.variables["rejected"].get(), reason=self.variables["reason"].get()).model_dump(mode="json")
            self.presenter.command("POST", "quality/sources/" + self.source["id"] + "/decide", body)
        except (ValueError, TypeError):
            self.workflow_error("Nhập lượng đạt/lỗi không âm (tổng phải dương), tối đa 6 chữ số thập phân và lý do")

    def workflow_saved(self, result):
        self.busy = False
        self.presenter.read(result["receipt_move_id"])
