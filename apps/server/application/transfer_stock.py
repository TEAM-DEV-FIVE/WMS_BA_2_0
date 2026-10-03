"""Transfer stock primitives; caller owns authorization, document locks and transaction."""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.master_data import active_reference, one
from apps.server.application.move_safety import check_reservations, location_tree, lock_open_period
from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError
from packages.contracts.traceability import COMPANY_OWNER

LOSS = UUID("00000000-0000-4110-8000-000000000020")


def lock_route(c, doc, day, operation, physical):
    warehouses = sorted({doc["warehouse_id"], doc["destination_warehouse_id"]})
    for warehouse in warehouses:
        active_reference(c, "warehouse", warehouse, "warehouse_id")
    impacted = (
        warehouses
        if operation == "ADJUST"
        else [doc["warehouse_id"] if operation == "DISPATCH" else doc["destination_warehouse_id"]]
    )
    for warehouse in impacted:
        lock_open_period(c, warehouse, day)
    ids = {doc["transit_location_id"]}
    for warehouse, targets in physical.items():
        location_tree(c, warehouse, targets)
        for target in targets:
            visited = set()
            while target:
                if target in visited:
                    raise DomainError("INVALID_TREE", "Cây vị trí không hợp lệ.")
                visited.add(target)
                ids.add(target)
                target = one(c, "SELECT parent_id FROM wms.location WHERE id=:id", id=target)["parent_id"]
    if operation == "ADJUST":
        ids.add(LOSS)
    for target in sorted(ids):
        row = one(c, "SELECT * FROM wms.location WHERE id=:id FOR UPDATE", id=target)
        if not row or not row["is_active"]:
            raise DomainError("INVALID_LOCATION", "Vị trí không còn hoạt động.")
    transit = one(c, "SELECT * FROM wms.location WHERE id=:id", id=doc["transit_location_id"])
    if transit["kind"] != "TRANSIT" or transit["warehouse_id"] or transit["parent_id"]:
        raise DomainError("INVALID_TRANSIT", "Transit không đúng lệnh chuyển.")
    if one(
        c,
        "SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL",
        id=transit["id"],
    ):
        raise DomainError("LOCATION_FROZEN", "Transit đang bị khóa.")
    for warehouse, targets in physical.items():
        location_tree(c, warehouse, targets)
        # A catalogue update may have changed an ancestor between discovery and
        # acquiring the location locks. Never validate an unlocked new path.
        for target in targets:
            current = target
            while current:
                if current not in ids:
                    raise DomainError("INVALID_TREE", "Cây vị trí đã đổi trong lúc khóa; tải lại và thử lại.")
                current = one(c, "SELECT parent_id FROM wms.location WHERE id=:id", id=current)["parent_id"]
    if operation == "ADJUST":
        loss = one(c, "SELECT * FROM wms.location WHERE id=:id", id=LOSS)
        if loss["kind"] != "LOSS" or loss["warehouse_id"]:
            raise DomainError("INVALID_LOCATION", "Đối ứng mất hàng không hợp lệ.")


def prepare_legs(c, legs, warehouse, day):
    stocks = {
        key: one(c, "SELECT * FROM wms.stock_item WHERE id=:id", id=key)
        for key in sorted({r["stock"] for r in legs})
    }
    if any(s is None for s in stocks.values()):
        raise DomainError("NOT_FOUND", "Không tìm thấy danh tính tồn.")
    for product in sorted({s["product_id"] for s in stocks.values()}):
        c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product})
    serials = set()
    for item_id, stock in stocks.items():
        if stock["owner_id"] != COMPANY_OWNER or stock["consignment_id"]:
            raise DomainError(
                "OWNERSHIP_UNSUPPORTED",
                "Chưa có chính sách chuyển kho ký gửi/chưa phân loại; không đổi chủ hàng.",
            )
        resolved = resolve_stock_identity(
            c,
            product_id=stock["product_id"],
            owner_id=stock["owner_id"],
            warehouse_id=warehouse,
            business_date=day,
            lot_id=stock["lot_id"],
            serial_id=stock["serial_id"],
        )
        if resolved != item_id:
            raise DomainError("SOURCE_MISMATCH", "Danh tính tồn đã thay đổi.")
        product = active_reference(c, "product", stock["product_id"], "product_id")
        unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
        for leg in [r for r in legs if r["stock"] == item_id]:
            if leg["qty"] != leg["qty"].quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Số lượng không đúng độ chính xác đơn vị.")
            leg["unit"] = product["base_uom_id"]
            if stock["serial_id"]:
                if leg["qty"] != 1 or stock["serial_id"] in serials:
                    raise DomainError("TRACKING_MISMATCH", "Một serial chỉ một dòng, lượng 1.")
                serials.add(stock["serial_id"])
    pairs = {(r["stock"], r[k]) for r in legs for k in ("source", "destination") if r[k] != LOSS}
    balances = {}
    for item_id, location in sorted(pairs, key=lambda p: (p[1], p[0])):
        c.execute(
            text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
            VALUES (:id,:stock,:location,0,0,1) ON CONFLICT (stock_item_id,location_id) DO NOTHING"""),
            {"id": uuid4(), "stock": item_id, "location": location},
        )
        balances[item_id, location] = one(
            c,
            """SELECT * FROM wms.stock_balance
            WHERE stock_item_id=:stock AND location_id=:location FOR UPDATE""",
            stock=item_id,
            location=location,
        )
    totals = defaultdict(Decimal)
    for r in legs:
        totals[r["stock"], r["source"]] += r["qty"]
    for pair, qty in sorted(totals.items(), key=lambda p: (p[0][1], p[0][0])):
        balance = balances[pair]
        check_reservations(c, *pair, balance["reserved"])
        if qty > balance["on_hand"] - balance["reserved"]:
            raise DomainError(
                "INSUFFICIENT_STOCK", "Không đủ tồn chưa giữ chỗ; không lấy hàng của phiếu khác."
            )
    for r in legs:
        stock = stocks[r["stock"]]
        if stock["serial_id"]:
            position = one(
                c, "SELECT * FROM wms.serial_position WHERE serial_id=:id FOR UPDATE", id=stock["serial_id"]
            )
            total = c.execute(
                text("""SELECT coalesce(sum(b.on_hand),0) FROM wms.stock_balance b
                JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id"""),
                {"id": stock["serial_id"]},
            ).scalar_one()
            if (
                not position
                or position["location_id"] != r["source"]
                or total != 1
                or (r["destination"] != LOSS and balances[r["stock"], r["destination"]]["on_hand"])
            ):
                raise DomainError("SERIAL_POSITION_CONFLICT", "Serial không ở đúng vị trí nguồn.")
    return stocks


def write_legs(c, legs, stocks, tx, evidence):
    for r in legs:
        move = uuid4()
        c.execute(
            text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,
            source_location_id,destination_location_id,quantity_base,base_uom_id)
            VALUES (:id,:tx,:line,:stock,:source,:destination,:qty,:unit)"""),
            {**r, "id": move, "tx": tx},
        )
        c.execute(
            text("INSERT INTO wms.transfer_move VALUES (:id,:dispatch,:disposition,:evidence)"),
            {"id": move, "dispatch": r["dispatch"], "disposition": r["disposition"], "evidence": evidence},
        )
        for location, qty in [(r["source"], -r["qty"]), (r["destination"], r["qty"])]:
            if location != LOSS:
                c.execute(
                    text("""UPDATE wms.stock_balance SET on_hand=on_hand+:qty,version=version+1
                    WHERE stock_item_id=:stock AND location_id=:location"""),
                    {"stock": r["stock"], "location": location, "qty": qty},
                )
        serial = stocks[r["stock"]]["serial_id"]
        if serial:
            if r["destination"] == LOSS:
                c.execute(text("DELETE FROM wms.serial_position WHERE serial_id=:id"), {"id": serial})
            else:
                c.execute(
                    text(
                        "UPDATE wms.serial_position SET location_id=:location,last_move_id=:move WHERE serial_id=:id"
                    ),
                    {"id": serial, "location": r["destination"], "move": move},
                )
