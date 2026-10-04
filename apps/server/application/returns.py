"""Physical returns linked to immutable posted moves, never reversals of orders.

Lock ancestors, source, return, warehouse/period, locations, products/identities,
balances/reservations. Source locks serialize net quantities across return drafts.
"""
from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, one
from apps.server.application.move_safety import (
    check_reservations,
    location_tree,
    lock_open_period,
    movable_quantity,
)
from apps.server.application.orders import amount, encode
from apps.server.application.receipts import EXTERNAL
from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.orders import OrderResult
from packages.contracts.receipts import OperationView
from packages.contracts.returns import ReturnLineInput, ReturnPlan, ReturnPostResult, ReturnSource, ReturnView
from packages.contracts.traceability import COMPANY_OWNER

SOURCE_KINDS = {"CUSTOMER_RETURN": "ISSUE", "SUPPLIER_RETURN": "RECEIPT"}
SOURCE_SQL = """SELECT m.id,m.line_id AS source_line_id,m.stock_item_id,m.quantity_base AS posted,
    m.base_uom_id,i.product_id,i.owner_id,o.code AS owner_code,i.consignment_id,i.lot_id,i.serial_id,
    p.sku,p.tracking,u.code AS base_uom_code,lot.code AS lot_code,s.code AS serial_code,
    d.id AS document_id,d.number AS document_number,d.kind AS document_kind,d.warehouse_id,d.partner_id,
    t.business_date,
    COALESCE((SELECT SUM(r.quantity_base) FROM wms.return_line rl
        JOIN wms.stock_move r ON r.line_id=rl.document_line_id
        JOIN wms.inventory_transaction rt ON rt.id=r.transaction_id
        JOIN wms.document rd ON rd.id=rt.document_id
        WHERE rl.source_move_id=m.id AND r.stock_item_id=m.stock_item_id
        AND ((rd.kind='CUSTOMER_RETURN' AND rt.operation='RECEIVE') OR
             (rd.kind='SUPPLIER_RETURN' AND rt.operation='ISSUE'))
        AND NOT EXISTS(SELECT 1 FROM wms.stock_move rev WHERE rev.reverses_move_id=r.id)),0) AS returned
    FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id
    JOIN wms.document d ON d.id=t.document_id
    JOIN wms.stock_item i ON i.id=m.stock_item_id JOIN wms.product p ON p.id=i.product_id
    JOIN wms.uom u ON u.id=m.base_uom_id JOIN wms.stock_owner o ON o.id=i.owner_id
    LEFT JOIN wms.lot lot ON lot.id=i.lot_id LEFT JOIN wms.serial s ON s.id=i.serial_id
    WHERE ((d.kind='ISSUE' AND t.operation='ISSUE') OR (d.kind='RECEIPT' AND t.operation='RECEIVE'))
    AND m.reverses_move_id IS NULL
    AND NOT EXISTS(SELECT 1 FROM wms.stock_move rev WHERE rev.reverses_move_id=m.id)"""


class ReturnService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.returns = self

    def document(self, auth, doc_id, *, lock=False):
        doc = self.orders.document(auth, doc_id, lock=lock)
        if doc["kind"] not in SOURCE_KINDS:
            raise DomainError("NOT_FOUND", "Không tìm thấy phiếu trả hàng.")
        return doc

    def source(self, auth, doc, *, lock=False):
        meta = one(auth.connection, "SELECT * FROM wms.return_document WHERE document_id=:id", id=doc["id"])
        if not meta:
            raise DomainError("UNSUPPORTED_RETURN", "Phiếu trả chưa có nguồn đã xác minh.")
        return self.orders.document(auth, meta["source_document_id"], SOURCE_KINDS[doc["kind"]], lock=lock)

    def lock_sources(self, auth, doc):
        self.source(auth, doc, lock=True)

    def snapshot(self, connection, doc):
        return {"source": one(connection, "SELECT * FROM wms.return_document WHERE document_id=:id", id=doc["id"]),
                "lines": self.saved_lines(connection, doc),
                "quarantine_enabled": self.identity.settings.supplier_return_quarantine_enabled}

    def sources(self, auth, kind, warehouse_id, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        broad = any(g["role_code"] not in {"RECEIVER", "PICKER"} for g in auth.grants("document.read", warehouse_id))
        rows = auth.connection.execute(text(SOURCE_SQL + """ AND d.kind=:kind AND d.warehouse_id=:warehouse
            AND (CAST(:after AS uuid) IS NULL OR m.id>:after)
            AND (:broad OR d.created_by=:actor OR EXISTS(SELECT 1 FROM wms.document_assignment a
              WHERE a.document_id=d.id AND a.user_id=:actor)) ORDER BY m.id LIMIT :limit"""),
            {"kind": SOURCE_KINDS[kind], "warehouse": warehouse_id, "after": after,
             "actor": auth.principal.user_id, "broad": broad, "limit": limit + 1}).mappings().all()
        items = []
        for row in rows[:limit]:
            allowed = row["owner_id"] == COMPANY_OWNER and row["consignment_id"] is None
            fields = {k: row[k] for k in ReturnSource.model_fields if k in row}
            items.append(ReturnSource(**fields, posted_base=amount(row["posted"]), returned_base=amount(row["returned"]),
                remaining_base=amount(row["posted"] - row["returned"]), returnable=allowed,
                blocked_reason=None if allowed else "Chưa có policy trả hàng ký gửi/chưa phân loại."))
        return {"items": items, "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    @staticmethod
    def saved_lines(c, doc):
        return [dict(r) for r in c.execute(text("""SELECT r.*,l.product_id,l.owner_id,l.consignment_id,l.uom_id,
            l.source_line_id,l.base_quantity AS quantity_base FROM wms.return_line r
            JOIN wms.document_line l ON l.id=r.document_line_id WHERE l.document_id=:id ORDER BY l.line_no"""),
            {"id": doc["id"]}).mappings()]

    def prepare(self, auth, kind, source, day, specs, *, lock=False):
        c = auth.connection
        active_reference(c, "warehouse", source["warehouse_id"], "warehouse_id")
        locations = location_tree(c, source["warehouse_id"], {s.location_id for s in specs}, lock=lock)
        sources = {}
        for move_id in sorted({s.source_move_id for s in specs}):
            row = one(c, SOURCE_SQL + " AND m.id=:id AND d.id=:doc", id=move_id, doc=source["id"])
            if not row:
                raise DomainError("SOURCE_MISMATCH", "Lần ghi sổ không thuộc nguồn hoặc đã bị đảo.")
            if row["owner_id"] != COMPANY_OWNER or row["consignment_id"] is not None:
                raise DomainError("OWNER_POLICY_REQUIRED", "Chưa có policy trả hàng ký gửi/chưa phân loại; giữ nguyên owner.")
            if day < row["business_date"]:
                raise DomainError("INVALID_DATE", "Ngày trả không được trước ngày ghi sổ nguồn.")
            sources[move_id] = row
        if lock:
            for product_id in sorted({r["product_id"] for r in sources.values()}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product_id})
        totals, serials, prepared = defaultdict(Decimal), set(), []
        for spec in specs:
            row, location = sources[spec.source_move_id], locations[spec.location_id]
            product = active_reference(c, "product", row["product_id"], "product_id")
            unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
            qty = Decimal(spec.quantity_base)
            if row["base_uom_id"] != unit["id"] or qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Lượng trả phải đúng đơn vị cơ sở và độ chính xác nguồn.")
            if kind == "CUSTOMER_RETURN" and location["kind"] != "QUARANTINE":
                raise DomainError("QUALITY_REQUIRED", "Khách trả phải vào QUARANTINE để chờ kiểm định.")
            if kind == "SUPPLIER_RETURN" and location["kind"] == "QUARANTINE" and not self.identity.settings.supplier_return_quarantine_enabled:
                raise DomainError("QUARANTINE_POLICY_REQUIRED", "Chưa bật policy trả NCC từ khu cách ly.")
            totals[row["id"]] += qty
            if totals[row["id"]] > row["posted"] - row["returned"]:
                raise DomainError("SOURCE_EXCEEDED", "Tổng trả vượt lượng còn được trả của lần ghi sổ nguồn.")
            if row["serial_id"]:
                if qty != 1 or row["serial_id"] in serials:
                    raise DomainError("TRACKING_MISMATCH", "Mỗi serial nguồn chỉ một dòng, lượng 1.")
                serials.add(row["serial_id"])
            if lock:
                resolved = resolve_stock_identity(c, product_id=row["product_id"], owner_id=row["owner_id"],
                    warehouse_id=source["warehouse_id"], business_date=day, lot_id=row["lot_id"], serial_id=row["serial_id"])
                if resolved != row["stock_item_id"]:
                    raise DomainError("TRACKING_MISMATCH", "Danh tính tồn không khớp nguồn.")
            prepared.append({"spec": spec, "source": row, "qty": qty})
        return prepared

    def saved_plan(self, auth, doc):
        rows = self.saved_lines(auth.connection, doc)
        count = auth.connection.execute(text("SELECT count(*) FROM wms.document_line WHERE document_id=:id"), {"id": doc["id"]}).scalar_one()
        if not rows or len(rows) != count:
            raise DomainError("UNSUPPORTED_RETURN", "Thiếu kế hoạch trả hàng có nguồn.")
        specs = [ReturnLineInput(source_move_id=r["source_move_id"], location_id=r["location_id"],
                                 quantity_base=amount(r["quantity_base"])) for r in rows]
        return rows, specs

    @staticmethod
    def match_saved(doc, source, rows, prepared):
        if (doc["warehouse_id"], doc["partner_id"]) != (source["warehouse_id"], source["partner_id"]):
            raise DomainError("SOURCE_MISMATCH", "Kho/đối tác không khớp nguồn.")
        for row, item in zip(rows, prepared):
            s = item["source"]
            if tuple(row[k] for k in ("product_id", "owner_id", "consignment_id", "uom_id", "source_line_id")) != (
                s["product_id"], s["owner_id"], s["consignment_id"], s["base_uom_id"], s["source_line_id"]):
                raise DomainError("SOURCE_MISMATCH", "Dòng trả không khớp move nguồn.")

    def validate_saved(self, auth, doc):
        source = self.source(auth, doc)
        rows, specs = self.saved_plan(auth, doc)
        prepared = self.prepare(auth, doc["kind"], source, doc["business_date"], specs)
        self.match_saved(doc, source, rows, prepared)

    def read(self, auth, doc_id):
        doc = self.document(auth, doc_id)
        source = self.source(auth, doc)
        view = self.orders.read(auth, doc_id)
        rows = auth.connection.execute(text("""SELECT r.*,l.base_quantity AS quantity_base,m.stock_item_id,
            loc.code AS location_code,lot.code AS lot_code,s.code AS serial_code,i.serial_id
            FROM wms.return_line r JOIN wms.document_line l ON l.id=r.document_line_id
            JOIN wms.stock_move m ON m.id=r.source_move_id JOIN wms.stock_item i ON i.id=m.stock_item_id
            JOIN wms.location loc ON loc.id=r.location_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
            LEFT JOIN wms.serial s ON s.id=i.serial_id WHERE l.document_id=:id ORDER BY l.line_no"""), {"id": doc_id}).mappings()
        actions = list(view.allowed_actions)
        if view.status == "APPROVED" and auth.allows("return.post", view.warehouse_id):
            actions.append("post")
        return ReturnView(**{**view.model_dump(), "allowed_actions": actions}, source_document_id=source["id"], source_document_number=source["number"],
            plan=[ReturnPlan(**{**r, "quantity_base": amount(r["quantity_base"])}) for r in rows])

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}
        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            source = self.orders.document(auth, payload.source_document_id, SOURCE_KINDS[payload.kind])
            auth.require("return.draft", source["warehouse_id"])
            if doc_id:
                old = self.document(auth, doc_id)
                self.orders.may_edit(auth, old)
                if old["kind"] != payload.kind or self.source(auth, old)["id"] != source["id"]:
                    raise DomainError("SOURCE_MISMATCH", "Không đổi loại/nguồn của phiếu đã tạo.")
            context["auth"] = auth
        def handle(uow):
            c, auth = uow.connection, context["auth"]
            source = self.orders.document(auth, payload.source_document_id, SOURCE_KINDS[payload.kind], lock=True)
            old = self.document(auth, doc_id, lock=True) if doc_id else None
            if old:
                require_version(old["version"], payload.expected_version)
                if old["status"] not in {"DRAFT", "REJECTED"}:
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp/từ chối; phiếu duyệt cần sửa lại.")
                self.orders.no_dependencies(c, doc_id, edit=True)
                if old["attributes"]:
                    raise DomainError("UNSUPPORTED_RETURN", "Không ghi đè dữ liệu mở rộng của phiếu cũ.")
            prepared = self.prepare(auth, payload.kind, source, payload.business_date, payload.lines)
            if old:
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                doc = {**old, "status": "DRAFT", "version": old["version"] + 1}
                c.execute(text("UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,reason=:reason WHERE id=:id"),
                          {**doc, "day": payload.business_date, "reason": payload.reason})
            else:
                sequence = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                prefix = "CR" if payload.kind == "CUSTOMER_RETURN" else "SR"
                doc = dict(id=uuid4(), number=f"{prefix}-{payload.business_date:%Y%m%d}-{sequence:08d}", kind=payload.kind,
                           status="DRAFT", warehouse_id=source["warehouse_id"], version=1)
                c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,partner_id,business_date,created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,:kind,'DRAFT',:warehouse_id,:partner,:day,:actor,:now,1,'{}',:reason)"""),
                    {**doc, "partner": source["partner_id"], "day": payload.business_date, "actor": actor,
                     "now": self.identity.clock(), "reason": payload.reason})
                c.execute(text("INSERT INTO wms.return_document VALUES (:id,:source)"), {"id": doc["id"], "source": source["id"]})
                c.execute(text("INSERT INTO wms.document_link(id,document_id,related_document_id,relation) VALUES (:id,:doc,:source,'RETURN_OF')"),
                          {"id": uuid4(), "doc": doc["id"], "source": source["id"]})
            for index, item in enumerate(prepared, 1):
                line_id, s, spec = uuid4(), item["source"], item["spec"]
                c.execute(text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,
                    factor_snapshot,base_quantity,source_line_id,owner_id,consignment_id)
                    VALUES (:id,:doc,:index,:product,:unit,:qty,1,:qty,:source,:owner,:agreement)"""),
                    {"id": line_id, "doc": doc["id"], "index": index, "product": s["product_id"], "unit": s["base_uom_id"],
                     "qty": item["qty"], "source": s["source_line_id"], "owner": s["owner_id"], "agreement": s["consignment_id"]})
                c.execute(text("INSERT INTO wms.return_line VALUES (:id,:source,:location)"),
                          {"id": line_id, "source": spec.source_move_id, "location": spec.location_id})
            result = OrderResult(**{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                                 request_id=request_id).model_dump(mode="json")
            self.orders.effects(c, actor, doc, "return.update" if old else "return.create", result, payload.reason, request_id)
            return CommandResult(result, 200 if old else 201)
        return self.bus.execute(actor_id=actor, key=key, command="return.update" if doc_id else "return.create",
            resource_id=doc_id or UUID(int=0), payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        digest = payload_hash("return.post", doc_id, payload.model_dump(mode="json"))
        context = {}
        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            doc = self.document(auth, doc_id)
            auth.require("return.post", doc["warehouse_id"])
            self.source(auth, doc)
            context["auth"] = auth
        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.document(auth, doc_id, lock=True)
            executed = one(c, "SELECT * FROM wms.inventory_transaction WHERE document_id=:id AND execution_key=:key",
                           id=doc_id, key=payload.execution_key)
            if executed:
                if executed["posted_by"] != actor or executed["request_hash"] != digest or not executed["response"]:
                    raise DomainError("EXECUTION_MISMATCH", "Execution key đã dùng với người/nội dung khác.")
                return CommandResult(executed["response"])
            require_version(doc["version"], payload.expected_version)
            self.orders.receipts.approved(c, doc)
            source = self.source(auth, doc)
            rows, specs = self.saved_plan(auth, doc)
            lock_open_period(c, doc["warehouse_id"], doc["business_date"])
            external = one(c, "SELECT * FROM wms.location WHERE id=:id FOR SHARE", id=EXTERNAL)
            if not external or not external["is_active"] or external["kind"] != "EXTERNAL":
                raise DomainError("INVALID_LOCATION", "Đối ứng EXTERNAL không hợp lệ.")
            prepared = self.prepare(auth, doc["kind"], source, doc["business_date"], specs, lock=True)
            self.match_saved(doc, source, rows, prepared)
            totals, balances = defaultdict(Decimal), {}
            for item in prepared:
                totals[item["source"]["stock_item_id"], item["spec"].location_id] += item["qty"]
            inbound = doc["kind"] == "CUSTOMER_RETURN"
            for (stock, location), qty in sorted(totals.items(), key=lambda p: (p[0][1], p[0][0])):
                c.execute(text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                    VALUES (:id,:stock,:location,0,0,1) ON CONFLICT (stock_item_id,location_id) DO NOTHING"""),
                    {"id": uuid4(), "stock": stock, "location": location})
                b = one(c, "SELECT * FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:location FOR UPDATE",
                        stock=stock, location=location)
                balances[stock, location] = b
            for pair, qty in sorted(totals.items(), key=lambda p: (p[0][1], p[0][0])):
                b = balances[pair]
                check_reservations(c, *pair, b["reserved"])
                if not inbound and qty > movable_quantity(b["on_hand"], b["reserved"]):
                    raise DomainError("INSUFFICIENT_STOCK", "Không đủ tồn chưa giữ chỗ của đúng owner/lô/serial tại nguồn.")
            for item in prepared:
                serial = item["source"]["serial_id"]
                if serial:
                    position = one(c, "SELECT * FROM wms.serial_position WHERE serial_id=:id FOR UPDATE", id=serial)
                    physical = c.execute(text("""SELECT COALESCE(SUM(b.on_hand),0) FROM wms.stock_balance b
                        JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id"""), {"id": serial}).scalar_one()
                    if (inbound and (position or physical != 0)) or (not inbound and (
                        not position or position["location_id"] != item["spec"].location_id or physical != 1)):
                        raise DomainError("SERIAL_POSITION_CONFLICT", "Serial đã có vị trí hoặc không còn tại nguồn trả.")
            tx = uuid4()
            doc.update(status="COMPLETED", version=doc["version"] + 1)
            result = ReturnPostResult(**{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                transaction_id=tx, request_id=request_id).model_dump(mode="json")
            c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by,request_hash,response)
                VALUES (:id,:doc,:execution,:operation,:day,:now,:actor,:hash,CAST(:response AS jsonb))"""),
                {"id": tx, "doc": doc_id, "execution": payload.execution_key, "operation": "RECEIVE" if inbound else "ISSUE",
                 "day": doc["business_date"], "now": self.identity.clock(), "actor": actor, "hash": digest, "response": encode(result)})
            for row, item in zip(rows, prepared):
                s, spec, move_id = item["source"], item["spec"], uuid4()
                c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
                    VALUES (:id,:tx,:line,:stock,:source,:destination,:qty,:unit)"""),
                    {"id": move_id, "tx": tx, "line": row["document_line_id"], "stock": s["stock_item_id"],
                     "source": EXTERNAL if inbound else spec.location_id, "destination": spec.location_id if inbound else EXTERNAL,
                     "qty": item["qty"], "unit": s["base_uom_id"]})
                c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand+:change,version=version+1 WHERE stock_item_id=:stock AND location_id=:location"),
                    {"stock": s["stock_item_id"], "location": spec.location_id, "change": item["qty"] if inbound else -item["qty"]})
                if s["serial_id"]:
                    if inbound:
                        c.execute(text("INSERT INTO wms.serial_position(id,serial_id,location_id,last_move_id) VALUES (:id,:serial,:location,:move)"),
                            {"id": uuid4(), "serial": s["serial_id"], "location": spec.location_id, "move": move_id})
                    else:
                        c.execute(text("DELETE FROM wms.serial_position WHERE serial_id=:id"), {"id": s["serial_id"]})
            c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), doc)
            self.orders.effects(c, actor, doc, "return.post", result, payload.reason, request_id)
            return CommandResult(result)
        return self.bus.execute(actor_id=actor, key=key, command="return.post", resource_id=doc_id,
            payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def operation(self, auth, key):
        record = one(auth.connection, "SELECT response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key AND command='return.post'",
                     actor=auth.principal.user_id, key=key)
        if not record:
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK; chỉ gửi lại cùng key và nội dung.")
        result = record["response"]
        doc = self.document(auth, UUID(result["id"]))
        auth.require("return.post", doc["warehouse_id"])
        self.source(auth, doc)
        return OperationView(**{k: result[k] for k in ["id", "status", "version", "request_id", "transaction_id"]})
