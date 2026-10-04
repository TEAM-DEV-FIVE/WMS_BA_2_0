"""Count policy v1: two agreeing independent rounds, controller then director.

Session -> adjustment document -> warehouse -> period -> locations -> products ->
identities -> balances -> reservations. Every command owns one CommandBus UoW.
"""
import hashlib
import json
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandResult
from apps.server.application.master_data import active_reference, one
from apps.server.application.move_safety import check_reservations, location_tree, lock_open_period
from apps.server.application.orders import amount, encode
from apps.server.application.stock_identity import resolve_stock_identity
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.counting import CountResult

LOSS = UUID("00000000-0000-4130-8000-000000000020")
PERMISSIONS = {"create": "count.create", "freeze": "count.create", "cancel": "count.create",
               "observe": "count.enter", "extra": "count.enter", "confirm-empty": "count.enter", "submit": "count.submit",
               "decide": "count.approve", "post": "adjustment.post"}
LINE_SQL = """SELECT l.*,p.sku,p.tracking,p.base_uom_id,u.decimal_places,i.product_id,i.owner_id,
    i.consignment_id,i.lot_id,i.serial_id,o.code AS owner_code,lot.code AS lot_code,
    s.code AS serial_code,loc.code AS location_code FROM wms.count_line l
    JOIN wms.stock_item i ON i.id=l.stock_item_id JOIN wms.product p ON p.id=i.product_id
    JOIN wms.uom u ON u.id=p.base_uom_id JOIN wms.stock_owner o ON o.id=i.owner_id
    JOIN wms.location loc ON loc.id=l.location_id LEFT JOIN wms.lot lot ON lot.id=i.lot_id
    LEFT JOIN wms.serial s ON s.id=i.serial_id WHERE l.session_id=:id ORDER BY l.id"""


def effects(c, identity, actor, row, action, result, reason, request_id, entity="count_session"):
    params = dict(actor=actor, warehouse=row["warehouse_id"], action=action, entity=entity,
                  target=row["id"], request=request_id, now=identity.clock(), data=encode(result), reason=reason)
    c.execute(text("""INSERT INTO wms.audit_event(id,actor_id,warehouse_id,action,entity_type,entity_id,
        request_id,occurred_at,after_data,reason) VALUES (:id,:actor,:warehouse,:action,:entity,:target,
        :request,:now,CAST(:data AS jsonb),:reason)"""), {**params, "id": uuid4()})
    c.execute(text("""INSERT INTO wms.outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
        VALUES (:id,:event,:target,CAST(:data AS jsonb),:now,:now,0)"""),
              {**params, "id": uuid4(), "event": action + ".v1"})


def require_state(row, *states):
    if row["status"] not in states:
        raise DomainError("INVALID_STATE", "Trạng thái không cho phép thao tác này.")


class CountingService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus

    @staticmethod
    def assigned(auth, row, location=None):
        return bool(one(auth.connection, """SELECT id FROM wms.count_assignment WHERE session_id=:id
            AND user_id=:actor AND (CAST(:loc AS uuid) IS NULL OR location_id=:loc) LIMIT 1""",
            id=row["id"], actor=auth.principal.user_id, loc=location))

    def visible(self, auth, row):
        warehouse = row["warehouse_id"]
        return (any(auth.allows(p, warehouse) for p in ("count.create", "count.snapshot.read", "count.approve"))
                or (auth.allows("count.enter", warehouse) and self.assigned(auth, row)))

    def session(self, auth, session_id, *, lock=False):
        row = one(auth.connection, "SELECT * FROM wms.count_session WHERE id=:id", id=session_id)
        if not row or not self.visible(auth, row):
            raise DomainError("NOT_FOUND", "Không tìm thấy phiên kiểm kê.")
        if lock:
            row = one(auth.connection, "SELECT * FROM wms.count_session WHERE id=:id FOR UPDATE", id=session_id)
            if row["adjustment_document_id"]:
                auth.connection.execute(text("SELECT id FROM wms.document WHERE id=:id FOR UPDATE"),
                                        {"id": row["adjustment_document_id"]})
        return row

    def can_review(self, auth, row):
        # Assignment permanently marks a blind counter for this session, even if
        # the user also has manager/controller permissions or changes roles later.
        return auth.allows("count.snapshot.read", row["warehouse_id"]) and not self.assigned(auth, row)

    @staticmethod
    def scope(c, session_id):
        return c.execute(text("SELECT location_id FROM wms.count_scope WHERE session_id=:id ORDER BY location_id"),
                         {"id": session_id}).scalars().all()

    @staticmethod
    def lines(c, session_id):
        return [dict(r) for r in c.execute(text(LINE_SQL), {"id": session_id}).mappings()]

    @staticmethod
    def observations(c, line_id):
        return [dict(r) for r in c.execute(text("SELECT * FROM wms.count_observation WHERE count_line_id=:id ORDER BY round_no"),
                                          {"id": line_id}).mappings()]

    def snapshot(self, c, row):
        return json.loads(encode({"policy_revision": 1, "required_rounds": 2,
            "roles": ["CONTROLLER", "DIRECTOR"], "warehouse_id": row["warehouse_id"],
            "business_date": row["business_date"], "scope": self.scope(c, row["id"]),
            "empty_confirmations": [dict(r) for r in c.execute(text("SELECT * FROM wms.count_empty_confirmation WHERE session_id=:id ORDER BY id"), {"id": row["id"]}).mappings()],
            "lines": [{**line, "observations": self.observations(c, line["id"])}
                      for line in self.lines(c, row["id"])]}))

    @staticmethod
    def submission(c, row):
        return one(c, "SELECT * FROM wms.count_submission WHERE session_id=:id ORDER BY session_version DESC LIMIT 1",
                   id=row["id"])

    @staticmethod
    def decisions(c, submission):
        return [dict(r) for r in c.execute(text("SELECT * FROM wms.count_decision WHERE submission_id=:id ORDER BY step_no"),
                                          {"id": submission["id"]}).mappings()] if submission else []

    def may_decide(self, auth, row):
        auth.require("count.approve", row["warehouse_id"])
        require_state(row, "SUBMITTED")
        sub = self.submission(auth.connection, row)
        previous = self.decisions(auth.connection, sub)
        if not sub or len(previous) >= 2 or any(d["decision"] != "APPROVE" for d in previous):
            raise DomainError("INVALID_STATE", "Phiên đã được quyết định.")
        if auth.principal.user_id in {row["created_by"], sub["requested_by"], *(d["decided_by"] for d in previous)} or self.assigned(auth, row):
            raise DomainError("SELF_APPROVAL", "Người lập/gửi/đếm hoặc đã duyệt bước trước không được duyệt.")
        role = ["CONTROLLER", "DIRECTOR"][len(previous)]
        if not any(g["role_code"] == role for g in auth.grants("count.approve", row["warehouse_id"])):
            raise DomainError("FORBIDDEN", "Không đúng vai trò của bước duyệt hiện tại.")
        if sub["content_snapshot"] != self.snapshot(auth.connection, row):
            raise DomainError("STALE_APPROVAL", "Nội dung kiểm kê khác bản gửi duyệt.")
        return sub, len(previous) + 1

    def listing(self, auth, warehouse_id, after=None, limit=50):
        if not any(auth.allows(p, warehouse_id) for p in ("count.create", "count.snapshot.read", "count.approve", "count.enter")):
            raise DomainError("NOT_FOUND", "Không tìm thấy kho kiểm kê.")
        broad = any(auth.allows(p, warehouse_id) for p in ("count.create", "count.snapshot.read", "count.approve"))
        rows = auth.connection.execute(text("""SELECT id,warehouse_id,number,status,version,business_date
            FROM wms.count_session s WHERE warehouse_id=:warehouse AND (CAST(:after AS uuid) IS NULL OR id>:after)
            AND (:broad OR EXISTS(SELECT 1 FROM wms.count_assignment a WHERE a.session_id=s.id AND a.user_id=:actor))
            ORDER BY id LIMIT :limit"""), dict(warehouse=warehouse_id, after=after, broad=broad,
            actor=auth.principal.user_id, limit=limit + 1)).mappings().all()
        return {"items": rows[:limit], "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    def read(self, auth, session_id):
        row, c = self.session(auth, session_id), auth.connection
        review = self.can_review(auth, row)
        actions = []
        for action, states in [("freeze", {"DRAFT"}), ("cancel", {"DRAFT", "FROZEN", "COUNTED", "SUBMITTED"}),
                               ("submit", {"FROZEN", "COUNTED"}), ("post", {"SUBMITTED"})]:
            if row["status"] in states and auth.allows(PERMISSIONS[action], row["warehouse_id"]):
                if action != "post" or self.approved(c, row):
                    actions.append(action)
        if row["status"] in {"FROZEN", "COUNTED"} and auth.allows("count.enter", row["warehouse_id"]) and self.assigned(auth, row):
            actions += ["observe", "extra", "confirm-empty"]
        try:
            self.may_decide(auth, row)
            actions.append("decide")
        except DomainError:
            pass
        lines = []
        for line in self.lines(c, session_id):
            assigned = self.assigned(auth, row, line["location_id"])
            if not review and not assigned:
                continue
            obs = self.observations(c, line["id"])
            item = {k: line[k] for k in ("id", "stock_item_id", "location_id", "location_code", "sku", "tracking", "owner_code",
                                        "consignment_id", "lot_code", "serial_code")}
            item.update(next_round=len(obs) + 1, can_count="observe" in actions and assigned and
                        (not obs or obs[-1]["counted_by"] != auth.principal.user_id))
            if review:
                item.update(snapshot_quantity=amount(line["snapshot_quantity"]),
                            approved_quantity=amount(line["approved_quantity"]) if line["approved_quantity"] is not None else None,
                            delta=amount(line["approved_quantity"] - line["snapshot_quantity"]) if line["approved_quantity"] is not None else None,
                            observations=[{k: amount(o[k]) if k == "quantity" else o[k]
                                           for k in ("round_no", "quantity", "counted_by", "counted_at", "reason")} for o in obs])
            lines.append(item)
        scope = []
        for loc in self.scope(c, session_id):
            if review or self.assigned(auth, row, loc):
                users = c.execute(text("SELECT user_id FROM wms.count_assignment WHERE session_id=:id AND location_id=:loc ORDER BY user_id"),
                                  {"id": session_id, "loc": loc}).scalars().all()
                scope.append({"location_id": loc, "user_ids": users})
        result = {k: row[k] for k in ("id", "warehouse_id", "number", "status", "version", "business_date", "reason")}
        result.update(mode="REVIEW" if review else "BLIND", lines=lines, scope=scope, allowed_actions=actions)
        if review:
            result["decisions"] = json.loads(encode(self.decisions(c, self.submission(c, row))))
            result["empty_confirmations"] = json.loads(encode([dict(r) for r in c.execute(text(
                "SELECT * FROM wms.count_empty_confirmation WHERE session_id=:id ORDER BY location_id,counted_at,id"),
                {"id": session_id}).mappings()]))
        return result

    def catalog(self, auth, warehouse_id, resource, after=None, limit=50, q=""):
        if resource == "users":
            auth.require("count.create", warehouse_id)
            sql = """SELECT DISTINCT u.id,u.username AS code,u.display_name AS name FROM wms.app_user u
                JOIN wms.user_role_grant g ON g.user_id=u.id JOIN wms.role r ON r.id=g.role_id AND r.is_active
                JOIN wms.role_permission rp ON rp.role_id=r.id JOIN wms.permission p ON p.id=rp.permission_id
                WHERE u.is_active AND p.code='count.enter' AND g.revoked_at IS NULL AND g.valid_from<=:now
                AND (g.valid_until IS NULL OR g.valid_until>:now) AND
                (g.scope_kind='ALL_WAREHOUSES' OR (g.scope_kind='WAREHOUSE' AND g.warehouse_id=:warehouse))"""
        else:
            if not any(auth.allows(p, warehouse_id) for p in ("count.create", "count.enter", "count.snapshot.read")):
                raise DomainError("NOT_FOUND", "Không tìm thấy danh mục kiểm kê.")
            sql = {"locations": "SELECT id,code,name FROM wms.location WHERE is_active AND warehouse_id=:warehouse AND kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')",
                   "products": "SELECT id,sku AS code,name FROM wms.product WHERE is_active",
                   "owners": "SELECT id,code,name FROM wms.stock_owner WHERE is_active AND kind<>'UNCLASSIFIED'",
                   "agreements": "SELECT id,code,source_ref AS name FROM wms.consignment_agreement WHERE is_active AND warehouse_id=:warehouse"}[resource]
        rows = auth.connection.execute(text("SELECT * FROM (" + sql + """ ) c WHERE
            (CAST(:after AS uuid) IS NULL OR id>:after) AND (strpos(lower(code),lower(:q))>0 OR strpos(lower(name),lower(:q))>0)
            ORDER BY id LIMIT :limit"""), dict(warehouse=warehouse_id, now=auth.now, after=after, q=q, limit=limit + 1)).mappings().all()
        return {"items": rows[:limit], "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    def authorize(self, auth, action, row, payload=None):
        auth.require(PERMISSIONS[action], row["warehouse_id"])
        if action in {"observe", "extra", "confirm-empty"}:
            loc = payload.location_id if action != "observe" else None
            if action == "observe":
                line = one(auth.connection, "SELECT location_id FROM wms.count_line WHERE id=:id AND session_id=:session",
                           id=payload.line_id, session=row["id"])
                if not line:
                    raise DomainError("NOT_FOUND", "Không tìm thấy dòng đếm.")
                loc = line["location_id"]
            if not self.assigned(auth, row, loc):
                raise DomainError("FORBIDDEN", "Chỉ đếm vị trí được phân công.")

    def write(self, access, key, action, payload, request_id, session_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context = {}

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            row = self.session(auth, session_id) if session_id else {"warehouse_id": payload.warehouse_id}
            self.authorize(auth, action, row, payload)
            context["auth"] = auth

        def handle(uow):
            auth, c = context["auth"], uow.connection
            if action == "create":
                row = self.create(auth, payload)
            else:
                row = self.session(auth, session_id, lock=True)
                self.authorize(auth, action, row, payload)
                if action == "post":
                    saved = one(c, "SELECT * FROM wms.count_execution WHERE session_id=:id", id=session_id)
                    if saved:
                        if saved["execution_key"] != payload.execution_key or saved["request_hash"] != self.post_hash(payload):
                            raise DomainError("EXECUTION_MISMATCH", "Phiên đã ghi sổ với yêu cầu khác.")
                        return CommandResult(saved["response"])
                require_version(row["version"], payload.expected_version)
                getattr(self, action.replace("-", "_"))(auth, row, payload)
                row["version"] += 1
                c.execute(text("UPDATE wms.count_session SET status=:status,version=:version,adjustment_document_id=:doc WHERE id=:id"),
                          {**row, "doc": row["adjustment_document_id"]})
            result = CountResult(**{k: row[k] for k in ("id", "warehouse_id", "number", "status", "version")},
                adjustment_document_id=row.get("adjustment_document_id"), transaction_id=row.get("transaction_id"),
                execution_key=payload.execution_key if action == "post" else None, request_id=request_id).model_dump(mode="json")
            effects(c, self.identity, actor, row, "count." + action, result, payload.reason, request_id)
            if action == "post":
                c.execute(text("INSERT INTO wms.count_execution VALUES (:id,:key,:hash,CAST(:response AS jsonb))"),
                          dict(id=row["id"], key=payload.execution_key, hash=self.post_hash(payload), response=encode(result)))
            return CommandResult(result, 201 if action == "create" else 200)

        return self.bus.execute(actor_id=actor, key=key, command="count." + action,
            resource_id=session_id or payload.warehouse_id, payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def create(self, auth, payload):
        c, actor = auth.connection, auth.principal.user_id
        lock_open_period(c, payload.warehouse_id, payload.business_date)
        location_tree(c, payload.warehouse_id, [s.location_id for s in payload.scope], lock=True, allow_shipping=True)
        row = dict(id=uuid4(), warehouse_id=payload.warehouse_id, number="COUNT-" + str(uuid4()), status="DRAFT", version=1)
        c.execute(text("""INSERT INTO wms.count_session(id,warehouse_id,number,status,created_by,version,business_date,reason)
            VALUES (:id,:warehouse_id,:number,:status,:actor,1,:day,:reason)"""),
                  {**row, "actor": actor, "day": payload.business_date, "reason": payload.reason})
        for scope in payload.scope:
            c.execute(text("INSERT INTO wms.count_scope VALUES (:session,:loc)"), {"session": row["id"], "loc": scope.location_id})
            for user in sorted(scope.user_ids):
                active_reference(c, "app_user", user, "user_ids")
                other = Authorization(c, Principal(user, auth.principal.session_id, "", "", None), auth.now)
                other.require("count.enter", payload.warehouse_id)
                c.execute(text("""INSERT INTO wms.count_assignment(id,session_id,location_id,user_id,assigned_by)
                    VALUES (:id,:session,:location,:user,:actor)"""),
                          dict(id=uuid4(), session=row["id"], location=scope.location_id, user=user, actor=actor))
        return row

    def lock_scope(self, c, row, *, own=False):
        lock_open_period(c, row["warehouse_id"], row["business_date"])
        locations = self.scope(c, row["id"])
        location_tree(c, row["warehouse_id"], locations, lock=True, allow_shipping=True,
                      count_session_id=row["id"] if own else None)
        if own:
            actual = c.execute(text("SELECT location_id FROM wms.count_location_lock WHERE session_id=:id AND released_at IS NULL ORDER BY location_id"),
                               {"id": row["id"]}).scalars().all()
            if actual != locations:
                raise DomainError("FREEZE_LOST", "Khóa kiểm kê không còn đủ phạm vi.")
        return locations

    def freeze(self, auth, row, payload):
        require_state(row, "DRAFT")
        c = auth.connection
        locations = self.lock_scope(c, row)
        balances = c.execute(text("SELECT * FROM wms.stock_balance WHERE location_id=ANY(:ids) ORDER BY location_id,stock_item_id FOR UPDATE"),
                             {"ids": locations}).mappings().all()
        if len(balances) > 2000:
            raise DomainError("COUNT_SCOPE_LIMIT", "Chia phạm vi kiểm kê nhỏ hơn 2000 danh tính tồn.")
        for b in balances:
            check_reservations(c, b["stock_item_id"], b["location_id"], b["reserved"])
            if b["reserved"]:
                raise DomainError("RESERVATION_OPEN", "Giải phóng reservation trước khi khóa kiểm kê.")
            if b["on_hand"]:
                c.execute(text("INSERT INTO wms.count_line(id,session_id,stock_item_id,location_id,snapshot_quantity) VALUES (:id,:session,:stock,:loc,:qty)"),
                          dict(id=uuid4(), session=row["id"], stock=b["stock_item_id"], loc=b["location_id"], qty=b["on_hand"]))
        # Detect orphan reservations too, rather than assuming every cache row exists.
        if one(c, "SELECT id FROM wms.reservation WHERE location_id=ANY(:ids) AND quantity>consumed+released LIMIT 1", ids=locations):
            raise DomainError("RESERVATION_OPEN", "Vị trí còn reservation chưa giải phóng.")
        for loc in locations:
            c.execute(text("INSERT INTO wms.count_location_lock(id,session_id,location_id,locked_at) VALUES (:id,:session,:loc,:now)"),
                      dict(id=uuid4(), session=row["id"], loc=loc, now=self.identity.clock()))
        c.execute(text("UPDATE wms.count_session SET frozen_at=:now WHERE id=:id"), {"now": self.identity.clock(), "id": row["id"]})
        row["status"] = "FROZEN"

    def observe(self, auth, row, payload):
        require_state(row, "FROZEN", "COUNTED")
        c = auth.connection
        line = next(r for r in self.lines(c, row["id"]) if r["id"] == payload.line_id)
        obs = self.observations(c, line["id"])
        if payload.round_no != len(obs) + 1:
            raise DomainError("COUNT_ROUND_CONFLICT", "Vòng đếm phải liên tiếp và không được ghi đè.")
        if obs and obs[-1]["counted_by"] == auth.principal.user_id:
            raise DomainError("INDEPENDENT_COUNTER_REQUIRED", "Vòng kế tiếp cần người đếm khác.")
        qty = Decimal(payload.quantity)
        if qty != qty.quantize(Decimal(1).scaleb(-line["decimal_places"])) or (line["tracking"] == "SERIAL" and qty not in {0, 1}):
            raise DomainError("INVALID_QUANTITY", "Sai độ chính xác đơn vị; serial chỉ nhận 0 hoặc 1.")
        if one(c, "SELECT id FROM wms.count_observation WHERE scan_event_key=:key", key=payload.scan_event_key):
            raise DomainError("DUPLICATE_SCAN", "Sự kiện đếm đã được ghi nhận.")
        c.execute(text("""INSERT INTO wms.count_observation(id,count_line_id,round_no,quantity,counted_by,counted_at,scan_event_key,reason)
            VALUES (:id,:line,:round,:qty,:actor,:now,:key,:reason)"""),
                  dict(id=uuid4(), line=line["id"], round=payload.round_no, qty=qty, actor=auth.principal.user_id,
                       now=self.identity.clock(), key=payload.scan_event_key, reason=payload.reason))
        c.execute(text("UPDATE wms.count_line SET approved_quantity=NULL WHERE session_id=:id"), {"id": row["id"]})
        row["status"] = "COUNTED"

    def extra(self, auth, row, payload):
        require_state(row, "FROZEN", "COUNTED")
        c = auth.connection
        self.lock_scope(c, row, own=True)
        if len(self.lines(c, row["id"])) >= 2000:
            raise DomainError("COUNT_SCOPE_LIMIT", "Phiên đã đạt giới hạn 2000 dòng.")
        c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": payload.product_id})
        product = active_reference(c, "product", payload.product_id, "product_id")
        if product["expiry_required"] and not payload.expires_on:
            raise DomainError("TRACKING_MISMATCH", "SKU yêu cầu hạn dùng của lô đã xác minh.")
        if ((product["tracking"] == "NONE" and (payload.lot_code or payload.serial_code or payload.expires_on)) or
            (product["tracking"] == "LOT" and (not payload.lot_code or payload.serial_code)) or
            (product["tracking"] == "SERIAL" and (not payload.serial_code or payload.lot_code or payload.expires_on))):
            raise DomainError("TRACKING_MISMATCH", "Nhập danh tính đúng tracking SKU.")
        lot_id = serial_id = None
        if payload.lot_code:
            lot = one(c, "SELECT * FROM wms.lot WHERE product_id=:product AND code=:code FOR UPDATE", product=payload.product_id, code=payload.lot_code)
            if lot and lot["expires_on"] != payload.expires_on:
                raise DomainError("TRACKING_MISMATCH", "Hạn dùng khác lô đã xác minh.")
            lot_id = lot["id"] if lot else uuid4()
            if not lot:
                c.execute(text("INSERT INTO wms.lot(id,product_id,code,expires_on,version) VALUES (:id,:product,:code,:expires,1)"),
                          dict(id=lot_id, product=payload.product_id, code=payload.lot_code, expires=payload.expires_on))
        if payload.serial_code:
            serial = one(c, "SELECT id FROM wms.serial WHERE product_id=:product AND code=:code FOR UPDATE", product=payload.product_id, code=payload.serial_code)
            serial_id = serial["id"] if serial else uuid4()
            if not serial:
                c.execute(text("INSERT INTO wms.serial(id,product_id,code) VALUES (:id,:product,:code)"),
                          dict(id=serial_id, product=payload.product_id, code=payload.serial_code))
            if one(c, """SELECT id FROM wms.stock_item WHERE serial_id=:serial AND
                (owner_id<>:owner OR consignment_id IS DISTINCT FROM CAST(:agreement AS uuid)) LIMIT 1""",
                serial=serial_id, owner=payload.owner_id, agreement=payload.consignment_id):
                raise DomainError("OWNERSHIP_CONFLICT", "Kiểm kê không chuyển chủ sở hữu/hợp đồng của serial đã biết.")
        stock = resolve_stock_identity(c, product_id=payload.product_id, owner_id=payload.owner_id,
            consignment_id=payload.consignment_id, warehouse_id=row["warehouse_id"], business_date=row["business_date"], lot_id=lot_id, serial_id=serial_id)
        if one(c, "SELECT id FROM wms.count_line WHERE session_id=:session AND stock_item_id=:stock AND location_id=:loc",
               session=row["id"], stock=stock, loc=payload.location_id):
            raise DomainError("DUPLICATE_COUNT_LINE", "Danh tính đã có trong phiên; chọn dòng hiện có.")
        c.execute(text("INSERT INTO wms.count_line(id,session_id,stock_item_id,location_id,snapshot_quantity) VALUES (:id,:session,:stock,:loc,0)"),
                  dict(id=uuid4(), session=row["id"], stock=stock, loc=payload.location_id))

    def submit(self, auth, row, payload):
        require_state(row, "COUNTED", "FROZEN")
        c = auth.connection
        self.lock_scope(c, row, own=True)
        lines = self.lines(c, row["id"])
        for location in self.scope(c, row["id"]):
            if not any(line["location_id"] == location for line in lines):
                confirmations = c.execute(text("SELECT count(*) FROM wms.count_empty_confirmation WHERE session_id=:id AND location_id=:loc"),
                                          {"id": row["id"], "loc": location}).scalar_one()
                if confirmations < 2:
                    raise DomainError("RECOUNT_REQUIRED", "Vị trí không có dòng hàng cần hai người đếm xác nhận trống.")
        for line in lines:
            obs = self.observations(c, line["id"])
            if len(obs) < 2 or obs[-1]["counted_by"] == obs[-2]["counted_by"] or obs[-1]["quantity"] != obs[-2]["quantity"]:
                raise DomainError("RECOUNT_REQUIRED", "Mỗi dòng cần hai vòng liên tiếp, độc lập và cùng số lượng.")
            c.execute(text("UPDATE wms.count_line SET approved_quantity=:qty WHERE id=:id"), {"id": line["id"], "qty": obs[-1]["quantity"]})
        if not row["adjustment_document_id"]:
            row["adjustment_document_id"] = uuid4()
            c.execute(text("""INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes,reason)
                VALUES (:id,:number,'ADJUSTMENT','SUBMITTED',:warehouse,:day,:actor,:now,1,'{}',:reason)"""),
                      dict(id=row["adjustment_document_id"], number=row["number"] + "-ADJ", warehouse=row["warehouse_id"],
                           day=row["business_date"], actor=row["created_by"], now=self.identity.clock(), reason=payload.reason))
        else:
            c.execute(text("UPDATE wms.document SET status='SUBMITTED',version=version+1 WHERE id=:id"), {"id": row["adjustment_document_id"]})
        c.execute(text("""INSERT INTO wms.count_submission(id,session_id,session_version,policy_revision,requested_by,created_at,content_snapshot)
            VALUES (:id,:session,:version,1,:actor,:now,CAST(:snapshot AS jsonb))"""),
                  dict(id=uuid4(), session=row["id"], version=row["version"] + 1, actor=auth.principal.user_id,
                       now=self.identity.clock(), snapshot=encode(self.snapshot(c, row))))
        row["status"] = "SUBMITTED"

    def confirm_empty(self, auth, row, payload):
        require_state(row, "FROZEN", "COUNTED")
        c = auth.connection
        if one(c, "SELECT id FROM wms.count_line WHERE session_id=:id AND location_id=:loc LIMIT 1", id=row["id"], loc=payload.location_id):
            raise DomainError("INVALID_STATE", "Vị trí có dòng hàng; nhập số đếm cho từng dòng, kể cả lượng 0.")
        if one(c, "SELECT id FROM wms.count_empty_confirmation WHERE session_id=:id AND location_id=:loc AND counted_by=:actor",
               id=row["id"], loc=payload.location_id, actor=auth.principal.user_id):
            raise DomainError("DUPLICATE_COUNT", "Người đếm đã xác nhận vị trí trống.")
        c.execute(text("INSERT INTO wms.count_empty_confirmation VALUES (:id,:session,:loc,:actor,:now,:reason)"),
                  dict(id=uuid4(), session=row["id"], loc=payload.location_id, actor=auth.principal.user_id,
                       now=self.identity.clock(), reason=payload.reason))
        row["status"] = "COUNTED"

    def decide(self, auth, row, payload):
        sub, step = self.may_decide(auth, row)
        c = auth.connection
        c.execute(text("INSERT INTO wms.count_decision VALUES (:id,:submission,:step,:decision,:actor,:now,:reason)"),
                  dict(id=uuid4(), submission=sub["id"], step=step, decision=payload.decision,
                       actor=auth.principal.user_id, now=self.identity.clock(), reason=payload.reason))
        if payload.decision == "REJECT":
            row["status"] = "COUNTED"
        c.execute(text("UPDATE wms.document SET status=:state,version=version+1 WHERE id=:id"),
                  dict(id=row["adjustment_document_id"], state="REJECTED" if payload.decision == "REJECT" else "APPROVED" if step == 2 else "SUBMITTED"))

    def approved(self, c, row):
        sub = self.submission(c, row)
        decisions = self.decisions(c, sub)
        return len(decisions) == 2 and all(d["decision"] == "APPROVE" for d in decisions)

    @staticmethod
    def post_hash(payload):
        return hashlib.sha256(encode(payload.model_dump(mode="json")).encode()).hexdigest()

    def post(self, auth, row, payload):
        require_state(row, "SUBMITTED")
        c = auth.connection
        if not self.approved(c, row):
            raise DomainError("APPROVAL_REQUIRED", "Cần đủ hai bước CONTROLLER rồi DIRECTOR.")
        if self.submission(c, row)["content_snapshot"] != self.snapshot(c, row):
            raise DomainError("STALE_APPROVAL", "Nội dung đã thay đổi sau duyệt.")
        self.lock_scope(c, row, own=True)
        # LOSS is an immutable system counterpart, never a cached balance.
        loss = one(c, "SELECT * FROM wms.location WHERE id=:id", id=LOSS)
        if not loss or loss["kind"] != "LOSS" or not loss["is_active"]:
            raise DomainError("INVALID_LOCATION", "Thiếu vị trí đối ứng điều chỉnh.")
        lines = self.lines(c, row["id"])
        for product in sorted({r["product_id"] for r in lines}):
            c.execute(text("SELECT id FROM wms.product WHERE id=:id FOR UPDATE"), {"id": product})
        for line in sorted(lines, key=lambda r: r["stock_item_id"]):
            stock = resolve_stock_identity(c, product_id=line["product_id"], owner_id=line["owner_id"],
                consignment_id=line["consignment_id"], warehouse_id=row["warehouse_id"], business_date=row["business_date"],
                lot_id=line["lot_id"], serial_id=line["serial_id"])
            if stock != line["stock_item_id"]:
                raise DomainError("STOCK_IDENTITY_CHANGED", "Danh tính tồn đã thay đổi.")
        for line in sorted(lines, key=lambda r: (r["location_id"], r["stock_item_id"])):
            c.execute(text("""INSERT INTO wms.stock_balance(id,stock_item_id,location_id,on_hand,reserved,version)
                VALUES (:id,:stock,:loc,0,0,1) ON CONFLICT (stock_item_id,location_id) DO NOTHING"""),
                      dict(id=uuid4(), stock=line["stock_item_id"], loc=line["location_id"]))
            b = one(c, "SELECT * FROM wms.stock_balance WHERE stock_item_id=:stock AND location_id=:loc FOR UPDATE",
                    stock=line["stock_item_id"], loc=line["location_id"])
            check_reservations(c, line["stock_item_id"], line["location_id"], b["reserved"])
            if b["reserved"] or b["on_hand"] != line["snapshot_quantity"]:
                raise DomainError("SNAPSHOT_CHANGED", "Số dư/giữ chỗ khác ảnh chụp kiểm kê; cần đối soát.")
            qty = line["approved_quantity"]
            if qty is None or qty != qty.quantize(Decimal(1).scaleb(-line["decimal_places"])) or (line["serial_id"] and qty not in {0, 1}):
                raise DomainError("INVALID_QUANTITY", "Lượng duyệt không hợp lệ.")
        serials = sorted({r["serial_id"] for r in lines if r["serial_id"]})
        for serial in serials:
            existing = c.execute(text("""SELECT b.stock_item_id,b.location_id,b.on_hand FROM wms.stock_balance b
                JOIN wms.stock_item i ON i.id=b.stock_item_id WHERE i.serial_id=:id AND b.on_hand>0"""), {"id": serial}).mappings().all()
            position = one(c, "SELECT * FROM wms.serial_position WHERE serial_id=:id FOR UPDATE", id=serial)
            if (len(existing) > 1 or any(b["on_hand"] != 1 for b in existing) or
                bool(existing) != bool(position) or (existing and position["location_id"] != existing[0]["location_id"])):
                raise DomainError("SERIAL_POSITION_CONFLICT", "Serial cần đối soát vị trí hiện hữu.")
            final = {(b["stock_item_id"], b["location_id"]): b["on_hand"] for b in existing}
            for line in [r for r in lines if r["serial_id"] == serial]:
                final[line["stock_item_id"], line["location_id"]] = line["approved_quantity"]
            final_items = {stock for (stock, _), qty in final.items() if qty}
            if existing and final_items and final_items != {existing[0]["stock_item_id"]}:
                raise DomainError("OWNERSHIP_CONFLICT", "Điều chỉnh kiểm kê không chuyển chủ của serial.")
            if sum(final.values()) not in {0, 1}:
                raise DomainError("SERIAL_POSITION_CONFLICT", "Không thể tạo hai vị trí/chủ sở hữu cho cùng serial.")
        tx = uuid4()
        c.execute(text("""INSERT INTO wms.inventory_transaction(id,document_id,execution_key,operation,business_date,posted_at,posted_by)
            VALUES (:id,:doc,:key,'ADJUST',:day,:now,:actor)"""), dict(id=tx, doc=row["adjustment_document_id"],
                key=payload.execution_key, day=row["business_date"], now=self.identity.clock(), actor=auth.principal.user_id))
        serial_moves = {}
        # Removing a misplaced serial precedes adding its same identity at the
        # observed location, so the database's global serial guard remains valid.
        for index, line in enumerate(sorted(lines, key=lambda r: r["approved_quantity"] - r["snapshot_quantity"]), 1):
            delta = line["approved_quantity"] - line["snapshot_quantity"]
            if not delta:
                continue
            doc_line, move = uuid4(), uuid4()
            c.execute(text("""INSERT INTO wms.document_line(id,document_id,line_no,product_id,uom_id,quantity,factor_snapshot,base_quantity,owner_id,consignment_id)
                VALUES (:id,:doc,:n,:product,:unit,:qty,1,:qty,:owner,:agreement)"""),
                      dict(id=doc_line, doc=row["adjustment_document_id"], n=index, product=line["product_id"], unit=line["base_uom_id"],
                           qty=abs(delta), owner=line["owner_id"], agreement=line["consignment_id"]))
            c.execute(text("""INSERT INTO wms.stock_move(id,transaction_id,line_id,stock_item_id,source_location_id,destination_location_id,quantity_base,base_uom_id)
                VALUES (:id,:tx,:line,:stock,:source,:destination,:qty,:unit)"""),
                      dict(id=move, tx=tx, line=doc_line, stock=line["stock_item_id"], qty=abs(delta), unit=line["base_uom_id"],
                           source=line["location_id"] if delta < 0 else LOSS, destination=LOSS if delta < 0 else line["location_id"]))
            c.execute(text("UPDATE wms.stock_balance SET on_hand=on_hand+:delta,version=version+1 WHERE stock_item_id=:stock AND location_id=:loc"),
                      dict(delta=delta, stock=line["stock_item_id"], loc=line["location_id"]))
            if line["serial_id"] and delta > 0:
                serial_moves[line["serial_id"]] = (line["location_id"], move)
        for serial in serials:
            if serial in serial_moves:
                location, move = serial_moves[serial]
                c.execute(text("""INSERT INTO wms.serial_position(id,serial_id,location_id,last_move_id) VALUES (:id,:serial,:loc,:move)
                    ON CONFLICT (serial_id) DO UPDATE SET location_id=:loc,last_move_id=:move"""),
                          dict(id=uuid4(), serial=serial, loc=location, move=move))
            elif any(r["serial_id"] == serial and r["approved_quantity"] < r["snapshot_quantity"] for r in lines):
                c.execute(text("DELETE FROM wms.serial_position WHERE serial_id=:id"), {"id": serial})
        c.execute(text("UPDATE wms.document SET status='COMPLETED',version=version+1 WHERE id=:id"), {"id": row["adjustment_document_id"]})
        self.release(c, row)
        row.update(status="POSTED", transaction_id=tx)

    def release(self, c, row):
        c.execute(text("UPDATE wms.count_location_lock SET released_at=:now WHERE session_id=:id AND released_at IS NULL"),
                  {"id": row["id"], "now": self.identity.clock()})

    def cancel(self, auth, row, payload):
        require_state(row, "DRAFT", "FROZEN", "COUNTED", "SUBMITTED")
        c = auth.connection
        # Cancellation only releases this session's locks; deactivated catalogue
        # rows or a different session's lock must not trap a cancelled draft.
        c.execute(text("SELECT id FROM wms.warehouse WHERE id=:id FOR SHARE"), {"id": row["warehouse_id"]})
        c.execute(text("SELECT id FROM wms.location WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"),
                  {"ids": self.scope(c, row["id"])})
        self.release(c, row)
        if row["adjustment_document_id"]:
            c.execute(text("UPDATE wms.document SET status='CANCELLED',version=version+1 WHERE id=:id"), {"id": row["adjustment_document_id"]})
        row["status"] = "CANCELLED"

    def operation(self, auth, key):
        saved = one(auth.connection, "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
                    actor=auth.principal.user_id, key=key)
        if not saved or not saved["command"].startswith("count."):
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK kiểm kê.")
        row = self.session(auth, UUID(saved["response"]["id"]))
        auth.require(PERMISSIONS[saved["command"].split(".")[1]], row["warehouse_id"])
        return saved["response"]
