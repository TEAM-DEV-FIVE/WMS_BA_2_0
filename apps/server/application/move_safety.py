"""Transaction helpers for subsequent stock flows. Call after source/document locks.

Order: warehouse SHARE (opening cutover), period UPDATE, locations/ancestors in
UUID order, products, stock identity, balances, reservations. Callers own the UoW.
No helper commits, authorizes a command, or changes ownership.
"""

from decimal import Decimal

from sqlalchemy import text

from apps.server.application.master_data import active_reference, invalid, one
from apps.server.domain.errors import DomainError


def lock_open_period(connection, warehouse_id, business_date):
    active_reference(connection, "warehouse", warehouse_id, "warehouse_id")
    rows = connection.execute(text("""SELECT * FROM wms.stock_period WHERE warehouse_id=:warehouse
        AND :day BETWEEN starts_on AND ends_on ORDER BY id FOR UPDATE"""),
                              {"warehouse": warehouse_id, "day": business_date}).mappings().all()
    if len(rows) != 1 or rows[0]["status"] != "OPEN":
        raise DomainError("PERIOD_CLOSED", "Ngày ghi sổ phải thuộc đúng một kỳ kho đang mở.")
    return rows[0]


def location_tree(connection, warehouse_id, location_ids, *, lock=False, count_session_id=None, allow_shipping=False):
    rows = {}
    for target in sorted(set(location_ids)):
        current, visited = target, set()
        while current:
            if current in visited or len(visited) > 10:
                invalid("location_id", "Cây vị trí có chu kỳ hoặc quá sâu.", "INVALID_TREE")
            visited.add(current)
            row = rows.get(current) or one(connection, "SELECT * FROM wms.location WHERE id=:id", id=current)
            if not row:
                invalid("location_id", "Không tìm thấy vị trí.")
            rows[current] = row
            current = row["parent_id"]
    if lock:
        for key in sorted(rows):
            rows[key] = one(connection, "SELECT * FROM wms.location WHERE id=:id FOR UPDATE", id=key)
    for target in location_ids:
        current, visited, depth = target, set(), 0
        while current:
            row = rows.get(current)
            if not row or current in visited:
                invalid("location_id", "Cây vị trí đã thay đổi hoặc có chu kỳ; tải lại.", "INVALID_TREE")
            visited.add(current)
            if not row["is_active"] or row["warehouse_id"] != warehouse_id:
                invalid("location_id", "Vị trí/cha phải đang hoạt động và thuộc cùng kho.", "INVALID_LOCATION")
            if depth and row["kind"] != "GROUP":
                invalid("location_id", "Cha vị trí phải là nhóm.", "INVALID_TREE")
            current, depth = row["parent_id"], depth + 1
        kind = rows[target]["kind"]
        if kind not in ({"STORAGE", "RECEIVING", "QUARANTINE", "SHIPPING"} if allow_shipping else
                        {"STORAGE", "RECEIVING", "QUARANTINE"}):
            invalid("location_id", "Chỉ hỗ trợ lưu trữ, nhận hàng và cách ly trong cùng kho.", "INVALID_LOCATION")
        if (kind == "STORAGE" and depth != 3) or (kind != "STORAGE" and depth > 2):
            invalid("location_id", "Cây lưu trữ phải theo Kho → Zone → Rack → Bin.", "INVALID_TREE")
        frozen = one(connection, "SELECT session_id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL", id=target)
        # Only the authorized counting service supplies its locked session after
        # checking state/approvals. No public DTO exposes this exception.
        if frozen and frozen["session_id"] != count_session_id:
            raise DomainError("LOCATION_FROZEN", "Vị trí đang khóa kiểm kê.")
    return {key: rows[key] for key in location_ids}


def movable_quantity(on_hand, reserved, *, frozen=False):
    """Physical quantity free of reservations; expiry/quality eligibility is separate."""
    return Decimal(0) if frozen else max(Decimal(0), Decimal(on_hand) - Decimal(reserved))


def stock_availability(on_hand, reserved, *, location_kind, expires_on, business_today, frozen=False):
    """Return (eligible, available) for one stock identity/location, never across UOMs.

    business_today comes from the server clock in the business timezone, not the
    document's possibly backdated business_date. Owner policy remains caller-owned.
    """
    eligible = Decimal(on_hand) if (
        location_kind == "STORAGE" and not frozen and (expires_on is None or expires_on >= business_today)
    ) else Decimal(0)
    return eligible, movable_quantity(eligible, reserved)


def check_reservations(connection, stock_item_id, location_id, reserved):
    # Expiry alone does not release a reservation; include it until consumed/released.
    rows = connection.execute(text("""SELECT quantity,consumed,released FROM wms.reservation
        WHERE stock_item_id=:stock AND location_id=:location ORDER BY id FOR UPDATE"""),
                              {"stock": stock_item_id, "location": location_id}).mappings()
    total = sum((r["quantity"] - r["consumed"] - r["released"] for r in rows), Decimal(0))
    if total != reserved:
        raise DomainError("RESERVATION_CONFLICT", "Số dư giữ chỗ không khớp reservation; cần đối soát.")
