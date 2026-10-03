"""Company opening stock, posted in full once before warehouse activity.

Lock document -> warehouse (exclusive for post) -> period -> locations -> products
-> identities -> balances. Warehouse lock conflicts with receiving's shared lock,
so the initial-stock check cannot race a receipt in another period/location.
"""

from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import text

from apps.server.application.commands import CommandResult, payload_hash
from apps.server.application.master_data import active_reference, invalid, one
from apps.server.application.orders import encode
from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.openings import OpeningLineInput, OpeningPlan, OpeningPostResult, OpeningView
from packages.contracts.orders import OrderResult
from packages.contracts.receipts import OperationView
from packages.contracts.traceability import COMPANY_OWNER

OPENING = UUID("00000000-0000-4000-8000-000000000202")
PHYSICAL = {"STORAGE", "RECEIVING", "QUARANTINE", "SHIPPING"}


class OpeningService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus
        orders.openings = self

    def metadata(self, connection, doc):
        meta = one(connection, "SELECT * FROM wms.opening_document WHERE document_id=:id", id=doc["id"])
        if not meta or meta["warehouse_id"] != doc["warehouse_id"]:
            raise DomainError("UNSUPPORTED_OPENING", "Phiếu cũ chưa có dữ liệu cutover đã xác minh.")
        return meta

    def snapshot(self, connection, doc):
        return {
            "metadata": self.metadata(connection, doc),
            "plan": [
                dict(r)
                for r in connection.execute(
                    text("""SELECT p.* FROM wms.opening_line p
                JOIN wms.document_line l ON l.id=p.document_line_id
                WHERE l.document_id=:id ORDER BY l.line_no"""),
                    {"id": doc["id"]},
                ).mappings()
            ],
        }

    def cutover(self, c, warehouse_id):
        # History, including reversed/zero-net moves, closes the cutover window permanently.
        if (
            one(
                c,
                """SELECT t.id FROM wms.inventory_transaction t JOIN wms.document d ON d.id=t.document_id
                WHERE d.warehouse_id=:wh OR d.destination_warehouse_id=:wh LIMIT 1""",
                wh=warehouse_id,
            )
            or one(
                c,
                """SELECT m.id FROM wms.stock_move m JOIN wms.location l
                ON l.id=m.source_location_id OR l.id=m.destination_location_id WHERE l.warehouse_id=:wh LIMIT 1""",
                wh=warehouse_id,
            )
            or one(
                c,
                """SELECT b.id FROM wms.stock_balance b JOIN wms.location l ON l.id=b.location_id
                WHERE l.warehouse_id=:wh AND (b.on_hand<>0 OR b.reserved<>0) LIMIT 1""",
                wh=warehouse_id,
            )
        ):
            raise DomainError("OPENING_CLOSED", "Kho đã có lịch sử/tồn; không được nạp thêm tồn đầu kỳ.")

    def validate_specs(self, c, warehouse, specs, *, lock_products=True):
        active_reference(c, "stock_owner", COMPANY_OWNER, "owner_id")
        for location_id in sorted({s.destination_location_id for s in specs}):
            location = active_reference(c, "location", location_id, "destination_location_id")
            if location["warehouse_id"] != warehouse or location["kind"] not in PHYSICAL:
                invalid("destination_location_id", "Chọn vị trí vật lý trong đúng kho.")
        if lock_products:
            for product_id in sorted({s.product_id for s in specs}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR SHARE"), {"id": product_id})
        serials = set()
        products = {}
        for spec in specs:
            if spec.owner_id != COMPANY_OWNER:
                invalid("owner_id", "Tồn đầu kỳ đợt này chỉ hỗ trợ hàng doanh nghiệp.")
            product = active_reference(c, "product", spec.product_id, "product_id")
            unit = active_reference(c, "uom", product["base_uom_id"], "uom_id")
            qty = Decimal(spec.quantity_base)
            if qty != qty.quantize(Decimal(1).scaleb(-unit["decimal_places"])):
                invalid("quantity_base", "Lượng tồn đầu kỳ không đúng độ chính xác đơn vị cơ sở.")
            self.orders.receipts.validate_tracking(product, spec, qty)
            serial_key = (spec.product_id, spec.serial_code)
            if spec.serial_code and serial_key in serials:
                invalid("serial_code", "Serial lặp trong phiếu tồn đầu kỳ.", "DUPLICATE_SERIAL")
            serials.add(serial_key)
            products[spec.product_id] = product
        return products

    def saved_specs(self, c, doc):
        self.metadata(c, doc)
        if (
            doc["partner_id"]
            or doc["destination_warehouse_id"]
            or doc["transit_location_id"]
            or doc["attributes"]
        ):
            raise DomainError("UNSUPPORTED_OPENING", "Phiếu có nguồn/thuộc tính ngoài phạm vi tồn đầu kỳ.")
        rows = list(
            c.execute(
                text("""SELECT l.*,p.document_line_id,p.destination_location_id,
            p.lot_code,p.serial_code,p.manufactured_on,p.expires_on FROM wms.document_line l
            LEFT JOIN wms.opening_line p ON p.document_line_id=l.id WHERE l.document_id=:id ORDER BY l.line_no"""),
                {"id": doc["id"]},
            ).mappings()
        )
        if not rows:
            raise DomainError("EMPTY_DOCUMENT", "Cần ít nhất một dòng tồn đầu kỳ.")
        specs = {}
        for row in rows:
            if (
                not row["document_line_id"]
                or row["source_line_id"]
                or row["consignment_id"]
                or row["reference_unit_price"] is not None
                or row["factor_snapshot"] != 1
                or row["quantity"] != row["base_quantity"]
                or row["closed_base_quantity"] != 0
            ):
                raise DomainError("OPENING_MISMATCH", "Dòng tồn đầu kỳ không khớp kế hoạch/đơn vị cơ sở.")
            try:
                spec = OpeningLineInput.model_validate(
                    {
                        **{k: row[k] for k in OpeningLineInput.model_fields if k != "quantity_base"},
                        "quantity_base": format(row["base_quantity"], "f"),
                    }
                )
            except ValidationError:
                raise DomainError("OPENING_MISMATCH", "Kế hoạch tồn đầu kỳ không hợp lệ.") from None
            specs[row["id"]] = spec
        return rows, specs

    def validate_saved(self, auth, doc):
        c = auth.connection
        self.orders.validate_header(c, "OPENING", doc["warehouse_id"], doc["partner_id"])
        self.cutover(c, doc["warehouse_id"])
        rows, specs = self.saved_specs(c, doc)
        products = self.validate_specs(c, doc["warehouse_id"], list(specs.values()))
        if any(row["uom_id"] != products[row["product_id"]]["base_uom_id"] for row in rows):
            raise DomainError("OPENING_MISMATCH", "Đơn vị cơ sở đã đổi; cần sửa/gửi lại.")
        return rows, specs

    def approved(self, c, doc):
        if doc["status"] != "APPROVED":
            raise DomainError("INVALID_STATE", "Tồn đầu kỳ phải được duyệt đầy đủ trước khi ghi sổ.")
        req = one(
            c,
            """SELECT * FROM wms.approval_request WHERE document_id=:id AND status='APPROVED'
            ORDER BY document_version DESC LIMIT 1""",
            id=doc["id"],
        )
        if not req or req["content_snapshot"] != self.orders.snapshot(c, doc):
            raise DomainError("STALE_APPROVAL", "Thiếu bản duyệt đúng nội dung hiện tại.")
        steps = list(
            c.execute(
                text("SELECT * FROM wms.approval_step WHERE request_id=:id ORDER BY step_no"),
                {"id": req["id"]},
            ).mappings()
        )
        if (
            not steps
            or any(s["status"] != "APPROVED" for s in steps)
            or doc["version"] != req["document_version"] + len(steps)
        ):
            raise DomainError("STALE_APPROVAL", "Version hoặc các bước duyệt không khớp.")

    def may_post(self, auth, doc):
        auth.require("opening.post", doc["warehouse_id"])

    def read(self, auth, doc_id):
        view = self.orders.read(auth, doc_id, "OPENING")
        doc = self.orders.document(auth, doc_id, "OPENING")
        meta = self.metadata(auth.connection, doc)
        # Read also works after cancellation (closed quantities) and completed posting.
        plan = []
        for line in view.lines:
            row = one(
                auth.connection,
                """SELECT p.*,l.code AS location_code FROM wms.opening_line p
                JOIN wms.location l ON l.id=p.destination_location_id WHERE p.document_line_id=:id""",
                id=line.id,
            )
            if not row:
                raise DomainError("OPENING_MISMATCH", "Thiếu kế hoạch tồn đầu kỳ.")
            plan.append(
                OpeningPlan(
                    **row,
                    product_id=line.product_id,
                    owner_id=line.owner_id,
                    quantity_base=line.base_quantity,
                    tracking=line.tracking,
                )
            )
        actions = list(view.allowed_actions)
        if doc["status"] == "APPROVED" and auth.allows("opening.post", doc["warehouse_id"]):
            actions.append("post")
        return OpeningView(
            **{**view.model_dump(), "allowed_actions": actions},
            batch_key=meta["batch_key"],
            signed_count_reference=meta["signed_count_reference"],
            plan=plan,
        )

    def write(self, access, key, payload, request_id, doc_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            auth.require("document.read", payload.warehouse_id, hidden=True)
            auth.require("opening.draft", payload.warehouse_id)
            if doc_id:
                self.orders.may_edit(auth, self.orders.document(auth, doc_id, "OPENING"))
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            if doc_id:
                doc = self.orders.document(auth, doc_id, "OPENING", lock=True)
                self.orders.may_edit(auth, doc)
                require_version(doc["version"], payload.expected_version)
                if doc["status"] not in {"DRAFT", "REJECTED"}:
                    raise DomainError("INVALID_STATE", "Chỉ sửa nháp hoặc phiếu từ chối.")
                meta = self.metadata(c, doc)
                if payload.warehouse_id != doc["warehouse_id"] or payload.batch_key != meta["batch_key"]:
                    invalid("batch_key", "Không đổi kho hoặc mã đợt của phiếu đã tạo.")
                self.orders.no_dependencies(c, doc_id, edit=True)
                self.saved_specs(c, doc)  # Refuse to silently discard unsupported legacy content.
            self.orders.validate_header(c, "OPENING", payload.warehouse_id, None)
            self.cutover(c, payload.warehouse_id)
            products = self.validate_specs(c, payload.warehouse_id, payload.lines)
            if doc_id:
                self.orders.invalidate(c, doc_id)
                c.execute(text("DELETE FROM wms.document_line WHERE document_id=:id"), {"id": doc_id})
                doc["version"] += 1
                c.execute(
                    text("""UPDATE wms.document SET status='DRAFT',version=:version,business_date=:day,
                    reason=:reason WHERE id=:id"""),
                    {**doc, "day": payload.business_date, "reason": payload.reason},
                )
                c.execute(
                    text("UPDATE wms.opening_document SET signed_count_reference=:ref WHERE document_id=:id"),
                    {"id": doc_id, "ref": payload.signed_count_reference},
                )
            else:
                if one(
                    c,
                    "SELECT document_id FROM wms.opening_document WHERE warehouse_id=:wh AND batch_key=:batch",
                    wh=payload.warehouse_id,
                    batch=payload.batch_key,
                ):
                    raise DomainError("DUPLICATE_BATCH", "Mã đợt đã có phiếu trong kho; đọc/sửa phiếu cũ.")
                sequence = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
                doc = dict(
                    id=uuid4(),
                    number=f"OPN-{payload.business_date:%Y%m%d}-{sequence:08d}",
                    kind="OPENING",
                    warehouse_id=payload.warehouse_id,
                    version=1,
                )
                c.execute(
                    text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,
                    created_by,created_at,version,attributes,reason)
                    VALUES (:id,:number,'OPENING','DRAFT',:warehouse_id,:day,:actor,:now,1,'{}',:reason)"""),
                    {
                        **doc,
                        "day": payload.business_date,
                        "actor": actor,
                        "now": self.identity.clock(),
                        "reason": payload.reason,
                    },
                )
                c.execute(
                    text("""INSERT INTO wms.opening_document(document_id,warehouse_id,batch_key,signed_count_reference)
                    VALUES (:id,:warehouse_id,:batch,:ref)"""),
                    {**doc, "batch": payload.batch_key, "ref": payload.signed_count_reference},
                )
            doc["status"] = "DRAFT"
            for index, spec in enumerate(payload.lines, 1):
                line_id = uuid4()
                c.execute(
                    text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,
                    factor_snapshot,base_quantity,owner_id)
                    VALUES (:id,:doc,:n,:product,:uom,:qty,1,:qty,:owner)"""),
                    {
                        "id": line_id,
                        "doc": doc["id"],
                        "n": index,
                        "product": spec.product_id,
                        "uom": products[spec.product_id]["base_uom_id"],
                        "qty": Decimal(spec.quantity_base),
                        "owner": spec.owner_id,
                    },
                )
                c.execute(
                    text("""INSERT INTO wms.opening_line(document_line_id,destination_location_id,
                    lot_code,serial_code,manufactured_on,expires_on)
                    VALUES (:id,:destination_location_id,:lot_code,:serial_code,:manufactured_on,:expires_on)"""),
                    {"id": line_id, **spec.model_dump()},
                )
            result = OrderResult(
                **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                request_id=request_id,
            ).model_dump(mode="json")
            self.orders.effects(
                c, actor, doc, "update" if doc_id else "create", result, payload.reason, request_id
            )
            return CommandResult(result, 200 if doc_id else 201)

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command="opening.update" if doc_id else "opening.create",
            resource_id=doc_id or UUID(int=0),
            payload=payload.model_dump(mode="json"),
            authorize=authorize,
            handle=handle,
        )

    def incoming_identity(self, c, doc, spec, today, destination):
        lot_id = serial_id = None
        if spec.lot_code:
            lot = one(
                c,
                "SELECT * FROM wms.lot WHERE product_id=:product AND code=:code FOR UPDATE",
                product=spec.product_id,
                code=spec.lot_code,
            )
            if lot and (lot["manufactured_on"], lot["expires_on"]) != (spec.manufactured_on, spec.expires_on):
                raise DomainError("LOT_METADATA_CONFLICT", "Ngày của lô khác dữ liệu đã lưu.")
            lot_id = lot["id"] if lot else uuid4()
            if not lot:
                c.execute(
                    text("""INSERT INTO wms.lot(id,product_id,code,manufactured_on,expires_on,version)
                    VALUES (:id,:product,:code,:made,:expiry,1)"""),
                    {
                        "id": lot_id,
                        "product": spec.product_id,
                        "code": spec.lot_code,
                        "made": spec.manufactured_on,
                        "expiry": spec.expires_on,
                    },
                )
            if spec.expires_on and spec.expires_on < today and destination["kind"] != "QUARANTINE":
                raise DomainError("LOT_EXPIRED", "Lô hết hạn chỉ được nạp vào khu cách ly.")
        if spec.serial_code:
            serial = one(
                c,
                "SELECT * FROM wms.serial WHERE product_id=:product AND code=:code FOR UPDATE",
                product=spec.product_id,
                code=spec.serial_code,
            )
            serial_id = serial["id"] if serial else uuid4()
            if serial and (
                one(c, "SELECT id FROM wms.serial_position WHERE serial_id=:id", id=serial_id)
                or one(
                    c,
                    """SELECT b.id FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
                    WHERE i.serial_id=:id AND b.on_hand>0""",
                    id=serial_id,
                )
            ):
                raise DomainError("SERIAL_ALREADY_PRESENT", "Serial đã có vị trí/tồn ở kho khác.")
            if not serial:
                c.execute(
                    text("INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:product,:code)"),
                    {"id": serial_id, "product": spec.product_id, "code": spec.serial_code},
                )
        stock = resolve_stock_identity(
            c,
            product_id=spec.product_id,
            owner_id=spec.owner_id,
            warehouse_id=doc["warehouse_id"],
            business_date=doc["business_date"],
            lot_id=lot_id,
            serial_id=serial_id,
        )
        return stock, serial_id

    def post(self, access, key, doc_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}
        digest = payload_hash("opening.post", doc_id, payload.model_dump(mode="json"))

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            self.may_post(auth, self.orders.document(auth, doc_id, "OPENING"))
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "OPENING", lock=True)
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
            self.approved(c, doc)
            c.execute(
                text("SELECT id FROM wms.warehouse WHERE id=:id FOR UPDATE"), {"id": doc["warehouse_id"]}
            )
            active_reference(c, "warehouse", doc["warehouse_id"], "warehouse_id")
            self.cutover(c, doc["warehouse_id"])
            periods = list(
                c.execute(
                    text("""SELECT * FROM wms.stock_period WHERE warehouse_id=:wh
                AND :day BETWEEN starts_on AND ends_on ORDER BY id FOR UPDATE"""),
                    {"wh": doc["warehouse_id"], "day": doc["business_date"]},
                ).mappings()
            )
            if len(periods) != 1 or periods[0]["status"] != "OPEN":
                raise DomainError("PERIOD_CLOSED", "Ngày ghi sổ phải thuộc đúng một kỳ kho đang mở.")
            rows, specs = self.saved_specs(c, doc)
            locations = {}
            for location_id in sorted({OPENING} | {s.destination_location_id for s in specs.values()}):
                lock = "SHARE" if location_id == OPENING else "UPDATE"
                location = one(c, f"SELECT * FROM wms.location WHERE id=:id FOR {lock}", id=location_id)
                if not location or not location["is_active"]:
                    invalid("destination_location_id", "Vị trí không còn hoạt động.")
                if location_id == OPENING and (
                    location["kind"] != "OPENING" or location["warehouse_id"] is not None
                ):
                    raise DomainError("SOURCE_MISMATCH", "Đối ứng tồn đầu kỳ không hợp lệ.")
                if one(
                    c,
                    "SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL",
                    id=location_id,
                ):
                    raise DomainError("LOCATION_FROZEN", "Vị trí đang khóa kiểm kê.")
                locations[location_id] = location
            for product_id in sorted({s.product_id for s in specs.values()}):
                c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product_id})
            products = self.validate_specs(c, doc["warehouse_id"], list(specs.values()), lock_products=False)
            if any(row["uom_id"] != products[row["product_id"]]["base_uom_id"] for row in rows):
                raise DomainError("OPENING_MISMATCH", "Đơn vị cơ sở không khớp bản duyệt.")
            today = (
                self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
            )
            moves = []
            for line_id, spec in specs.items():
                stock, serial = self.incoming_identity(
                    c, doc, spec, today, locations[spec.destination_location_id]
                )
                moves.append(
                    dict(
                        id=uuid4(),
                        line=line_id,
                        stock=stock,
                        serial=serial,
                        destination=spec.destination_location_id,
                        quantity=Decimal(spec.quantity_base),
                        unit=products[spec.product_id]["base_uom_id"],
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
            tx_id = uuid4()
            doc.update(status="COMPLETED", version=doc["version"] + 1)
            result = OpeningPostResult(
                **{k: doc[k] for k in ["id", "number", "kind", "warehouse_id", "status", "version"]},
                request_id=request_id,
                transaction_id=tx_id,
            ).model_dump(mode="json")
            c.execute(
                text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,
                posted_at,posted_by,request_hash,response) VALUES (:id,:doc,:key,'OPEN',:day,:now,:actor,:hash,CAST(:response AS jsonb))"""),
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
                    {**move, "tx": tx_id, "source": OPENING},
                )
                c.execute(
                    text("""UPDATE wms.stock_balance SET on_hand=on_hand+:quantity,version=version+1
                    WHERE stock_item_id=:stock AND location_id=:destination"""),
                    move,
                )
                if move["serial"]:
                    c.execute(
                        text("""INSERT INTO wms.serial_position(id,serial_id,location_id,last_move_id)
                        VALUES (:position,:serial,:destination,:id)"""),
                        {**move, "position": uuid4()},
                    )
            c.execute(text("UPDATE wms.document SET status=:status,version=:version WHERE id=:id"), doc)
            self.orders.effects(c, actor, doc, "post", result, payload.reason, request_id)
            return CommandResult(result)

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command="opening.post",
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
        if not record or record["command"] != "opening.post":
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK; chỉ gửi lại cùng key và nội dung.")
        result = record["response"]
        self.may_post(auth, self.orders.document(auth, UUID(result["id"]), "OPENING"))
        return OperationView(
            **{k: result[k] for k in ["id", "status", "version", "request_id", "transaction_id"]}
        )
