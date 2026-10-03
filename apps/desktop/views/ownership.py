import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from uuid import UUID

from apps.desktop.presenters.ownership import OwnershipPresenter
from apps.desktop.views.master_data import MasterDataView


class OwnershipCatalogView(MasterDataView):
    entities = {
        "Chủ hàng": ("stock-owners", "partner.write", "partner.write"),
        "Hợp đồng ký gửi": ("consignment-agreements", "partner.write", "partner.write"),
    }
    fields = {
        "stock-owners": ["code", "name", "partner_id", "is_active"],
        "consignment-agreements": ["code", "owner_id", "warehouse_id", "valid_from", "valid_until", "source_ref", "is_active"],
    }

    def save(self):
        if self.current and self.current.get("kind") in {"COMPANY", "UNCLASSIFIED"}:
            self.status.set("Chủ hàng hệ thống bất biến; chỉ sửa chủ hàng ký gửi.")
            return
        super().save()


class OwnershipStockView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=16)
        self.presenter = OwnershipPresenter(self, api)
        self.warehouses, self.busy = [], False
        self.warehouse, self.location, self.item, self.status, self.totals = (tk.StringVar() for _ in range(5))
        self.status.set("Chọn kho và định danh tồn để xem số lượng theo chủ sở hữu.")
        form = ttk.Frame(self)
        form.pack(fill="x")
        self.inputs = []
        for index, (label, variable) in enumerate((("Kho", self.warehouse), ("Vị trí (UUID)", self.location),
                                                    ("Danh tính tồn (stock_item UUID)", self.item))):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=5)
            if index == 0:
                entry = self.selector = ttk.Combobox(form, textvariable=variable, state="readonly", width=52)
                entry.bind("<<ComboboxSelected>>", self.scope_changed)
            else:
                entry = ttk.Entry(form, textvariable=variable, width=55)
                entry.bind("<Return>", lambda event: self.search())
            entry.grid(row=index, column=1, sticky="w", padx=10)
            self.inputs.append(entry)
        self.button = ttk.Button(form, text="Tra tồn theo chủ sở hữu", command=self.search)
        self.button.grid(row=3, column=1, sticky="w", padx=10, pady=10)
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(fill="x", pady=8)
        ttk.Label(self, textvariable=self.totals, wraplength=800).pack(fill="x", pady=8)
        self.table = ttk.Treeview(self, columns=("owner", "partner", "qty"), show="headings", height=8)
        for name, label, width in (("owner", "Chủ hàng ký gửi (ID)", 280), ("partner", "Nhà cung cấp (ID)", 280),
                                   ("qty", "Lượng đơn vị cơ sở", 170)):
            self.table.heading(name, text=label)
            self.table.column(name, width=width)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text="Số lượng thuộc cùng SKU/lô/serial tại vị trí đã chọn. Transit được tra riêng. "
                  "API hiện cần UUID vị trí và stock_item lấy từ kết quả nghiệp vụ; chưa có danh sách tồn để chọn.",
                  wraplength=800).pack(fill="x", pady=8)
        self.enable()

    def session_changed(self, user=None, warehouses=None):
        self.presenter.reset()
        self.warehouses = list(warehouses or []) if user else []
        self.selector.configure(values=[f"{row.code} · {row.name}" for row in self.warehouses])
        self.warehouse.set("")
        self.location.set("")
        self.item.set("")
        if self.warehouses:
            self.selector.current(0)
        self.status.set("Chọn kho và nhập định danh để tra tồn." if user else "Đăng nhập để tra tồn.")
        self.enable()

    def scope_changed(self, event=None):
        self.presenter.reset()
        self.location.set("")
        self.item.set("")
        self.status.set("Kho đã đổi; nhập lại vị trí và danh tính tồn.")
        self.enable()

    def search(self):
        if self.busy or self.selector.current() < 0:
            return
        try:
            location, item = UUID(self.location.get().strip()), UUID(self.item.get().strip())
        except ValueError:
            self.catalog_clear()
            self.status.set("Nhập UUID hợp lệ cho vị trí và danh tính tồn.")
            return
        self.presenter.search(self.warehouses[self.selector.current()].id, location, item)

    def catalog_busy(self):
        self.catalog_clear()
        self.busy = True
        self.status.set("Đang tra tồn…")
        self.enable()

    def catalog_clear(self):
        self.busy = False
        self.table.delete(*self.table.get_children())
        self.totals.set("")

    def catalog_loaded(self, result, refs):
        self.busy = False
        consigned = sum((Decimal(row.quantity_base) for row in result.consigned_by_owner), Decimal(0))
        self.totals.set(f"Vật lý: {result.physical_base} · Doanh nghiệp: {result.owned_base} · "
                        f"Ký gửi: {consigned:.6f} · Chưa phân loại: {result.unclassified_base}")
        for row in result.consigned_by_owner:
            self.table.insert("", "end", values=(str(row.owner_id), str(row.owner_partner_id), row.quantity_base))
        self.status.set(f"Số liệu tại {result.as_of.isoformat()} · đơn vị cơ sở của sản phẩm.")
        self.enable()

    def catalog_error(self, message, *, uncertain):
        self.catalog_clear()
        self.status.set(message)
        self.enable()

    def enable(self):
        for widget in (*self.inputs, self.button):
            widget.state(["!disabled"] if self.warehouses and not self.busy else ["disabled"])

    def release_variables(self):
        self.warehouse = self.location = self.item = self.status = self.totals = None


class OwnershipView(ttk.Notebook):
    def __init__(self, parent, api):
        super().__init__(parent)
        self.catalog = OwnershipCatalogView(self, api)
        self.stock = OwnershipStockView(self, api)
        self.add(self.catalog, text="Chủ hàng / hợp đồng")
        self.add(self.stock, text="Tồn theo chủ sở hữu")

    def session_changed(self, user=None, warehouses=None):
        self.catalog.session_changed(user)
        self.stock.session_changed(user, warehouses)

    def drain(self):
        for view in (self.catalog, self.stock):
            view.presenter.drain()

    def close(self):
        for view in (self.catalog, self.stock):
            view.presenter.close()
            view.release_variables()

    def finish(self):
        for view in (self.catalog, self.stock):
            view.presenter.finish()
