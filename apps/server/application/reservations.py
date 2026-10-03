"""ISSUE allocations. Callers lock the source SO and ISSUE before these DB helpers.

All allocations are COMPANY stock; quantities are in the product's base UOM.
The same location/product/balance/reservation lock order is required by future
picking, transfer, returns and expiry adapters. No Python mutex protects stock.
"""

from collections import defaultdict
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.master_data import active_reference, invalid, one
from apps.server.application.orders import amount
from apps.server.domain.errors import DomainError
from packages.contracts.issues import AllocationView, ReservationView
from packages.contracts.traceability import COMPANY_OWNER


class ReservationService:
    def __init__(self, issues):
        self.issues = issues
        self.identity = issues.identity

    def today(self):
        return self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()

    def rows(self, c, doc_id, *, lock=False):
        return [dict(r) for r in c.execute(text("""SELECT r.*,l.product_id,l.source_line_id,l.owner_id,
            l.consignment_id,l.document_id FROM wms.reservation r
            JOIN wms.document_line l ON l.id=r.line_id WHERE l.document_id=:doc ORDER BY r.id
            """ + ("FOR UPDATE OF r" if lock else "")), {"doc": doc_id}).mappings()]

    def view(self, c, doc_id):
        rows = c.execute(text("""SELECT r.*,r.line_id AS document_line_id,l.code AS location_code,
            i.owner_id,p.sku,lot.code AS lot_code,s.code AS serial_code
            FROM wms.reservation r JOIN wms.document_line dl ON dl.id=r.line_id
            JOIN wms.stock_item i ON i.id=r.stock_item_id JOIN wms.product p ON p.id=i.product_id
            JOIN wms.location l ON l.id=r.location_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
            LEFT JOIN wms.serial s ON s.id=i.serial_id
            WHERE dl.document_id=:id ORDER BY dl.line_no,lot.expires_on NULLS LAST,r.id"""),
            {"id": doc_id}).mappings()
        return [ReservationView(
            **{k: r[k] for k in ("id", "document_line_id", "stock_item_id", "location_id", "location_code",
                                 "owner_id", "sku", "lot_code", "serial_code", "expires_at")},
            **{k: amount(r[k]) for k in ("quantity", "consumed", "released")},
            remaining_base=amount(self.remaining(r)),
            expired=r["expires_at"] is not None and r["expires_at"] <= self.identity.clock(),
        ) for r in rows]

    @staticmethod
    def remaining(row):
        return row["quantity"] - row["consumed"] - row["released"]

    def inventory(self, c, doc, lines, *, allocate=False, reservations=(), lock=True):
        """Lock locations before products/identities/balances. Returns a coherent pool.

        Allocating locks STORAGE locations in the warehouse, including empty bins,
        so an inbound move into an existing bin shares the same lock boundary.
        Reads for a proposal are advisory; reserve repeats this under row locks.
        """
        if lock:
            c.execute(text("SELECT id FROM wms.warehouse WHERE id=:id FOR SHARE"), {"id": doc["warehouse_id"]})
        location_ids = {r["location_id"] for r in reservations}
        if allocate:
            location_ids.update(c.execute(text("SELECT id FROM wms.location WHERE warehouse_id=:wh AND kind='STORAGE'"),
                                          {"wh": doc["warehouse_id"]}).scalars())
        locations = {}
        for loc in sorted(location_ids):
            locations[loc] = one(c, "SELECT * FROM wms.location WHERE id=:id" + (" FOR UPDATE" if lock else ""), id=loc)
        products = sorted({line["product_id"] for line in lines})
        if lock:
            for product in products:
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product})
            # Stock identities are immutable; use the established product-first lock barrier.
            c.execute(text("SELECT id FROM wms.stock_item WHERE product_id=ANY(:products) ORDER BY id FOR UPDATE"),
                      {"products": products})
            c.execute(text("""SELECT b.id FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
                WHERE i.product_id=ANY(:products) AND b.location_id=ANY(:locations)
                ORDER BY b.location_id,b.stock_item_id FOR UPDATE OF b"""),
                {"products": products, "locations": sorted(location_ids)})
        rows = [dict(r) for r in c.execute(text("""SELECT b.*,i.product_id,i.owner_id,i.consignment_id,
            i.lot_id,i.serial_id,p.sku,p.tracking,p.expiry_required,p.is_active AS product_active,p.base_uom_id,
            u.decimal_places,u.is_active AS unit_active,lot.code AS lot_code,lot.expires_on,
            lot.product_id AS lot_product,s.code AS serial_code,s.product_id AS serial_product,
            pos.location_id AS serial_location,l.code AS location_code,l.is_active AS location_active,
            l.kind AS location_kind,l.warehouse_id,
            EXISTS(SELECT 1 FROM wms.count_location_lock cl WHERE cl.location_id=l.id AND cl.released_at IS NULL) AS frozen,
            COALESCE((SELECT sum(r.quantity-r.consumed-r.released) FROM wms.reservation r
                WHERE r.stock_item_id=b.stock_item_id AND r.location_id=b.location_id),0) AS actual_reserved
            FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
            JOIN wms.product p ON p.id=i.product_id JOIN wms.uom u ON u.id=p.base_uom_id
            JOIN wms.location l ON l.id=b.location_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
            LEFT JOIN wms.serial s ON s.id=i.serial_id LEFT JOIN wms.serial_position pos ON pos.serial_id=i.serial_id
            WHERE i.product_id=ANY(:products) AND b.location_id=ANY(:locations)
            ORDER BY lot.expires_on NULLS LAST,i.id,b.location_id"""),
            {"products": products, "locations": sorted(location_ids)}).mappings()]
        if lock and any(r["reserved"] != r["actual_reserved"] for r in rows):
            raise DomainError("BALANCE_CONFLICT", "Số giữ chỗ không khớp chi tiết; cần đối soát trước thao tác.")
        return {(r["stock_item_id"], r["location_id"]): r for r in rows}

    def eligible(self, row, warehouse_id):
        if row["owner_id"] != COMPANY_OWNER or row["consignment_id"] is not None:
            return False
        if not (row["product_active"] and row["unit_active"] and row["location_active"]):
            return False
        if row["warehouse_id"] != warehouse_id or row["location_kind"] != "STORAGE" or row["frozen"]:
            return False
        if row["expires_on"] is not None and row["expires_on"] < self.today():
            return False
        if row["expiry_required"] and row["expires_on"] is None:
            return False
        if row["tracking"] == "NONE":
            return row["lot_id"] is None and row["serial_id"] is None
        if row["tracking"] == "LOT":
            return row["lot_product"] == row["product_id"] and row["serial_id"] is None
        return (row["tracking"] == "SERIAL" and row["serial_product"] == row["product_id"]
                and row["lot_id"] is None and row["serial_location"] == row["location_id"] and row["on_hand"] == 1)

    def quantity(self, c, line, qty):
        product = active_reference(c, "product", line["product_id"], "product_id")
        unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
        if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
            invalid("quantity_base", "Lượng phải đúng độ chính xác đơn vị cơ sở.")
        if product["tracking"] == "SERIAL" and qty != qty.to_integral_value():
            invalid("quantity_base", "Hàng serial cần lượng nguyên.")

    def plan(self, c, doc, source, totals, inventory):
        saved = {r["id"]: r for r in self.issues.orders.lines(c, doc)}
        parents = {r["id"]: r for r in self.issues.orders.lines(c, source)}
        held = defaultdict(Decimal)
        for r in self.rows(c, doc["id"]):
            held[r["line_id"]] += self.remaining(r)
        source_held = dict(c.execute(text("""SELECT coalesce(l.source_line_id,l.id),sum(r.quantity-r.consumed-r.released)
            FROM wms.reservation r JOIN wms.document_line l ON l.id=r.line_id
            WHERE l.document_id=:source OR l.source_line_id IN (SELECT id FROM wms.document_line WHERE document_id=:source)
            GROUP BY coalesce(l.source_line_id,l.id)"""), {"source": source["id"]}).all())
        free = {key: r["on_hand"] - r["reserved"] for key, r in inventory.items()}
        plan = []
        for line_id, qty in sorted(totals.items()):
            line = saved.get(line_id)
            if not line:
                invalid("document_line_id", "Dòng giữ hàng không thuộc phiếu xuất.")
            parent = parents.get(line["source_line_id"])
            self.issues.match_source(line, parent)
            self.quantity(c, line, qty)
            if qty > Decimal(line["remaining_base"]) - held[line_id]:
                raise DomainError("ISSUE_EXCEEDED", "Giữ vượt phần còn lại chưa giữ của dòng xuất.")
            if qty > Decimal(parent["remaining_base"]) - source_held.get(parent["id"], Decimal(0)):
                raise DomainError("SOURCE_EXCEEDED", "SO không còn đủ nhu cầu chưa giữ.")
            left = qty
            for pair, row in inventory.items():
                if row["product_id"] != line["product_id"] or not self.eligible(row, doc["warehouse_id"]):
                    continue
                take = min(free[pair], left)
                if take <= 0:
                    continue
                if row["tracking"] == "SERIAL" and take != 1:
                    raise DomainError("BALANCE_CONFLICT", "Số dư serial không hợp lệ.")
                plan.append(AllocationView(
                    document_line_id=line_id, stock_item_id=pair[0], location_id=pair[1], quantity_base=amount(take),
                    **{k: row[k] for k in ("sku", "location_code", "owner_id", "lot_code", "serial_code", "expires_on")},
                ))
                free[pair] -= take
                left -= take
                if left == 0:
                    break
            if left:
                raise DomainError("INSUFFICIENT_STOCK", f"Chỉ còn {amount(qty-left)} đơn vị cơ sở hợp lệ cho dòng này. Chọn lượng giữ nhỏ hơn để giữ từng phần.")
            source_held[parent["id"]] = source_held.get(parent["id"], Decimal(0)) + qty
        if len(plan) > 500:
            raise DomainError("ALLOCATION_LIMIT", "Lượt giữ cần quá nhiều nguồn; chia thành các lượt nhỏ hơn.")
        return plan

    def reserve(self, auth, doc, source, payload):
        c = auth.connection
        if payload.expires_at is not None and payload.expires_at <= self.identity.clock():
            invalid("expires_at", "Hạn giữ chỗ phải sau thời điểm hiện tại.")
        totals = defaultdict(Decimal)
        requested = {}
        for spec in payload.lines:
            totals[spec.document_line_id] += Decimal(spec.quantity_base)
            requested[(spec.document_line_id, spec.stock_item_id, spec.location_id)] = Decimal(spec.quantity_base)
        lines = self.issues.orders.lines(c, doc)
        inventory = self.inventory(c, doc, lines, allocate=True)
        plan = self.plan(c, doc, source, totals, inventory)
        expected = {(p.document_line_id, p.stock_item_id, p.location_id): Decimal(p.quantity_base) for p in plan}
        if requested != expected:
            raise DomainError("FEFO_CHANGED", "Nguồn giữ không còn khớp FEFO/khả dụng; tải lại đề xuất và xác nhận.")
        for spec in plan:
            c.execute(text("""INSERT INTO wms.reservation
                (id,line_id,stock_item_id,location_id,quantity,consumed,released,expires_at,created_by)
                VALUES (:id,:line,:stock,:location,:qty,0,0,:expiry,:actor)"""),
                {"id": uuid4(), "line": spec.document_line_id, "stock": spec.stock_item_id,
                 "location": spec.location_id, "qty": Decimal(spec.quantity_base), "expiry": payload.expires_at,
                 "actor": auth.principal.user_id})
            c.execute(text("""UPDATE wms.stock_balance SET reserved=reserved+:qty,version=version+1
                WHERE stock_item_id=:stock AND location_id=:location"""),
                {"stock": spec.stock_item_id, "location": spec.location_id, "qty": Decimal(spec.quantity_base)})

    def release(self, c, doc, quantities=None, *, expired_only=False):
        old = self.rows(c, doc["id"])
        lines = self.issues.orders.lines(c, doc)
        inventory = self.inventory(c, doc, lines, reservations=old)
        rows = {r["id"]: r for r in self.rows(c, doc["id"], lock=True)}
        if quantities is None:
            quantities = {r["id"]: self.remaining(r) for r in rows.values() if self.remaining(r) > 0
                          and (not expired_only or r["expires_at"] is not None
                               and r["expires_at"] <= self.identity.clock())}
        for reservation_id, qty in quantities.items():
            row = rows.get(reservation_id)
            if not row or qty > self.remaining(row):
                raise DomainError("RESERVATION_MISMATCH", "Giữ chỗ không thuộc phiếu hoặc không đủ lượng còn lại.")
            self.check_fulfillment(c, reservation_id)
            balance = inventory.get((row["stock_item_id"], row["location_id"]))
            if not balance or balance["reserved"] < qty:
                raise DomainError("BALANCE_CONFLICT", "Không tìm thấy số dư giữ chỗ hợp lệ.")
            if qty != qty.quantize(Decimal(1).scaleb(-balance["decimal_places"])) or (balance["tracking"] == "SERIAL" and qty != 1):
                invalid("quantity_base", "Lượng giải phóng không đúng UOM/serial.")
            c.execute(text("UPDATE wms.reservation SET released=released+:qty WHERE id=:id"),
                      {"qty": qty, "id": reservation_id})
            c.execute(text("""UPDATE wms.stock_balance SET reserved=reserved-:qty,version=version+1
                WHERE stock_item_id=:stock AND location_id=:location"""),
                {"qty": qty, "stock": row["stock_item_id"], "location": row["location_id"]})
            balance["reserved"] -= qty
        return quantities

    @staticmethod
    def check_fulfillment(c, reservation_id):
        if one(c, "SELECT id FROM wms.pick_task WHERE reservation_id=:id AND status<>'CANCELLED' LIMIT 1",
               id=reservation_id):
            raise DomainError("FULFILLMENT_ACTIVE", "Cần xử lý nhiệm vụ soạn hàng trước khi thay giữ chỗ.")
