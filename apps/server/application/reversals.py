"""Reviewed full-transaction inverses; originals and reservations stay immutable."""
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application import reversal_stock as stock
from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import one
from apps.server.application.orders import amount, encode
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.reversals import ReversalLine, ReversalResult, ReversalSource, ReversalView

OPERATIONS = {"RECEIPT": {"RECEIVE"}, "OPENING": {"OPEN"}, "ISSUE": {"ISSUE"},
    "INTERNAL_MOVE": {"MOVE"}, "TRANSFER": {"DISPATCH", "ARRIVE"},
    "CUSTOMER_RETURN": {"RECEIVE"}, "SUPPLIER_RETURN": {"ISSUE"}, "ADJUSTMENT": {"ADJUST"}}


class ReversalService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.reversals = self

    @staticmethod
    def metadata(c, doc_id):
        meta = one(c, "SELECT * FROM wms.reversal_document WHERE document_id=:id", id=doc_id)
        if not meta:
            raise DomainError("UNSUPPORTED_REVERSAL", "Phiếu đảo thiếu liên kết giao dịch gốc.")
        return meta

    def source(self, auth, tx_id):
        c = auth.connection
        tx = one(c, "SELECT * FROM wms.inventory_transaction WHERE id=:id", id=tx_id)
        if not tx:
            raise DomainError("NOT_FOUND", "Không tìm thấy lần ghi sổ.")
        doc = auth.document(tx["document_id"])
        warehouses = {doc["warehouse_id"]}
        if doc["kind"] == "REVERSAL":
            original = self.metadata(c, doc["id"])
            parent_tx = one(c, "SELECT * FROM wms.inventory_transaction WHERE id=:id", id=original["source_transaction_id"])
            if not parent_tx or parent_tx["operation"] == "REVERSE":
                raise DomainError("UNSUPPORTED_REVERSAL", "Liên kết phiếu đảo không hợp lệ.")
            warehouses.update(self.source(auth, parent_tx["id"])[2])
        if doc["destination_warehouse_id"]:
            warehouses.add(doc["destination_warehouse_id"])
        count = one(c, "SELECT * FROM wms.count_session WHERE adjustment_document_id=:id", id=doc["id"])
        if count:
            auth.require("count.snapshot.read", doc["warehouse_id"], hidden=True)
            if one(c, "SELECT id FROM wms.count_assignment WHERE session_id=:id AND user_id=:user LIMIT 1",
                   id=count["id"], user=auth.principal.user_id):
                raise DomainError("NOT_FOUND", "Người đếm không được đọc số liệu điều chỉnh của phiên đếm mù.")
        loss = one(c, "SELECT * FROM wms.transfer_adjustment WHERE document_id=:id", id=doc["id"])
        if loss:
            parent = auth.document(loss["source_transfer_id"])
            if parent["kind"] != "TRANSFER" or not parent["destination_warehouse_id"]:
                raise DomainError("UNSUPPORTED_SOURCE", "Điều chỉnh mất hàng thiếu lệnh chuyển kho hợp lệ.")
            warehouses.update([parent["warehouse_id"], parent["destination_warehouse_id"]])
        for warehouse in warehouses:
            auth.require("document.read", warehouse, hidden=True)
        return tx, doc, warehouses

    def scope(self, auth, doc):
        meta = self.metadata(auth.connection, doc["id"])
        return self.source(auth, meta["source_transaction_id"])[2]

    def lifecycle(self, auth, doc, action):
        permission = "adjustment.approve" if action == "decide" else (
            "adjustment.post" if action == "post" else "document.assign" if action == "assign" else
            "document.cancel" if action in {"cancel", "close"} else "adjustment.draft")
        for warehouse in self.scope(auth, doc):
            auth.require(permission, warehouse)

    def lock_source(self, auth, tx_id):
        """Lock ancestors by level, then source; count session precedes its ADJUSTMENT.

        Source links are immutable once posted. Re-read them under the source locks
        before validation; never obtain a parent document lock after a child.
        """
        c = auth.connection
        _, doc, _ = self.source(auth, tx_id)
        levels, visiting = {}, set()

        def visit(doc_id):
            if doc_id in visiting or len(visiting) > 32:
                raise DomainError("SOURCE_MISMATCH", "Liên kết nguồn có chu kỳ hoặc quá sâu.")
            if doc_id in levels:
                return levels[doc_id]
            visiting.add(doc_id)
            parents = c.execute(text("""SELECT parent.document_id FROM wms.document_line child
                JOIN wms.document_line parent ON parent.id=child.source_line_id WHERE child.document_id=:id
                UNION SELECT source_document_id FROM wms.return_document WHERE document_id=:id
                UNION SELECT source_transfer_id FROM wms.transfer_adjustment WHERE document_id=:id
                UNION SELECT t.document_id FROM wms.move_line ml JOIN wms.document_line l ON l.id=ml.document_line_id
                    JOIN wms.quality_decision q ON q.id=ml.quality_decision_id JOIN wms.stock_move m ON m.id=q.receipt_move_id
                    JOIN wms.inventory_transaction t ON t.id=m.transaction_id WHERE l.document_id=:id"""),
                    {"id": doc_id}).scalars().all()
            level = max((visit(parent) + 1 for parent in sorted(set(parents))), default=0)
            levels[doc_id] = level
            visiting.remove(doc_id)
            return level

        visit(doc["id"])
        for doc_id in sorted(levels, key=lambda key: (levels[key], key)):
            c.execute(text("SELECT id FROM wms.count_session WHERE adjustment_document_id=:id ORDER BY id FOR UPDATE"), {"id": doc_id})
            c.execute(text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": doc_id})
        return self.source(auth, tx_id)

    def lock_sources(self, auth, doc):
        return self.lock_source(auth, self.metadata(auth.connection, doc["id"])["source_transaction_id"])

    @staticmethod
    def source_view(c, tx, doc):
        rev = one(c, "SELECT id FROM wms.inventory_transaction WHERE reverses_transaction_id=:id", id=tx["id"])
        return ReversalSource(id=tx["id"], document_id=doc["id"], document_number=doc["number"], document_kind=doc["kind"],
            source_version=doc["version"], warehouse_id=doc["warehouse_id"], operation=tx["operation"],
            business_date=tx["business_date"], reversal_transaction_id=rev["id"] if rev else None)

    @staticmethod
    def plan(rows):
        return [ReversalLine(**{k: amount(r[k]) if k == "quantity_base" else r[k] for k in ReversalLine.model_fields}) for r in rows]

    def available(self, c, tx, doc, rows):
        if tx["operation"] == "REVERSE" or tx["reverses_transaction_id"] or doc["kind"] == "REVERSAL":
            raise DomainError("REVERSAL_OF_REVERSAL", "Không đảo một phiếu đảo; dùng chứng từ bù được duyệt.")
        if one(c, "SELECT id FROM wms.inventory_transaction WHERE reverses_transaction_id=:id", id=tx["id"]):
            raise DomainError("ALREADY_REVERSED", "Lần ghi sổ đã được đảo.")
        if tx["operation"] not in OPERATIONS.get(doc["kind"], set()):
            raise DomainError("UNSUPPORTED_SOURCE", "Loại nguồn chưa đủ chứng cứ để đảo.")
        if not rows:
            raise DomainError("EMPTY_TRANSACTION", "Giao dịch không có phát sinh tồn để đảo.")
        if len(rows) > 2000:
            raise DomainError("REVERSAL_LIMIT", "Giao dịch vượt giới hạn 2000 dòng đảo.")
        # Old ledgers may predate typed execution plans. Never infer missing
        # provenance from the document kind or the current quantity alone.
        metadata = {"OPENING": "opening_document", "ISSUE": "issue_document",
                    "CUSTOMER_RETURN": "return_document", "SUPPLIER_RETURN": "return_document"}.get(doc["kind"])
        if metadata and not one(c, f"SELECT document_id FROM wms.{metadata} WHERE document_id=:id", id=doc["id"]):
            raise DomainError("UNSUPPORTED_SOURCE", "Nguồn cũ thiếu kế hoạch nghiệp vụ đã xác minh.")
        plan = {"OPENING": "opening_line", "INTERNAL_MOVE": "move_line", "TRANSFER": "transfer_line",
                "CUSTOMER_RETURN": "return_line", "SUPPLIER_RETURN": "return_line"}.get(doc["kind"])
        if plan and any(not one(c, f"SELECT document_line_id FROM wms.{plan} WHERE document_line_id=:id", id=r["original_line_id"]) for r in rows):
            raise DomainError("UNSUPPORTED_SOURCE", "Nguồn cũ thiếu liên kết dòng thực hiện.")
        if doc["kind"] == "RECEIPT" and not any(r["consignment_id"] for r in rows):
            try:
                parent = UUID(doc["attributes"]["receipt_plan"]["source_order_id"])
            except (KeyError, TypeError, ValueError):
                raise DomainError("UNSUPPORTED_SOURCE", "Phiếu nhận cũ thiếu kế hoạch PO đã xác minh.") from None
            if any(not one(c, """SELECT l.id FROM wms.document_line l JOIN wms.document_line p ON p.id=l.source_line_id
                JOIN wms.document d ON d.id=p.document_id WHERE l.id=:id AND d.id=:parent AND d.kind='PO'""",
                id=r["original_line_id"], parent=parent) for r in rows):
                raise DomainError("SOURCE_MISMATCH", "Dòng nhận không khớp PO nguồn.")
        if doc["kind"] in {"CUSTOMER_RETURN", "SUPPLIER_RETURN"} and one(c, """SELECT r.document_line_id
            FROM wms.return_line r JOIN wms.document_line l ON l.id=r.document_line_id
            JOIN wms.stock_move inverse ON inverse.reverses_move_id=r.source_move_id WHERE l.document_id=:id LIMIT 1""", id=doc["id"]):
            raise DomainError("SOURCE_MISMATCH", "Nguồn trả hàng đã bị đảo.")
        if doc["kind"] == "TRANSFER" and (not doc["transit_location_id"] or any(
            not one(c, "SELECT move_id FROM wms.transfer_move WHERE move_id=:id", id=r["source_move_id"]) for r in rows)):
            raise DomainError("UNSUPPORTED_SOURCE", "Chuyển kho thiếu liên kết transit/phát sinh đã xác minh.")
        if doc["kind"] == "ADJUSTMENT" and not (
            one(c, "SELECT id FROM wms.count_session WHERE adjustment_document_id=:id AND status='POSTED'", id=doc["id"]) or
            one(c, "SELECT document_id FROM wms.transfer_adjustment WHERE document_id=:id", id=doc["id"])
        ):
            raise DomainError("UNSUPPORTED_SOURCE", "Điều chỉnh cũ thiếu nguồn kiểm kê/chuyển kho đã xác minh.")

    def check(self, auth, tx, doc, warehouses, day, rows, *, lock=False):
        self.available(auth.connection, tx, doc, rows)
        stock.validate_route(auth.connection, warehouses, tx["business_date"], day, rows, lock=lock)
        return stock.prepare(auth.connection, tx, rows, stock.business_today(self.identity), lock=lock)

    def preview(self, auth, tx_id, day):
        tx, doc, warehouses = self.source(auth, tx_id)
        rows, blockers = stock.moves(auth.connection, tx_id), []
        try:
            self.check(auth, tx, doc, warehouses, day, rows)
        except DomainError as exc:
            blockers.append(dict(code=exc.code, message=exc.message))
        return dict(source=self.source_view(auth.connection, tx, doc), business_date=day,
            warehouse_ids=sorted(warehouses), eligible=not blockers, blockers=blockers,
            plan=self.plan(rows), effects=stock.effects(auth.connection, rows))

    def sources(self, auth, warehouse_id, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        ids = auth.connection.execute(text("""SELECT t.id FROM wms.inventory_transaction t JOIN wms.document d ON d.id=t.document_id
            WHERE d.warehouse_id=:warehouse
            AND (CAST(:after AS uuid) IS NULL OR t.id>:after) ORDER BY t.id LIMIT :limit"""),
            dict(warehouse=warehouse_id, after=after, limit=limit + 1)).scalars().all()
        items = []
        for tx_id in ids[:limit]:
            try:
                tx, doc, _ = self.source(auth, tx_id)
                items.append(self.source_view(auth.connection, tx, doc))
            except DomainError as exc:
                if exc.code not in {"NOT_FOUND", "FORBIDDEN"}:
                    raise
        return dict(items=items, next_after=ids[limit - 1] if len(ids) > limit else None)

    def listing(self, auth, warehouse_id, status=None, after=None, limit=50):
        result = self.orders.listing(auth, "REVERSAL", warehouse_id, status, after, limit)
        visible = []
        for item in result["items"]:
            try:
                self.orders.document(auth, item.id, "REVERSAL")
                visible.append(item)
            except DomainError as exc:
                if exc.code not in {"NOT_FOUND", "FORBIDDEN"}:
                    raise
        return {**result, "items": visible}

    def snapshot(self, c, doc):
        return {"source": self.metadata(c, doc["id"]), "lines": [dict(r) for r in c.execute(text("""SELECT r.*
            FROM wms.reversal_line r JOIN wms.document_line l ON l.id=r.document_line_id
            WHERE l.document_id=:id ORDER BY l.line_no"""), {"id": doc["id"]}).mappings()]}

    def validate_saved(self, auth, doc, *, lock=False):
        c = auth.connection
        meta = self.metadata(c, doc["id"])
        tx, source, warehouses = self.source(auth, meta["source_transaction_id"])
        rows = stock.moves(c, tx["id"])
        self.available(c, tx, source, rows)
        if source["version"] != meta["source_version"]:
            raise DomainError("STALE_SOURCE", "Chứng từ gốc đã đổi; sửa nháp và xem lại ảnh hưởng trước khi gửi duyệt.")
        stored = c.execute(text("""SELECT l.*,r.source_move_id FROM wms.document_line l
            LEFT JOIN wms.reversal_line r ON r.document_line_id=l.id WHERE l.document_id=:id ORDER BY l.line_no"""),
            {"id": doc["id"]}).mappings().all()
        if len(stored) != len(rows) or doc["warehouse_id"] != source["warehouse_id"]:
            raise DomainError("SOURCE_MISMATCH", "Phiếu đảo không chứa đầy đủ giao dịch gốc.")
        line_ids = {}
        for line, row in zip(stored, rows):
            if (line["source_move_id"], line["source_line_id"], line["product_id"], line["uom_id"],
                line["owner_id"], line["consignment_id"], line["quantity"], line["base_quantity"], line["factor_snapshot"]) != (
                row["source_move_id"], row["original_line_id"], row["product_id"], row["base_uom_id"],
                row["owner_id"], row["consignment_id"], row["quantity_base"], row["quantity_base"], 1):
                raise DomainError("SOURCE_MISMATCH", "Dòng đảo phải khớp chính xác số lượng/danh tính của dòng gốc.")
            line_ids[row["source_move_id"]] = line["id"]
        projected, positions = self.check(auth, tx, source, warehouses, doc["business_date"], rows, lock=lock)
        return tx, source, rows, line_ids, projected, positions

    def read(self, auth, doc_id):
        view = self.orders.read(auth, doc_id, "REVERSAL")
        doc = self.orders.document(auth, doc_id, "REVERSAL")
        meta = self.metadata(auth.connection, doc_id)
        posted = one(auth.connection, "SELECT id FROM wms.inventory_transaction WHERE document_id=:id AND operation='REVERSE'", id=doc_id)
        actions = list(view.allowed_actions)
        if view.status == "APPROVED":
            try:
                self.lifecycle(auth, doc, "post")
                actions.append("post")
            except DomainError:
                pass
        return ReversalView(**{**view.model_dump(), "allowed_actions": actions},
            source_transaction_id=meta["source_transaction_id"],
            source_document_id=self.source(auth, meta["source_transaction_id"])[1]["id"],
            source_version=meta["source_version"], reversal_reason=meta["reversal_reason"],
            transaction_id=posted["id"] if posted else None,
            plan=self.plan(stock.moves(auth.connection, meta["source_transaction_id"])),
            preview=self.preview(auth, meta["source_transaction_id"], doc["business_date"]))

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            _, _, warehouses = self.source(auth, payload.source_transaction_id)
            for warehouse in warehouses:
                auth.require("adjustment.draft", warehouse)
            if doc_id:
                self.orders.may_edit(auth, self.orders.document(auth, doc_id, "REVERSAL"))
                if self.metadata(auth.connection, doc_id)["source_transaction_id"] != payload.source_transaction_id:
                    raise DomainError("SOURCE_MISMATCH", "Không đổi giao dịch gốc của phiếu đảo đã tạo.")
            context["auth"] = auth

        def handle(uow):
            auth, c = context["auth"], uow.connection
            tx, source, warehouses = self.lock_source(auth, payload.source_transaction_id)
            rows = stock.moves(c, tx["id"])
            self.available(c, tx, source, rows)
            if source["version"] != payload.source_version:
                raise DomainError("STALE_SOURCE", "Nguồn đã thay đổi; tải lại preview.")
            doc = self.orders.document(auth, doc_id, "REVERSAL", lock=True) if doc_id else None
            if doc:
                require_version(doc["version"], payload.expected_version)
                self.orders.may_edit(auth, doc)
                if doc["status"] not in {"DRAFT", "REJECTED"}:
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp hoặc phiếu bị từ chối.")
            self.check(auth, tx, source, warehouses, payload.business_date, rows)
            if doc:
                self.orders.no_dependencies(c, doc_id, edit=True)
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                doc.update(status="DRAFT", version=doc["version"] + 1)
                c.execute(text("UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,reason=:reason WHERE id=:id"),
                          {**doc, "day": payload.business_date, "reason": payload.reason})
                c.execute(text("UPDATE wms.reversal_document SET source_version=:version,reversal_reason=:reason WHERE document_id=:id"),
                          dict(id=doc_id, version=payload.source_version, reason=payload.reason))
            else:
                seq = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                doc = dict(id=uuid4(), number=f"REV-{payload.business_date:%Y%m%d}-{seq:08d}", kind="REVERSAL",
                           status="DRAFT", warehouse_id=source["warehouse_id"], version=1)
                c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'REVERSAL','DRAFT',:warehouse_id,:day,:actor,:now,1,'{}',:reason)"""),
                          {**doc, "day": payload.business_date, "actor": actor, "now": self.identity.clock(), "reason": payload.reason})
                c.execute(text("INSERT INTO wms.reversal_document VALUES (:id,:tx,:version,:reason)"),
                          dict(id=doc["id"], tx=tx["id"], version=payload.source_version, reason=payload.reason))
                c.execute(text("INSERT INTO wms.document_link VALUES (:id,:doc,:source,'REVERSAL_OF')"),
                          dict(id=uuid4(), doc=doc["id"], source=source["id"]))
            for n, r in enumerate(rows, 1):
                line_id = uuid4()
                c.execute(text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,
                    base_quantity,source_line_id,owner_id,consignment_id)
                    VALUES (:id,:doc,:n,:product,:unit,:qty,1,:qty,:source,:owner,:agreement)"""),
                    dict(id=line_id, doc=doc["id"], n=n, product=r["product_id"], unit=r["base_uom_id"], qty=r["quantity_base"],
                         source=r["original_line_id"], owner=r["owner_id"], agreement=r["consignment_id"]))
                c.execute(text("INSERT INTO wms.reversal_line VALUES (:id,:move)"), dict(id=line_id, move=r["source_move_id"]))
            result = ReversalResult(**{k: doc[k] for k in ("id", "number", "kind", "warehouse_id", "status", "version")},
                source_transaction_id=tx["id"], request_id=request_id).model_dump(mode="json")
            self.orders.effects(c, actor, doc, "reversal.update" if doc_id else "reversal.create", result, payload.reason, request_id)
            return CommandResult(result, 200 if doc_id else 201)

        return self.bus.execute(actor_id=actor, key=key, command="reversal.update" if doc_id else "reversal.create",
            resource_id=doc_id or UUID(int=0), payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        digest, context = payload_hash("reversal.post", doc_id, payload.model_dump(mode="json")), {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            doc = self.orders.document(auth, doc_id, "REVERSAL")
            self.lifecycle(auth, doc, "post")
            context["auth"] = auth

        def handle(uow):
            auth, c = context["auth"], uow.connection
            doc = self.orders.document(auth, doc_id, "REVERSAL", lock=True)
            saved = one(c, "SELECT * FROM wms.inventory_transaction WHERE document_id=:id AND execution_key=:key",
                        id=doc_id, key=payload.execution_key)
            if saved:
                if saved["posted_by"] != actor or saved["request_hash"] != digest or not saved["response"]:
                    raise DomainError("EXECUTION_MISMATCH", "Execution key đã dùng với nội dung hoặc người khác.")
                return CommandResult(saved["response"])
            require_version(doc["version"], payload.expected_version)
            self.orders.receipts.approved(c, doc)
            tx, source, rows, line_ids, projected, positions = self.validate_saved(auth, doc, lock=True)
            transaction = uuid4()
            doc.update(status="COMPLETED", version=doc["version"] + 1)
            result = ReversalResult(**{k: doc[k] for k in ("id", "number", "kind", "warehouse_id", "status", "version")},
                source_transaction_id=tx["id"], transaction_id=transaction, request_id=request_id).model_dump(mode="json")
            c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,
                posted_at,posted_by,reverses_transaction_id,request_hash,response)
                VALUES (:id,:doc,:key,'REVERSE',:day,:now,:actor,:original,:hash,CAST(:response AS jsonb))"""),
                dict(id=transaction, doc=doc_id, key=payload.execution_key, day=doc["business_date"], now=self.identity.clock(),
                     actor=actor, original=tx["id"], hash=digest, response=encode(result)))
            stock.write(c, transaction, rows, line_ids, projected, positions)
            c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), doc)
            # Versions invalidate stale UI/approval snapshots. Header state, closed
            # quantities, counts and historical reservation consumption stay intact.
            c.execute(text("UPDATE wms.document SET version=version+1 WHERE id=:id"), {"id": source["id"]})
            self.orders.effects(c, actor, doc, "reversal.post", result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(actor_id=actor, key=key, command="reversal.post", resource_id=doc_id,
            payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def operation(self, auth, key):
        saved = one(auth.connection, "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
                    actor=auth.principal.user_id, key=key)
        if not saved or saved["response"].get("kind") != "REVERSAL" or not (
            saved["command"].startswith("reversal.") or saved["command"].startswith("order.None.")):
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK của phiếu đảo.")
        result = saved["response"]
        doc = self.orders.document(auth, UUID(result["id"]), "REVERSAL")
        action = saved["command"].rsplit(".", 1)[-1]
        self.lifecycle(auth, doc, action)
        if action not in {"post", "decide", "assign", "cancel", "close"}:
            self.orders.may_edit(auth, doc)
        return dict(command=saved["command"], result={**result,
            "source_transaction_id": self.metadata(auth.connection, doc["id"])["source_transaction_id"]})
