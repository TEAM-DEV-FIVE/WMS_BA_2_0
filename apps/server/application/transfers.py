"""Approved COMPANY transfers, partial arrivals and independently approved transit losses."""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, one, page
from apps.server.application.move_safety import location_tree
from apps.server.application.orders import SUMMARY_SQL, amount, encode
from apps.server.application.transfer_stock import LOSS, lock_route, prepare_legs, write_legs
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.orders import OrderSummary
from packages.contracts.traceability import COMPANY_OWNER
from packages.contracts.transfers import TransferPostResult, TransferResult, TransferView

PLAN_SQL = """SELECT p.*,l.product_id,l.owner_id,l.consignment_id,l.uom_id,l.base_quantity AS quantity_base,
 i.product_id AS item_product,i.owner_id AS item_owner,i.consignment_id AS item_agreement,
 i.lot_id,i.serial_id,pr.sku,pr.tracking,pr.base_uom_id,o.code AS owner_code,
 lot.code AS lot_code,lot.expires_on,s.code AS serial_code,src.code AS source_code
 FROM wms.transfer_line p JOIN wms.document_line l ON l.id=p.document_line_id
 JOIN wms.stock_item i ON i.id=p.stock_item_id JOIN wms.product pr ON pr.id=i.product_id
 JOIN wms.stock_owner o ON o.id=i.owner_id JOIN wms.location src ON src.id=p.source_location_id
 LEFT JOIN wms.lot lot ON lot.id=i.lot_id LEFT JOIN wms.serial s ON s.id=i.serial_id
 WHERE l.document_id=:id ORDER BY l.line_no"""


class TransferService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.transfers = self

    def execute(self, access, key, name, resource, payload, authorize, handle):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def check(uow):
            auth = self.identity.authorization(uow.connection, access)
            authorize(auth)
            context["auth"] = auth

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command=name,
            resource_id=resource or UUID(int=0),
            payload=payload.model_dump(mode="json"),
            authorize=check,
            handle=lambda uow: handle(context["auth"]),
        )

    @staticmethod
    def both(auth, doc, permission):
        for warehouse in sorted({doc["warehouse_id"], doc["destination_warehouse_id"]}):
            auth.require(permission, warehouse)

    @staticmethod
    def assigned(auth, doc):
        return doc["created_by"] == auth.principal.user_id or bool(
            one(
                auth.connection,
                "SELECT id FROM wms.document_assignment WHERE document_id=:id AND user_id=:user",
                id=doc["id"],
                user=auth.principal.user_id,
            )
        )

    def document(self, auth, doc_id, *, lock=False):
        c = auth.connection
        doc = one(c, "SELECT * FROM wms.document WHERE id=:id AND kind='TRANSFER'", id=doc_id)
        if not doc:
            raise DomainError("NOT_FOUND", "Không tìm thấy lệnh chuyển.")
        grants = [
            g
            for w in [doc["warehouse_id"], doc["destination_warehouse_id"]]
            for g in auth.grants("document.read", w)
        ]
        if not grants or not (
            any(g["role_code"] not in {"PICKER", "RECEIVER"} for g in grants) or self.assigned(auth, doc)
        ):
            raise DomainError("NOT_FOUND", "Không tìm thấy lệnh chuyển trong phạm vi được giao.")
        if lock:
            c.execute(text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": doc_id})
            return self.document(auth, doc_id)
        return doc

    def loss_parent(self, auth, doc, *, lock=False):
        link = one(
            auth.connection, "SELECT * FROM wms.transfer_adjustment WHERE document_id=:id", id=doc["id"]
        )
        if not link:
            raise DomainError("NOT_FOUND", "Chỉ hỗ trợ điều chỉnh mất hàng có nguồn TRANSFER.")
        parent = self.document(auth, link["source_transfer_id"], lock=lock)
        self.both(auth, parent, "document.read")
        return parent, link

    def lifecycle(self, auth, doc, action):
        parent = doc if doc["kind"] == "TRANSFER" else self.loss_parent(auth, doc)[0]
        self.both(auth, parent, "document.read")
        permission = (
            ("document.approve" if doc["kind"] == "TRANSFER" else "adjustment.approve")
            if action == "decide"
            else (
                "document.assign"
                if action == "assign"
                else "document.cancel"
                if action in {"cancel", "close"}
                else "transfer.draft"
                if doc["kind"] == "TRANSFER"
                else "adjustment.draft"
            )
        )
        self.both(auth, parent, permission)

    def may_post(self, auth, doc, operation):
        if operation == "ADJUST":
            parent = self.loss_parent(auth, doc)[0]
            self.both(auth, parent, "adjustment.post")
            return parent
        parent = self.document(auth, doc["id"])
        auth.require(
            "transfer.dispatch" if operation == "DISPATCH" else "transfer.receive",
            parent["warehouse_id"] if operation == "DISPATCH" else parent["destination_warehouse_id"],
        )
        if not self.assigned(auth, parent):
            raise DomainError("FORBIDDEN", "Chỉ người lập hoặc người được giao thực hiện lệnh chuyển.")
        return parent

    def snapshot(self, c, doc):
        if doc["kind"] == "ADJUSTMENT":
            return one(c, "SELECT * FROM wms.transfer_adjustment WHERE document_id=:id", id=doc["id"])
        return {
            "destination_warehouse_id": doc["destination_warehouse_id"],
            "transit_location_id": doc["transit_location_id"],
            "plan": [
                dict(r)
                for r in c.execute(
                    text("""SELECT p.* FROM wms.transfer_line p
                JOIN wms.document_line l ON l.id=p.document_line_id WHERE l.document_id=:id ORDER BY l.line_no"""),
                    {"id": doc["id"]},
                ).mappings()
            ],
        }

    def plans(self, c, doc):
        return [dict(r) for r in c.execute(text(PLAN_SQL), {"id": doc["id"]}).mappings()]

    def validate_saved(self, auth, doc, *, lock_products=False):
        c = auth.connection
        if doc["kind"] == "ADJUSTMENT":
            parent, link = self.loss_parent(auth, doc)
            source, evidence, qty = self.loss_spec(c, doc, parent, link)
            self.check_loss(c, source, evidence, qty)
            return
        if doc["warehouse_id"] == doc["destination_warehouse_id"]:
            raise DomainError("INVALID_WAREHOUSE", "Kho nguồn và đích phải khác nhau.")
        for warehouse in sorted({doc["warehouse_id"], doc["destination_warehouse_id"]}):
            active_reference(c, "warehouse", warehouse, "warehouse_id")
        rows = self.plans(c, doc)
        count = c.execute(
            text("SELECT count(*) FROM wms.document_line WHERE document_id=:id"), {"id": doc["id"]}
        ).scalar_one()
        if not rows or len(rows) != count:
            raise DomainError("INVALID_TRANSFER", "Thiếu kế hoạch chuyển kho đã xác minh.")
        locations = location_tree(c, doc["warehouse_id"], {r["source_location_id"] for r in rows})
        if lock_products:
            # Acquire the strongest product lock before active_reference takes SHARE;
            # opposite routes can otherwise deadlock while upgrading shared locks.
            for product in sorted({r["product_id"] for r in rows}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product})
        today = self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
        serials, pairs = set(), set()
        for r in rows:
            if (
                r["owner_id"] != COMPANY_OWNER
                or r["item_owner"] != COMPANY_OWNER
                or r["consignment_id"]
                or r["item_agreement"]
            ):
                raise DomainError(
                    "OWNERSHIP_UNSUPPORTED", "Chưa có chính sách chuyển kho ký gửi/chưa phân loại."
                )
            active_reference(c, "stock_owner", r["owner_id"], "owner_id")
            active_reference(c, "product", r["product_id"], "product_id")
            unit = active_reference(c, "uom", r["uom_id"], "uom_id")
            if r["product_id"] != r["item_product"] or r["uom_id"] != r["base_uom_id"]:
                raise DomainError("SOURCE_MISMATCH", "Kế hoạch không khớp SKU/đơn vị/danh tính tồn.")
            if locations[r["source_location_id"]]["kind"] != "STORAGE":
                raise DomainError("QUALITY_REQUIRED", "Chỉ xuất chuyển hàng đã cất vào STORAGE.")
            if r["expires_on"] and r["expires_on"] < today:
                raise DomainError("LOT_EXPIRED", "Không xuất chuyển lô hết hạn.")
            if r["quantity_base"] != r["quantity_base"].quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Lượng không đúng độ chính xác đơn vị.")
            pair = r["stock_item_id"], r["source_location_id"]
            if pair in pairs or (r["serial_id"] and (r["quantity_base"] != 1 or r["serial_id"] in serials)):
                raise DomainError("TRACKING_MISMATCH", "Dòng nguồn/serial bị lặp hoặc sai số lượng.")
            pairs.add(pair)
            serials.add(r["serial_id"])

    def sources(self, c, doc_id):
        return [
            dict(r)
            for r in c.execute(
                text("""SELECT m.id AS dispatch_move_id,m.line_id AS document_line_id,
            m.stock_item_id,m.quantity_base AS dispatched,t.business_date AS dispatched_on,i.product_id,i.owner_id,i.consignment_id,i.serial_id,
            p.sku,o.code AS owner_code,lot.code AS lot_code,s.code AS serial_code,m.base_uom_id,
            coalesce((SELECT sum(x.quantity_base) FROM wms.transfer_move a JOIN wms.stock_move x ON x.id=a.move_id
                WHERE a.dispatch_move_id=m.id AND a.disposition IN ('GOOD','DAMAGED')),0) AS received,
            coalesce((SELECT sum(x.quantity_base) FROM wms.transfer_move a JOIN wms.stock_move x ON x.id=a.move_id
                WHERE a.dispatch_move_id=m.id AND a.disposition='LOSS'),0) AS lost
            FROM wms.stock_move m JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='DISPATCH'
            JOIN wms.stock_item i ON i.id=m.stock_item_id JOIN wms.product p ON p.id=i.product_id
            JOIN wms.stock_owner o ON o.id=i.owner_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
            LEFT JOIN wms.serial s ON s.id=i.serial_id WHERE t.document_id=:id ORDER BY m.id"""),
                {"id": doc_id},
            ).mappings()
        ]

    @staticmethod
    def remaining(source):
        return source["dispatched"] - source["received"] - source["lost"]

    def result(self, doc, parent, request_id, **extra):
        model = TransferPostResult if "transaction_id" in extra else TransferResult
        return model(
            **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
            destination_warehouse_id=parent["destination_warehouse_id"],
            source_transfer_id=parent["id"] if doc["kind"] == "ADJUSTMENT" else None,
            request_id=request_id,
            **extra,
        ).model_dump(mode="json")

    def write(self, access, key, payload, request_id, doc_id=None):
        def authorize(auth):
            self.both(auth, payload.model_dump(), "document.read")
            self.both(auth, payload.model_dump(), "transfer.draft")
            if doc_id:
                self.orders.may_edit(auth, self.orders.document(auth, doc_id, "TRANSFER"))

        def handle(auth):
            c = auth.connection
            if doc_id:
                doc = self.orders.document(auth, doc_id, "TRANSFER", lock=True)
                require_version(doc["version"], payload.expected_version)
                if doc["status"] not in {"DRAFT", "REJECTED"} or (
                    doc["warehouse_id"],
                    doc["destination_warehouse_id"],
                ) != (payload.warehouse_id, payload.destination_warehouse_id):
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp/từ chối, không đổi hai kho của phiếu.")
                self.orders.no_dependencies(c, doc_id, edit=True)
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                c.execute(
                    text(
                        "UPDATE wms.document SET business_date=:day,reason=:reason,status='DRAFT',version=version+1 WHERE id=:id"
                    ),
                    {"id": doc_id, "day": payload.business_date, "reason": payload.reason},
                )
                doc = self.document(auth, doc_id)
            else:
                sequence = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                doc = dict(
                    id=uuid4(),
                    number=f"TRF-{payload.business_date:%Y%m%d}-{sequence:08d}",
                    kind="TRANSFER",
                    warehouse_id=payload.warehouse_id,
                    destination_warehouse_id=payload.destination_warehouse_id,
                    transit_location_id=uuid4(),
                    business_date=payload.business_date,
                    status="DRAFT",
                    version=1,
                )
                c.execute(
                    text(
                        "INSERT INTO wms.location(id,code,name,kind,is_active,version) VALUES (:id,:code,:name,'TRANSIT',true,1)"
                    ),
                    {
                        "id": doc["transit_location_id"],
                        "code": doc["number"] + "-TRANSIT",
                        "name": "Đang vận chuyển " + doc["number"],
                    },
                )
                c.execute(
                    text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,destination_warehouse_id,
                    transit_location_id,business_date,created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'TRANSFER','DRAFT',:warehouse_id,:destination_warehouse_id,:transit_location_id,
                    :business_date,:actor,:now,1,'{}',:reason)"""),
                    {
                        **doc,
                        "actor": auth.principal.user_id,
                        "now": self.identity.clock(),
                        "reason": payload.reason,
                    },
                )
            for index, spec in enumerate(payload.lines, 1):
                stock = one(
                    c,
                    "SELECT i.*,p.base_uom_id FROM wms.stock_item i JOIN wms.product p ON p.id=i.product_id WHERE i.id=:id",
                    id=spec.stock_item_id,
                )
                if not stock:
                    raise DomainError("NOT_FOUND", "Không tìm thấy danh tính tồn nguồn.")
                if stock["owner_id"] != COMPANY_OWNER or stock["consignment_id"]:
                    raise DomainError(
                        "OWNERSHIP_UNSUPPORTED", "Chưa có chính sách chuyển kho ký gửi/chưa phân loại."
                    )
                line = uuid4()
                c.execute(
                    text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,consignment_id)
                    VALUES (:id,:doc,:n,:product_id,:base_uom_id,:qty,1,:qty,:owner_id,:consignment_id)"""),
                    {**stock, "id": line, "doc": doc["id"], "n": index, "qty": Decimal(spec.quantity_base)},
                )
                c.execute(
                    text("INSERT INTO wms.transfer_line VALUES (:id,:stock,:source)"),
                    {"id": line, "stock": spec.stock_item_id, "source": spec.source_location_id},
                )
            self.validate_saved(auth, doc)
            result = self.result(doc, doc, request_id)
            self.orders.effects(
                c,
                auth.principal.user_id,
                doc,
                "transfer.update" if doc_id else "transfer.create",
                result,
                payload.reason,
                request_id,
            )
            return CommandResult(result, 200 if doc_id else 201)

        return self.execute(
            access,
            key,
            "transfer.update" if doc_id else "transfer.create",
            doc_id,
            payload,
            authorize,
            handle,
        )

    def post(self, access, key, doc_id, payload, request_id, operation):
        def target(auth, lock=False):
            if operation == "ADJUST":
                doc = self.orders.document(auth, doc_id, "ADJUSTMENT", lock=lock)
                return doc, self.loss_parent(auth, doc)[0]
            doc = self.document(auth, doc_id, lock=lock)
            return doc, doc

        def authorize(auth):
            self.may_post(auth, target(auth)[0], operation)

        name = {
            "DISPATCH": "transfer.dispatch",
            "ARRIVE": "transfer.receive",
            "ADJUST": "transfer.loss.post",
        }[operation]
        digest = payload_hash(name, doc_id, payload.model_dump(mode="json"))

        def handle(auth):
            c, actor = auth.connection, auth.principal.user_id
            doc, parent = target(auth, lock=True)
            executed = one(
                c,
                "SELECT * FROM wms.inventory_transaction WHERE document_id=:id AND execution_key=:key",
                id=doc_id,
                key=payload.execution_key,
            )
            if executed:
                if (
                    executed["posted_by"] != actor
                    or executed["request_hash"] != digest
                    or not executed["response"]
                ):
                    raise DomainError(
                        "EXECUTION_MISMATCH", "Execution key đã dùng với người hoặc nội dung khác."
                    )
                return CommandResult(executed["response"])
            require_version(doc["version"], payload.expected_version)
            self.orders.receipts.approved(c, doc)
            day = payload.business_date if operation == "ARRIVE" else doc["business_date"]
            if operation == "DISPATCH":
                if doc["status"] != "APPROVED" or self.sources(c, doc_id):
                    raise DomainError(
                        "ALREADY_POSTED", "Phiếu đã xuất chuyển; chỉ nhận phần đang vận chuyển."
                    )
                rows = self.plans(c, doc)
                physical = {doc["warehouse_id"]: {r["source_location_id"] for r in rows}}
                legs = [
                    dict(
                        stock=r["stock_item_id"],
                        line=r["document_line_id"],
                        source=r["source_location_id"],
                        destination=doc["transit_location_id"],
                        qty=r["quantity_base"],
                        dispatch=None,
                        disposition="DISPATCH",
                    )
                    for r in rows
                ]
            elif operation == "ARRIVE":
                sources = {r["dispatch_move_id"]: r for r in self.sources(c, doc_id)}
                totals, legs = defaultdict(Decimal), []
                for spec in payload.lines:
                    source = sources.get(spec.dispatch_move_id)
                    if not source:
                        raise DomainError("SOURCE_MISMATCH", "Lần xuất không thuộc lệnh chuyển này.")
                    if day < source["dispatched_on"]:
                        raise DomainError("INVALID_DATE", "Ngày nhận không được trước ngày xuất chuyển.")
                    qty = Decimal(spec.quantity_base)
                    totals[spec.dispatch_move_id] += qty
                    if totals[spec.dispatch_move_id] > self.remaining(source):
                        raise DomainError("SOURCE_EXCEEDED", "Vượt lượng đã gửi còn trong transit.")
                    legs.append(
                        dict(
                            stock=source["stock_item_id"],
                            line=source["document_line_id"],
                            source=doc["transit_location_id"],
                            destination=spec.destination_location_id,
                            qty=qty,
                            dispatch=spec.dispatch_move_id,
                            disposition=spec.disposition,
                        )
                    )
                physical = {doc["destination_warehouse_id"]: {r["destination"] for r in legs}}
            else:
                parent, link = self.loss_parent(auth, doc)
                source, evidence, qty = self.loss_spec(c, doc, parent, link)
                self.check_loss(c, source, evidence, qty)
                if day < source["dispatched_on"]:
                    raise DomainError("INVALID_DATE", "Ngày điều chỉnh không được trước ngày xuất chuyển.")
                line = one(c, "SELECT id FROM wms.document_line WHERE document_id=:id", id=doc_id)
                legs = [
                    dict(
                        stock=source["stock_item_id"],
                        line=line["id"],
                        source=parent["transit_location_id"],
                        destination=LOSS,
                        qty=qty,
                        dispatch=source["dispatch_move_id"],
                        disposition="LOSS",
                    )
                ]
                physical = {}
            lock_route(c, parent, day, operation, physical)
            if operation == "DISPATCH":
                self.validate_saved(auth, doc, lock_products=True)
                if one(
                    c, """SELECT p.id FROM wms.package p WHERE p.document_id=:id LIMIT 1""", id=doc_id
                ) or one(
                    c,
                    """SELECT t.id
                    FROM wms.pick_task t JOIN wms.reservation r ON r.id=t.reservation_id JOIN wms.document_line l ON l.id=r.line_id
                    WHERE l.document_id=:id AND t.status<>'CANCELLED' LIMIT 1""",
                    id=doc_id,
                ):
                    raise DomainError(
                        "DEPENDENT_DOCUMENT", "Phiếu có task/kiện cần workflow soạn hàng tương ứng."
                    )
            elif operation == "ARRIVE":
                locations = location_tree(
                    c, doc["destination_warehouse_id"], physical[doc["destination_warehouse_id"]]
                )
                for r in legs:
                    expected = "QUARANTINE" if r["disposition"] == "DAMAGED" else "RECEIVING"
                    if locations[r["destination"]]["kind"] != expected:
                        raise DomainError(
                            "INVALID_LOCATION",
                            "Hàng nhận đi RECEIVING; hàng hỏng đi QUARANTINE kèm chứng cứ.",
                        )
            warehouse = (
                parent["warehouse_id"] if operation == "DISPATCH" else parent["destination_warehouse_id"]
            )
            stocks = prepare_legs(c, legs, warehouse, day)
            tx = uuid4()
            # Compute the final state before inserting the immutable execution ACK.
            totals_before = self.sources(c, parent["id"])
            left = sum((self.remaining(r) for r in totals_before), Decimal(0)) - sum(
                (r["qty"] for r in legs), Decimal(0)
            )
            parent_status = "PARTIAL" if operation == "DISPATCH" or left > 0 else "COMPLETED"
            doc.update(
                status="COMPLETED" if operation == "ADJUST" else parent_status, version=doc["version"] + 1
            )
            result = self.result(doc, parent, request_id, transaction_id=tx, operation=operation)
            c.execute(
                text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,
                posted_at,posted_by,request_hash,response) VALUES (:id,:doc,:key,:op,:day,:now,:actor,:hash,CAST(:body AS jsonb))"""),
                {
                    "id": tx,
                    "doc": doc_id,
                    "key": payload.execution_key,
                    "op": operation,
                    "day": day,
                    "now": self.identity.clock(),
                    "actor": actor,
                    "hash": digest,
                    "body": encode(result),
                },
            )
            write_legs(c, legs, stocks, tx, payload.evidence_ref)
            c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), doc)
            if operation == "ADJUST":
                c.execute(
                    text("UPDATE wms.document SET status=:status,version=version+1 WHERE id=:id"),
                    {"id": parent["id"], "status": parent_status},
                )
            self.orders.effects(c, actor, doc, name, result, payload.reason, request_id)
            return CommandResult(result)

        return self.execute(access, key, name, doc_id, payload, authorize, handle)

    def discrepancy(self, access, key, doc_id, payload, request_id):
        def authorize(auth):
            self.may_post(auth, self.document(auth, doc_id), "ARRIVE")

        def handle(auth):
            c = auth.connection
            doc = self.document(auth, doc_id, lock=True)
            require_version(doc["version"], payload.expected_version)
            source = next(
                (r for r in self.sources(c, doc_id) if r["dispatch_move_id"] == payload.dispatch_move_id),
                None,
            )
            qty = Decimal(payload.quantity_base)
            if not source or qty > self.remaining(source):
                raise DomainError("SOURCE_EXCEEDED", "Chỉ lập chứng cứ cho lượng còn trong transit.")
            unit = active_reference(c, "uom", source["base_uom_id"], "uom_id")
            if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Số lượng không đúng đơn vị cơ sở.")
            evidence = uuid4()
            c.execute(
                text(
                    "INSERT INTO wms.transfer_discrepancy VALUES (:id,:doc,:source,:kind,:qty,:evidence,:actor,:now)"
                ),
                {
                    "id": evidence,
                    "doc": doc_id,
                    "source": payload.dispatch_move_id,
                    "kind": payload.kind,
                    "qty": qty,
                    "evidence": payload.evidence_ref,
                    "actor": auth.principal.user_id,
                    "now": self.identity.clock(),
                },
            )
            doc["version"] += 1
            c.execute(text("UPDATE wms.document SET version=:version WHERE id=:id"), doc)
            result = self.result(doc, doc, request_id, discrepancy_id=evidence)
            self.orders.effects(
                c, auth.principal.user_id, doc, "transfer.discrepancy", result, payload.reason, request_id
            )
            return CommandResult(result)

        return self.execute(access, key, "transfer.discrepancy", doc_id, payload, authorize, handle)

    def loss_spec(self, c, doc, parent, link):
        evidence = one(c, "SELECT * FROM wms.transfer_discrepancy WHERE id=:id", id=link["discrepancy_id"])
        source = next(
            (
                r
                for r in self.sources(c, parent["id"])
                if r["dispatch_move_id"] == evidence["dispatch_move_id"]
            ),
            None,
        )
        line = one(c, "SELECT * FROM wms.document_line WHERE document_id=:id", id=doc["id"])
        if (
            not source
            or not line
            or (
                line["source_line_id"],
                line["product_id"],
                line["owner_id"],
                line["consignment_id"],
                line["uom_id"],
            )
            != (
                source["document_line_id"],
                source["product_id"],
                source["owner_id"],
                source["consignment_id"],
                source["base_uom_id"],
            )
        ):
            raise DomainError("SOURCE_MISMATCH", "Điều chỉnh không khớp lần xuất chuyển.")
        return source, evidence, line["base_quantity"]

    def check_loss(self, c, source, evidence, qty):
        used = c.execute(
            text("""SELECT coalesce(sum(m.quantity_base),0) FROM wms.transfer_adjustment a
            JOIN wms.inventory_transaction t ON t.document_id=a.document_id AND t.operation='ADJUST'
            JOIN wms.stock_move m ON m.transaction_id=t.id WHERE a.discrepancy_id=:id"""),
            {"id": evidence["id"]},
        ).scalar_one()
        if qty > self.remaining(source) or qty > evidence["quantity"] - used:
            raise DomainError("SOURCE_EXCEEDED", "Vượt lượng thiếu đã xác minh còn trong transit.")

    def create_loss(self, access, key, doc_id, payload, request_id):
        def authorize(auth):
            doc = self.document(auth, doc_id)
            self.both(auth, doc, "document.read")
            self.both(auth, doc, "adjustment.draft")

        def handle(auth):
            c = auth.connection
            parent = self.document(auth, doc_id, lock=True)
            require_version(parent["version"], payload.expected_version)
            evidence = one(
                c,
                "SELECT * FROM wms.transfer_discrepancy WHERE id=:id AND transfer_document_id=:doc",
                id=payload.discrepancy_id,
                doc=doc_id,
            )
            source = next(
                (
                    r
                    for r in self.sources(c, doc_id)
                    if evidence and r["dispatch_move_id"] == evidence["dispatch_move_id"]
                ),
                None,
            )
            if not source:
                raise DomainError("SOURCE_MISMATCH", "Chứng cứ không thuộc lệnh chuyển.")
            qty = Decimal(payload.quantity_base)
            self.check_loss(c, source, evidence, qty)
            unit = active_reference(c, "uom", source["base_uom_id"], "uom_id")
            if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                raise DomainError("INVALID_QUANTITY", "Số lượng không đúng đơn vị cơ sở.")
            seq = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
            doc = dict(
                id=uuid4(),
                number=f"TLOSS-{seq:08d}",
                kind="ADJUSTMENT",
                warehouse_id=parent["warehouse_id"],
                status="DRAFT",
                version=1,
            )
            c.execute(
                text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes,reason)
                VALUES (:id,:number,'ADJUSTMENT','DRAFT',:warehouse_id,:day,:actor,:now,1,'{}',:reason)"""),
                {
                    **doc,
                    "day": payload.business_date,
                    "actor": auth.principal.user_id,
                    "now": self.identity.clock(),
                    "reason": payload.reason,
                },
            )
            c.execute(
                text("INSERT INTO wms.transfer_adjustment VALUES (:id,:parent,:evidence)"),
                {"id": doc["id"], "parent": doc_id, "evidence": evidence["id"]},
            )
            c.execute(
                text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,source_line_id,owner_id,consignment_id)
                VALUES (:id,:doc,1,:product_id,:base_uom_id,:qty,1,:qty,:document_line_id,:owner_id,:consignment_id)"""),
                {**source, "id": uuid4(), "doc": doc["id"], "qty": qty},
            )
            result = self.result(doc, parent, request_id, discrepancy_id=evidence["id"])
            self.orders.effects(
                c, auth.principal.user_id, doc, "transfer.loss.create", result, payload.reason, request_id
            )
            return CommandResult(result, 201)

        return self.execute(access, key, "transfer.loss.create", doc_id, payload, authorize, handle)

    def listing(self, auth, warehouse_id, status=None, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        broad = any(
            g["role_code"] not in {"RECEIVER", "PICKER"} for g in auth.grants("document.read", warehouse_id)
        )
        result = page(
            auth.connection,
            SUMMARY_SQL
            + """ WHERE d.kind='TRANSFER'
            AND (:wh IN (d.warehouse_id,d.destination_warehouse_id))
            AND (CAST(:status AS text) IS NULL OR d.status=:status)
            AND (CAST(:after AS uuid) IS NULL OR d.id>:after)
            AND (:broad OR d.created_by=:actor OR EXISTS(SELECT 1 FROM wms.document_assignment a
                WHERE a.document_id=d.id AND a.user_id=:actor)) ORDER BY d.id LIMIT :limit""",
            {
                "wh": warehouse_id,
                "status": status,
                "after": after,
                "actor": auth.principal.user_id,
                "broad": broad,
            },
            limit,
        )
        result["items"] = [
            OrderSummary(**{k: r[k] for k in OrderSummary.model_fields}) for r in result["items"]
        ]
        return result

    def read(self, auth, doc_id):
        c = auth.connection
        raw = one(c, "SELECT * FROM wms.document WHERE id=:id", id=doc_id)
        if raw and raw["kind"] == "ADJUSTMENT":
            doc = self.orders.document(auth, doc_id, "ADJUSTMENT")
            parent, link = self.loss_parent(auth, doc)
        else:
            doc = parent = self.document(auth, doc_id)
            link = None
        summary = one(c, SUMMARY_SQL + " WHERE d.id=:id", id=doc_id)
        both = all(
            auth.allows("document.read", parent[k]) for k in ["warehouse_id", "destination_warehouse_id"]
        )
        approvals, actions = [], []
        if both:
            generic = self.orders.read(auth, doc_id)
            approvals = generic.approvals
            actions = [a for a in generic.allowed_actions if a != "close"]
            if link:
                actions = [
                    a for a in actions if a not in {"edit", "assign"}
                ]  # Loss quantities are immutable; cancel and create a corrected draft.
        if doc["status"] in {"APPROVED", "PARTIAL"}:
            for op, action in (
                [("ADJUST", "post")] if link else [("DISPATCH", "dispatch"), ("ARRIVE", "receive")]
            ):
                try:
                    if op == "ARRIVE" and doc["status"] != "PARTIAL":
                        continue
                    self.may_post(auth, doc, op)
                    if op != "DISPATCH" or doc["status"] == "APPROVED":
                        actions.append(action)
                    if op == "ARRIVE":
                        actions.append("discrepancy")
                except DomainError:
                    pass
            if (
                not link
                and doc["status"] == "PARTIAL"
                and all(
                    auth.allows("adjustment.draft", parent[k])
                    for k in ["warehouse_id", "destination_warehouse_id"]
                )
            ):
                actions.append("loss")
        plans = self.plans(c, parent)
        if link:
            source, _, qty = self.loss_spec(c, doc, parent, link)
            plans = [
                {**r, "quantity_base": qty}
                for r in plans
                if r["document_line_id"] == source["document_line_id"]
            ]
        from packages.contracts.transfers import TransferPlan

        rendered_plans = []
        for r in plans:
            row = {k: r[k] for k in TransferPlan.model_fields if k != "quantity_base"}
            if not auth.allows("document.read", parent["warehouse_id"]):
                row.update(source_location_id=None, source_code=None)
            rendered_plans.append({**row, "quantity_base": amount(r["quantity_base"])})
        sources = [
            {
                **{
                    k: r[k]
                    for k in [
                        "dispatch_move_id",
                        "document_line_id",
                        "stock_item_id",
                        "sku",
                        "owner_code",
                        "lot_code",
                        "serial_code",
                    ]
                },
                "dispatched_base": amount(r["dispatched"]),
                "received_base": amount(r["received"]),
                "lost_base": amount(r["lost"]),
                "remaining_base": amount(self.remaining(r)),
            }
            for r in self.sources(c, parent["id"])
        ]
        evidence = [
            {
                **{
                    k: r[k]
                    for k in ["id", "dispatch_move_id", "kind", "evidence_ref", "recorded_by", "recorded_at"]
                },
                "quantity_base": amount(r["quantity"]),
            }
            for r in c.execute(
                text("""SELECT * FROM wms.transfer_discrepancy
                     WHERE transfer_document_id=:id ORDER BY recorded_at DESC,id DESC LIMIT 200"""),
                {"id": parent["id"]},
            ).mappings()
        ]
        children = (
            c.execute(
                text(
                    SUMMARY_SQL
                    + """ JOIN wms.transfer_adjustment a ON a.document_id=d.id
            WHERE a.source_transfer_id=:id ORDER BY d.created_at DESC,d.id DESC LIMIT 200"""
                ),
                {"id": parent["id"]},
            ).mappings()
            if both
            else []
        )
        return TransferView(
            **{k: summary[k] for k in OrderSummary.model_fields},
            destination_warehouse_id=parent["destination_warehouse_id"],
            transit_location_id=parent["transit_location_id"],
            source_transfer_id=parent["id"] if link else None,
            discrepancy_id=link["discrepancy_id"] if link else None,
            reason=doc["reason"],
            plan=rendered_plans,
            sources=sources,
            discrepancies=evidence,
            adjustments=[OrderSummary(**{k: r[k] for k in OrderSummary.model_fields}) for r in children],
            approvals=approvals,
            assigned_user_ids=c.execute(
                text("SELECT user_id FROM wms.document_assignment WHERE document_id=:id ORDER BY user_id"),
                {"id": doc["id"]},
            )
            .scalars()
            .all(),
            allowed_actions=actions,
        )

    def history(self, auth, doc_id, after=None, limit=50):
        self.document(auth, doc_id)
        rows = page(
            auth.connection,
            """SELECT m.id,t.document_id,t.id AS transaction_id,x.dispatch_move_id,
            t.operation,x.disposition,m.quantity_base,x.evidence_ref,t.posted_at,t.posted_by,
            l.code AS destination_code,l.warehouse_id AS destination_warehouse
            FROM wms.transfer_move x JOIN wms.stock_move m ON m.id=x.move_id
            JOIN wms.inventory_transaction t ON t.id=m.transaction_id JOIN wms.location l ON l.id=m.destination_location_id
            WHERE (t.document_id=:doc OR t.document_id IN (SELECT document_id FROM wms.transfer_adjustment WHERE source_transfer_id=:doc))
            AND (CAST(:after AS uuid) IS NULL OR m.id>:after) ORDER BY m.id LIMIT :limit""",
            {"doc": doc_id, "after": after},
            limit,
        )
        for r in rows["items"]:
            warehouse = r.pop("destination_warehouse")
            if warehouse and not auth.allows("document.read", warehouse):
                r["destination_code"] = None
            r["quantity_base"] = amount(r["quantity_base"])
        return rows

    def operation(self, auth, key):
        row = one(
            auth.connection,
            """SELECT response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key
            AND command IN ('transfer.dispatch','transfer.receive','transfer.loss.post')""",
            actor=auth.principal.user_id,
            key=key,
        )
        if not row:
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK; chỉ gửi lại đúng key và nội dung.")
        result = row["response"]
        doc = (
            self.orders.document(auth, UUID(result["id"]), "ADJUSTMENT")
            if result["operation"] == "ADJUST"
            else self.document(auth, UUID(result["id"]))
        )
        self.may_post(auth, doc, result["operation"])
        return TransferPostResult.model_validate(result)

    def assignees(self, auth, doc_id, after=None, limit=100):
        doc = self.document(auth, doc_id)
        self.both(auth, doc, "document.assign")
        return page(
            auth.connection,
            """SELECT u.id,u.username,u.display_name FROM wms.app_user u
            WHERE u.is_active AND (CAST(:after AS uuid) IS NULL OR u.id>:after) AND EXISTS(
            SELECT 1 FROM wms.user_role_grant g JOIN wms.role r ON r.id=g.role_id AND r.is_active
            JOIN wms.role_permission rp ON rp.role_id=r.id JOIN wms.permission p ON p.id=rp.permission_id
            WHERE g.user_id=u.id AND g.revoked_at IS NULL AND g.valid_from<=:now
            AND (g.valid_until IS NULL OR g.valid_until>:now) AND p.code='document.read'
            AND (g.scope_kind='ALL_WAREHOUSES' OR (g.scope_kind='WAREHOUSE' AND g.warehouse_id IN (:src,:dst))))
            ORDER BY u.id LIMIT :limit""",
            {
                "after": after,
                "now": self.identity.clock(),
                "src": doc["warehouse_id"],
                "dst": doc["destination_warehouse_id"],
            },
            limit,
        )

    def evidences(self, auth, doc_id, after=None, limit=50):
        self.document(auth, doc_id)
        result = page(
            auth.connection,
            """SELECT id,dispatch_move_id,kind,quantity AS quantity_base,
            evidence_ref,recorded_by,recorded_at FROM wms.transfer_discrepancy WHERE transfer_document_id=:id
            AND (CAST(:after AS uuid) IS NULL OR id>:after) ORDER BY id LIMIT :limit""",
            {"id": doc_id, "after": after},
            limit,
        )
        for row in result["items"]:
            row["quantity_base"] = amount(row["quantity_base"])
        return result

    def adjustments(self, auth, doc_id, after=None, limit=50):
        doc = self.document(auth, doc_id)
        self.both(auth, doc, "document.read")
        result = page(
            auth.connection,
            SUMMARY_SQL
            + """ JOIN wms.transfer_adjustment a ON a.document_id=d.id
            WHERE a.source_transfer_id=:id AND (CAST(:after AS uuid) IS NULL OR d.id>:after)
            ORDER BY d.id LIMIT :limit""",
            {"id": doc_id, "after": after},
            limit,
        )
        result["items"] = [
            OrderSummary(**{k: r[k] for k in OrderSummary.model_fields}) for r in result["items"]
        ]
        return result
