"""Explicit print projection: no raw attributes, prices or private custom fields."""

from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError, require_version

TITLES = {
    "RECEIPT": "PHIẾU NHẬP KHO",
    "ISSUE": "PHIẾU XUẤT KHO",
    "TRANSFER": "PHIẾU CHUYỂN KHO",
    "COUNT": "PHIẾU KIỂM KÊ",
    "PRODUCT_LABEL": "TEM HÀNG / SERIAL",
    "LOCATION_LABEL": "TEM VỊ TRÍ",
}


def source(service, auth, criteria, *, capture=False):
    c, template, source_id = auth.connection, criteria.template, criteria.source_id
    warehouse = criteria.warehouse_id
    auth.require("print.execute", warehouse)
    if template in {"RECEIPT", "ISSUE", "TRANSFER"}:
        row = service.orders.document(auth, source_id, template)
        if row["warehouse_id"] != warehouse:
            raise DomainError("NOT_FOUND", "Chứng từ không thuộc kho chọn.")
        for wh in {warehouse, row["destination_warehouse_id"]} - {None}:
            auth.require("print.execute", wh)
            if criteria.include_price:
                auth.require("price.read", wh)
        if not capture:
            return row
        view = service.orders.read(auth, source_id).model_dump(mode="json")
        lines = []
        for line in view["lines"]:
            item = {
                k: line.get(k)
                for k in (
                    "sku",
                    "product_name",
                    "quantity",
                    "uom_code",
                    "base_quantity",
                    "base_uom_code",
                    "posted_base",
                    "owner_code",
                )
            }
            if criteria.include_price:
                item["reference_unit_price"] = one(
                    c, "SELECT reference_unit_price FROM wms.document_line WHERE id=:id", id=line["id"]
                )["reference_unit_price"]
            if template == "RECEIPT":
                plan = row["attributes"].get("receipt_plan", {}).get("lines", {}).get(str(line["id"]), {})
                item["trace"] = plan.get("serial_code") or plan.get("lot_code") or ""
                if plan.get("destination_location_id"):
                    item["location"] = one(
                        c, "SELECT code FROM wms.location WHERE id=:id", id=plan["destination_location_id"]
                    )["code"]
            elif template == "TRANSFER":
                trace = one(
                    c,
                    """SELECT COALESCE(s.code,lot.code,'') AS trace,loc.code AS location
                    FROM wms.transfer_line t JOIN wms.stock_item i ON i.id=t.stock_item_id
                    JOIN wms.location loc ON loc.id=t.source_location_id LEFT JOIN wms.serial s ON s.id=i.serial_id
                    LEFT JOIN wms.lot lot ON lot.id=i.lot_id WHERE t.document_line_id=:id""",
                    id=line["id"],
                )
                if trace:
                    item.update(dict(trace))
            lines.append(item)
        header = {k: view.get(k) for k in ("number", "kind", "status", "business_date", "partner_name")}
        if row["destination_warehouse_id"]:
            header["destination"] = one(
                c, "SELECT code,name FROM wms.warehouse WHERE id=:id", id=row["destination_warehouse_id"]
            )["name"]
    elif template == "COUNT":
        row = service.counting.session(auth, source_id)
        if row["warehouse_id"] != warehouse:
            raise DomainError("NOT_FOUND", "Phiên không thuộc kho chọn.")
        # Always blind paper, including for controllers; never snapshot or previous counts.
        if not capture:
            return row
        view = service.counting.read(auth, source_id)
        header = {k: view.get(k) for k in ("number", "status", "business_date")}
        lines = [
            {k: line.get(k) for k in ("sku", "owner_code", "lot_code", "serial_code", "location_code")}
            for line in view["lines"]
        ]
    else:
        auth.require("master.read")
        if template == "LOCATION_LABEL":
            row = one(
                c,
                "SELECT * FROM wms.location WHERE id=:id AND warehouse_id=:wh AND is_active",
                id=source_id,
                wh=warehouse,
            )
            if not row:
                raise DomainError("NOT_FOUND", "Không tìm thấy vị trí.")
            header = dict(number=row["code"], name=row["name"], barcode=row["code"], symbology="QR")
        else:
            row = one(c, "SELECT * FROM wms.product WHERE id=:id AND is_active", id=source_id)
            if not row:
                raise DomainError("NOT_FOUND", "Không tìm thấy mặt hàng.")
            header = dict(number=row["sku"], name=row["name"], barcode=row["sku"], symbology="Code128")
            if criteria.serial_id:
                serial = service.traceability.visible_serial(auth, criteria.serial_id, warehouse)
                if serial["product_id"] != source_id:
                    raise DomainError("NOT_FOUND", "Serial không thuộc mặt hàng.")
                header.update(serial_code=serial["code"], barcode=serial["code"], symbology="QR")
        if not capture:
            return row
        lines = []
    require_version(row["version"], criteria.expected_version)
    if len(lines) > 1000:
        raise DomainError("PRINT_LIMIT", "Tối đa 1.000 dòng trong bản in.")
    wh = one(c, "SELECT code,name FROM wms.warehouse WHERE id=:id", id=warehouse)
    header.update(warehouse=wh["name"], warehouse_code=wh["code"])
    return dict(
        template=template,
        template_version=1,
        paper=criteria.paper,
        header=header,
        lines=lines,
        source_id=str(source_id),
        source_version=row["version"],
        include_price=criteria.include_price,
    )


def current_snapshot_scope(service, auth, job):
    from packages.contracts.printing import PrintCreate

    criteria = PrintCreate.model_validate(job["criteria"])
    source(service, auth, criteria)
    if criteria.template == "COUNT":
        # Assignments can narrow after capture. Recheck every printed location on each access.
        row = service.counting.session(auth, criteria.source_id)
        if not service.counting.can_review(auth, row):
            for line in job["snapshot"]["lines"]:
                location = one(
                    auth.connection,
                    "SELECT id FROM wms.location WHERE warehouse_id=:wh AND code=:code",
                    wh=criteria.warehouse_id,
                    code=line["location_code"],
                )
                if not location or not service.counting.assigned(auth, row, location["id"]):
                    raise DomainError("FORBIDDEN", "Phân công kiểm kê đã thay đổi.")
