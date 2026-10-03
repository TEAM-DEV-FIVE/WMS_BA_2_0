"""Approved SO -> ISSUE -> FEFO reservation -> partial outbound posting."""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, invalid, one
from apps.server.application.orders import encode
from apps.server.application.receipts import EXTERNAL
from apps.server.application.reservations import ReservationService
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.issues import IssueOperation, IssuePostResult, IssueView, ReservationPlan
from packages.contracts.orders import OrderResult
from packages.contracts.traceability import COMPANY_OWNER


class IssueService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        self.reservations = ReservationService(self)
        orders.issues = self

    def source(self, auth, doc):
        row = one(auth.connection, "SELECT source_order_id FROM wms.issue_document WHERE document_id=:id", id=doc["id"])
        if not row:
            raise DomainError("UNSUPPORTED_ISSUE", "Phiếu xuất cũ chưa có liên kết SO đã xác minh.")
        return self.orders.document(auth, row["source_order_id"], "SO")

    def snapshot(self, c, doc):
        row = one(c, "SELECT source_order_id FROM wms.issue_document WHERE document_id=:id", id=doc["id"])
        return dict(row) if row else None

    def approved(self, c, doc):
        if doc["status"] not in {"APPROVED", "PARTIAL"}:
            raise DomainError("INVALID_STATE", "SO/phiếu xuất phải đã duyệt và còn thực hiện.")
        self.orders.receipts.approved(c, doc)

    @staticmethod
    def match_source(line, parent):
        if (not parent or line["product_id"] != parent["product_id"] or line["owner_id"] != COMPANY_OWNER
                or parent["owner_id"] != COMPANY_OWNER or line["consignment_id"] or parent["consignment_id"]):
            raise DomainError("SOURCE_MISMATCH", "Dòng xuất không khớp SO/owner; chưa hỗ trợ xuất hàng ký gửi.")

    def validate_saved(self, auth, doc):
        c = auth.connection
        source = self.source(auth, doc)
        self.approved(c, source)
        self.orders.validate_header(c, "SO", source["warehouse_id"], source["partner_id"])
        active_reference(c, "stock_owner", COMPANY_OWNER, "owner_id")
        if doc["warehouse_id"] != source["warehouse_id"] or doc["partner_id"] != source["partner_id"]:
            raise DomainError("SOURCE_MISMATCH", "Phiếu xuất không khớp kho/khách hàng của SO.")
        parents = {r["id"]: r for r in self.orders.lines(c, source)}
        for line in self.orders.lines(c, doc):
            self.match_source(line, parents.get(line["source_line_id"]))
        return source

    def may_handle(self, auth, doc, permission):
        auth.require(permission, doc["warehouse_id"])
        if doc["created_by"] != auth.principal.user_id and not one(auth.connection,
                "SELECT id FROM wms.document_assignment WHERE document_id=:doc AND user_id=:user",
                doc=doc["id"], user=auth.principal.user_id):
            raise DomainError("FORBIDDEN", "Chỉ người lập hoặc được giao mới giữ/giải phóng/xuất hàng.")
        self.source(auth, doc)  # Recheck source visibility, including on replay/lookup.

    def read(self, auth, doc_id):
        view = self.orders.read(auth, doc_id, "ISSUE")
        doc = self.orders.document(auth, doc_id, "ISSUE")
        source = self.source(auth, doc)
        actions = list(view.allowed_actions)
        if doc["status"] in {"APPROVED", "PARTIAL"}:
            for permission, names in [("reservation.manage", ["plan", "reserve", "release", "expire"]),
                                      ("issue.post", ["post"])]:
                try:
                    self.may_handle(auth, doc, permission)
                    actions += names
                except DomainError:
                    pass
        return IssueView(**{**view.model_dump(), "allowed_actions": actions}, source_order_id=source["id"],
                         source_line_ids={r["id"]: r["source_line_id"] for r in self.orders.lines(auth.connection, doc)},
                         reservations=self.reservations.view(auth.connection, doc_id))

    def prepare(self, auth, source, payload):
        c = auth.connection
        self.approved(c, source)
        self.orders.validate_header(c, "SO", source["warehouse_id"], source["partner_id"])
        parents = {r["id"]: r for r in self.orders.lines(c, source)}
        rows = []
        for number, spec in enumerate(payload.lines, 1):
            parent = parents.get(spec.source_line_id)
            if not parent:
                invalid("source_line_id", "Dòng phải thuộc SO nguồn được chọn.")
            self.match_source(parent, parent)
            qty = Decimal(spec.quantity_base)
            self.reservations.quantity(c, parent, qty)
            if qty > Decimal(parent["remaining_base"]):
                raise DomainError("SOURCE_EXCEEDED", "Kế hoạch xuất vượt phần SO còn lại.")
            product = active_reference(c, "product", parent["product_id"], "product_id")
            rows.append(dict(id=uuid4(), line_no=number, source_line_id=parent["id"], product_id=parent["product_id"],
                             uom_id=product["base_uom_id"], quantity=qty, owner_id=COMPANY_OWNER))
        return rows

    def no_dependencies(self, c, doc_id, *, edit=False, closing=False):
        doc = one(c, "SELECT * FROM wms.document WHERE id=:id", id=doc_id)
        if not closing and one(c, "SELECT id FROM wms.inventory_transaction WHERE document_id=:id LIMIT 1", id=doc_id):
            raise DomainError("ALREADY_POSTED", "Phiếu đã ghi sổ; chỉ đóng phần còn lại, không sửa/hủy lịch sử.")
        if one(c, """SELECT child.id FROM wms.document_line child JOIN wms.document_line parent
            ON parent.id=child.source_line_id WHERE parent.document_id=:id LIMIT 1""", id=doc_id):
            raise DomainError("DEPENDENT_DOCUMENT", "Phiếu đã có chứng từ tham chiếu; xử lý phụ thuộc trước.")
        if one(c, "SELECT id FROM wms.package WHERE document_id=:id LIMIT 1", id=doc_id):
            raise DomainError("FULFILLMENT_ACTIVE", "Cần xử lý đóng kiện trước khi thay đổi phiếu.")
        # The authorized edit/cancel/close owns the parent+child locks. Release and
        # invalidation are in its transaction; failures roll all of them back.
        self.reservations.release(c, doc)

    def result(self, doc, request_id):
        return OrderResult(**{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                           request_id=request_id).model_dump(mode="json")

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            source = self.orders.document(auth, payload.source_order_id, "SO")
            auth.require("issue.draft", source["warehouse_id"])
            if doc_id:
                doc = self.orders.document(auth, doc_id, "ISSUE")
                self.orders.may_edit(auth, doc)
                if self.source(auth, doc)["id"] != source["id"]:
                    invalid("source_order_id", "Không đổi SO nguồn của phiếu đã tạo.")
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            source = self.orders.document(auth, payload.source_order_id, "SO", lock=True)
            if doc_id:
                doc = self.orders.document(auth, doc_id, "ISSUE", lock=True)
                require_version(doc["version"], payload.expected_version)
                self.orders.may_edit(auth, doc)
                if doc["status"] not in {"DRAFT", "REJECTED"}:
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp/từ chối; phiếu đã duyệt cần đưa về nháp.")
                self.no_dependencies(c, doc_id, edit=True)
            rows = self.prepare(auth, source, payload)
            if doc_id:
                existing = {r["source_line_id"]: r for r in self.orders.lines(c, doc)}
                retained = {r["source_line_id"] for r in rows}
                for source_line, old in existing.items():
                    if source_line not in retained:
                        if one(c, "SELECT id FROM wms.reservation WHERE line_id=:id LIMIT 1", id=old["id"]):
                            raise DomainError("RESERVATION_HISTORY", "Dòng đã có lịch sử giữ chỗ: giữ dòng hoặc hủy phiếu và lập lại.")
                        c.execute(text("DELETE FROM wms.document_line WHERE id=:id"), {"id": old["id"]})
                # Stable line IDs preserve released reservation history. Move line
                # numbers aside to allow reordering without transient UNIQUE conflicts.
                c.execute(text("UPDATE wms.document_line SET line_no=line_no+1000 WHERE document_id=:id"), {"id": doc_id})
                for row in rows:
                    old = existing.get(row["source_line_id"])
                    if old:
                        row["id"] = old["id"]
                self.orders.invalidate(c, doc_id)
                doc["version"] += 1
                c.execute(text("""UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,
                    reason=:reason WHERE id=:id"""), {**doc, "day": payload.business_date, "reason": payload.reason})
            else:
                seq = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                doc = dict(id=uuid4(), number=f"ISS-{payload.business_date:%Y%m%d}-{seq:08d}", kind="ISSUE",
                           warehouse_id=source["warehouse_id"], version=1)
                c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,partner_id,business_date,
                    created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'ISSUE','DRAFT',:warehouse_id,:partner,:day,:actor,:now,1,'{}',:reason)"""),
                    {**doc, "partner": source["partner_id"], "day": payload.business_date, "actor": actor,
                     "now": self.identity.clock(), "reason": payload.reason})
                c.execute(text("INSERT INTO wms.issue_document VALUES (:id,:source)"), {"id": doc["id"], "source": source["id"]})
            doc["status"] = "DRAFT"
            for row in rows:
                c.execute(text("""INSERT INTO wms.document_line
                    (id,document_id,line_no,source_line_id,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id)
                    VALUES (:id,:doc,:line_no,:source_line_id,:product_id,:uom_id,:quantity,1,:quantity,:owner_id)
                    ON CONFLICT (id) DO UPDATE SET line_no=EXCLUDED.line_no,quantity=EXCLUDED.quantity,
                    base_quantity=EXCLUDED.base_quantity"""), {**row, "doc": doc["id"]})
            result = self.result(doc, request_id)
            self.orders.effects(c, actor, doc, "issue.update" if doc_id else "issue.create", result, payload.reason, request_id)
            return CommandResult(result, 200 if doc_id else 201)

        return self.bus.execute(actor_id=actor, key=key, command="issue.update" if doc_id else "issue.create",
                                resource_id=doc_id or UUID(int=0), payload=payload.model_dump(mode="json"),
                                authorize=authorize, handle=handle)

    def plan(self, auth, doc_id, line_id, quantity):
        doc = self.orders.document(auth, doc_id, "ISSUE")
        self.may_handle(auth, doc, "reservation.manage")
        source = self.validate_saved(auth, doc)
        self.approved(auth.connection, doc)
        inventory = self.reservations.inventory(auth.connection, doc, self.orders.lines(auth.connection, doc),
                                                allocate=True, lock=False)
        lines = self.reservations.plan(auth.connection, doc, source, {line_id: Decimal(quantity)}, inventory)
        return ReservationPlan(document_id=doc_id, version=doc["version"], lines=lines)

    def manage(self, access, key, doc_id, payload, request_id, action):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            self.may_handle(auth, self.orders.document(auth, doc_id, "ISSUE"), "reservation.manage")
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "ISSUE", lock=True)
            self.may_handle(auth, doc, "reservation.manage")
            require_version(doc["version"], payload.expected_version)
            if action == "reserve":
                self.approved(c, doc)
                source = self.validate_saved(auth, doc)
                self.reservations.reserve(auth, doc, source, payload)
            elif action == "release":
                self.reservations.release(c, doc, {s.reservation_id: Decimal(s.quantity_base) for s in payload.lines})
            else:
                self.reservations.release(c, doc, expired_only=True)
            doc["version"] += 1
            c.execute(text("UPDATE wms.document SET version=:version WHERE id=:id"), doc)
            result = self.result(doc, request_id)
            self.orders.effects(c, actor, doc, "issue." + action, result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(actor_id=actor, key=key, command="issue." + action, resource_id=doc_id,
                                payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}
        digest = payload_hash("issue.post", doc_id, payload.model_dump(mode="json"))

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            self.may_handle(auth, self.orders.document(auth, doc_id, "ISSUE"), "issue.post")
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "ISSUE", lock=True)
            self.may_handle(auth, doc, "issue.post")
            executed = one(c, "SELECT * FROM wms.inventory_transaction WHERE document_id=:id AND execution_key=:key",
                           id=doc_id, key=payload.execution_key)
            if executed:
                if executed["posted_by"] != actor or executed["request_hash"] != digest or not executed["response"]:
                    raise DomainError("EXECUTION_MISMATCH", "Execution key đã ghi sổ với người/nội dung khác.")
                return CommandResult(executed["response"])
            require_version(doc["version"], payload.expected_version)
            source = self.validate_saved(auth, doc)
            self.approved(c, doc)
            active_reference(c, "warehouse", doc["warehouse_id"], "warehouse_id")
            periods = list(c.execute(text("""SELECT * FROM wms.stock_period WHERE warehouse_id=:wh
                AND :day BETWEEN starts_on AND ends_on ORDER BY id FOR UPDATE"""),
                {"wh": doc["warehouse_id"], "day": doc["business_date"]}).mappings())
            if len(periods) != 1 or periods[0]["status"] != "OPEN":
                raise DomainError("PERIOD_CLOSED", "Ngày ghi sổ phải thuộc đúng một kỳ kho đang mở.")
            # Lock EXTERNAL in the same UUID order as the other locations.
            old = self.reservations.rows(c, doc_id)
            saved = {r["id"]: r for r in self.orders.lines(c, doc)}
            parents = {r["id"]: r for r in self.orders.lines(c, source)}
            inventory = self.reservations.inventory(c, doc, list(saved.values()),
                                                    reservations=[*old, {"location_id": EXTERNAL}])
            destination = one(c, "SELECT * FROM wms.location WHERE id=:id", id=EXTERNAL)
            if not destination or destination["kind"] != "EXTERNAL" or destination["warehouse_id"] or not destination["is_active"]:
                raise DomainError("SOURCE_MISMATCH", "Đối ứng xuất hàng không hợp lệ.")
            held = {r["id"]: r for r in self.reservations.rows(c, doc_id, lock=True)}
            line_totals, source_totals, moves = defaultdict(Decimal), defaultdict(Decimal), []
            for spec in payload.lines:
                reservation = held.get(spec.reservation_id)
                qty = Decimal(spec.quantity_base)
                if not reservation or qty > self.reservations.remaining(reservation):
                    raise DomainError("RESERVATION_MISMATCH", "Không đủ giữ chỗ thuộc phiếu để xuất.")
                if reservation["expires_at"] is not None and reservation["expires_at"] <= self.identity.clock():
                    raise DomainError("RESERVATION_EXPIRED", "Giữ chỗ hết hạn; giải phóng và giữ lại trước khi xuất.")
                self.reservations.check_fulfillment(c, reservation["id"])
                line = saved[reservation["line_id"]]
                parent = parents.get(line["source_line_id"])
                self.match_source(line, parent)
                stock = inventory.get((reservation["stock_item_id"], reservation["location_id"]))
                if not stock or stock["product_id"] != line["product_id"] or not self.reservations.eligible(stock, doc["warehouse_id"]):
                    raise DomainError("STOCK_INELIGIBLE", "Nguồn hàng không còn hợp lệ: kiểm tra owner, hạn dùng, vị trí/khóa kiểm kê.")
                self.reservations.quantity(c, line, qty)
                if stock["tracking"] == "SERIAL" and qty != 1:
                    invalid("quantity_base", "Mỗi serial xuất đúng một đơn vị.")
                if stock["on_hand"] < qty or stock["reserved"] < qty:
                    raise DomainError("INSUFFICIENT_STOCK", "Không đủ tồn/giữ chỗ hợp lệ; cần đối soát.")
                line_totals[line["id"]] += qty
                source_totals[parent["id"]] += qty
                if line_totals[line["id"]] > Decimal(line["remaining_base"]):
                    raise DomainError("ISSUE_EXCEEDED", "Vượt phần phiếu xuất còn lại.")
                if source_totals[parent["id"]] > Decimal(parent["remaining_base"]):
                    raise DomainError("SOURCE_EXCEEDED", "Vượt phần SO còn lại.")
                stock["on_hand"] -= qty
                stock["reserved"] -= qty
                moves.append(dict(id=uuid4(), line=line["id"], stock=reservation["stock_item_id"],
                                  location=reservation["location_id"], quantity=qty, unit=stock["base_uom_id"],
                                  serial=stock["serial_id"], reservation=reservation["id"]))
            doc["status"] = "COMPLETED" if all(Decimal(r["remaining_base"]) == line_totals[r["id"]] for r in saved.values()) else "PARTIAL"
            source["status"] = "COMPLETED" if all(Decimal(r["remaining_base"]) == source_totals[r["id"]] for r in parents.values()) else "PARTIAL"
            doc["version"] += 1
            source["version"] += 1
            tx_id = uuid4()
            result = IssuePostResult(**self.result(doc, request_id), transaction_id=tx_id,
                                     source_order_id=source["id"], source_order_version=source["version"],
                                     source_order_status=source["status"]).model_dump(mode="json")
            c.execute(text("""INSERT INTO wms.inventory_transaction
                (id,document_id,execution_key,operation,business_date,posted_at,posted_by,request_hash,response)
                VALUES (:id,:doc,:key,'ISSUE',:day,:now,:actor,:hash,CAST(:response AS jsonb))"""),
                {"id": tx_id, "doc": doc_id, "key": payload.execution_key, "day": doc["business_date"],
                 "now": self.identity.clock(), "actor": actor, "hash": digest, "response": encode(result)})
            for move in moves:
                c.execute(text("""INSERT INTO wms.stock_move
                    (id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
                    VALUES (:id,:tx,:line,:stock,:location,:destination,:quantity,:unit)"""),
                    {**move, "tx": tx_id, "destination": EXTERNAL})
                c.execute(text("""UPDATE wms.stock_balance SET on_hand=on_hand-:quantity,reserved=reserved-:quantity,
                    version=version+1 WHERE stock_item_id=:stock AND location_id=:location"""), move)
                c.execute(text("UPDATE wms.reservation SET consumed=consumed+:quantity WHERE id=:reservation"), move)
                c.execute(text("""INSERT INTO wms.reservation_consumption(id,reservation_id,move_id,quantity)
                    VALUES (:consumption,:reservation,:id,:quantity)"""), {**move, "consumption": uuid4()})
                if move["serial"]:
                    c.execute(text("DELETE FROM wms.serial_position WHERE serial_id=:serial"), move)
            for changed in (source, doc):
                c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), changed)
            self.orders.effects(c, actor, doc, "issue.post", result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(actor_id=actor, key=key, command="issue.post", resource_id=doc_id,
                                payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def operation(self, auth, key):
        record = one(auth.connection, "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
                     actor=auth.principal.user_id, key=key)
        lifecycle = {"order.None." + action for action in ("submit", "revise", "cancel", "close", "assign", "decide")}
        if (not record or record["response"].get("kind") != "ISSUE"
                or not (record["command"].startswith("issue.") or record["command"] in lifecycle)):
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK; chỉ gửi lại đúng key và nội dung cũ.")
        doc = self.orders.document(auth, UUID(record["response"]["id"]), "ISSUE")
        action = record["command"].split(".")[-1]
        if action in {"create", "update", "submit", "revise"}:
            self.orders.may_edit(auth, doc)
            self.source(auth, doc)
        elif action in {"cancel", "close", "assign", "decide"}:
            auth.require({"assign": "document.assign", "decide": "document.approve"}.get(action, "document.cancel"),
                         doc["warehouse_id"])
            self.source(auth, doc)
        else:
            self.may_handle(auth, doc, "issue.post" if action == "post" else "reservation.manage")
        return IssueOperation(command=record["command"], result=record["response"])
