"""Reservation-bound fulfillment. Lock SO -> ISSUE -> inventory -> reservations.

Every child mutation also advances the ISSUE progress version. Neither approval
content nor physical/reserved balances change here. Old untyped rows fail closed.
"""
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization
from apps.server.application.commands import CommandResult
from apps.server.application.master_data import active_reference, one
from apps.server.application.move_safety import location_tree
from apps.server.application.orders import amount
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.fulfillment import (
    FulfillmentOperation,
    FulfillmentResult,
    FulfillmentView,
    PackageView,
    PackLineView,
    PickerPage,
    PickView,
)


class PickingService:
    def __init__(self, issues):
        from apps.server.application.packing import PackingService
        self.issues, self.orders, self.identity = issues, issues.orders, issues.identity
        self.reservations, self.bus = issues.reservations, issues.bus
        self.packing = PackingService(self)
        issues.fulfillment = self

    def access(self, auth, doc, action, entity=None, assigned_to=None):
        self.issues.source(auth, doc)  # source visibility is rechecked even for cached ACKs
        permission = "document.assign" if action == "pick.assign" else "pick.confirm"
        auth.require(permission, doc["warehouse_id"])
        if action == "pick.create" and assigned_to != auth.principal.user_id:
            auth.require("document.assign", doc["warehouse_id"])
        if entity and action.startswith("pick."):
            if action in {"pick.start", "pick.confirm", "pick.reject"}:
                if entity["assigned_to"] != auth.principal.user_id:
                    raise DomainError("FORBIDDEN", "Chỉ người được giao mới xác nhận nhiệm vụ soạn.")
            elif action == "pick.cancel" and entity["assigned_to"] != auth.principal.user_id:
                auth.require("document.assign", doc["warehouse_id"])

    def target(self, auth, doc, user_id):
        user = one(auth.connection, "SELECT id FROM wms.app_user WHERE id=:id AND is_active FOR SHARE", id=user_id)
        if not user:
            raise DomainError("ASSIGNEE_INELIGIBLE", "Người được giao không còn hoạt động.")
        target = Authorization(auth.connection, replace(auth.principal, user_id=user_id), auth.now)
        if not target.allows("pick.confirm", doc["warehouse_id"]):
            raise DomainError("ASSIGNEE_INELIGIBLE", "Người được giao cần quyền soạn trong kho này.")
        try:
            self.orders.document(target, doc["id"], "ISSUE")
            self.issues.source(target, doc)
        except DomainError:
            raise DomainError("ASSIGNEE_INELIGIBLE", "Cần giao quyền xem cả phiếu xuất và SO nguồn trước khi duyệt.") from None

    def assignees(self, auth, doc_id, after=None, limit=50):
        doc = self.orders.document(auth, doc_id, "ISSUE")
        self.issues.source(auth, doc)
        auth.require("pick.confirm", doc["warehouse_id"])
        # Scan a bounded user page; next cursor follows scanned rows, including
        # ineligible ones. No names outside the document's scope are returned.
        users = list(auth.connection.execute(text("""SELECT id,display_name FROM wms.app_user
            WHERE is_active AND (CAST(:after AS uuid) IS NULL OR id>:after)
            ORDER BY id LIMIT :limit"""), {"after": after, "limit": limit + 1}).mappings())
        items = []
        for user in users[:limit]:
            if user["id"] != auth.principal.user_id and not auth.allows("document.assign", doc["warehouse_id"]):
                continue
            try:
                self.target(auth, doc, user["id"])
            except DomainError:
                continue
            items.append(dict(user))
        return PickerPage(items=items, next_after=users[limit-1]["id"] if len(users) > limit else None)

    def tasks(self, c, doc_id):
        return [dict(r) for r in c.execute(text("""SELECT t.*,u.display_name AS assignee_name FROM wms.pick_task t
            JOIN wms.reservation r ON r.id=t.reservation_id JOIN wms.document_line l ON l.id=r.line_id
            JOIN wms.app_user u ON u.id=t.assigned_to WHERE l.document_id=:id ORDER BY t.id"""), {"id": doc_id}).mappings()]

    def entity(self, c, doc_id, kind, entity_id):
        if kind == "pick":
            row = one(c, """SELECT t.* FROM wms.pick_task t JOIN wms.reservation r ON r.id=t.reservation_id
                JOIN wms.document_line l ON l.id=r.line_id WHERE t.id=:id AND l.document_id=:doc""", id=entity_id, doc=doc_id)
        else:
            row = one(c, "SELECT * FROM wms.package WHERE id=:id AND document_id=:doc", id=entity_id, doc=doc_id)
        if not row:
            raise DomainError("NOT_FOUND", "Không tìm thấy nhiệm vụ/kiện thuộc phiếu.")
        return row

    def read(self, auth, doc_id):
        doc = self.orders.document(auth, doc_id, "ISSUE")
        source = self.issues.source(auth, doc)
        active = doc["status"] in {"APPROVED", "PARTIAL"}
        writable = auth.allows("pick.confirm", doc["warehouse_id"])
        tasks = []
        for row in self.tasks(auth.connection, doc_id):
            actions = []
            if row["target_quantity"] is not None and row["status"] != "CANCELLED":
                if writable and (row["assigned_to"] == auth.principal.user_id or auth.allows("document.assign", doc["warehouse_id"])):
                    actions.append("cancel")
                if active and row["status"] in {"OPEN", "PICKING"}:
                    if writable and row["assigned_to"] == auth.principal.user_id:
                        actions += ["confirm", "reject"] + (["start"] if row["status"] == "OPEN" else [])
                    if auth.allows("document.assign", doc["warehouse_id"]):
                        actions.append("assign")
            tasks.append(PickView(**{k: row[k] for k in ("id", "reservation_id", "assigned_to", "assignee_name", "status", "version", "reason")},
                target_quantity=amount(row["target_quantity"]) if row["target_quantity"] is not None else None,
                picked_quantity=amount(row["picked_quantity"]), consumed_quantity=amount(row["consumed_quantity"]),
                unpacked_base=amount(self.packing.unpacked(auth.connection, row)), allowed_actions=actions))
        packages = []
        for row in auth.connection.execute(text("SELECT * FROM wms.package WHERE document_id=:id ORDER BY id"), {"id": doc_id}).mappings():
            lines = [PackLineView(**{k: r[k] for k in ("id", "pick_task_id", "document_line_id", "stock_item_id")},
                         quantity=amount(r["quantity"]), consumed_quantity=amount(r["consumed_quantity"]))
                     for r in self.packing.lines(auth.connection, row["id"])]
            actions = (["cancel"] if writable and row["status"] in {"DRAFT", "PACKED"} else [])
            if active and writable and row["status"] == "DRAFT":
                actions.append("seal")
            packages.append(PackageView(**{k: row[k] for k in ("id", "code", "status", "version", "reason")}, lines=lines, allowed_actions=actions))
        return FulfillmentView(**{k: doc[k] for k in ("id", "warehouse_id", "number", "status", "version")},
            source_order_id=source["id"], reservations=self.reservations.view(auth.connection, doc_id),
            tasks=tasks, packages=packages, allowed_actions=["pick.create", "package.create"] if active and writable else [])

    def stock(self, auth, doc):
        c = auth.connection
        self.issues.validate_saved(auth, doc)
        self.issues.approved(c, doc)
        lines = self.orders.lines(c, doc)
        old = self.reservations.rows(c, doc["id"])
        self.lock_locations(c, doc, old)
        inventory = self.reservations.inventory(c, doc, lines, reservations=old)
        held = {r["id"]: r for r in self.reservations.rows(c, doc["id"], lock=True)}
        return held, inventory

    def lock_locations(self, c, doc, reservations, extra=()):
        """B03 ancestry validation before B02 product locks; include EXTERNAL at post.

        Validate unchanged parent pointers after taking the sorted location locks.
        Never acquire an unseen ancestor after locking a product/balance.
        """
        active_reference(c, "warehouse", doc["warehouse_id"], "warehouse_id")
        targets = {r["location_id"] for r in reservations if self.reservations.remaining(r) > 0}
        parents = {}
        for target in sorted(targets):
            current, visited = target, set()
            while current:
                if current in visited or len(visited) > 10:
                    raise DomainError("INVALID_TREE", "Cây vị trí không hợp lệ.")
                visited.add(current)
                row = one(c, "SELECT parent_id FROM wms.location WHERE id=:id", id=current)
                if not row:
                    raise DomainError("INVALID_LOCATION", "Không tìm thấy vị trí giữ chỗ.")
                parents[current] = row["parent_id"]
                current = row["parent_id"]
        for loc in sorted(set(parents) | set(extra) | {r["location_id"] for r in reservations}):
            row = one(c, "SELECT parent_id FROM wms.location WHERE id=:id FOR UPDATE", id=loc)
            if not row or loc in parents and row["parent_id"] != parents[loc]:
                raise DomainError("INVALID_TREE", "Cây vị trí đã đổi; tải lại nguồn hàng.")
        location_tree(c, doc["warehouse_id"], targets)
        if one(c, "SELECT id FROM wms.package WHERE document_id=:id AND status IS NULL LIMIT 1", id=doc["id"]):
            raise DomainError("LEGACY_FULFILLMENT", "Kiện cũ thiếu nguồn soạn; cần đối soát riêng.")

    def valid_reservation(self, c, doc, held, inventory, reservation_id, quantity):
        row = held.get(reservation_id)
        if not row or quantity > self.reservations.remaining(row) or quantity <= 0:
            raise DomainError("RESERVATION_MISMATCH", "Lượng soạn/đóng kiện phải thuộc phần giữ chỗ còn lại của phiếu.")
        if row["expires_at"] is not None and row["expires_at"] <= self.identity.clock():
            raise DomainError("RESERVATION_EXPIRED", "Giữ chỗ hết hạn; hủy kiện/nhiệm vụ rồi giải phóng.")
        stock = inventory.get((row["stock_item_id"], row["location_id"]))
        if (not stock or stock["product_id"] != row["product_id"] or stock["owner_id"] != row["owner_id"]
                or stock["consignment_id"] != row["consignment_id"] or not self.reservations.eligible(stock, doc["warehouse_id"])
                or stock["on_hand"] < quantity or stock["reserved"] < quantity):
            raise DomainError("STOCK_INELIGIBLE", "Nguồn hàng không còn hợp lệ: kiểm tra owner, lô/serial, hạn và khóa kiểm kê.")
        self.reservations.quantity(c, row, quantity)
        if stock["tracking"] == "SERIAL" and quantity != 1:
            raise DomainError("SERIAL_QUANTITY", "Mỗi serial soạn/đóng kiện đúng một đơn vị.")
        return row, stock

    def change_pick(self, auth, doc, action, payload, entity, held, inventory):
        c = auth.connection
        if action == "pick.create":
            qty = Decimal(payload.quantity_base)
            row, _ = self.valid_reservation(c, doc, held, inventory, payload.reservation_id, qty)
            self.target(auth, doc, payload.assigned_to)
            tasks = [t for t in self.tasks(c, doc["id"]) if t["reservation_id"] == row["id"] and t["status"] != "CANCELLED"]
            if any(t["target_quantity"] is None for t in tasks):
                raise DomainError("LEGACY_FULFILLMENT", "Nhiệm vụ cũ thiếu nguồn lượng; cần đối soát riêng.")
            allocated = sum((t["picked_quantity"] if t["status"] == "DONE" else t["target_quantity"]) - t["consumed_quantity"] for t in tasks)
            if allocated + qty > self.reservations.remaining(row):
                raise DomainError("PICK_EXCEEDED", "Lượng đã giao soạn vượt phần giữ chỗ còn lại.")
            entity = dict(id=uuid4(), status="OPEN", version=1, picked_quantity=Decimal(0), assigned_to=payload.assigned_to)
            c.execute(text("""INSERT INTO wms.pick_task(id,reservation_id,assigned_to,picked_quantity,status,version,
                target_quantity,reason,created_by,created_at) VALUES (:id,:res,:user,0,'OPEN',1,:qty,:reason,:actor,:now)"""),
                {**entity, "res": row["id"], "user": payload.assigned_to, "qty": qty, "reason": payload.reason,
                 "actor": auth.principal.user_id, "now": self.identity.clock()})
            return entity
        if entity["target_quantity"] is None:
            raise DomainError("LEGACY_FULFILLMENT", "Không chuyển trạng thái nhiệm vụ cũ thiếu nguồn lượng.")
        if entity["status"] == "CANCELLED" or (action != "pick.cancel" and entity["status"] == "DONE"):
            raise DomainError("INVALID_STATE", "Nhiệm vụ đã kết thúc; tải lại trạng thái.")
        if action == "pick.cancel":
            if self.packing.allocated(c, entity["id"]) > 0:
                raise DomainError("PACKAGE_ACTIVE", "Hủy kiện còn lượng chưa xuất trước khi hủy nhiệm vụ.")
            entity["status"] = "CANCELLED"
        else:
            self.valid_reservation(c, doc, held, inventory, entity["reservation_id"], entity["target_quantity"])
            if action == "pick.assign":
                self.target(auth, doc, payload.assigned_to)
                entity["assigned_to"] = payload.assigned_to
            elif action == "pick.start":
                if entity["status"] != "OPEN":
                    raise DomainError("INVALID_STATE", "Nhiệm vụ đã bắt đầu.")
                entity["status"] = "PICKING"
            elif action == "pick.reject":
                entity["status"] = "CANCELLED"
            else:
                qty = Decimal(payload.quantity_base)
                _, stock = self.valid_reservation(c, doc, held, inventory, entity["reservation_id"], qty)
                if qty > entity["target_quantity"]:
                    raise DomainError("PICK_EXCEEDED", "Không được xác nhận vượt lượng giao soạn.")
                barcode = one(c, """SELECT b.id FROM wms.barcode b JOIN wms.product_uom pu ON pu.id=b.product_uom_id
                    JOIN wms.uom u ON u.id=pu.uom_id WHERE pu.product_id=:product AND b.code=:code
                    AND b.is_active AND pu.is_active AND u.is_active""",
                              product=stock["product_id"], code=payload.item_code)
                if (payload.location_code != stock["location_code"] or (payload.item_code != stock["sku"] and not barcode)
                        or payload.trace_code != (stock["lot_code"] or stock["serial_code"])):
                    raise DomainError("SCAN_MISMATCH", "Mã vị trí, SKU/barcode hoặc lô/serial không khớp nhiệm vụ.")
                entity.update(status="DONE", picked_quantity=qty)
        entity["version"] += 1
        c.execute(text("""UPDATE wms.pick_task SET status=:status,version=:version,assigned_to=:assigned_to,
            picked_quantity=:picked_quantity,reason=:reason WHERE id=:id"""), {**entity, "reason": payload.reason})
        return entity

    def command(self, access, key, doc_id, action, payload, request_id, entity_id=None):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id
        context, kind = {}, action.split(".")[0]

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            doc = self.orders.document(auth, doc_id, "ISSUE")
            entity = self.entity(uow.connection, doc_id, kind, entity_id) if entity_id else None
            self.access(auth, doc, action, entity, getattr(payload, "assigned_to", None))
            context["auth"] = auth

        def handle(uow):
            c, auth = uow.connection, context["auth"]
            doc = self.orders.document(auth, doc_id, "ISSUE", lock=True)
            require_version(doc["version"], payload.expected_version)
            entity = self.entity(c, doc_id, kind, entity_id) if entity_id else None
            self.access(auth, doc, action, entity, getattr(payload, "assigned_to", None))
            if entity:
                require_version(entity["version"], payload.entity_version)
            # Cancellation must remain possible after expiry, freeze or source closure.
            held, inventory = ({}, {}) if action.endswith("cancel") else self.stock(auth, doc)
            entity = (self.change_pick if kind == "pick" else self.packing.change)(auth, doc, action, payload, entity, held, inventory)
            doc["version"] += 1
            c.execute(text("UPDATE wms.document SET version=:version WHERE id=:id"), doc)
            result = FulfillmentResult(**self.issues.result(doc, request_id), entity_id=entity["id"], entity_kind=kind,
                entity_status=entity["status"], entity_version=entity["version"],
                assigned_to=entity.get("assigned_to"),
                quantity_base=amount(entity["picked_quantity"]) if kind == "pick" else None).model_dump(mode="json")
            self.orders.effects(c, actor, doc, "fulfillment." + action, result, payload.reason, request_id)
            return CommandResult(result, 201 if action.endswith("create") else 200)

        return self.bus.execute(actor_id=actor, key=key, command="fulfillment." + action, resource_id=entity_id or doc_id,
            payload={"document_id": str(doc_id), **payload.model_dump(mode="json")}, authorize=authorize, handle=handle)

    def operation(self, auth, key):
        row = one(auth.connection, "SELECT command,response FROM wms.idempotency_record WHERE actor_id=:actor AND key=:key",
                  actor=auth.principal.user_id, key=key)
        if not row or not row["command"].startswith("fulfillment."):
            raise DomainError("NOT_FOUND", "Chưa tìm thấy ACK soạn/đóng kiện.")
        result = FulfillmentResult.model_validate(row["response"])
        doc = self.orders.document(auth, result.id, "ISSUE")
        entity = self.entity(auth.connection, result.id, result.entity_kind, result.entity_id)
        action = row["command"].removeprefix("fulfillment.")
        # The original recipient is part of the ACK/audit. A later reassignment
        # cannot downgrade the permission needed to reconcile delegated creation.
        self.access(auth, doc, action, entity, result.assigned_to)
        return FulfillmentOperation(command=row["command"], result=result)
