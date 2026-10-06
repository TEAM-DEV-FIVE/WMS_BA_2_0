import json
import tkinter as tk
from tkinter import ttk
from uuid import UUID

from apps.desktop.presenters.custom_fields import CustomFieldPresenter
from apps.desktop.views.moves import WorkflowView
from packages.contracts.custom_fields import KINDS, FieldDefinition, SchemaWrite, ValuesWrite


class CustomFieldView(WorkflowView):
    def __init__(self, parent, api):
        super().__init__(parent, api, CustomFieldPresenter, scrollable=True)
        self.definition = self.record = None
        self.fields, self.targets, self.inputs, self.input_widgets = [], [], {}, []
        self.after = None
        self.variable("kind", "PO")
        self.kind = self.combo(self.top, "kind", 20)
        self.kind.configure(values=KINDS)
        self.kind.pack(side="left")
        self.kind.bind("<<ComboboxSelected>>", self.kind_changed)
        self.reason_form()
        self.retry_form()
        tabs = ttk.Notebook(self.content)
        tabs.pack(fill="both", expand=True)
        admin, entry = ttk.Frame(tabs, padding=8), ttk.Frame(tabs, padding=8)
        tabs.add(entry, text="Giá trị mở rộng")
        tabs.add(admin, text="Định nghĩa bộ trường")
        self.tabs = tabs
        row = ttk.Frame(admin)
        row.pack(fill="x")
        self.schema_button = ttk.Button(row, text="Tải bộ trường", command=self.load_schema)
        self.schema_button.pack(side="left")
        self.publish_button = ttk.Button(row, text="Phát hành phiên bản", command=self.publish)
        self.publish_button.pack(side="left", padx=5)
        ttk.Label(admin, text="Bỏ trường hoặc đổi kiểu tạo phiên bản mới. Chứng từ cũ giữ nguyên bộ trường đã gắn.", wraplength=680).pack(fill="x", pady=4)
        self.field_table = self.tree(admin, ["code", "label", "type", "required", "access"],
            ["Mã", "Tên hiển thị", "Kiểu", "Bắt buộc", "Quyền"], [140, 220, 90, 70, 80], height=4)
        self.field_table.bind("<<TreeviewSelect>>", self.select_field)
        form = ttk.Frame(admin)
        form.pack(fill="x", pady=4)
        self.definition_widgets = []
        for index, (name, label) in enumerate([("code", "Mã trường"), ("label", "Tên hiển thị"),
                ("value_type", "Kiểu"), ("required", "Bắt buộc"), ("visibility", "Quyền"),
                ("max_length", "Dài tối đa"), ("minimum", "Tối thiểu"), ("maximum", "Tối đa"), ("choices", "Lựa chọn (dấu |)")]):
            ttk.Label(form, text=label).grid(row=index//3*2, column=index%3, sticky="w")
            self.variable(name, {"value_type": "TEXT", "required": "Không", "visibility": "BUSINESS", "max_length": "2000"}.get(name, ""))
            if name in {"value_type", "required", "visibility"}:
                widget = self.combo(form, name, 22)
                widget.configure(values={"value_type": ("TEXT", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "ENUM"),
                                         "required": ("Không", "Có"), "visibility": ("BUSINESS", "PRICE")}[name])
            else:
                widget = ttk.Entry(form, textvariable=self.variables[name], width=24)
            widget.grid(row=index//3*2+1, column=index%3, sticky="ew", padx=(0, 8), pady=(0, 4))
            form.columnconfigure(index%3, weight=1)
            self.definition_widgets.append(widget)
        buttons = ttk.Frame(admin)
        buttons.pack(fill="x")
        self.add_button = ttk.Button(buttons, text="Thêm / cập nhật trường", command=self.add_field)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(buttons, text="Bỏ trường đã chọn", command=self.remove_field)
        self.remove_button.pack(side="left", padx=5)
        row = ttk.Frame(entry)
        row.pack(fill="x")
        self.targets_button = ttk.Button(row, text="Tải đối tượng", command=self.load_targets)
        self.targets_button.pack(side="left")
        self.next_button = ttk.Button(row, text="Trang sau", command=lambda: self.load_targets(self.after))
        self.next_button.pack(side="left", padx=5)
        self.target_selector = self.combo(entry, "target", 65)
        self.target_selector.pack(fill="x", pady=4)
        self.target_selector.bind("<<ComboboxSelected>>", self.select_target)
        row = ttk.Frame(entry)
        row.pack(fill="x")
        ttk.Label(row, text="ID đối tượng (hoặc chọn ở trên)").pack(side="left")
        self.target_entry = ttk.Entry(row, textvariable=self.variable("target_id"))
        self.target_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.read_button = ttk.Button(row, text="Tải giá trị", command=self.read)
        self.read_button.pack(side="left")
        row = ttk.Frame(entry)
        row.pack(fill="x", pady=4)
        self.latest_button = ttk.Button(row, text="Xem bộ trường mới nhất", command=lambda: self.read(latest=True))
        self.latest_button.pack(side="left")
        self.save_button = ttk.Button(row, text="Lưu giá trị / chuyển phiên bản", command=self.save)
        self.save_button.pack(side="left", padx=5)
        self.history_button = ttk.Button(row, text="Lịch sử gần nhất", command=self.history)
        self.history_button.pack(side="left")
        ttk.Label(entry, textvariable=self.variables["detail"], wraplength=680).pack(fill="x", pady=4)
        self.value_frame = ttk.Frame(entry)
        self.value_frame.pack(fill="both", expand=True)
        self.history_table = self.tree(entry, ["version", "schema", "values"],
                                      ["Phiên bản đối tượng", "Bộ trường", "Giá trị"], [140, 80, 460], height=3)
        self.enable()

    def session_changed(self, user=None, warehouses=None):
        super().session_changed(user, warehouses)
        self.permissions = list(user.global_permissions) if user else []
        self.enable()

    def kind_changed(self, event=None):
        permissions = self.permissions
        self.presenter.reset(self.presenter.user_id, self.warehouse_id())
        self.permissions = permissions
        self.enable()

    def scope_changed(self, event=None):
        self.kind_changed(event)

    def load_schema(self):
        self.presenter.submit("schema", "GET", "custom-fields/schemas/"+self.variables["kind"].get())

    def render_fields(self):
        self.field_table.delete(*self.field_table.get_children())
        for f in self.fields:
            self.field_table.insert("", "end", iid=f["code"], values=(f["code"], f["label"], f["value_type"], "Có" if f["required"] else "Không", f["visibility"]))

    def select_field(self, event=None):
        selected = self.field_table.selection()
        if not selected:
            return
        f = next(f for f in self.fields if f["code"] == selected[0])
        for name in ("code", "label", "value_type", "visibility"):
            self.variables[name].set(f[name])
        self.variables["required"].set("Có" if f["required"] else "Không")
        for name in ("max_length", "minimum", "maximum"):
            self.variables[name].set(str(f["validation"][name]) if f["validation"][name] is not None else "")
        self.variables["choices"].set("|".join(f["validation"]["choices"]))

    def add_field(self):
        try:
            values = {name: self.variables[name].get() for name in ("code", "label", "value_type", "visibility")}
            rules = {"max_length": int(self.variables["max_length"].get()),
                     "minimum": self.variables["minimum"].get() or None, "maximum": self.variables["maximum"].get() or None,
                     "choices": self.variables["choices"].get().split("|") if self.variables["choices"].get() else []}
            field = FieldDefinition(**values, required=self.variables["required"].get() == "Có", validation=rules).model_dump(mode="json")
            self.fields = [f for f in self.fields if f["code"] != field["code"]] + [field]
            self.render_fields()
        except (ValueError, TypeError):
            self.workflow_error("Kiểm tra mã trường, kiểu dữ liệu và ràng buộc.")

    def remove_field(self):
        selected = self.field_table.selection()
        self.fields = [f for f in self.fields if f["code"] not in selected]
        self.render_fields()

    def publish(self):
        if not self.definition:
            return
        try:
            body = SchemaWrite(expected_version=self.definition["version"], reason=self.variables["reason"].get(), fields=self.fields)
            self.presenter.command("PUT", "custom-fields/schemas/"+self.definition["entity_type"], body.model_dump(mode="json"))
        except ValueError:
            self.workflow_error("Kiểm tra bộ trường và nhập lý do phát hành.")

    @property
    def target_type(self):
        return "products" if self.variables["kind"].get() == "PRODUCT" else "documents"

    def load_targets(self, after=None):
        self.presenter.targets(self.variables["kind"].get(), after)

    def select_target(self, event=None):
        index = self.target_selector.current()
        if index >= 0:
            self.variables["target_id"].set(self.targets[index]["id"])
            self.read()

    def path(self):
        return self.presenter.target_path(self.target_type, str(UUID(self.variables["target_id"].get())))

    def read(self, latest=False):
        try:
            path = self.path()
            if latest:
                path += ("&" if "?" in path else "?")+"latest=true"
            self.presenter.submit("values", "GET", path)
        except ValueError:
            self.workflow_error("Chọn đối tượng hoặc nhập ID hợp lệ.")

    def history(self):
        try:
            path = self.path().split("?")
            self.presenter.submit("history", "GET", path[0]+"/history"+("?"+path[1] if len(path)>1 else ""))
        except ValueError:
            self.workflow_error("Chọn đối tượng trước.")

    def clear_inputs(self):
        self.inputs.clear()
        self.input_widgets.clear()
        for widget in self.value_frame.winfo_children():
            widget.destroy()

    def render_values(self):
        self.clear_inputs()
        for index, field in enumerate(self.record["schema"]["fields"]):
            value = self.record["values"].get(field["code"])
            label = field["label"]+(" *" if field["required"] else "")+f" ({field['value_type']})"
            ttk.Label(self.value_frame, text=label, wraplength=250).grid(row=index, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=("Có" if value else "Không") if type(value) is bool else str(value) if value is not None else "")
            self.inputs[field["code"]] = var
            if field["value_type"] in {"BOOLEAN", "ENUM"}:
                widget = ttk.Combobox(self.value_frame, textvariable=var, state="readonly",
                    values=[""]+(["Có", "Không"] if field["value_type"] == "BOOLEAN" else field["validation"]["choices"]))
            else:
                widget = ttk.Entry(self.value_frame, textvariable=var)
            widget.grid(row=index, column=1, sticky="ew", padx=5, pady=3)
            self.input_widgets.append((widget, field))
        self.value_frame.columnconfigure(1, weight=1)

    def save(self):
        if not self.record or not self.record["schema"]["revision_id"]:
            return
        try:
            values = {}
            for f in self.record["schema"]["fields"]:
                if f["visibility"] == "PRICE" and not self.record["can_write_price"]:
                    continue
                value = self.inputs[f["code"]].get()
                values[f["code"]] = None if value == "" else int(value) if f["value_type"] == "INTEGER" else value == "Có" if f["value_type"] == "BOOLEAN" else value
            body = ValuesWrite(expected_version=self.record["version"], expected_revision_id=self.record["revision_id"],
                revision_id=self.record["schema"]["revision_id"], values=values, reason=self.variables["reason"].get())
            path = self.presenter.target_path(self.record["target_type"], self.record["id"])
            self.presenter.command("PUT", path, body.model_dump(mode="json"))
        except (ValueError, TypeError):
            self.workflow_error("Kiểm tra kiểu giá trị và nhập lý do thay đổi.")

    def workflow_loaded(self, action, data, permissions):
        self.busy = False
        self.permissions = permissions
        if action == "schema":
            self.definition, self.fields = data, list(data["fields"])
            self.render_fields()
        elif action == "targets":
            self.targets, self.after = data["items"], data.get("next_after")
            self.variables["target"].set("")
            self.target_selector.configure(values=[f"{r.get('number', r.get('sku', r['id']))} · {r.get('name', r.get('status', ''))}" for r in self.targets])
        elif action == "values":
            self.record = data
            self.variables["detail"].set(f"Phiên bản đối tượng {data['version']} · Bộ trường {data['schema']['version']}. Chuyển bộ trường chỉ có hiệu lực sau khi lưu.")
            self.history_table.delete(*self.history_table.get_children())
            self.render_values()
        elif action == "history":
            self.history_table.delete(*self.history_table.get_children())
            for r in data["items"]:
                self.history_table.insert("", "end", values=(r["target_version"], r["schema"]["version"], json.dumps(r["values"], ensure_ascii=False)))
        self.variables["status"].set("Đã tải dữ liệu máy chủ.")
        self.enable()

    def workflow_saved(self, data):
        self.busy = False
        self.variables["status"].set(f"Máy chủ đã xác nhận phiên bản {data['version']}. Tải lại trước khi sửa tiếp.")
        self.definition = self.record = None
        self.fields = []
        self.clear_inputs()
        self.render_fields()
        self.enable()

    def workflow_clear(self):
        self.busy = False
        self.definition = self.record = None
        self.fields, self.targets, self.permissions = [], [], []
        self.after = None
        if hasattr(self, "value_frame"):
            self.clear_inputs()
            self.render_fields()
            self.history_table.delete(*self.history_table.get_children())
            self.target_selector.configure(values=[])
        for name in ("reason", "detail", "target", "target_id", "code", "label", "choices", "minimum", "maximum"):
            if name in self.variables:
                self.variables[name].set("")

    def enable(self):
        if not hasattr(self, "save_button"):
            return
        active = bool(self.presenter.user_id) and not self.busy and not self.presenter.uncertain
        admin = active and "config.manage" in self.permissions
        for widget in (self.schema_button, self.add_button, self.remove_button, *self.definition_widgets):
            self.set_enabled(widget, admin)
        self.set_enabled(self.publish_button, admin and self.definition is not None)
        for widget in (self.targets_button, self.read_button, self.latest_button, self.history_button, self.kind, self.target_entry, self.target_selector):
            self.set_enabled(widget, active)
        self.set_enabled(self.next_button, active and self.after is not None)
        self.set_enabled(self.save_button, active and self.record is not None and self.record["editable"] and bool(self.record["schema"]["revision_id"]))
        self.set_enabled(self.retry_button, bool(self.presenter.uncertain) and not self.busy)
        for widget, field in self.input_widgets:
            self.set_enabled(widget, active and self.record["editable"] and (field["visibility"] != "PRICE" or self.record["can_write_price"]))

    def release_variables(self):
        self.inputs.clear()
        super().release_variables()
