from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, one, page
from apps.server.application.move_safety import (
    check_reservations,
    location_tree,
    lock_open_period,
    movable_quantity,
    stock_availability,
)
from apps.server.application.orders import amount, encode
from apps.server.application.quality import decision_moved
from apps.server.application.stock_identity import resolve_stock_identity, validate_ownership
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.moves import MoveLineInput, MovePlan, MovePostResult, MoveView
from packages.contracts.orders import OrderResult
from packages.contracts.receipts import OperationView


class MoveService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.moves = self

    def locations(self, auth, warehouse_id, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        return page(auth.connection, """SELECT id,code,name,kind FROM wms.location
            WHERE warehouse_id=:warehouse AND is_active AND kind IN ('RECEIVING','QUARANTINE','STORAGE')
            AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit""",
                    {"warehouse": warehouse_id, "after": after}, limit)

    def stock(self, auth, warehouse_id, after=None, limit=50):
        auth.require("stock.read", warehouse_id, hidden=True)
        result = page(auth.connection, """SELECT b.id,b.stock_item_id,b.location_id AS source_location_id,
            l.code AS source_code,l.kind AS source_kind,p.sku,p.tracking,lot.code AS lot_code,s.code AS serial_code,
            o.code AS owner_code,i.owner_id,i.consignment_id,b.on_hand,b.reserved,lot.expires_on,
            EXISTS(SELECT 1 FROM wms.count_location_lock c WHERE c.location_id=l.id AND c.released_at IS NULL) AS frozen
            FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
            JOIN wms.product p ON p.id=i.product_id JOIN wms.stock_owner o ON o.id=i.owner_id
            JOIN wms.location l ON l.id=b.location_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
            LEFT JOIN wms.serial s ON s.id=i.serial_id
            WHERE l.warehouse_id=:warehouse AND l.is_active AND b.on_hand>0
            AND l.kind IN ('RECEIVING','QUARANTINE','STORAGE') AND (CAST(:after AS uuid) IS NULL OR b.id>:after)
            ORDER BY b.id LIMIT :limit""", {"warehouse": warehouse_id, "after": after}, limit)
        today = self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
        for row in result["items"]:
            expiry = row.pop("expires_on")
            free = movable_quantity(row["on_hand"], row["reserved"], frozen=row["frozen"])
            row["movable_base"] = amount(free)
            eligible, available = stock_availability(row["on_hand"], row["reserved"], location_kind=row["source_kind"],
                expires_on=expiry, business_today=today, frozen=row["frozen"])
            row["eligible_base"], row["available_base"] = amount(eligible), amount(available)
            row["on_hand"], row["reserved"] = amount(row["on_hand"]), amount(row["reserved"])
        return result

    def snapshot(self, connection, doc):
        return [dict(r) for r in connection.execute(text("""SELECT p.* FROM wms.move_line p
            JOIN wms.document_line l ON l.id=p.document_line_id WHERE l.document_id=:id ORDER BY l.line_no"""),
                                                     {"id": doc["id"]}).mappings()]

    def lock_sources(self, auth, doc=None, decisions=()):
        ids = set(decisions)
        if doc:
            ids.update(r["quality_decision_id"] for r in self.snapshot(auth.connection, doc) if r["quality_decision_id"])
        receipts, parents = set(), set()
        for qid in sorted(ids):
            source = one(auth.connection, """SELECT t.document_id FROM wms.quality_decision q
                JOIN wms.stock_move m ON m.id=q.receipt_move_id JOIN wms.inventory_transaction t ON t.id=m.transaction_id
                WHERE q.id=:id""", id=qid)
            if not source:
                raise DomainError("NOT_FOUND", "Không tìm thấy quyết định chất lượng.")
            receipt = self.orders.document(auth, source["document_id"], "RECEIPT")
            parent = self.orders.receipts.source(auth, receipt)
            receipts.add(receipt["id"])
            if parent:
                parents.add(parent["id"])
        for tier in [parents, receipts]:
            for doc_id in sorted(tier):
                auth.connection.execute(text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": doc_id})

    def saved_lines(self, connection, doc):
        return [dict(row) for row in connection.execute(text("""SELECT p.*,l.product_id,l.owner_id,l.consignment_id,
            l.base_quantity AS quantity_base,l.uom_id,l.source_line_id FROM wms.move_line p
            JOIN wms.document_line l ON l.id=p.document_line_id WHERE l.document_id=:id ORDER BY l.line_no"""),
                                                       {"id": doc["id"]}).mappings()]

    def validate_lines(self, auth, warehouse_id, business_date, lines, *, lock=False):
        c = auth.connection
        active_reference(c, "warehouse", warehouse_id, "warehouse_id")
        locations = location_tree(c, warehouse_id, {x.source_location_id for x in lines} |
                                  {x.destination_location_id for x in lines}, lock=lock)
        stocks = {}
        for item_id in sorted({x.stock_item_id for x in lines}):
            stock = one(c, "SELECT * FROM wms.stock_item WHERE id=:id", id=item_id)
            if not stock:
                raise DomainError("NOT_FOUND", "Không tìm thấy danh tính tồn.")
            validate_ownership(c, owner_id=stock["owner_id"], consignment_id=stock["consignment_id"],
                               warehouse_id=warehouse_id, business_date=business_date)
            stocks[item_id] = stock
        if lock:
            for product_id in sorted({r["product_id"] for r in stocks.values()}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product_id})
        prepared, decisions, serials = [], defaultdict(Decimal), set()
        today = self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
        for spec in lines:
            stock = stocks[spec.stock_item_id]
            product = active_reference(c, "product", stock["product_id"], "product_id")
            unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
            qty = Decimal(spec.quantity_base)
            if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Lượng chuyển không đúng độ chính xác đơn vị cơ sở.")
            if lock:
                resolved = resolve_stock_identity(c, product_id=stock["product_id"], owner_id=stock["owner_id"],
                    warehouse_id=warehouse_id, business_date=business_date, lot_id=stock["lot_id"], serial_id=stock["serial_id"], consignment_id=stock["consignment_id"])
                if resolved != spec.stock_item_id:
                    raise DomainError("TRACKING_MISMATCH", "Danh tính tồn không khớp lô/serial/chủ hàng.")
            source, destination = locations[spec.source_location_id], locations[spec.destination_location_id]
            if source["id"] == destination["id"]:
                raise DomainError("INVALID_LOCATION", "Nguồn và đích phải khác nhau.")
            if stock["lot_id"]:
                lot = one(c, "SELECT * FROM wms.lot WHERE id=:id", id=stock["lot_id"])
                if not lot or lot["product_id"] != product["id"]:
                    raise DomainError("TRACKING_MISMATCH", "Lô không thuộc sản phẩm.")
                if destination["kind"] == "STORAGE" and lot["expires_on"] and lot["expires_on"] < today:
                    raise DomainError("LOT_EXPIRED", "Lô hết hạn không được cất vào STORAGE; phải cách ly.")
            if product["tracking"] == "SERIAL":
                if qty != 1 or not stock["serial_id"] or stock["serial_id"] in serials:
                    raise DomainError("TRACKING_MISMATCH", "Mỗi serial một dòng, lượng 1, không lặp.")
                serials.add(stock["serial_id"])
            source_line = None
            if spec.quality_decision_id:
                q = one(c, """SELECT q.*,m.stock_item_id,m.destination_location_id,m.line_id FROM wms.quality_decision q
                    JOIN wms.stock_move m ON m.id=q.receipt_move_id
                    WHERE q.id=:id AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)""",
                        id=spec.quality_decision_id)
                if not q or q["stock_item_id"] != spec.stock_item_id or q["destination_location_id"] != spec.source_location_id:
                    raise DomainError("SOURCE_MISMATCH", "Quyết định không khớp hàng/lô/serial/chủ hàng/vị trí nguồn.")
                target = "STORAGE" if q["result"] == "ACCEPT" else "QUARANTINE"
                if source["kind"] not in {"RECEIVING", "QUARANTINE"} or destination["kind"] != target:
                    raise DomainError("QUALITY_REQUIRED", "Hàng đạt đi STORAGE; hàng lỗi đi QUARANTINE từ đúng lần nhận.")
                decisions[q["id"]] += qty
                if decisions[q["id"]] > q["quantity"] - decision_moved(c, q["id"]):
                    raise DomainError("SOURCE_EXCEEDED", "Vượt lượng còn cất/chuyển của quyết định chất lượng.")
                source_line = q["line_id"]
            elif source["kind"] != "STORAGE" or destination["kind"] not in {"STORAGE", "QUARANTINE"}:
                raise DomainError("QUALITY_REQUIRED", "Nguồn nhận/cách ly cần quyết định chất lượng trước khi cất/chuyển.")
            prepared.append({"spec": spec, "stock": stock, "product": product, "qty": qty, "source_line": source_line})
        return prepared

    def saved_plan(self, auth, doc):
        rows = self.saved_lines(auth.connection, doc)
        if not rows or len(rows) != auth.connection.execute(text("SELECT count(*) FROM wms.document_line WHERE document_id=:id"), {"id": doc["id"]}).scalar_one():
            raise DomainError("UNSUPPORTED_MOVE", "Thiếu kế hoạch typed cho phiếu di chuyển.")
        specs = [MoveLineInput(**{k: amount(r[k]) if k == "quantity_base" else r[k] for k in MoveLineInput.model_fields}) for r in rows]
        return rows, specs

    @staticmethod
    def match_saved(rows, prepared):
        for row, p in zip(rows, prepared):
            if (row["product_id"], row["owner_id"], row["consignment_id"], row["uom_id"], row["source_line_id"]) != (
                p["stock"]["product_id"], p["stock"]["owner_id"], p["stock"]["consignment_id"], p["product"]["base_uom_id"], p["source_line"]):
                raise DomainError("SOURCE_MISMATCH", "Dòng chuyển không khớp danh tính/kế hoạch.")

    def validate_saved(self, auth, doc):
        rows, specs = self.saved_plan(auth, doc)
        prepared = self.validate_lines(auth, doc["warehouse_id"], doc["business_date"], specs)
        self.match_saved(rows, prepared)

    def read(self, auth, doc_id):
        view = self.orders.read(auth, doc_id, "INTERNAL_MOVE")
        rows = auth.connection.execute(text("""SELECT p.*,l.base_quantity AS quantity_base,src.code AS source_code,
            dst.code AS destination_code,lot.code AS lot_code,s.code AS serial_code FROM wms.move_line p
            JOIN wms.document_line l ON l.id=p.document_line_id JOIN wms.stock_item i ON i.id=p.stock_item_id
            JOIN wms.location src ON src.id=p.source_location_id JOIN wms.location dst ON dst.id=p.destination_location_id
            LEFT JOIN wms.lot lot ON lot.id=i.lot_id LEFT JOIN wms.serial s ON s.id=i.serial_id
            WHERE l.document_id=:id ORDER BY l.line_no"""), {"id": doc_id}).mappings()
        plans = [MovePlan(**{**r, "quantity_base": amount(r["quantity_base"])}) for r in rows]
        actions = list(view.allowed_actions)
        if view.status == "APPROVED" and auth.allows("move.post", view.warehouse_id):
            actions.append("post")
        return MoveView(**{**view.model_dump(), "allowed_actions": actions}, plan=plans)

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}
        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            auth.require("document.read", payload.warehouse_id, hidden=True)
            auth.require("move.draft", payload.warehouse_id)
            if doc_id:
                self.orders.may_edit(auth, self.orders.document(auth, doc_id, "INTERNAL_MOVE"))
            context["auth"] = auth
        def handle(uow):
            c, auth = uow.connection, context["auth"]
            old = self.orders.document(auth, doc_id, "INTERNAL_MOVE") if doc_id else None
            self.lock_sources(auth, old, {r.quality_decision_id for r in payload.lines if r.quality_decision_id})
            if old:
                old = self.orders.document(auth, doc_id, "INTERNAL_MOVE", lock=True)
                require_version(old["version"], payload.expected_version)
                if old["status"] not in {"DRAFT", "REJECTED"} or old["warehouse_id"] != payload.warehouse_id:
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp/từ chối và không đổi kho.")
                self.orders.no_dependencies(c, doc_id, edit=True)
                if old["attributes"]:
                    raise DomainError("UNSUPPORTED_MOVE", "Không ghi đè attributes của phiếu cũ.")
            prepared = self.validate_lines(auth, payload.warehouse_id, payload.business_date, payload.lines)
            if old:
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                doc = {**old, "status": "DRAFT", "version": old["version"] + 1}
                c.execute(text("UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,reason=:reason WHERE id=:id"),
                          {**doc, "day": payload.business_date, "reason": payload.reason})
            else:
                sequence = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                doc = dict(id=uuid4(), number=f"MOV-{payload.business_date:%Y%m%d}-{sequence:08d}", kind="INTERNAL_MOVE",
                           status="DRAFT", warehouse_id=payload.warehouse_id, version=1)
                c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'INTERNAL_MOVE','DRAFT',:warehouse_id,:day,:actor,:now,1,'{}',:reason)"""),
                          {**doc, "day": payload.business_date, "actor": actor, "now": self.identity.clock(), "reason": payload.reason})
            for index, item in enumerate(prepared, 1):
                spec, stock, product = item["spec"], item["stock"], item["product"]
                line_id = uuid4()
                c.execute(text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,
                    factor_snapshot,base_quantity,source_line_id,owner_id,consignment_id)
                    VALUES (:id,:doc,:index,:product,:unit,:qty,1,:qty,:source,:owner,:agreement)"""),
                    {"id": line_id, "doc": doc["id"], "index": index, "product": product["id"], "unit": product["base_uom_id"],
                     "qty": item["qty"], "source": item["source_line"], "owner": stock["owner_id"], "agreement": stock["consignment_id"]})
                c.execute(text("""INSERT INTO wms.move_line VALUES (:id,:stock,:source,:destination,:quality)"""),
                          {"id": line_id, "stock": spec.stock_item_id, "source": spec.source_location_id,
                           "destination": spec.destination_location_id, "quality": spec.quality_decision_id})
            result = OrderResult(**{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                                 request_id=request_id).model_dump(mode="json")
            self.orders.effects(c, actor, doc, "move.update" if old else "move.create", result, payload.reason, request_id)
            return CommandResult(result, 200 if old else 201)
        return self.bus.execute(actor_id=actor, key=key, command="move.update" if doc_id else "move.create",
            resource_id=doc_id or UUID(int=0), payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        digest = payload_hash("move.post", doc_id, payload.model_dump(mode="json"))
        context = {}
        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            doc = self.orders.document(auth, doc_id, "INTERNAL_MOVE")
            auth.require("move.post", doc["warehouse_id"])
            context["auth"] = auth
        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "INTERNAL_MOVE", lock=True)
            executed = one(c, "SELECT * FROM wms.inventory_transaction WHERE document_id=:id AND execution_key=:key",
                           id=doc_id, key=payload.execution_key)
            if executed:
                if executed["posted_by"] != actor or executed["request_hash"] != digest or not executed["response"]:
                    raise DomainError("EXECUTION_MISMATCH", "Execution key đã dùng với người/nội dung khác.")
                return CommandResult(executed["response"])
            require_version(doc["version"], payload.expected_version)
            self.orders.receipts.approved(c, doc)
            rows, specs = self.saved_plan(auth, doc)
            lock_open_period(c, doc["warehouse_id"], doc["business_date"])
            prepared = self.validate_lines(auth, doc["warehouse_id"], doc["business_date"], specs, lock=True)
            self.match_saved(rows, prepared)
            pairs = {(r.stock_item_id, r.source_location_id) for r in specs} | {(r.stock_item_id, r.destination_location_id) for r in specs}
            balances = {}
            for stock_id, location_id in sorted(pairs, key=lambda p: (p[1], p[0])):
                c.execute(text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                    VALUES (:id,:stock,:location,0,0,1) ON CONFLICT (stock_item_id,location_id) DO NOTHING"""),
                          {"id": uuid4(), "stock": stock_id, "location": location_id})
                balances[stock_id, location_id] = one(c, "SELECT * FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:location FOR UPDATE",
                                                      stock=stock_id, location=location_id)
            totals = defaultdict(Decimal)
            for item in prepared:
                spec = item["spec"]
                totals[spec.stock_item_id, spec.source_location_id] += item["qty"]
            for pair, qty in sorted(totals.items(), key=lambda item: (item[0][1], item[0][0])):
                balance = balances[pair]
                check_reservations(c, *pair, balance["reserved"])
                if qty > movable_quantity(balance["on_hand"], balance["reserved"]):
                    raise DomainError("INSUFFICIENT_STOCK", "Không đủ hàng chưa giữ chỗ tại nguồn; không di chuyển reservation.")
            for item in prepared:
                serial, spec = item["stock"]["serial_id"], item["spec"]
                if serial:
                    position = one(c, "SELECT * FROM wms.serial_position WHERE serial_id=:id FOR UPDATE", id=serial)
                    physical = c.execute(text("""SELECT COALESCE(SUM(b.on_hand),0) FROM wms.stock_balance b
                        JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id"""), {"id": serial}).scalar_one()
                    if not position or position["location_id"] != spec.source_location_id or physical != 1 or balances[spec.stock_item_id, spec.destination_location_id]["on_hand"] != 0:
                        raise DomainError("SERIAL_POSITION_CONFLICT", "Vị trí/tồn serial đã thay đổi; tải lại.")
            tx = uuid4()
            doc.update(status="COMPLETED", version=doc["version"] + 1)
            result = MovePostResult(**{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                                    transaction_id=tx, request_id=request_id).model_dump(mode="json")
            c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by,request_hash,response)
                VALUES (:id,:doc,:execution,'MOVE',:day,:now,:actor,:hash,CAST(:result AS jsonb))"""),
                      {"id": tx, "doc": doc_id, "execution": payload.execution_key, "day": doc["business_date"],
                       "now": self.identity.clock(), "actor": actor, "hash": digest, "result": encode(result)})
            for row, item in zip(rows, prepared):
                spec, move_id = item["spec"], uuid4()
                c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
                    VALUES (:id,:tx,:line,:stock,:source,:destination,:qty,:unit)"""),
                          {"id": move_id, "tx": tx, "line": row["document_line_id"], "stock": spec.stock_item_id,
                           "source": spec.source_location_id, "destination": spec.destination_location_id,
                           "qty": item["qty"], "unit": item["product"]["base_uom_id"]})
                for location, change in [(spec.source_location_id, -item["qty"]), (spec.destination_location_id, item["qty"])]:
                    c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand+:change,version=version+1 WHERE stock_item_id=:stock AND location_id=:location"),
                              {"stock": spec.stock_item_id, "location": location, "change": change})
                if item["stock"]["serial_id"]:
                    c.execute(text("UPDATE wms.serial_position SET location_id=:location,last_move_id=:move WHERE serial_id=:serial"),
                              {"location": spec.destination_location_id, "move": move_id, "serial": item["stock"]["serial_id"]})
                if spec.quality_decision_id:
                    c.execute(text("UPDATE wms.quality_decision SET followup_document_id=COALESCE(followup_document_id,:doc) WHERE id=:id"),
                              {"id": spec.quality_decision_id, "doc": doc_id})
            c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), doc)
            self.orders.effects(c, actor, doc, "move.post", result, payload.reason, request_id)
            return CommandResult(result)
        return self.bus.execute(actor_id=actor, key=key, command="move.post", resource_id=doc_id,
                                payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def operation(self, auth, key):
        record = one(auth.connection, "SELECT response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key AND command='move.post'",
                     actor=auth.principal.user_id, key=key)
        if not record:
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK; chỉ gửi lại cùng key và nội dung.")
        result = record["response"]
        doc = self.orders.document(auth, UUID(result["id"]), "INTERNAL_MOVE")
        auth.require("move.post", doc["warehouse_id"])
        return OperationView(**{k: result[k] for k in ["id", "status", "version", "request_id", "transaction_id"]})
