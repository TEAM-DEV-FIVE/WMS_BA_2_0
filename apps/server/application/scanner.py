"""Exact HID lookup bounded to the currently authorized document/count. Read only."""

from decimal import Decimal

from sqlalchemy import text

from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError, require_version


def resolve(service, auth, payload):
    c = auth.connection
    code = payload.code
    qty = Decimal(payload.quantity)
    if payload.flow == "COUNT":
        row = service.counting.session(auth, payload.source_id)
        auth.require("count.enter", row["warehouse_id"])
        view = service.counting.read(auth, payload.source_id)
        lines = []
        for line in view["lines"]:
            if not line["can_count"]:
                continue
            stock = one(c, "SELECT product_id FROM wms.stock_item WHERE id=:id", id=line["stock_item_id"])
            lines.append({**line, "product_id": stock["product_id"]})
    else:
        kind = "ISSUE" if payload.flow == "PICK" else payload.flow
        row = (
            service.orders.transfers.document(auth, payload.source_id)
            if payload.flow == "TRANSFER"
            else service.orders.document(auth, payload.source_id, kind)
        )
        permission = {
            "PICK": "pick.confirm",
            "RECEIPT": "receipt.post",
            "ISSUE": "issue.post",
            "TRANSFER": "transfer.dispatch",
        }[payload.flow]
        # Existing document visibility remains mandatory; do not broaden picker assignments.
        if payload.flow == "PICK":
            service.orders.issues.may_handle(auth, row, "pick.confirm")
        elif payload.flow == "TRANSFER" and row["status"] in {"PARTIAL", "COMPLETED"}:
            auth.require("transfer.receive", row["destination_warehouse_id"])
        else:
            auth.require(permission, row["warehouse_id"])
        lines = service.orders.lines(c, row)
        if payload.flow == "PICK":
            assigned = set(
                c.execute(
                    text("""SELECT r.line_id FROM wms.pick_task t
                JOIN wms.reservation r ON r.id=t.reservation_id WHERE t.assigned_to=:actor
                AND t.status IN ('OPEN','PICKING')"""),
                    dict(actor=auth.principal.user_id),
                ).scalars()
            )
            lines = [line for line in lines if line["id"] in assigned]
        if payload.flow == "TRANSFER" and row["status"] in {"PARTIAL", "COMPLETED"}:
            sources = service.orders.transfers.sources(c, row["id"])
            for line in lines:
                line["remaining_base"] = str(
                    sum(
                        (
                            service.orders.transfers.remaining(s)
                            for s in sources
                            if s["document_line_id"] == line["id"]
                        ),
                        Decimal(0),
                    )
                )
        if payload.flow == "RECEIPT":
            for line in lines:
                spec = row["attributes"].get("receipt_plan", {}).get("lines", {}).get(str(line["id"]), {})
                line.update(serial_code=spec.get("serial_code"), lot_code=spec.get("lot_code"))
        else:
            for line in lines:
                traces = (
                    c.execute(
                        text("""SELECT DISTINCT s.code FROM wms.stock_item i JOIN wms.serial s ON s.id=i.serial_id
                    WHERE i.id IN (SELECT stock_item_id FROM wms.reservation WHERE line_id=:line
                    UNION SELECT stock_item_id FROM wms.transfer_line WHERE document_line_id=:line)"""),
                        dict(line=line["id"]),
                    )
                    .scalars()
                    .all()
                )
                line["serial_codes"] = traces
    require_version(row["version"], payload.expected_version)
    barcode = one(
        c,
        """SELECT pu.product_id,pu.factor FROM wms.barcode b JOIN wms.product_uom pu
        ON pu.id=b.product_uom_id AND pu.is_active JOIN wms.product p ON p.id=pu.product_id AND p.is_active
        WHERE b.code=:code AND b.is_active""",
        code=code,
    )
    matched = []
    for line in lines:
        serial = code == line.get("serial_code") or code in line.get("serial_codes", [])
        product_match = code == line["sku"] or (barcode and barcode["product_id"] == line["product_id"])
        if not serial and not product_match:
            continue
        factor = (
            barcode["factor"]
            if barcode and barcode["product_id"] == line["product_id"] and not serial
            else Decimal(1)
        )
        base = qty * factor
        unit = one(
            c,
            """SELECT u.decimal_places FROM wms.product p JOIN wms.uom u ON u.id=p.base_uom_id
                      WHERE p.id=:id""",
            id=line["product_id"],
        )
        if (
            base < 0
            or (base == 0 and payload.flow != "COUNT")
            or base != base.quantize(Decimal(1).scaleb(-unit["decimal_places"]))
            or (
                line["tracking"] == "SERIAL"
                and (base not in ({0, 1} if payload.flow == "COUNT" else {1}) or not serial)
            )
        ):
            raise DomainError(
                "INVALID_QUANTITY",
                "Kiểm tra ĐVT; hàng serial cần quét đúng serial và lượng 1 (kiểm kê: 0/1).",
            )
        if payload.flow != "COUNT" and base > Decimal(line["remaining_base"]):
            raise DomainError("OVER_QUANTITY", "Lượng quét vượt lượng còn lại trên phiếu.")
        item = dict(
            line_id=str(line["id"]),
            sku=line["sku"],
            quantity_base=format(base, "f"),
            serial_code=code if serial else None,
            location_code=line.get("location_code"),
        )
        if payload.flow == "PICK":
            tasks = (
                c.execute(
                    text("""SELECT t.id,t.target_quantity-t.picked_quantity AS remaining,s.code AS serial_code
                FROM wms.pick_task t JOIN wms.reservation r ON r.id=t.reservation_id
                JOIN wms.stock_item i ON i.id=r.stock_item_id LEFT JOIN wms.serial s ON s.id=i.serial_id
                WHERE r.line_id=:line AND t.assigned_to=:actor AND t.status IN ('OPEN','PICKING')"""),
                    dict(line=line["id"], actor=auth.principal.user_id),
                )
                .mappings()
                .all()
            )
            eligible = [
                t
                for t in tasks
                if t["remaining"] is not None
                and base <= t["remaining"]
                and (not serial or t["serial_code"] == code)
            ]
            if not eligible:
                raise DomainError("OVER_QUANTITY", "Lượng quét vượt phần còn được giao soạn.")
            matched.extend({**item, "task_id": str(t["id"])} for t in eligible)
        else:
            matched.append(item)
    if not matched:
        raise DomainError("SCAN_NOT_FOUND", "Không tìm thấy mã chính xác trong phiếu/phân công hiện tại.")
    return dict(source_id=str(payload.source_id), version=row["version"], matches=matched)
