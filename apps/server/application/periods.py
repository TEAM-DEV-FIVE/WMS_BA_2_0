from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandResult
from apps.server.application.counting import effects, require_state
from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.periods import PeriodResult

PERMISSIONS = {"create": "period.create", "close": "period.close", "confirm-reopen": "period.close", "reopen": "period.reopen"}


class PeriodService:
    def __init__(self, orders):
        self.identity, self.bus = orders.identity, orders.bus

    @staticmethod
    def visible(auth, warehouse_id):
        if not any(auth.allows(p, warehouse_id) for p in ("document.read", "period.create", "period.close", "period.reopen")):
            raise DomainError("NOT_FOUND", "Không tìm thấy kỳ kho.")

    def period(self, auth, period_id):
        row = one(auth.connection, "SELECT * FROM wms.stock_period WHERE id=:id", id=period_id)
        if not row:
            raise DomainError("NOT_FOUND", "Không tìm thấy kỳ kho.")
        self.visible(auth, row["warehouse_id"])
        return row

    @staticmethod
    def confirmation(c, row, now):
        return one(c, """SELECT * FROM wms.period_reopen_confirmation WHERE period_id=:id AND period_version=:version
            AND confirmed_at>=:since ORDER BY confirmed_at DESC,id DESC LIMIT 1""",
                   id=row["id"], version=row["version"], since=now - timedelta(hours=24))

    def view(self, auth, row):
        actions = [action for action in ("close", "confirm-reopen", "reopen") if auth.allows(PERMISSIONS[action], row["warehouse_id"])
                   and row["status"] == ("OPEN" if action == "close" else "CLOSED")]
        confirmation = self.confirmation(auth.connection, row, auth.now) if row["status"] == "CLOSED" else None
        return {**{k: row[k] for k in ("id", "warehouse_id", "starts_on", "ends_on", "status", "version")},
                "allowed_actions": actions, "confirmation_id": confirmation["id"] if confirmation else None}

    def read(self, auth, period_id):
        return self.view(auth, self.period(auth, period_id))

    def listing(self, auth, warehouse_id, after=None, limit=50):
        self.visible(auth, warehouse_id)
        rows = auth.connection.execute(text("SELECT * FROM wms.stock_period WHERE warehouse_id=:warehouse AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit"),
                                       dict(warehouse=warehouse_id, after=after, limit=limit + 1)).mappings().all()
        return {"items": [self.view(auth, r) for r in rows[:limit]], "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    @staticmethod
    def reconcile(c, warehouse):
        # Warehouse UPDATE excludes every conforming inventory writer while
        # these checks run. No document is locked after warehouse/period locks.
        queries = ["""WITH legs AS (
            SELECT stock_item_id,destination_location_id AS location_id,quantity_base AS qty FROM wms.stock_move
            UNION ALL SELECT stock_item_id,source_location_id,-quantity_base FROM wms.stock_move),
            ledger AS (SELECT stock_item_id,location_id,sum(qty) qty FROM legs JOIN wms.location l ON l.id=location_id
                WHERE l.warehouse_id=:warehouse AND l.kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING','TRANSIT') GROUP BY stock_item_id,location_id),
            balances AS (SELECT b.* FROM wms.stock_balance b JOIN wms.location l ON l.id=b.location_id WHERE l.warehouse_id=:warehouse)
            SELECT 1 FROM ledger l FULL JOIN balances b USING(stock_item_id,location_id)
            WHERE COALESCE(l.qty,0)<>COALESCE(b.on_hand,0) LIMIT 1""",
            """WITH reservations AS (SELECT r.stock_item_id,r.location_id,sum(quantity-consumed-released) qty
                FROM wms.reservation r JOIN wms.location l ON l.id=r.location_id WHERE l.warehouse_id=:warehouse GROUP BY r.stock_item_id,r.location_id),
            balances AS (SELECT b.* FROM wms.stock_balance b JOIN wms.location l ON l.id=b.location_id WHERE l.warehouse_id=:warehouse)
            SELECT 1 FROM reservations r FULL JOIN balances b USING(stock_item_id,location_id)
            WHERE COALESCE(r.qty,0)<>COALESCE(b.reserved,0) LIMIT 1""",
            """SELECT 1 FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
                JOIN wms.location l ON l.id=b.location_id LEFT JOIN wms.serial_position sp ON sp.serial_id=i.serial_id
                WHERE l.warehouse_id=:warehouse AND i.serial_id IS NOT NULL AND b.on_hand>0
                AND (b.on_hand<>1 OR sp.location_id IS DISTINCT FROM b.location_id) LIMIT 1""",
            """SELECT 1 FROM wms.serial_position sp JOIN wms.location l ON l.id=sp.location_id
                WHERE l.warehouse_id=:warehouse AND NOT EXISTS (SELECT 1 FROM wms.stock_balance b
                    JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=sp.serial_id
                    AND b.location_id=sp.location_id AND b.on_hand=1) LIMIT 1"""]
        if any(c.execute(text(query), {"warehouse": warehouse}).first() for query in queries):
            raise DomainError("RECONCILIATION_FAILED", "Sổ, số dư, reservation hoặc serial chưa khớp; cần đối soát.")

    def write(self, access, key, action, payload, request_id, period_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            warehouse = self.period(auth, period_id)["warehouse_id"] if period_id else payload.warehouse_id
            auth.require(PERMISSIONS[action], warehouse)
            context.update(auth=auth, warehouse=warehouse)

        def handle(uow):
            c, auth, warehouse = uow.connection, context["auth"], context["warehouse"]
            wh = one(c, "SELECT * FROM wms.warehouse WHERE id=:id AND is_active FOR UPDATE", id=warehouse)
            if not wh:
                raise DomainError("INVALID_REFERENCE", "Kho không còn hoạt động.")
            # This also serializes creation of overlapping periods; no extension
            # privilege is required for a GiST exclusion constraint.
            periods = c.execute(text("SELECT * FROM wms.stock_period WHERE warehouse_id=:id ORDER BY id FOR UPDATE"),
                                {"id": warehouse}).mappings().all()
            confirmation_id = None
            if action == "create":
                if any(payload.starts_on <= p["ends_on"] and payload.ends_on >= p["starts_on"] for p in periods):
                    raise DomainError("PERIOD_OVERLAP", "Kỳ kho không được chồng lấn ngày, kể cả kỳ đã khóa.")
                row = dict(id=uuid4(), warehouse_id=warehouse, status="OPEN", version=1)
                c.execute(text("INSERT INTO wms.stock_period(id,warehouse_id,starts_on,ends_on,status,version) VALUES (:id,:warehouse_id,:start,:end,'OPEN',1)"),
                          {**row, "start": payload.starts_on, "end": payload.ends_on})
            else:
                row = dict(next(p for p in periods if p["id"] == period_id))
                require_version(row["version"], payload.expected_version)
                require_state(row, "OPEN" if action == "close" else "CLOSED")
                self.reconcile(c, warehouse)
                if action == "close":
                    if one(c, """SELECT id FROM wms.count_session WHERE warehouse_id=:warehouse AND status NOT IN ('POSTED','CANCELLED')
                        AND business_date BETWEEN :start AND :end LIMIT 1""", warehouse=warehouse, start=row["starts_on"], end=row["ends_on"]):
                        raise DomainError("COUNT_PENDING", "Kỳ còn phiên kiểm kê chưa hoàn tất/hủy.")
                    if one(c, """SELECT id FROM wms.document WHERE (warehouse_id=:warehouse OR destination_warehouse_id=:warehouse)
                        AND business_date BETWEEN :start AND :end AND kind NOT IN ('PO','SO')
                        AND status NOT IN ('COMPLETED','CANCELLED') LIMIT 1""", warehouse=warehouse, start=row["starts_on"], end=row["ends_on"]):
                        raise DomainError("DOCUMENT_PENDING", "Kỳ còn chứng từ kho chưa hoàn tất/hủy.")
                    row["status"] = "CLOSED"
                elif action == "confirm-reopen":
                    confirmation_id = uuid4()
                    # Confirmation advances the period version. Only that exact
                    # version can be reopened; later confirmation/close invalidates it.
                    c.execute(text("INSERT INTO wms.period_reopen_confirmation VALUES (:id,:period,:version,:actor,:now,:reason)"),
                              dict(id=confirmation_id, period=period_id, version=row["version"] + 1,
                                   actor=actor, now=auth.now, reason=payload.reason))
                else:
                    confirmation = one(c, "SELECT * FROM wms.period_reopen_confirmation WHERE id=:id AND period_id=:period",
                                       id=payload.confirmation_id, period=period_id)
                    if (not confirmation or confirmation["period_version"] != row["version"] or
                        confirmation["confirmed_at"] < auth.now - timedelta(hours=24) or confirmation["confirmed_by"] == actor):
                        raise DomainError("CONTROLLER_CONFIRMATION_REQUIRED", "Cần xác nhận độc lập của kiểm soát viên trong 24 giờ cho đúng version kỳ.")
                    controller = one(c, "SELECT id FROM wms.app_user WHERE id=:id AND is_active", id=confirmation["confirmed_by"])
                    principal = Principal(confirmation["confirmed_by"], auth.principal.session_id, "", "", None)
                    if not controller or not Authorization(c, principal, auth.now).allows("period.close", warehouse):
                        raise DomainError("CONTROLLER_CONFIRMATION_REQUIRED", "Người xác nhận không còn quyền kiểm soát kỳ.")
                    row["status"] = "OPEN"
                row["version"] += 1
                c.execute(text("""UPDATE wms.stock_period SET status=:status,version=:version,
                    closed_by=CASE WHEN :closing THEN :actor ELSE closed_by END,
                    closed_at=CASE WHEN :closing THEN :now ELSE closed_at END WHERE id=:id"""),
                          {**row, "actor": actor, "now": auth.now, "closing": action == "close"})
            result = PeriodResult(**{k: row[k] for k in ("id", "warehouse_id", "status", "version")},
                                  request_id=request_id, confirmation_id=confirmation_id).model_dump(mode="json")
            effects(c, self.identity, actor, row, "period." + action, result, payload.reason, request_id, "stock_period")
            return CommandResult(result, 201 if action == "create" else 200)

        return self.bus.execute(actor_id=actor, key=key, command="period." + action,
            resource_id=period_id or payload.warehouse_id, payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def operation(self, auth, key):
        saved = one(auth.connection, "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
                    actor=auth.principal.user_id, key=key)
        if not saved or not saved["command"].startswith("period."):
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK kỳ kho.")
        row = self.period(auth, UUID(saved["response"]["id"]))
        auth.require(PERMISSIONS[saved["command"].split(".")[1]], row["warehouse_id"])
        return saved["response"]
