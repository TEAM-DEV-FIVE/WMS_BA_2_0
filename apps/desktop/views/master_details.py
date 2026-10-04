"""Product UOM revisions, exact barcodes and permission-scoped reference prices."""

import tkinter as tk
from tkinter import ttk
from urllib.parse import urlencode

from apps.desktop.presenters.master_data import MasterDataPresenter
from apps.desktop.views.catalog_lookup import CatalogLookup, reference_label


class ProductDetailsView(ttk.Frame):
    modes = ("Quy đổi UOM", "Barcode", "Giá tham chiếu")
    resources = ("product-uoms", "barcodes", "prices")

    def __init__(self, parent, api):
        super().__init__(parent, padding=16)
        self.presenter = MasterDataPresenter(self, api)
        self.busy, self.lookup = False, None
        self.permissions, self.warehouses = set(), []
        self.actor_id, self.suspended = None, {}
        self.product, self.uom, self.conversion, self.current = None, None, None, None
        self.rows, self.next_after = {}, None
        self.mode = tk.StringVar(value=self.modes[0])
        self.query, self.status, self.product_text, self.warehouse = (tk.StringVar() for _ in range(4))
        self.status.set("Chọn sản phẩm để xem quy đổi UOM hoặc giá; barcode tìm theo mã.")
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.selector = ttk.Combobox(bar, textvariable=self.mode, values=self.modes, state="readonly", width=18)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self.switch)
        self.search = ttk.Entry(bar, textvariable=self.query, width=22)
        self.search.pack(side="left", padx=8)
        self.search.bind("<Return>", lambda event: self.load())
        self.load_button = ttk.Button(bar, text="Tìm / tải lại", command=self.load)
        self.load_button.pack(side="left")
        self.next_button = ttk.Button(bar, text="Trang sau", command=lambda: self.load(True))
        self.next_button.pack(side="left", padx=8)
        context = ttk.Frame(self)
        context.pack(fill="x", pady=8)
        self.product_button = ttk.Button(context, text="Chọn sản phẩm…", command=self.choose_product)
        self.product_button.grid(row=0, column=0, sticky="w")
        ttk.Label(context, textvariable=self.product_text, wraplength=550).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Label(context, text="Kho đọc giá").grid(row=1, column=0, sticky="w", pady=6)
        self.warehouse_selector = ttk.Combobox(context, textvariable=self.warehouse, state="readonly", width=44)
        self.warehouse_selector.grid(row=1, column=1, sticky="w", padx=10)
        self.warehouse_selector.bind("<<ComboboxSelected>>", self.scope_changed)
        ttk.Label(self, textvariable=self.status, wraplength=820).pack(fill="x", pady=6)
        self.table = ttk.Treeview(self, columns=("code", "detail", "state"), show="headings", height=6)
        for column, label, width in (("code", "Đơn vị / barcode / ngày hiệu lực", 240),
                                     ("detail", "Quy cách / giá quản trị", 330), ("state", "Revision / trạng thái", 180)):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=60)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.form = ttk.Frame(self)
        self.form.pack(fill="x", pady=8)
        self.variables, self.inputs, self.labels = {}, {}, {}
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.new_button = ttk.Button(actions, text="Tạo mới / revision mới", command=self.new)
        self.new_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Lưu", command=self.save)
        self.save_button.pack(side="left", padx=8)
        self.retry_button = ttk.Button(actions, text="Gửi lại cùng yêu cầu", command=self.presenter.retry)
        self.retry_button.pack(side="left")
        self.rebuild()

    def resource(self):
        return self.resources[self.modes.index(self.mode.get())]

    def session_changed(self, user=None, warehouses=None):
        if self.lookup:
            self.lookup.cancel()
        if self.actor_id and self.presenter.uncertain:
            self.suspended[self.actor_id] = self.presenter.uncertain
        self.presenter.reset()
        self.actor_id = user.id if user else None
        self.permissions = set(user.global_permissions if user else [])
        self.warehouses = list(warehouses or [])
        self.warehouse_selector.configure(values=[f"{row.code} · {row.name}" for row in self.warehouses])
        self.warehouse.set("")
        if self.warehouses:
            self.warehouse_selector.current(0)
        pending = self.suspended.pop(self.actor_id, None)
        if pending:
            resource, record_id, body, _ = pending
            self.mode.set(self.modes[self.resources.index(resource)])
            self.rebuild()
            self.presenter.uncertain = pending
            for field, variable in self.variables.items():
                value = body.get(field, "")
                variable.set("Có" if value is True else "Không" if value is False else str(value))
            self.status.set("Yêu cầu trước chưa rõ kết quả. Gửi lại nguyên yêu cầu để xác nhận.")
        self.enable()

    def switch(self, event=None):
        self.presenter.reset()
        self.rebuild()

    def rebuild(self):
        self.variables.clear()
        self.inputs.clear()
        self.labels.clear()
        for child in self.form.winfo_children():
            child.destroy()
        specs = {
            "product-uoms": [("uom_id", "Đơn vị quy đổi"), ("factor", "Hệ số chính xác"), ("reason", "Lý do")],
            "barcodes": [("code", "Barcode (giữ số 0 đầu)"), ("product_uom_id", "Quy cách sản phẩm"),
                         ("is_active", "Đang dùng"), ("reason", "Lý do")],
            "prices": [("effective_on", "Ngày hiệu lực (YYYY-MM-DD)"), ("amount", "Giá tham chiếu"),
                       ("currency", "Tiền tệ (VD: VND)"), ("source", "Nguồn giá")],
        }
        for index, (field, label) in enumerate(specs[self.resource()]):
            ttk.Label(self.form, text=label).grid(row=index, column=0, sticky="w", pady=2)
            variable = self.variables[field] = tk.StringVar()
            if field == "is_active":
                widget = ttk.Combobox(self.form, textvariable=variable, state="readonly", values=["Có", "Không"])
            else:
                widget = ttk.Entry(self.form, textvariable=variable, width=55)
                if field.endswith("_id"):
                    widget.state(["readonly"])
            widget.grid(row=index, column=1, sticky="ew", padx=10, pady=2)
            self.inputs[field] = widget
            if field.endswith("_id"):
                button = ttk.Button(self.form, text="Tìm…", command=lambda f=field: self.choose_reference(f))
                button.grid(row=index, column=2)
                self.inputs[field + "_button"] = button
        self.new()

    def new(self):
        if self.presenter.uncertain or self.busy:
            return
        self.current, self.uom, self.conversion = None, None, None
        for field, variable in self.variables.items():
            variable.set("Có" if field == "is_active" else "VND" if field == "currency" else "")
        self.enable()

    def open_picker(self, path, callback, **options):
        if self.busy or self.presenter.uncertain:
            return
        self.lookup = CatalogLookup(self, path, callback, **options)
        self.lookup.load()

    def choose_product(self):
        self.open_picker("master/products", self.set_product, filters={"active": "true"})

    def set_product(self, row):
        self.product = row
        self.product_text.set(f"{row['sku']} · {row['name']} · version {row['version']}")
        self.clear_rows()
        self.new()

    def choose_reference(self, field):
        if field == "uom_id":
            self.open_picker("master/uoms", self.set_uom, filters={"active": "true"})
        elif self.product:
            self.open_picker("master/product-uoms", self.set_conversion,
                             filters={"product_id": self.product["id"], "active": "true"}, searchable=False)
        else:
            self.status.set("Chọn sản phẩm trước khi chọn quy cách cho barcode.")

    def set_uom(self, row):
        self.uom = row
        self.variables["uom_id"].set(reference_label(row))

    def set_conversion(self, row):
        self.conversion = row
        self.variables["product_uom_id"].set(reference_label(row))

    def scope_changed(self, event=None):
        self.presenter.sequence += 1
        self.busy = False
        self.clear_rows()
        self.enable()

    def load(self, next_page=False):
        if self.busy or self.presenter.uncertain:
            return
        resource = self.resource()
        if resource != "barcodes" and not self.product:
            self.status.set("Chọn sản phẩm trước khi tải dữ liệu.")
            return
        params = {"limit": 50}
        if next_page and self.next_after:
            params["after"] = self.next_after
        if resource == "barcodes":
            params["q"] = self.query.get()
            path = "master/barcodes"
        else:
            product = self.product["id"]
            path = "master/product-uoms"
            params["product_id"] = product
            if resource == "prices":
                index = self.warehouse_selector.current()
                if index < 0:
                    self.status.set("Chọn kho có quyền đọc giá.")
                    return
                path = "master/products/" + product + "/prices"
                params = {key: value for key, value in params.items() if key != "product_id"}
                params["warehouse_id"] = str(self.warehouses[index].id)
            # Refresh version at the same snapshot as the user explicitly reloads the list.
            def run():
                selected = self.presenter.api.get("master/products/" + product)
                result = self.presenter.api.get(path + "?" + urlencode(params))
                result["product"] = selected
                return result
            self.presenter.submit("page", run)
            return
        self.presenter.load_page(path, params)

    def select(self, event=None):
        selection = self.table.selection()
        if self.busy or self.presenter.uncertain or self.resource() != "barcodes" or not selection:
            return
        self.current = self.rows[selection[0]]
        for field, variable in self.variables.items():
            value = self.current.get(field, "")
            variable.set("Có" if value is True else "Không" if value is False else str(value))
        self.enable()

    def save(self):
        resource = self.resource()
        permission = "price.write" if resource == "prices" else "master.write"
        if self.busy or self.presenter.uncertain or permission not in self.permissions:
            return
        body = {field: variable.get().strip() for field, variable in self.variables.items()}
        record_id = None
        if resource != "barcodes" and not self.product:
            self.status.set("Chọn sản phẩm trước khi lưu.")
            return
        if resource == "product-uoms":
            if not self.uom:
                self.status.set("Chọn đơn vị quy đổi.")
                return
            body.update(product_id=self.product["id"], uom_id=self.uom["id"], expected_product_version=self.product["version"])
        elif resource == "barcodes":
            body["is_active"] = body["is_active"] == "Có"
            if self.current:
                record_id = self.current["id"]
                body.update(product_uom_id=self.current["product_uom_id"], expected_version=self.current["version"])
            elif self.conversion:
                body["product_uom_id"] = self.conversion["id"]
            else:
                self.status.set("Chọn quy cách sản phẩm cho barcode.")
                return
        else:
            body["product_id"] = self.product["id"]
        self.presenter.save(resource, record_id, body)

    def catalog_busy(self):
        self.busy = True
        self.status.set("Đang xử lý…")
        self.enable()
        if self.lookup:
            self.lookup.busy()

    def catalog_reference_loaded(self, result):
        self.busy = False
        if self.lookup:
            self.lookup.loaded(result)
        self.enable()

    def catalog_loaded(self, result, refs):
        self.busy = False
        self.clear_rows()
        self.rows = {row["id"]: row for row in result["items"]}
        self.next_after = result["next_after"]
        if "product" in result:
            self.product = result["product"]
            self.product_text.set(f"{self.product['sku']} · {self.product['name']} · version {self.product['version']}")
        for row in self.rows.values():
            if self.resource() == "product-uoms":
                values = (row["uom_id"], "× " + row["factor"], f"r{row['revision']} · " + ("Đang dùng" if row["is_active"] else "Ngừng dùng"))
            elif self.resource() == "prices":
                values = (row["effective_on"], row["amount"] + " " + row["currency"], row["source"])
            else:
                values = (row["code"], row["product_uom_id"], "Đang dùng" if row["is_active"] else "Ngừng dùng")
            self.table.insert("", "end", iid=row["id"], values=values)
        if self.current and self.resource() == "barcodes" and self.current["id"] in self.rows:
            self.table.selection_set(self.current["id"])
            self.select()
        self.status.set(f"Đã tải {len(self.rows)} bản ghi." + (" Barcode tìm trên toàn danh mục." if self.resource() == "barcodes" else ""))
        self.enable()

    def catalog_saved(self, result):
        self.busy = False
        self.clear_rows()
        if self.resource() == "barcodes":
            self.current = result
        elif self.resource() == "product-uoms":
            # The API increments the product version once; reload is needed before another revision.
            self.product = None
            self.product_text.set("Chọn lại sản phẩm để lấy version hiện tại.")
        self.status.set("Đã lưu. Tải lại để đọc dữ liệu với quyền hiện hành.")
        self.enable()

    def catalog_error(self, message, *, uncertain):
        self.busy = False
        self.status.set(message + (" Chưa rõ kết quả; gửi lại cùng yêu cầu." if uncertain else ""))
        if self.lookup:
            self.lookup.error(message)
        self.enable()

    def clear_rows(self):
        self.rows, self.next_after = {}, None
        self.table.delete(*self.table.get_children())

    def catalog_clear(self):
        self.busy = False
        self.clear_rows()
        self.product = self.uom = self.conversion = self.current = None
        self.product_text.set("")
        self.query.set("")
        self.status.set("Chọn sản phẩm để xem quy đổi / giá; barcode tìm theo mã.")
        for variable in self.variables.values():
            variable.set("")

    def enable(self):
        free = not self.busy and not self.presenter.uncertain
        readable = "master.read" in self.permissions
        writable = ("price.write" if self.resource() == "prices" else "master.write") in self.permissions
        for widget in (self.selector, self.product_button, self.load_button):
            widget.state(["!disabled"] if free and readable else ["disabled"])
        self.search.state(["!disabled"] if free and readable and self.resource() == "barcodes" else ["disabled"])
        self.warehouse_selector.state(["!disabled"] if free and self.resource() == "prices" else ["disabled"])
        self.next_button.state(["!disabled"] if free and readable and self.next_after else ["disabled"])
        for widget in (self.new_button, self.save_button, *self.inputs.values()):
            widget.state(["!disabled"] if free and writable else ["disabled"])
        if self.current and self.resource() == "barcodes":
            for field in ("code", "product_uom_id", "product_uom_id_button"):
                self.inputs[field].state(["disabled"])
        self.retry_button.state(["!disabled"] if self.presenter.uncertain and not self.busy else ["disabled"])

    def release_variables(self):
        if self.lookup:
            self.lookup.cancel()
        self.variables.clear()
        self.suspended.clear()
        self.mode = self.query = self.status = self.product_text = self.warehouse = None
