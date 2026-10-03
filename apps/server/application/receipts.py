"""Approved PO receipts. Plan is part of the immutable approval snapshot.

Lock order: source PO, receipt, warehouse/period, locations, products, identities,
balances. Product locks serialize identity creation across overlapping receipts.
"""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, invalid, one
from apps.server.application.orders import encode
from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.receipts import OperationView, ReceiptPlan, ReceiptPostResult, ReceiptView
from packages.contracts.traceability import COMPANY_OWNER

EXTERNAL = UUID("00000000-0000-4000-8000-000000000201")


class ReceiptService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.receipts = self

    def source(self, auth, doc):
        try:
            source_id = UUID(doc["attributes"]["receipt_plan"]["source_order_id"])
        except (KeyError, ValueError, TypeError):
            raise DomainError("UNSUPPORTED_RECEIPT", "Phiếu cũ chưa có kế hoạch nhận đã xác minh.") from None
        return self.orders.document(auth, source_id, "PO")

    def approved(self, connection, doc):
        if doc["status"] not in {"APPROVED", "PARTIAL"}:
            raise DomainError("INVALID_STATE", "Phiếu nguồn/phiếu nhận phải đã duyệt và còn thực hiện.")
        req = one(
            connection,
            """SELECT * FROM wms.approval_request
            WHERE document_id=:id AND status='APPROVED' ORDER BY document_version DESC LIMIT 1""",
            id=doc["id"],
        )
        if not req or req["content_snapshot"] != self.orders.snapshot(connection, doc):
            raise DomainError("STALE_APPROVAL", "Thiếu bản duyệt đúng nội dung hiện tại.")
        steps = (
            connection.execute(
                text("SELECT status FROM wms.approval_step WHERE request_id=:id"), {"id": req["id"]}
            )
            .scalars()
            .all()
        )
        if (
            not steps
            or any(s != "APPROVED" for s in steps)
            or doc["version"] < req["document_version"] + len(steps)
        ):
            raise DomainError("STALE_APPROVAL", "Chưa hoàn tất các bước duyệt.")

    def validate_saved(self, auth, doc):
        source = self.source(auth, doc)
        self.approved(auth.connection, source)
        self.orders.validate_header(auth.connection, "PO", source["warehouse_id"], source["partner_id"])
        if doc["warehouse_id"] != source["warehouse_id"] or doc["partner_id"] != source["partner_id"]:
            raise DomainError("SOURCE_MISMATCH", "Phiếu nhận không khớp kho/nhà cung cấp của PO.")

    def may_post(self, auth, doc):
        auth.require("receipt.post", doc["warehouse_id"])
        if doc["created_by"] != auth.principal.user_id and not one(
            auth.connection,
            "SELECT id FROM wms.document_assignment WHERE document_id=:id AND user_id=:user",
            id=doc["id"],
            user=auth.principal.user_id,
        ):
            raise DomainError("FORBIDDEN", "Chỉ người lập hoặc được giao mới ghi sổ nhận hàng.")
        self.source(auth, doc)  # Source visibility is rechecked even on replay.

    def locations(self, auth, warehouse_id):
        auth.require("document.read", warehouse_id, hidden=True)
        if not (
            auth.allows("receipt.draft", warehouse_id)
            or auth.allows("receipt.post", warehouse_id)
            or auth.allows("document.approve", warehouse_id)
        ):
            auth.require("receipt.draft", warehouse_id)
        return [
            dict(row)
            for row in auth.connection.execute(
                text("""SELECT id,code,name,kind
            FROM wms.location WHERE warehouse_id=:id AND is_active AND kind IN ('RECEIVING','QUARANTINE')
            ORDER BY code LIMIT 500"""),
                {"id": warehouse_id},
            ).mappings()
        ]

    def read(self, auth, doc_id):
        view = self.orders.read(auth, doc_id, "RECEIPT")
        doc = self.orders.document(auth, doc_id, "RECEIPT")
        source = self.source(auth, doc)
        plan = []
        for line_id, spec in doc["attributes"]["receipt_plan"]["lines"].items():
            line = next((line for line in view.lines if str(line.id) == line_id), None)
            if not line:
                raise DomainError("SOURCE_MISMATCH", "Kế hoạch không khớp dòng nhận.")
            location = one(
                auth.connection,
                "SELECT code FROM wms.location WHERE id=:id",
                id=UUID(spec["destination_location_id"]),
            )
            plan.append(
                ReceiptPlan(
                    **spec, document_line_id=line_id, location_code=location["code"], tracking=line.tracking
                )
            )
        actions = list(view.allowed_actions)
        if doc["status"] in {"APPROVED", "PARTIAL"}:
            try:
                self.may_post(auth, doc)
                actions.append("post")
            except DomainError:
                pass
        return ReceiptView(
            **{**view.model_dump(), "allowed_actions": actions}, source_order_id=source["id"], plan=plan
        )

    def validate_tracking(self, product, spec, qty):
        tracking = product["tracking"]
        lot, serial = spec.lot_code, spec.serial_code
        if (
            (tracking == "NONE" and (lot or serial))
            or (tracking == "LOT" and (not lot or serial))
            or (tracking == "SERIAL" and (not serial or lot or qty != 1))
        ):
            invalid(
                "lines",
                "Lô/serial không đúng loại sản phẩm; mỗi serial có lượng cơ sở 1.",
                "TRACKING_MISMATCH",
            )
        if tracking != "LOT" and (spec.manufactured_on or spec.expires_on):
            invalid("lines", "Ngày sản xuất/hạn dùng chỉ áp dụng cho lô.")
        if spec.manufactured_on and spec.expires_on and spec.manufactured_on > spec.expires_on:
            invalid("expires_on", "Hạn dùng phải từ ngày sản xuất trở đi.")
        if product["expiry_required"] and not spec.expires_on:
            invalid("expires_on", "Sản phẩm yêu cầu hạn dùng của lô.", "LOT_EXPIRY_REQUIRED")

    def prepare(self, auth, source, payload):
        c = auth.connection
        self.approved(c, source)
        self.orders.validate_header(c, "PO", source["warehouse_id"], source["partner_id"])
        parents = {r["id"]: r for r in self.orders.lines(c, source)}
        totals, serials, rows, plan = defaultdict(Decimal), set(), [], {}
        for index, spec in enumerate(payload.lines, 1):
            parent = parents.get(spec.source_line_id)
            if not parent:
                invalid("source_line_id", "Mọi dòng nhận phải thuộc đúng PO được chọn.")
            if parent["owner_id"] != COMPANY_OWNER or parent["consignment_id"]:
                invalid("owner_id", "Luồng nhận từ PO chỉ nhận hàng doanh nghiệp.")
            product = active_reference(c, "product", parent["product_id"], "product_id")
            unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
            qty = Decimal(spec.quantity_base)
            if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                invalid("quantity_base", "Lượng nhận không đúng độ chính xác đơn vị cơ sở.")
            self.validate_tracking(product, spec, qty)
            serial_key = (parent["product_id"], spec.serial_code)
            if spec.serial_code and serial_key in serials:
                invalid("serial_code", "Serial lặp trong cùng phiếu.", "DUPLICATE_SERIAL")
            serials.add(serial_key)
            location = active_reference(
                c, "location", spec.destination_location_id, "destination_location_id"
            )
            if location["warehouse_id"] != source["warehouse_id"] or location["kind"] not in {
                "RECEIVING",
                "QUARANTINE",
            }:
                invalid("destination_location_id", "Chọn vị trí nhận/cách ly thuộc kho PO.")
            totals[parent["id"]] += qty
            if totals[parent["id"]] > Decimal(parent["remaining_base"]):
                raise DomainError("SOURCE_EXCEEDED", "Tổng lượng nhận vượt phần còn lại của dòng PO.")
            line_id = uuid4()
            rows.append(
                dict(
                    id=line_id,
                    line_no=index,
                    product_id=parent["product_id"],
                    uom_id=product["base_uom_id"],
                    quantity=qty,
                    source_line_id=parent["id"],
                    owner_id=COMPANY_OWNER,
                )
            )
            plan[str(line_id)] = spec.model_dump(mode="json")
        return rows, {"receipt_plan": {"source_order_id": str(source["id"]), "lines": plan}}

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            context["auth"] = auth
            source = self.orders.document(auth, payload.source_order_id, "PO")
            auth.require("receipt.draft", source["warehouse_id"])
            if doc_id:
                doc = self.orders.document(auth, doc_id, "RECEIPT")
                self.orders.may_edit(auth, doc)
                if self.source(auth, doc)["id"] != source["id"]:
                    invalid("source_order_id", "Không đổi PO nguồn của phiếu đã tạo.")

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            source = self.orders.document(auth, payload.source_order_id, "PO", lock=True)
            if doc_id:
                doc = self.orders.document(auth, doc_id, "RECEIPT", lock=True)
                require_version(doc["version"], payload.expected_version)
                self.orders.may_edit(auth, doc)
                if doc["status"] not in {"DRAFT", "REJECTED"}:
                    raise DomainError("INVALID_STATE", "Chỉ sửa phiếu nháp hoặc từ chối.")
                self.orders.no_dependencies(c, doc_id, edit=True)
                # Preserve unknown legacy attributes instead of silently overwriting them.
                if set(doc["attributes"]) != {"receipt_plan"}:
                    raise DomainError("UNSUPPORTED_RECEIPT", "Phiếu có dữ liệu mở rộng chưa hỗ trợ sửa.")
            rows, attrs = self.prepare(auth, source, payload)
            if doc_id:
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                doc["version"] += 1
                c.execute(
                    text("""UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,
                    attributes=CAST(:attrs AS jsonb),reason=:reason WHERE id=:id"""),
                    {**doc, "day": payload.business_date, "attrs": encode(attrs), "reason": payload.reason},
                )
            else:
                sequence = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                number = f"RCV-{payload.business_date:%Y%m%d}-{sequence:08d}"
                doc = dict(
                    id=uuid4(), number=number, kind="RECEIPT", warehouse_id=source["warehouse_id"], version=1
                )
                c.execute(
                    text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,partner_id,business_date,
                    created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'RECEIPT','DRAFT',:warehouse_id,:partner,:day,:actor,:now,1,CAST(:attrs AS jsonb),:reason)"""),
                    {
                        **doc,
                        "partner": source["partner_id"],
                        "day": payload.business_date,
                        "actor": actor,
                        "now": self.identity.clock(),
                        "attrs": encode(attrs),
                        "reason": payload.reason,
                    },
                )
            doc["status"] = "DRAFT"
            for row in rows:
                c.execute(
                    text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,
                    factor_snapshot,base_quantity,source_line_id,owner_id)
                    VALUES (:id,:doc,:line_no,:product_id,:uom_id,:quantity,1,:quantity,:source_line_id,:owner_id)"""),
                    {**row, "doc": doc["id"]},
                )
            from packages.contracts.orders import OrderResult

            result = OrderResult(
                **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                request_id=request_id,
            ).model_dump(mode="json")
            self.orders.effects(
                c,
                actor,
                doc,
                "receipt.update" if doc_id else "receipt.create",
                result,
                payload.reason,
                request_id,
            )
            return CommandResult(result, 200 if doc_id else 201)

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command="receipt.update" if doc_id else "receipt.create",
            resource_id=doc_id or UUID(int=0),
            payload=payload.model_dump(mode="json"),
            authorize=authorize,
            handle=handle,
        )

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}
        digest = payload_hash("receipt.post", doc_id, payload.model_dump(mode="json"))

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            self.may_post(auth, self.orders.document(auth, doc_id, "RECEIPT"))
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "RECEIPT", lock=True)
            self.may_post(auth, doc)
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
                        "EXECUTION_MISMATCH", "Execution key đã ghi sổ với người/nội dung khác."
                    )
                return CommandResult(executed["response"])
            require_version(doc["version"], payload.expected_version)
            self.validate_saved(auth, doc)
            self.approved(c, doc)
            source = self.source(auth, doc)
            # Warehouse lock coordinates period provisioning; closing uses the same period row lock.
            active_reference(c, "warehouse", doc["warehouse_id"], "warehouse_id")
            periods = (
                c.execute(
                    text("""SELECT * FROM wms.stock_period WHERE warehouse_id=:wh
                AND :day BETWEEN starts_on AND ends_on ORDER BY id FOR UPDATE"""),
                    {"wh": doc["warehouse_id"], "day": doc["business_date"]},
                )
                .mappings()
                .all()
            )
            if len(periods) != 1 or periods[0]["status"] != "OPEN":
                raise DomainError("PERIOD_CLOSED", "Ngày ghi sổ phải thuộc đúng một kỳ kho đang mở.")
            saved = {r["id"]: r for r in self.orders.lines(c, doc)}
            parents = {r["id"]: r for r in self.orders.lines(c, source)}
            specs, totals = {}, defaultdict(Decimal)
            for item in payload.lines:
                line = saved.get(item.document_line_id)
                if not line:
                    invalid("document_line_id", "Dòng ghi sổ không thuộc phiếu nhận.")
                raw = doc["attributes"]["receipt_plan"]["lines"].get(str(item.document_line_id))
                from packages.contracts.receipts import ReceiptLineInput

                spec = ReceiptLineInput.model_validate(raw)
                qty = Decimal(item.quantity_base)
                parent = parents.get(line["source_line_id"])
                if (
                    not parent
                    or spec.source_line_id != parent["id"]
                    or line["product_id"] != parent["product_id"]
                    or line["owner_id"] != COMPANY_OWNER
                    or line["consignment_id"]
                ):
                    raise DomainError("SOURCE_MISMATCH", "Dòng nhận không khớp PO/ownership.")
                if qty > Decimal(line["remaining_base"]):
                    raise DomainError("RECEIPT_EXCEEDED", "Lượng ghi sổ vượt phần còn lại của dòng nhận.")
                totals[parent["id"]] += qty
                if totals[parent["id"]] > Decimal(parent["remaining_base"]):
                    raise DomainError("SOURCE_EXCEEDED", "PO không còn đủ lượng để nhận.")
                specs[item.document_line_id] = (spec, qty)
            locations = {}
            for location_id in sorted(
                {EXTERNAL} | {spec.destination_location_id for spec, _ in specs.values()}
            ):
                lock = "SHARE" if location_id == EXTERNAL else "UPDATE"
                location = one(c, f"SELECT * FROM wms.location WHERE id=:id FOR {lock}", id=location_id)
                if not location or not location["is_active"]:
                    invalid("destination_location_id", "Vị trí đã ngừng hoạt động.")
                if location_id == EXTERNAL:
                    if location["kind"] != "EXTERNAL" or location["warehouse_id"] is not None:
                        raise DomainError("SOURCE_MISMATCH", "Đối ứng nhận hàng không hợp lệ.")
                elif location["warehouse_id"] != doc["warehouse_id"] or location["kind"] not in {
                    "RECEIVING",
                    "QUARANTINE",
                }:
                    invalid("destination_location_id", "Vị trí nhận phải thuộc kho và loại nhận/cách ly.")
                if one(
                    c,
                    "SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL",
                    id=location_id,
                ):
                    raise DomainError("LOCATION_FROZEN", "Vị trí đang khóa kiểm kê.")
                locations[location_id] = location
            for product in sorted({saved[line_id]["product_id"] for line_id in specs}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product})
            moves = []
            today = self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
            for line_id, (spec, qty) in specs.items():
                line = saved[line_id]
                product = active_reference(c, "product", line["product_id"], "product_id")
                unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
                if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                    invalid("quantity_base", "Lượng ghi sổ không đúng độ chính xác đơn vị cơ sở.")
                self.validate_tracking(product, spec, qty)
                lot_id = serial_id = None
                if spec.lot_code:
                    lot = one(
                        c,
                        "SELECT * FROM wms.lot WHERE product_id=:product AND code=:code FOR UPDATE",
                        product=product["id"],
                        code=spec.lot_code,
                    )
                    if lot and (lot["manufactured_on"], lot["expires_on"]) != (
                        spec.manufactured_on,
                        spec.expires_on,
                    ):
                        raise DomainError("LOT_METADATA_CONFLICT", "Ngày của lô khác dữ liệu đã lưu.")
                    lot_id = lot["id"] if lot else uuid4()
                    if not lot:
                        c.execute(
                            text(
                                "INSERT INTO wms.lot(id,product_id,code,manufactured_on,expires_on,version) VALUES (:id,:product,:code,:made,:expiry,1)"
                            ),
                            {
                                "id": lot_id,
                                "product": product["id"],
                                "code": spec.lot_code,
                                "made": spec.manufactured_on,
                                "expiry": spec.expires_on,
                            },
                        )
                    if (
                        spec.expires_on
                        and spec.expires_on < today
                        and locations[spec.destination_location_id]["kind"] != "QUARANTINE"
                    ):
                        raise DomainError("LOT_EXPIRED", "Lô hết hạn chỉ được nhận vào khu cách ly.")
                if spec.serial_code:
                    serial = one(
                        c,
                        "SELECT * FROM wms.serial WHERE product_id=:product AND code=:code FOR UPDATE",
                        product=product["id"],
                        code=spec.serial_code,
                    )
                    serial_id = serial["id"] if serial else uuid4()
                    if serial and (
                        one(c, "SELECT id FROM wms.serial_position WHERE serial_id=:id", id=serial_id)
                        or one(
                            c,
                            "SELECT b.id FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id AND b.on_hand>0",
                            id=serial_id,
                        )
                    ):
                        raise DomainError(
                            "SERIAL_ALREADY_PRESENT",
                            "Serial đã có vị trí/tồn; cần xử lý nghiệp vụ trả/đảo trước.",
                        )
                    if not serial:
                        c.execute(
                            text("INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:product,:code)"),
                            {"id": serial_id, "product": product["id"], "code": spec.serial_code},
                        )
                stock = resolve_stock_identity(
                    c,
                    product_id=product["id"],
                    owner_id=COMPANY_OWNER,
                    warehouse_id=doc["warehouse_id"],
                    business_date=doc["business_date"],
                    lot_id=lot_id,
                    serial_id=serial_id,
                )
                moves.append(
                    dict(
                        id=uuid4(),
                        line=line_id,
                        stock=stock,
                        destination=spec.destination_location_id,
                        quantity=qty,
                        unit=product["base_uom_id"],
                        serial=serial_id,
                    )
                )
            for location_id, stock_id in sorted({(m["destination"], m["stock"]) for m in moves}):
                c.execute(
                    text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                    VALUES (:id,:stock,:location,0,0,1) ON CONFLICT (stock_item_id,location_id) DO NOTHING"""),
                    {"id": uuid4(), "stock": stock_id, "location": location_id},
                )
                c.execute(
                    text(
                        "SELECT id FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:location FOR UPDATE"
                    ),
                    {"stock": stock_id, "location": location_id},
                )
            doc["status"] = (
                "COMPLETED"
                if all(
                    Decimal(r["remaining_base"]) == specs.get(r["id"], (None, Decimal(0)))[1]
                    for r in saved.values()
                )
                else "PARTIAL"
            )
            source["status"] = (
                "COMPLETED"
                if all(Decimal(r["remaining_base"]) == totals[r["id"]] for r in parents.values())
                else "PARTIAL"
            )
            doc["version"] += 1
            source["version"] += 1
            tx_id = uuid4()
            result = ReceiptPostResult(
                **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                request_id=request_id,
                transaction_id=tx_id,
                source_order_id=source["id"],
                source_order_version=source["version"],
                source_order_status=source["status"],
            ).model_dump(mode="json")
            c.execute(
                text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,
                posted_at,posted_by,request_hash,response) VALUES (:id,:doc,:key,'RECEIVE',:day,:now,:actor,:hash,CAST(:response AS jsonb))"""),
                {
                    "id": tx_id,
                    "doc": doc_id,
                    "key": payload.execution_key,
                    "day": doc["business_date"],
                    "now": self.identity.clock(),
                    "actor": actor,
                    "hash": digest,
                    "response": encode(result),
                },
            )
            for move in moves:
                c.execute(
                    text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,
                    destination_location_id,quantity_base,base_uom_id) VALUES (:id,:tx,:line,:stock,:source,:destination,:quantity,:unit)"""),
                    {**move, "tx": tx_id, "source": EXTERNAL},
                )
                c.execute(
                    text("""UPDATE wms.stock_balance SET on_hand=on_hand+:quantity,version=version+1
                    WHERE stock_item_id=:stock AND location_id=:destination"""),
                    move,
                )
                if move["serial"]:
                    c.execute(
                        text(
                            "INSERT INTO wms.serial_position(id,serial_id,location_id,last_move_id) VALUES (:id,:serial,:location,:move)"
                        ),
                        {
                            "id": uuid4(),
                            "serial": move["serial"],
                            "location": move["destination"],
                            "move": move["id"],
                        },
                    )
            for changed in [source, doc]:
                c.execute(
                    text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), changed
                )
            self.orders.effects(c, actor, doc, "receipt.post", result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command="receipt.post",
            resource_id=doc_id,
            payload=payload.model_dump(mode="json"),
            authorize=authorize,
            handle=handle,
        )

    def operation(self, auth, key):
        record = one(
            auth.connection,
            "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
            actor=auth.principal.user_id,
            key=key,
        )
        if not record or record["command"] != "receipt.post":
            raise DomainError("NOT_FOUND", "Chưa tìm thấy kết quả ghi sổ; chỉ gửi lại cùng key và nội dung.")
        result = record["response"]
        doc = self.orders.document(auth, UUID(result["id"]), "RECEIPT")
        self.may_post(auth, doc)
        return OperationView(
            **{k: result[k] for k in ["id", "status", "version", "request_id", "transaction_id"]}
        )
