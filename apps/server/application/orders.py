"""PO/SO lifecycle. No stock mutation; downstream posting must lock its source order first."""

import json
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandBus, CommandResult
from apps.server.application.master_data import active_reference, invalid, one
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.database import PostgresUnitOfWork
from packages.contracts.orders import ApprovalView, OrderResult, OrderView
from packages.contracts.traceability import COMPANY_OWNER

DRAFT_PERMISSION = {"PO": "po.draft", "SO": "so.draft", "RECEIPT": "receipt.draft", "OPENING": "opening.draft"}
SUMMARY_SQL = """SELECT d.*,p.name AS partner_name,u.display_name AS creator_name FROM wms.document d
    LEFT JOIN wms.partner p ON p.id=d.partner_id JOIN wms.app_user u ON u.id=d.created_by"""


def encode(value):
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def amount(value):
    return format(value, ".6f")


class OrderService:
    def __init__(self, identity):
        self.identity = identity
        self.bus = CommandBus(lambda: PostgresUnitOfWork(identity.engine))

    def document(self, auth, doc_id, kind=None, lock=False):
        doc = auth.document(doc_id)
        if doc["kind"] not in DRAFT_PERMISSION or (kind and doc["kind"] != kind):
            raise DomainError("NOT_FOUND", "Không tìm thấy PO/SO.")
        if lock:
            if doc["kind"] == "RECEIPT":
                source = self.receipts.source(auth, doc)
                auth.connection.execute(
                    text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": source["id"]}
                )
            auth.connection.execute(
                text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"), {"id": doc_id}
            )
            doc = auth.document(doc_id)
        return doc

    def may_edit(self, auth, doc):
        auth.require(DRAFT_PERMISSION[doc["kind"]], doc["warehouse_id"])
        if doc["created_by"] != auth.principal.user_id and not one(
            auth.connection,
            "SELECT id FROM wms.document_assignment WHERE document_id=:doc AND user_id=:user",
            doc=doc["id"],
            user=auth.principal.user_id,
        ):
            raise DomainError("FORBIDDEN", "Chỉ người lập hoặc được giao mới sửa/gửi phiếu.")

    def listing(self, auth, kind, warehouse_id, status=None, after=None, limit=50):
        auth.require("document.read", warehouse_id, hidden=True)
        grants = auth.grants("document.read", warehouse_id)
        broad = any(g["role_code"] not in {"RECEIVER", "PICKER"} for g in grants)
        rows = (
            auth.connection.execute(
                text(
                    SUMMARY_SQL
                    + """ WHERE d.kind=:kind AND d.warehouse_id=:warehouse
            AND (CAST(:status AS text) IS NULL OR d.status=:status)
            AND (CAST(:after AS uuid) IS NULL OR d.id>:after)
            AND (:broad OR d.created_by=:user OR EXISTS(SELECT 1 FROM wms.document_assignment a
                WHERE a.document_id=d.id AND a.user_id=:user)) ORDER BY d.id LIMIT :limit"""
                ),
                {
                    "kind": kind,
                    "warehouse": warehouse_id,
                    "status": status,
                    "after": after,
                    "broad": broad,
                    "user": auth.principal.user_id,
                    "limit": limit + 1,
                },
            )
            .mappings()
            .all()
        )
        from packages.contracts.orders import OrderSummary

        items = [OrderSummary(**{k: r[k] for k in OrderSummary.model_fields}) for r in rows[:limit]]
        return {"items": items, "next_after": items[-1].id if len(rows) > limit else None}

    def lines(self, connection, doc):
        # Return net fulfillment; reversal removes the original move once, never subtracts twice.
        rows = (
            connection.execute(
                text("""SELECT l.*,p.sku,p.name AS product_name,p.tracking,bu.code AS base_uom_code,u.code AS uom_code,o.code AS owner_code,
            (SELECT pu.id FROM wms.product_uom pu WHERE pu.product_id=l.product_id AND pu.uom_id=l.uom_id AND pu.factor=l.factor_snapshot AND pu.is_active ORDER BY pu.revision DESC LIMIT 1) AS product_uom_id,
            COALESCE((SELECT SUM(m.quantity_base) FROM wms.document_line child
                JOIN wms.stock_move m ON m.line_id=child.id JOIN wms.inventory_transaction t ON t.id=m.transaction_id
                JOIN wms.document d ON d.id=child.document_id AND d.id=t.document_id
                WHERE ((:direct AND child.id=l.id) OR (NOT :direct AND child.source_line_id=l.id)) AND child.product_id=l.product_id
                  AND child.owner_id=l.owner_id AND child.consignment_id IS NOT DISTINCT FROM l.consignment_id
                  AND t.operation=:operation AND d.kind=:child_kind
                  AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)),0) AS posted
            FROM wms.document_line l JOIN wms.product p ON p.id=l.product_id
            JOIN wms.uom u ON u.id=l.uom_id JOIN wms.uom bu ON bu.id=p.base_uom_id JOIN wms.stock_owner o ON o.id=l.owner_id
            WHERE l.document_id=:doc ORDER BY l.line_no"""),
                {
                    "doc": doc["id"],
                    "operation": {"SO": "ISSUE", "OPENING": "OPEN"}.get(doc["kind"], "RECEIVE"),
                    "child_kind": {"SO": "ISSUE", "OPENING": "OPENING"}.get(doc["kind"], "RECEIPT"),
                    "direct": doc["kind"] in {"RECEIPT", "OPENING"},
                },
            )
            .mappings()
            .all()
        )
        result = []
        for row in rows:
            r = dict(row)
            remaining = r["base_quantity"] - r["posted"] - r["closed_base_quantity"]
            if remaining < 0:
                raise DomainError("QUANTITY_CONFLICT", "Sổ vượt lượng yêu cầu; cần đối soát trước thao tác.")
            for field in ["quantity", "factor_snapshot", "base_quantity"]:
                r[field] = format(r[field], "f")
            r.update(
                posted_base=amount(r.pop("posted")),
                closed_base=amount(r["closed_base_quantity"]),
                remaining_base=amount(remaining),
            )
            result.append(r)
        return result

    def snapshot(self, connection, doc):
        lines = (
            connection.execute(
                text("SELECT * FROM wms.document_line WHERE document_id=:doc ORDER BY line_no"),
                {"doc": doc["id"]},
            )
            .mappings()
            .all()
        )
        assignments = (
            connection.execute(
                text("SELECT user_id FROM wms.document_assignment WHERE document_id=:doc ORDER BY user_id"),
                {"doc": doc["id"]},
            )
            .scalars()
            .all()
        )
        return json.loads(
            encode(
                {
                    "header": {
                        k: doc[k]
                        for k in ["id", "kind", "warehouse_id", "partner_id", "business_date", "attributes"]
                    },
                    "lines": [dict(r) for r in lines],
                    "assigned_user_ids": assignments,
                    **({"opening": self.openings.snapshot(connection, doc)} if doc["kind"] == "OPENING" else {}),
                }
            )
        )

    def approval(self, auth, request_id):
        req = one(
            auth.connection,
            "SELECT r.*,p.revision AS policy_revision FROM wms.approval_request r JOIN wms.approval_policy p ON p.id=r.policy_id WHERE r.id=:id",
            id=request_id,
        )
        if not req:
            raise DomainError("NOT_FOUND", "Không tìm thấy yêu cầu duyệt.")
        doc = self.document(auth, req["document_id"])
        steps = (
            auth.connection.execute(
                text("""SELECT s.*,r.code AS role_code,a.code AS alternative_code,u.display_name AS decider_name
            FROM wms.approval_step s JOIN wms.role r ON r.id=s.required_role_id
            LEFT JOIN wms.role a ON a.id=s.alternative_role_id LEFT JOIN wms.app_user u ON u.id=s.decided_by
            WHERE s.request_id=:id ORDER BY s.step_no"""),
                {"id": request_id},
            )
            .mappings()
            .all()
        )
        can_decide = False
        if req["status"] == "PENDING" and doc["status"] == "SUBMITTED":
            try:
                self.approver(auth, doc, req, steps)
                can_decide = True
            except DomainError:
                pass
        return ApprovalView(
            id=req["id"],
            document_id=doc["id"],
            document_version=req["document_version"],
            current_version=doc["version"],
            policy_revision=req["policy_revision"],
            requested_by=req["requested_by"],
            status=req["status"],
            created_at=req["created_at"],
            steps=[
                {
                    **{
                        k: s[k]
                        for k in ["step_no", "status", "decided_by", "decider_name", "decided_at", "comment"]
                    },
                    "roles": [s["role_code"]] + ([s["alternative_code"]] if s["alternative_code"] else []),
                }
                for s in steps
            ],
            can_decide=can_decide,
        )

    def approver(self, auth, doc, req, steps):
        prior = tuple(s["decided_by"] for s in steps if s["decided_by"])
        auth.require_approval(doc, requester_id=req["requested_by"], previous_approvers=prior)
        pending = next((s for s in steps if s["status"] == "PENDING"), None)
        if not pending or any(s["status"] == "REJECTED" for s in steps):
            raise DomainError("INVALID_STATE", "Yêu cầu đã có quyết định.")
        roles = {pending["role_code"], pending["alternative_code"]}
        permission = "opening.approve" if doc["kind"] == "OPENING" else "document.approve"
        if not any(g["role_code"] in roles for g in auth.grants(permission, doc["warehouse_id"])):
            raise DomainError("FORBIDDEN", "Không đúng vai trò của bước duyệt hiện tại.")
        return pending

    def read(self, auth, doc_id, kind=None):
        doc = self.document(auth, doc_id, kind)
        summary = one(auth.connection, SUMMARY_SQL + " WHERE d.id=:id", id=doc_id)
        rows = self.lines(auth.connection, doc)
        reqs = (
            auth.connection.execute(
                text("SELECT id FROM wms.approval_request WHERE document_id=:id ORDER BY document_version"),
                {"id": doc_id},
            )
            .scalars()
            .all()
        )
        approvals = [self.approval(auth, x) for x in reqs]
        actions = []
        try:
            self.may_edit(auth, doc)
            if doc["status"] in {"DRAFT", "REJECTED"}:
                actions += ["edit", "submit"]
            if doc["status"] == "APPROVED":
                actions += ["revise"]
        except DomainError:
            pass
        if auth.allows("document.assign", doc["warehouse_id"]) and doc["status"] in {"DRAFT", "REJECTED"}:
            actions += ["assign"]
        if auth.allows("document.cancel", doc["warehouse_id"]):
            if doc["status"] in {"DRAFT", "REJECTED", "SUBMITTED", "APPROVED"}:
                actions += ["cancel"]
            if doc["status"] == "PARTIAL" and doc["kind"] not in {"RECEIPT", "OPENING"}:
                actions += ["close"]
        if any(a.can_decide for a in approvals):
            actions += ["approve", "reject"]
        from packages.contracts.orders import OrderLineView, OrderSummary

        return OrderView(
            **{k: summary[k] for k in OrderSummary.model_fields},
            reason=doc["reason"],
            lines=[OrderLineView(**{k: r[k] for k in OrderLineView.model_fields}) for r in rows],
            assigned_user_ids=auth.connection.execute(
                text("SELECT user_id FROM wms.document_assignment WHERE document_id=:id ORDER BY user_id"),
                {"id": doc_id},
            )
            .scalars()
            .all(),
            approvals=approvals,
            allowed_actions=actions,
        )

    def validate_header(self, connection, kind, warehouse, partner):
        active_reference(connection, "warehouse", warehouse, "warehouse_id")
        if kind == "OPENING":
            if partner is not None:
                invalid("partner_id", "Tồn đầu kỳ không có nhà cung cấp nguồn.")
            return
        row = active_reference(connection, "partner", partner, "partner_id")
        if not row["is_customer" if kind == "SO" else "is_supplier"]:
            invalid("partner_id", "PO cần nhà cung cấp; SO cần khách hàng.")

    def prepare_lines(self, connection, payload):
        result = []
        # Same product lock used by master writes, always in UUID order.
        for product_id in sorted({line.product_id for line in payload.lines}):
            connection.execute(text("SELECT id FROM wms.product WHERE id=:id FOR SHARE"), {"id": product_id})
        for number, line in enumerate(payload.lines, 1):
            p = active_reference(connection, "product", line.product_id, "product_id")
            conversion = one(
                connection,
                """SELECT pu.*,u.decimal_places FROM wms.product_uom pu
                JOIN wms.uom u ON u.id=pu.uom_id AND u.is_active WHERE pu.id=:id AND pu.product_id=:product AND pu.is_active FOR SHARE OF pu,u""",
                id=line.product_uom_id,
                product=line.product_id,
            )
            if not conversion:
                invalid("product_uom_id", "Quy đổi không còn hoạt động hoặc không thuộc sản phẩm.")
            unit = active_reference(connection, "uom", p["base_uom_id"], "product_id")
            with localcontext() as ctx:
                ctx.prec = 50
                qty = Decimal(line.quantity)
                base = qty * conversion["factor"]
                if (
                    qty != qty.quantize(Decimal(1).scaleb(-conversion["decimal_places"]))
                    or base != base.quantize(Decimal(1).scaleb(-min(unit["decimal_places"], 6)))
                    or base >= Decimal("100000000000000")
                ):
                    invalid(
                        "quantity",
                        "Số lượng không đúng độ chính xác UOM hoặc vượt giới hạn; không tự làm tròn.",
                    )
                if p["tracking"] == "SERIAL" and base != base.to_integral_value():
                    invalid("quantity", "Sản phẩm serial cần lượng nguyên.")
            # Orders are purchases/sales of company stock. Consignment is not implicitly a purchase/sale.
            if line.owner_id != COMPANY_OWNER or line.consignment_id is not None:
                invalid(
                    "owner_id", "PO/SO hiện chỉ hỗ trợ hàng doanh nghiệp; ký gửi cần luồng và policy riêng."
                )
            result.append(
                dict(
                    id=uuid4(),
                    line_no=number,
                    product_id=line.product_id,
                    uom_id=conversion["uom_id"],
                    quantity=qty,
                    factor_snapshot=conversion["factor"],
                    base_quantity=base,
                    owner_id=line.owner_id,
                )
            )
        return result

    def no_dependencies(self, connection, doc_id, *, edit=False, closing=False):
        if one(
            connection, "SELECT id FROM wms.inventory_transaction WHERE document_id=:id LIMIT 1", id=doc_id
        ):
            raise DomainError("ALREADY_POSTED", "Phiếu có lịch sử ghi sổ; không sửa/hủy trực tiếp.")
        child_status = "" if edit else " AND c.status NOT IN ('CANCELLED','COMPLETED')"
        if one(
            connection,
            """SELECT child.id FROM wms.document_line parent JOIN wms.document_line child ON child.source_line_id=parent.id
            JOIN wms.document c ON c.id=child.document_id WHERE parent.document_id=:id"""
            + child_status
            + " LIMIT 1",
            id=doc_id,
        ):
            raise DomainError("DEPENDENT_DOCUMENT", "Còn phiếu tham chiếu; xử lý phiếu con trước.")
        if one(
            connection,
            """SELECT r.id FROM wms.reservation r JOIN wms.document_line l ON l.id=r.line_id
            WHERE (l.document_id=:id OR l.source_line_id IN
                (SELECT id FROM wms.document_line WHERE document_id=:id))
              AND r.quantity>r.consumed+r.released LIMIT 1""",
            id=doc_id,
        ):
            raise DomainError("RESERVATION_OPEN", "Cần giải phóng giữ chỗ bằng nghiệp vụ kho trước.")
        if not closing:
            doc = one(connection, "SELECT * FROM wms.document WHERE id=:id", id=doc_id)
            if any(Decimal(line["posted_base"]) > 0 for line in self.lines(connection, doc)):
                raise DomainError("ALREADY_POSTED", "Đã thực hiện một phần; dùng đóng phần còn lại.")

    def invalidate(self, connection, doc_id):
        connection.execute(
            text(
                "UPDATE wms.approval_request SET status='INVALIDATED' WHERE document_id=:id AND status IN ('PENDING','APPROVED')"
            ),
            {"id": doc_id},
        )

    def effects(self, connection, actor, doc, action, result, reason, request_id):
        prefix = {"RECEIPT": "receipt.", "OPENING": "opening."}.get(doc["kind"], "order.")
        event = action if action.startswith(("receipt.", "opening.")) else prefix + action
        params = {
            "id": uuid4(),
            "actor": actor,
            "warehouse": doc["warehouse_id"],
            "action": event,
            "doc": doc["id"],
            "request": request_id,
            "now": self.identity.clock(),
            "data": encode(result),
            "reason": reason,
        }
        connection.execute(
            text("""INSERT INTO wms.audit_event(id,actor_id,warehouse_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
            VALUES (:id,:actor,:warehouse,:action,'document',:doc,:request,:now,CAST(:data AS jsonb),:reason)"""),
            params,
        )
        connection.execute(
            text("""INSERT INTO wms.outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,:event,:doc,CAST(:data AS jsonb),:now,:now,0)"""),
            {
                "id": uuid4(),
                "event": event + ".v1",
                "doc": doc["id"],
                "data": encode(result),
                "now": self.identity.clock(),
            },
        )

    def write(self, access, key, kind, action, payload, request_id, resource_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        doc_id = resource_id or uuid4()
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            context["auth"] = auth
            if action == "create":
                auth.require("document.read", payload.warehouse_id, hidden=True)
                auth.require(DRAFT_PERMISSION[kind], payload.warehouse_id)
            else:
                if action == "decide":
                    req = one(
                        uow.connection, "SELECT * FROM wms.approval_request WHERE id=:id", id=resource_id
                    )
                    if not req:
                        raise DomainError("NOT_FOUND", "Không tìm thấy yêu cầu duyệt.")
                    context["request"] = req
                    doc = self.document(auth, req["document_id"])
                    auth.require("opening.approve" if doc["kind"] == "OPENING" else "document.approve", doc["warehouse_id"])
                else:
                    doc = self.document(auth, doc_id, kind)
                    if action in {"assign", "cancel", "close"}:
                        auth.require(
                            "document.assign" if action == "assign" else "document.cancel",
                            doc["warehouse_id"],
                        )
                    else:
                        self.may_edit(auth, doc)
                context["doc"] = doc

        def handle(uow):
            c = uow.connection
            auth = context["auth"]
            approval_id = None
            if action == "create":
                self.validate_header(c, kind, payload.warehouse_id, payload.partner_id)
                lines = self.prepare_lines(c, payload)
                number = f"{kind}-{payload.business_date:%Y%m%d}-{c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one():08d}"
                doc = dict(
                    id=doc_id,
                    number=number,
                    kind=kind,
                    warehouse_id=payload.warehouse_id,
                    status="DRAFT",
                    version=1,
                )
                c.execute(
                    text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,partner_id,business_date,created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,:kind,'DRAFT',:warehouse,:partner,:day,:actor,:now,1,'{}',:reason)"""),
                    {
                        "id": doc_id,
                        "number": number,
                        "kind": kind,
                        "warehouse": payload.warehouse_id,
                        "partner": payload.partner_id,
                        "day": payload.business_date,
                        "actor": actor,
                        "now": self.identity.clock(),
                        "reason": payload.reason,
                    },
                )
            else:
                doc = self.document(auth, context["doc"]["id"], kind, lock=True)
                require_version(doc["version"], payload.expected_version)
                if doc["kind"] == "RECEIPT" and action in {"submit", "decide"}:
                    self.receipts.validate_saved(auth, doc)
                if doc["kind"] == "OPENING" and action in {"submit", "decide"}:
                    self.openings.validate_saved(auth, doc)
                if doc["kind"] in {"RECEIPT", "OPENING"} and action == "close":
                    raise DomainError("INVALID_STATE", "Loại phiếu này không hỗ trợ đóng thiếu.")
                if action in {"update", "submit", "revise"}:
                    self.may_edit(auth, doc)
                if action == "update":
                    if doc["status"] not in {"DRAFT", "REJECTED"}:
                        raise DomainError(
                            "INVALID_STATE", "Chỉ sửa nháp/từ chối. Phiếu đã duyệt cần yêu cầu sửa lại."
                        )
                    if payload.warehouse_id != doc["warehouse_id"]:
                        invalid("warehouse_id", "Không chuyển kho của phiếu đã tạo.")
                    self.no_dependencies(c, doc["id"], edit=True)
                    if one(
                        c,
                        """SELECT id FROM wms.document_line WHERE document_id=:id
                        AND (reference_unit_price IS NOT NULL OR source_line_id IS NOT NULL) LIMIT 1""",
                        id=doc["id"],
                    ):
                        raise DomainError(
                            "UNSUPPORTED_ORDER_FIELDS",
                            "Phiếu có giá/nguồn cũ chưa được hỗ trợ sửa; giữ nguyên dữ liệu.",
                        )
                    self.validate_header(c, doc["kind"], payload.warehouse_id, payload.partner_id)
                    lines = self.prepare_lines(c, payload)
                    self.invalidate(c, doc["id"])
                    c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc["id"]})
                    c.execute(
                        text("UPDATE wms.document SET partner_id=:partner,business_date=:day WHERE id=:id"),
                        {"id": doc["id"], "partner": payload.partner_id, "day": payload.business_date},
                    )
                    doc["status"] = "DRAFT"
                elif action == "submit":
                    if doc["status"] not in {"DRAFT", "REJECTED"}:
                        raise DomainError("INVALID_STATE", "Phiếu không ở trạng thái gửi duyệt.")
                    self.validate_header(c, doc["kind"], doc["warehouse_id"], doc["partner_id"])
                    saved = self.lines(c, doc)
                    if not saved:
                        raise DomainError("EMPTY_DOCUMENT", "Cần ít nhất một dòng hàng.")
                    for line in saved:
                        active_reference(c, "product", line["product_id"], "product_id")
                        if line["owner_id"] != COMPANY_OWNER:
                            invalid("owner_id", "Chưa hỗ trợ duyệt đơn ký gửi hoặc chưa phân loại.")
                    policy = one(
                        c,
                        "SELECT * FROM wms.approval_policy WHERE document_kind=:kind AND is_active FOR SHARE",
                        kind=doc["kind"],
                    )
                    steps = (
                        c.execute(
                            text(
                                "SELECT * FROM wms.approval_policy_step WHERE policy_id=:id ORDER BY step_no FOR SHARE"
                            ),
                            {"id": policy["id"]},
                        )
                        .mappings()
                        .all()
                        if policy
                        else []
                    )
                    if not steps or [s["step_no"] for s in steps] != list(range(1, len(steps) + 1)):
                        raise DomainError(
                            "POLICY_MISSING", "Chưa có policy duyệt hợp lệ; không tự bỏ qua duyệt."
                        )
                    approval_id = uuid4()
                    c.execute(
                        text("""INSERT INTO wms.approval_request(id,document_id,document_version,policy_id,requested_by,status,created_at,content_snapshot)
                        VALUES (:id,:doc,:version,:policy,:actor,'PENDING',:now,CAST(:snapshot AS jsonb))"""),
                        {
                            "id": approval_id,
                            "doc": doc["id"],
                            "version": doc["version"] + 1,
                            "policy": policy["id"],
                            "actor": actor,
                            "now": self.identity.clock(),
                            "snapshot": encode(self.snapshot(c, doc)),
                        },
                    )
                    for step in steps:
                        c.execute(
                            text("""INSERT INTO wms.approval_step(id,request_id,step_no,required_role_id,alternative_role_id,status)
                            VALUES (:id,:request,:step,:role,:alt,'PENDING')"""),
                            {
                                "id": uuid4(),
                                "request": approval_id,
                                "step": step["step_no"],
                                "role": step["role_id"],
                                "alt": step["alternative_role_id"],
                            },
                        )
                    doc["status"] = "SUBMITTED"
                elif action == "decide":
                    req = one(c, "SELECT * FROM wms.approval_request WHERE id=:id FOR UPDATE", id=resource_id)
                    if req["status"] != "PENDING" or doc["status"] != "SUBMITTED":
                        raise DomainError("INVALID_STATE", "Yêu cầu duyệt không còn chờ quyết định.")
                    steps = (
                        c.execute(
                            text("""SELECT s.*,r.code AS role_code,a.code AS alternative_code FROM wms.approval_step s
                        JOIN wms.role r ON r.id=s.required_role_id LEFT JOIN wms.role a ON a.id=s.alternative_role_id
                        WHERE s.request_id=:id ORDER BY s.step_no FOR UPDATE OF s"""),
                            {"id": resource_id},
                        )
                        .mappings()
                        .all()
                    )
                    step = self.approver(auth, doc, req, steps)
                    if req["content_snapshot"] != self.snapshot(c, doc) or doc["version"] != req[
                        "document_version"
                    ] + sum(s["status"] == "APPROVED" for s in steps):
                        raise DomainError("STALE_APPROVAL", "Nội dung/version đã đổi; cần gửi duyệt lại.")
                    decision = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
                    c.execute(
                        text(
                            "UPDATE wms.approval_step SET status=:status,decided_by=:actor,decided_at=:now,comment=:comment WHERE id=:id"
                        ),
                        {
                            "id": step["id"],
                            "status": decision,
                            "actor": actor,
                            "now": self.identity.clock(),
                            "comment": payload.reason,
                        },
                    )
                    final = decision == "REJECTED" or all(
                        s["id"] == step["id"] or s["status"] == "APPROVED" for s in steps
                    )
                    if final:
                        c.execute(
                            text("UPDATE wms.approval_request SET status=:status WHERE id=:id"),
                            {"status": decision, "id": resource_id},
                        )
                        doc["status"] = decision
                    approval_id = resource_id
                elif action == "revise":
                    if doc["status"] != "APPROVED":
                        raise DomainError("INVALID_STATE", "Chỉ đưa phiếu đã duyệt chưa thực hiện về nháp.")
                    self.no_dependencies(c, doc["id"], edit=True)
                    self.invalidate(c, doc["id"])
                    doc["status"] = "DRAFT"
                elif action == "assign":
                    if doc["status"] not in {"DRAFT", "REJECTED"}:
                        raise DomainError(
                            "INVALID_STATE", "Phân công trước khi gửi duyệt; muốn đổi cần đưa về nháp."
                        )
                    for user in payload.user_ids:
                        person = active_reference(c, "app_user", user, "user_ids")
                        target = Authorization(
                            c,
                            Principal(user, UUID(int=0), person["username"], person["display_name"], None),
                            self.identity.clock(),
                        )
                        target.require("document.read", doc["warehouse_id"])
                    c.execute(
                        text("DELETE FROM wms.document_assignment WHERE document_id=:id"), {"id": doc["id"]}
                    )
                    for user in payload.user_ids:
                        c.execute(
                            text(
                                "INSERT INTO wms.document_assignment(id,document_id,user_id,assigned_by) VALUES (:id,:doc,:user,:actor)"
                            ),
                            {"id": uuid4(), "doc": doc["id"], "user": user, "actor": actor},
                        )
                elif action in {"cancel", "close"}:
                    if action == "cancel" and doc["status"] not in {
                        "DRAFT",
                        "SUBMITTED",
                        "REJECTED",
                        "APPROVED",
                    }:
                        raise DomainError(
                            "INVALID_STATE", "Phiếu không thể hủy; phần đã thực hiện cần đóng thiếu."
                        )
                    if action == "close" and doc["status"] != "PARTIAL":
                        raise DomainError("INVALID_STATE", "Chỉ đóng phần còn lại của phiếu PARTIAL.")
                    self.no_dependencies(c, doc["id"], closing=action == "close")
                    for line in self.lines(c, doc):
                        c.execute(
                            text(
                                "UPDATE wms.document_line SET closed_base_quantity=base_quantity-:posted WHERE id=:id"
                            ),
                            {"id": line["id"], "posted": Decimal(line["posted_base"])},
                        )
                    self.invalidate(c, doc["id"])
                    doc["status"] = "COMPLETED" if action == "close" else "CANCELLED"
                doc["version"] += 1
                c.execute(
                    text(
                        "UPDATE wms.document SET status=:status,version=:version,reason=:reason WHERE id=:id"
                    ),
                    {**doc, "reason": payload.reason},
                )
            if action in {"create", "update"}:
                for line in lines:
                    c.execute(
                        text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id)
                        VALUES (:id,:doc,:line_no,:product_id,:uom_id,:quantity,:factor_snapshot,:base_quantity,:owner_id)"""),
                        {**line, "doc": doc["id"]},
                    )
            result = OrderResult(
                **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                request_id=request_id,
                approval_request_id=approval_id,
            ).model_dump(mode="json")
            self.effects(c, actor, doc, action, result, payload.reason, request_id)
            return CommandResult(result, 201 if action == "create" else 200)

        # Create must hash a stable resource, not its newly generated result UUID.
        return self.bus.execute(
            actor_id=actor,
            key=key,
            command=f"order.{kind}.{action}",
            resource_id=resource_id or UUID(int=0),
            payload=payload.model_dump(mode="json"),
            authorize=authorize,
            handle=handle,
        )
