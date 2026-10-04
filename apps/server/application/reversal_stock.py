"""Exact inverse stock legs. The caller owns source/document locks and the UoW.

Unallocated NONE/LOT stock has no per-unit provenance. Conservatively reject an
effective depletion from an original destination; refilling a bin is not proof
that the original goods remain there. Cancelled inverse pairs do not deplete it.
"""
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.master_data import one
from apps.server.application.move_safety import check_reservations, location_tree
from apps.server.application.orders import amount
from apps.server.domain.errors import DomainError
from packages.contracts.traceability import COMPANY_OWNER

CACHED = {"STORAGE", "RECEIVING", "QUARANTINE", "SHIPPING", "TRANSIT"}
COUNTERPART = {"EXTERNAL", "LOSS", "OPENING"}
MOVE_SQL = """SELECT m.id AS source_move_id,m.stock_item_id,m.quantity_base,m.base_uom_id,
    i.product_id,i.owner_id,i.consignment_id,i.lot_id,i.serial_id,p.sku,p.tracking,
    p.base_uom_id AS current_uom,p.is_active AS product_active,u.decimal_places,
    o.code AS owner_code,lot.code AS lot_code,lot.expires_on,s.code AS serial_code,
    m.destination_location_id AS source_location_id,src.code AS source_code,src.kind AS source_kind,
    m.source_location_id AS destination_location_id,dst.code AS destination_code,dst.kind AS destination_kind,
    src.warehouse_id AS source_warehouse,dst.warehouse_id AS destination_warehouse,
    l.product_id AS line_product,l.owner_id AS line_owner,l.consignment_id AS line_agreement,l.id AS original_line_id
    FROM wms.stock_move m JOIN wms.stock_item i ON i.id=m.stock_item_id
    JOIN wms.product p ON p.id=i.product_id JOIN wms.uom u ON u.id=m.base_uom_id
    JOIN wms.stock_owner o ON o.id=i.owner_id JOIN wms.document_line l ON l.id=m.line_id
    JOIN wms.location src ON src.id=m.destination_location_id JOIN wms.location dst ON dst.id=m.source_location_id
    LEFT JOIN wms.lot lot ON lot.id=i.lot_id LEFT JOIN wms.serial s ON s.id=i.serial_id
    WHERE m.transaction_id=:id ORDER BY m.id"""


def moves(c, tx_id):
    return [dict(r) for r in c.execute(text(MOVE_SQL), {"id": tx_id}).mappings()]


def effects(c, rows):
    deltas, names = defaultdict(Decimal), {}
    for r in rows:
        for side, sign in (("source", -1), ("destination", 1)):
            if r[side + "_kind"] in CACHED:
                pair = r["stock_item_id"], r[side + "_location_id"]
                deltas[pair] += sign * r["quantity_base"]
                names[pair] = r[side + "_code"]
    result = []
    for (stock, loc), delta in sorted(deltas.items(), key=lambda x: (x[0][1], x[0][0])):
        b = one(c, "SELECT on_hand,reserved FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:loc", stock=stock, loc=loc)
        on_hand, reserved = (b["on_hand"], b["reserved"]) if b else (Decimal(0), Decimal(0))
        result.append(dict(stock_item_id=stock, location_id=loc, location_code=names[stock, loc],
            on_hand=amount(on_hand), reserved=amount(reserved), delta=amount(delta), projected_on_hand=amount(on_hand + delta)))
    return result


def validate_route(c, warehouses, original_day, day, rows, *, lock=False):
    if day < original_day:
        raise DomainError("INVALID_DATE", "Ngày đảo không được trước ngày ghi sổ gốc.")
    for warehouse in sorted(warehouses):
        wh = one(c, "SELECT * FROM wms.warehouse WHERE id=:id" + (" FOR SHARE" if lock else ""), id=warehouse)
        if not wh or not wh["is_active"]:
            raise DomainError("INVALID_WAREHOUSE", "Kho không còn hoạt động.")
    periods = c.execute(text("""SELECT * FROM wms.stock_period WHERE warehouse_id=ANY(:warehouses)
        AND ((:original BETWEEN starts_on AND ends_on) OR (:day BETWEEN starts_on AND ends_on))
        ORDER BY id""" + (" FOR UPDATE" if lock else "")),
        dict(warehouses=sorted(warehouses), original=original_day, day=day)).mappings().all()
    for warehouse in warehouses:
        for required_day in {original_day, day}:
            matching = [p for p in periods if p["warehouse_id"] == warehouse and p["starts_on"] <= required_day <= p["ends_on"]]
            if len(matching) != 1 or matching[0]["status"] != "OPEN":
                raise DomainError("PERIOD_CLOSED", "Kỳ gốc và kỳ ghi đảo tại các kho liên quan phải đang mở.")
    endpoints = {r[side + "_location_id"] for r in rows for side in ("source", "destination")}
    all_ids = set(endpoints)
    for target in endpoints:
        current, visited = target, set()
        while current:
            if current in visited or len(visited) > 10:
                raise DomainError("INVALID_TREE", "Cây vị trí có chu kỳ hoặc quá sâu.")
            visited.add(current)
            row = one(c, "SELECT * FROM wms.location WHERE id=:id", id=current)
            if not row:
                raise DomainError("INVALID_LOCATION", "Thiếu vị trí nguồn/đích.")
            all_ids.add(current)
            current = row["parent_id"]
    if lock:
        c.execute(text("SELECT id FROM wms.location WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"), {"ids": sorted(all_ids)})
    physical = defaultdict(set)
    for target in endpoints:
        row = one(c, "SELECT * FROM wms.location WHERE id=:id", id=target)
        if not row["is_active"] or row["kind"] not in CACHED | COUNTERPART:
            raise DomainError("INVALID_LOCATION", "Vị trí không hoạt động hoặc không cho ghi sổ.")
        if row["kind"] in CACHED - {"TRANSIT"}:
            if row["warehouse_id"] not in warehouses:
                raise DomainError("SOURCE_MISMATCH", "Vị trí không thuộc kho của giao dịch gốc.")
            physical[row["warehouse_id"]].add(target)
        elif row["warehouse_id"] or row["parent_id"]:
            raise DomainError("INVALID_LOCATION", "Đối ứng hoặc transit phải là vị trí hệ thống.")
        if one(c, "SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL", id=target):
            raise DomainError("LOCATION_FROZEN", "Vị trí đang khóa kiểm kê; đảo không được bỏ qua khóa.")
        current, visited = row["parent_id"], {target}
        while current:
            if current not in all_ids or current in visited or len(visited) > 10:
                raise DomainError("INVALID_TREE", "Cây vị trí đã thay đổi; tải lại trước khi đảo.")
            visited.add(current)
            current = one(c, "SELECT parent_id FROM wms.location WHERE id=:id", id=current)["parent_id"]
    for warehouse, ids in physical.items():
        location_tree(c, warehouse, ids, allow_shipping=True)


def validate_downstream(c, tx, rows):
    source_ids = [r["source_move_id"] for r in rows]
    # Decision evidence has no cancellation workflow: never silently discard it.
    if one(c, "SELECT id FROM wms.quality_decision WHERE receipt_move_id=ANY(:ids) LIMIT 1", ids=source_ids):
        raise DomainError("DEPENDENT_QUALITY", "Nguồn đã có quyết định kiểm định; dùng chứng từ bù được duyệt.")
    if one(c, """SELECT d.id FROM wms.return_line rl JOIN wms.document_line l ON l.id=rl.document_line_id
        JOIN wms.document d ON d.id=l.document_id WHERE rl.source_move_id=ANY(:ids) AND d.status<>'CANCELLED'
        AND (d.status<>'COMPLETED' OR EXISTS(SELECT 1 FROM wms.stock_move m WHERE m.line_id=l.id
          AND m.reverses_move_id IS NULL AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id))) LIMIT 1""", ids=source_ids):
        raise DomainError("DEPENDENT_RETURN", "Nguồn còn phiếu trả hàng chưa hủy hoặc chưa đảo.")
    if one(c, """SELECT m.id FROM wms.transfer_move tm JOIN wms.stock_move m ON m.id=tm.move_id
        WHERE tm.dispatch_move_id=ANY(:ids) AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id) LIMIT 1""", ids=source_ids):
        raise DomainError("DEPENDENT_TRANSFER", "Lần xuất chuyển đã có nhận hoặc điều chỉnh transit chưa đảo.")
    if one(c, """SELECT d.id FROM wms.transfer_adjustment a JOIN wms.document d ON d.id=a.document_id
        JOIN wms.transfer_discrepancy e ON e.id=a.discrepancy_id
        WHERE e.dispatch_move_id=ANY(:ids) AND d.status NOT IN ('CANCELLED','COMPLETED') LIMIT 1""", ids=source_ids):
        raise DomainError("DEPENDENT_TRANSFER", "Lần xuất chuyển còn điều chỉnh mất hàng đang xử lý.")
    for r in rows:
        if r["source_kind"] in CACHED and one(c, """SELECT m.id FROM wms.stock_move m
            WHERE m.stock_item_id=:stock AND m.source_location_id=:loc AND m.transaction_id<>:tx
            AND m.reverses_move_id IS NULL AND NOT EXISTS(SELECT 1 FROM wms.stock_move rev WHERE rev.reverses_move_id=m.id)
            LIMIT 1""", stock=r["stock_item_id"], loc=r["source_location_id"], tx=tx["id"]):
            raise DomainError("DOWNSTREAM_STOCK", "Danh tính/vị trí đích có phát sinh xuất chưa đảo; không thể chứng minh nguồn đảo còn nguyên.")


def prepare(c, tx, rows, today, *, lock=False):
    if lock:
        c.execute(text("SELECT id FROM wms.product WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"),
                  {"ids": sorted({r["product_id"] for r in rows})})
        c.execute(text("SELECT id FROM wms.stock_item WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"),
                  {"ids": sorted({r["stock_item_id"] for r in rows})})
    for r in rows:
        if r["owner_id"] != COMPANY_OWNER or r["consignment_id"]:
            raise DomainError("OWNER_POLICY_REQUIRED", "Chưa có policy đảo hàng ký gửi/chưa phân loại; giữ nguyên chủ hàng.")
        if (r["product_id"], r["owner_id"], r["consignment_id"]) != (r["line_product"], r["line_owner"], r["line_agreement"]):
            raise DomainError("SOURCE_MISMATCH", "Dòng gốc không khớp danh tính tồn.")
        product = one(c, "SELECT * FROM wms.product WHERE id=:id", id=r["product_id"])
        if not product["is_active"] or product["base_uom_id"] != r["base_uom_id"]:
            raise DomainError("SOURCE_MISMATCH", "Sản phẩm/đơn vị cơ sở không còn khớp nguồn.")
        if r["quantity_base"] != r["quantity_base"].quantize(Decimal(1).scaleb(-r["decimal_places"])):
            raise DomainError("INVALID_QUANTITY", "Lượng nguồn không đúng độ chính xác đơn vị.")
        lot = one(c, "SELECT expires_on FROM wms.lot WHERE id=:id" + (" FOR UPDATE" if lock else ""), id=r["lot_id"]) if r["lot_id"] else None
        if r["destination_kind"] == "STORAGE" and lot and lot["expires_on"] and lot["expires_on"] < today:
            raise DomainError("LOT_EXPIRED", "Không đảo hàng hết hạn vào STORAGE; cần chứng từ bù cách ly.")
    projected = effects(c, rows)
    if lock:
        for b in projected:
            c.execute(text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                VALUES (:id,:stock,:loc,0,0,1) ON CONFLICT(stock_item_id,location_id) DO NOTHING"""),
                dict(id=uuid4(), stock=b["stock_item_id"], loc=b["location_id"]))
            c.execute(text("SELECT id FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:loc FOR UPDATE"),
                      dict(stock=b["stock_item_id"], loc=b["location_id"]))
        projected = effects(c, rows)
    for b in projected:
        reserved, delta = Decimal(b["reserved"]), Decimal(b["delta"])
        if lock:
            check_reservations(c, b["stock_item_id"], b["location_id"], reserved)
        if delta < 0 and reserved:
            raise DomainError("RESERVATION_OPEN", "Nguồn đảo đang có reservation; không chiếm giữ chỗ của phiếu khác.")
        if Decimal(b["projected_on_hand"]) < reserved:
            raise DomainError("INSUFFICIENT_STOCK", "Không đủ lượng của đúng danh tính tồn để đảo.")
    serial_positions = {}
    for serial in sorted({r["serial_id"] for r in rows if r["serial_id"]}):
        if lock:
            c.execute(text("SELECT id FROM wms.serial WHERE id=:id FOR UPDATE"), {"id": serial})
        related = [r for r in rows if r["serial_id"] == serial]
        if any(r["quantity_base"] != 1 for r in related) or len({r["stock_item_id"] for r in related}) != 1:
            raise DomainError("SERIAL_POSITION_CONFLICT", "Serial phải giữ nguyên danh tính và lượng 1.")
        existing = c.execute(text("""SELECT b.stock_item_id,b.location_id,b.on_hand FROM wms.stock_balance b
            JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id AND b.on_hand>0"""), {"id": serial}).mappings().all()
        position = one(c, "SELECT * FROM wms.serial_position WHERE serial_id=:id" + (" FOR UPDATE" if lock else ""), id=serial)
        if len(existing) > 1 or any(b["on_hand"] != 1 for b in existing) or bool(existing) != bool(position) or (
            position and position["location_id"] != existing[0]["location_id"]):
            raise DomainError("SERIAL_POSITION_CONFLICT", "Serial cần đối soát vị trí hiện tại.")
        final = {(b["stock_item_id"], b["location_id"]): b["on_hand"] for b in existing}
        for b in projected:
            if b["stock_item_id"] == related[0]["stock_item_id"]:
                final[b["stock_item_id"], b["location_id"]] = Decimal(b["projected_on_hand"])
        if any(q not in {0, 1} for q in final.values()) or sum(final.values()) not in {0, 1}:
            raise DomainError("SERIAL_POSITION_CONFLICT", "Đảo không được tạo serial ở hai vị trí hoặc sai chủ.")
        serial_positions[serial] = next((loc for (_, loc), qty in final.items() if qty), None)
    validate_downstream(c, tx, rows)
    return projected, serial_positions


def write(c, tx_id, rows, line_ids, projected, serial_positions):
    move_ids = {}
    for r in rows:
        move = uuid4()
        move_ids[r["source_move_id"]] = move
        c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,
            destination_location_id,quantity_base,base_uom_id,reverses_move_id)
            VALUES (:id,:tx,:line,:stock,:src,:dst,:qty,:unit,:original)"""),
            dict(id=move, tx=tx_id, line=line_ids[r["source_move_id"]], stock=r["stock_item_id"], src=r["source_location_id"],
                 dst=r["destination_location_id"], qty=r["quantity_base"], unit=r["base_uom_id"], original=r["source_move_id"]))
    # Negative deltas first also handle a count that relocated a serial through LOSS.
    for b in sorted(projected, key=lambda b: Decimal(b["delta"])):
        c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand+:delta,version=version+1 WHERE stock_item_id=:stock AND location_id=:loc"),
                  dict(delta=Decimal(b["delta"]), stock=b["stock_item_id"], loc=b["location_id"]))
    for serial, location in serial_positions.items():
        if location is None:
            c.execute(text("DELETE FROM wms.serial_position WHERE serial_id=:id"), {"id": serial})
        else:
            row = next(r for r in rows if r["serial_id"] == serial and r["destination_location_id"] == location)
            c.execute(text("""INSERT INTO wms.serial_position(id,serial_id,location_id,last_move_id)
                VALUES (:id,:serial,:loc,:move) ON CONFLICT(serial_id) DO UPDATE SET location_id=:loc,last_move_id=:move"""),
                dict(id=uuid4(), serial=serial, loc=location, move=move_ids[row["source_move_id"]]))


def business_today(identity):
    return identity.clock().astimezone(ZoneInfo(identity.settings.business_timezone)).date()
