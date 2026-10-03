from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from apps.server.application.commands import CommandResult
from apps.server.application.master_data import active_reference, one
from apps.server.application.move_safety import location_tree
from apps.server.application.orders import amount
from apps.server.application.stock_identity import validate_ownership
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.quality import QualityDecision, QualityHistory, QualityResult, QualitySource

SOURCE_SQL = """SELECT m.id,t.document_id AS receipt_id,d.number AS receipt_number,d.version,l.warehouse_id,t.business_date,d.kind AS document_kind,
    m.stock_item_id,i.product_id,p.sku,p.tracking,lot.code AS lot_code,s.code AS serial_code,
    i.owner_id,o.code AS owner_code,i.consignment_id,m.destination_location_id AS source_location_id,
    l.code AS location_code,m.quantity_base AS received,
    COALESCE((SELECT SUM(q.quantity) FROM wms.quality_decision q WHERE q.receipt_move_id=m.id),0) AS decided
    FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id
    JOIN wms.document d ON d.id=t.document_id AND
        ((t.operation='RECEIVE' AND d.kind IN ('RECEIPT','CUSTOMER_RETURN')) OR
         (t.operation='ARRIVE' AND d.kind='TRANSFER'))
    JOIN wms.stock_item i ON i.id=m.stock_item_id JOIN wms.product p ON p.id=i.product_id
    JOIN wms.stock_owner o ON o.id=i.owner_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
    LEFT JOIN wms.serial s ON s.id=i.serial_id JOIN wms.location l ON l.id=m.destination_location_id
    WHERE NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)"""


def decision_moved(connection, decision_id):
    return connection.execute(text("""SELECT COALESCE(SUM(m.quantity_base),0) FROM wms.move_line l
        JOIN wms.stock_move m ON m.line_id=l.document_line_id
        JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='MOVE'
        WHERE l.quality_decision_id=:id AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)"""),
                              {"id": decision_id}).scalar_one()


class QualityService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus

    def source(self, auth, source_id, *, lock=False):
        row = one(auth.connection, SOURCE_SQL + " AND m.id=:id", id=source_id)
        if not row:
            raise DomainError("NOT_FOUND", "Không tìm thấy lần nhận để kiểm định.")
        if row["document_kind"] == "TRANSFER":
            self.orders.transfers.document(auth, row["receipt_id"], lock=lock)
            auth.require("document.read", row["warehouse_id"], hidden=True)
        else:
            self.orders.document(auth, row["receipt_id"], row["document_kind"], lock=lock)
        if lock:
            row = one(auth.connection, SOURCE_SQL + " AND m.id=:id", id=source_id)
            if not row:
                raise DomainError("SOURCE_MISMATCH", "Nguồn kiểm định đã bị đảo; tải lại.")
        return row

    @staticmethod
    def view(row):
        return QualitySource(**{k: row[k] for k in QualitySource.model_fields
                                if k not in {"received_base", "decided_base", "remaining_base"}},
                             received_base=amount(row["received"]), decided_base=amount(row["decided"]),
                             remaining_base=amount(row["received"] - row["decided"]))

    def listing(self, auth, warehouse_id, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        broad = any(g["role_code"] not in {"RECEIVER", "PICKER"} for g in auth.grants("document.read", warehouse_id))
        rows = auth.connection.execute(text(SOURCE_SQL + """ AND l.warehouse_id=:warehouse
            AND (CAST(:after AS uuid) IS NULL OR m.id>:after)
            AND (:broad OR d.created_by=:actor OR EXISTS(SELECT 1 FROM wms.document_assignment a
                WHERE a.document_id=d.id AND a.user_id=:actor)) ORDER BY m.id LIMIT :limit"""),
            {"warehouse": warehouse_id, "after": after, "broad": broad, "actor": auth.principal.user_id,
             "limit": limit + 1}).mappings().all()
        return {"items": [self.view(row) for row in rows[:limit]],
                "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    def history(self, auth, source_id, after=None, limit=50):
        source = self.source(auth, source_id)
        rows = auth.connection.execute(text("""SELECT * FROM wms.quality_decision WHERE receipt_move_id=:id
            AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit"""),
                                       {"id": source_id, "after": after, "limit": limit + 1}).mappings().all()
        items = []
        for row in rows[:limit]:
            moved = decision_moved(auth.connection, row["id"])
            items.append(QualityDecision(**{**row, "quantity": amount(row["quantity"])},
                                         moved_base=amount(moved), remaining_base=amount(row["quantity"] - moved)))
        return QualityHistory(source=self.view(source), items=items,
                              next_after=rows[limit - 1]["id"] if len(rows) > limit else None,
                              allowed_actions=["decide"] if auth.allows("quality.decide", source["warehouse_id"]) else [])

    def decide(self, access, key, source_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            source = self.source(auth, source_id)
            auth.require("quality.decide", source["warehouse_id"])
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            source = self.source(auth, source_id, lock=True)
            require_version(source["version"], payload.expected_version)
            active_reference(c, "warehouse", source["warehouse_id"], "warehouse_id")
            locations = location_tree(c, source["warehouse_id"], [source["source_location_id"]], lock=True)
            if locations[source["source_location_id"]]["kind"] not in {"RECEIVING", "QUARANTINE"}:
                raise DomainError("INVALID_LOCATION", "Chỉ kiểm định nguồn nhận/cách ly.")
            validate_ownership(c, owner_id=source["owner_id"], consignment_id=source["consignment_id"],
                               warehouse_id=source["warehouse_id"], business_date=source["business_date"])
            product = active_reference(c, "product", source["product_id"], "product_id")
            unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
            quantities = [Decimal(payload.accepted_base), Decimal(payload.rejected_base)]
            if any(q != q.quantize(Decimal(1).scaleb(-unit["decimal_places"])) for q in quantities):
                raise DomainError("INVALID_QUANTITY", "Số lượng không đúng độ chính xác đơn vị cơ sở.")
            if sum(quantities) > source["received"] - source["decided"]:
                raise DomainError("SOURCE_EXCEEDED", "Tổng quyết định vượt lượng còn kiểm định của lần nhận.")
            if product["tracking"] == "SERIAL" and any(q not in {0, 1} for q in quantities):
                raise DomainError("TRACKING_MISMATCH", "Mỗi serial chỉ nhận một quyết định cho số lượng 1.")
            ids = []
            for result, quantity in zip(["ACCEPT", "REJECT"], quantities):
                if not quantity:
                    continue
                decision_id = uuid4()
                c.execute(text("""INSERT INTO wms.quality_decision
                    (id,receipt_move_id,quantity,result,reason,decided_by,decided_at)
                    VALUES (:id,:source,:qty,:result,:reason,:actor,:now)"""),
                          {"id": decision_id, "source": source_id, "qty": quantity, "result": result,
                           "reason": payload.reason, "actor": actor, "now": self.identity.clock()})
                ids.append(decision_id)
            c.execute(text("UPDATE wms.document SET version=version+1 WHERE id=:id"), {"id": source["receipt_id"]})
            result = QualityResult(id=source["receipt_id"], receipt_move_id=source_id, warehouse_id=source["warehouse_id"],
                                   version=source["version"] + 1, decision_ids=ids, request_id=request_id).model_dump(mode="json")
            self.orders.effects(c, actor, {"id": source["receipt_id"], "kind": source["document_kind"], "warehouse_id": source["warehouse_id"]},
                                "quality.decide", result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(actor_id=actor, key=key, command="quality.decide", resource_id=source_id,
                                payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)
