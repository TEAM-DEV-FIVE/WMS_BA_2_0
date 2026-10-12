from datetime import date
from tkinter import ttk

from apps.desktop.presenters.periods import PeriodPresenter
from apps.desktop.views.moves import WorkflowView
from apps.desktop.views.pagination import install_pagination
from apps.desktop.views.ui_help import HelpButton
from packages.contracts.orders import OrderAction
from packages.contracts.periods import PeriodInput, PeriodReopen


class PeriodView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, PeriodPresenter, scrollable=True)
        self.doc, self.next_after = None, None
        self.load_button = ttk.Button(self.top, text="Tải kỳ kho", command=self.presenter.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(self.top, text="Trang sau", command=lambda: self.presenter.load(after=self.next_after))
        self.next_button.pack(side="left", padx=5)
        self.table = self.tree(self.content, ["start", "end", "status", "version"], ["Từ ngày", "Đến ngày", "Trạng thái", "Version"], [190, 190, 190, 100], height=8)
        self.table.bind("<<TreeviewSelect>>", self.select)
        information = ttk.Frame(self.content)
        information.pack(fill="x", pady=(8, 12))
        HelpButton(information, "Nhập ngày theo dạng YYYY-MM-DD. Khóa kỳ yêu cầu hết phiếu kho/kiểm kê chờ và sổ khớp số dư; mở lại cần xác nhận độc lập trong 24 giờ, đúng phiên bản kỳ và phiên MFA.", label="Quy định kỳ kho").pack(side="right")
        HelpButton(information, self.variables["detail"], title="Thông tin kỳ kho", label="Xem thông tin kỳ").pack(side="right", padx=(0, 12))
        form = ttk.Frame(self.content)
        form.pack(anchor="w", pady=(0, 12))
        self.inputs = []
        for row, (name, title) in enumerate([("starts_on", "Từ ngày"), ("ends_on", "Đến ngày"), ("reason", "Lý do")]):
            ttk.Label(form, text=title, width=14).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            entry = ttk.Entry(form, textvariable=self.variable(name, date.today().isoformat() if name != "reason" else ""), width=48)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            if name == "reason":
                self.reason_entry = entry
            else:
                self.inputs.append(entry)
        actions = ttk.Frame(self.content)
        actions.pack(anchor="w", pady=(0, 16))
        self.buttons = {}
        action_specs = [
            ("create", "Mở kỳ mới", "Primary.TButton"),
            ("close", "Khóa kỳ / đối soát", "Amber.TButton"),
            ("confirm-reopen", "Kiểm soát viên xác nhận mở lại", "Teal.TButton"),
            ("reopen", "Giám đốc mở lại (MFA)", "Purple.TButton"),
        ]
        for index, (action, title, style) in enumerate(action_specs):
            button = self.buttons[action] = ttk.Button(actions, text=title, command=lambda a=action: self.action(a), style=style)
            button.grid(row=(index // 2) * 2, column=(index % 2) * 2, sticky="nsew")
        actions.columnconfigure(1, minsize=12)
        actions.rowconfigure(1, minsize=12)
        for column in (0, 2):
            actions.columnconfigure(column, weight=1, uniform="period-actions")
        for row in (0, 2):
            actions.rowconfigure(row, weight=1, uniform="period-action-rows")
        self.retry_form(operation=True)
        self.retry_button.configure(style="Slate.TButton")
        self.operation_button.configure(style="Indigo.TButton")
        self.operation_button.pack_configure(padx=(12, 0))
        self.session_changed()
        install_pagination(self, lambda after: self.presenter.load(after=after), limit=50, resource='periods')
        self.enable()

    def enable(self):
        free = bool(self.presenter.user_id and self.warehouse_id()) and not self.busy
        writable = free and not self.presenter.uncertain
        for widget in [self.selector, self.load_button]:
            self.set_enabled(widget, free)
        self.set_enabled(self.next_button, free and self.next_after)
        for widget in self.inputs + [self.reason_entry]:
            self.set_enabled(widget, writable)
        for action, button in self.buttons.items():
            allowed = "period.create" in self.permissions if action == "create" else self.doc and action in self.doc["allowed_actions"]
            self.set_enabled(button, writable and allowed)
        self.set_enabled(self.retry_button, free and self.presenter.uncertain)
        self.set_enabled(self.operation_button, free and self.presenter.uncertain)
        if hasattr(self, "pagination"):
            self.pagination.set_enabled(self.load_button.instate(["!disabled"]) and not self.presenter.uncertain)

    def workflow_clear(self):
        self.doc, self.next_after, self.permissions, self.busy = None, None, [], False
        self.table.delete(*self.table.get_children())
        for name in self.variables:
            if name not in {"warehouse", "status"}:
                self.variables[name].set("")

    def select(self, event=None):
        selected = self.table.selection()
        if selected and not self.busy and not self.presenter.uncertain:
            self.presenter.read(selected[0])

    def action(self, action):
        if self.busy or self.presenter.uncertain:
            return
        try:
            reason = self.variables["reason"].get()
            if action == "create":
                model = PeriodInput(warehouse_id=self.warehouse_id(), starts_on=self.variables["starts_on"].get(),
                                    ends_on=self.variables["ends_on"].get(), reason=reason)
                path = "periods"
            else:
                if not self.doc:
                    return
                args = dict(expected_version=self.doc["version"], reason=reason)
                model = PeriodReopen(**args, confirmation_id=self.doc["confirmation_id"]) if action == "reopen" else OrderAction(**args)
                path = "periods/" + self.doc["id"] + "/" + action
            self.presenter.command("POST", path, model.model_dump(mode="json"))
        except (ValueError, TypeError):
            self.workflow_error("Nhập ngày hợp lệ, lý do; tải xác nhận kiểm soát viên trước khi mở lại")

    def workflow_loaded(self, action, data, permissions):
        if action == 'periods':
            self.pagination.loaded(data)
        self.busy, self.permissions = False, permissions
        if action == "periods":
            self.next_after = data["next_after"]
            self.table.delete(*self.table.get_children())
            for row in data["items"]:
                self.table.insert("", "end", iid=row["id"], values=(row["starts_on"], row["ends_on"], row["status"], row["version"]))
        else:
            self.doc = data
            self.variables["detail"].set(f"{data['starts_on']} → {data['ends_on']}\n{data['status']}  v{data['version']}\n" +
                                         ("Đã có xác nhận mở lại" if data["confirmation_id"] else "Chưa có xác nhận mở lại"))
            self.variables["reason"].set("")
        self.variables["status"].set("Đã tải kỳ kho")
        self.enable()

    def workflow_saved(self, result):
        self.busy = False
        self.presenter.read(result["id"])
