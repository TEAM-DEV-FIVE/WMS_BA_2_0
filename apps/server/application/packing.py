"""Logical packages and their exact consumption by ISSUE ledger moves."""
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError


class PackingService:
    def __init__(self, picking):
        self.picking = picking

    def lines(self, c, package_id):
        return [dict(r) for r in c.execute(text("SELECT * FROM wms.package_line WHERE package_id=:id ORDER BY id"),
                                         {"id": package_id}).mappings()]

    def allocated(self, c, task_id):
        return c.execute(text("""SELECT COALESCE(sum(l.quantity-l.consumed_quantity),0) FROM wms.package_line l
            JOIN wms.package p ON p.id=l.package_id WHERE l.pick_task_id=:id AND p.status<>'CANCELLED'"""),
            {"id": task_id}).scalar_one()

    def unpacked(self, c, task):
        return task["picked_quantity"] - task["consumed_quantity"] - self.allocated(c, task["id"])

    def change(self, auth, doc, action, payload, entity, held, inventory):
        c, pick = auth.connection, self.picking
        if action == "package.create":
            if one(c, "SELECT id FROM wms.package WHERE document_id=:doc AND code=:code", doc=doc["id"], code=payload.code):
                raise DomainError("PACKAGE_CODE_EXISTS", "Mã kiện đã dùng trên phiếu; chọn mã mới để giữ lịch sử.")
            prepared = []
            for spec in payload.lines:
                task = pick.entity(c, doc["id"], "pick", spec.pick_task_id)
                qty = Decimal(spec.quantity_base)
                if task["target_quantity"] is None or task["status"] != "DONE":
                    raise DomainError("PICK_INCOMPLETE", "Chỉ đóng kiện từ nhiệm vụ đã xác nhận soạn.")
                row, _ = pick.valid_reservation(c, doc, held, inventory, task["reservation_id"], qty)
                if qty > self.unpacked(c, task):
                    raise DomainError("PACK_EXCEEDED", "Vượt lượng đã soạn chưa nằm trong kiện/chưa xuất.")
                prepared.append(dict(id=uuid4(), task=task["id"], line=row["line_id"], stock=row["stock_item_id"], quantity=qty))
            entity = dict(id=uuid4(), status="DRAFT", version=1)
            c.execute(text("""INSERT INTO wms.package(id,document_id,code,status,version,reason,created_by,created_at)
                VALUES (:id,:doc,:code,'DRAFT',1,:reason,:actor,:now)"""),
                {**entity, "doc": doc["id"], "code": payload.code, "reason": payload.reason,
                 "actor": auth.principal.user_id, "now": pick.identity.clock()})
            for line in prepared:
                c.execute(text("""INSERT INTO wms.package_line(id,package_id,document_line_id,stock_item_id,quantity,pick_task_id)
                    VALUES (:id,:package,:line,:stock,:quantity,:task)"""), {**line, "package": entity["id"]})
            return entity
        if entity["status"] is None:
            raise DomainError("LEGACY_FULFILLMENT", "Kiện cũ chưa có nguồn nhiệm vụ; cần đối soát riêng.")
        if entity["status"] == "CANCELLED" or action == "package.seal" and entity["status"] != "DRAFT":
            raise DomainError("INVALID_STATE", "Kiện không còn ở trạng thái cho phép thao tác.")
        if action == "package.seal":
            totals = defaultdict(Decimal)
            lines = self.lines(c, entity["id"])
            if not lines:
                raise DomainError("PACKAGE_EMPTY", "Không được chốt kiện rỗng.")
            for line in lines:
                task = pick.entity(c, doc["id"], "pick", line["pick_task_id"])
                if task["status"] != "DONE" or task["target_quantity"] is None or self.unpacked(c, task) < 0:
                    raise DomainError("PICK_INCOMPLETE", "Nguồn soạn không còn hợp lệ.")
                totals[task["reservation_id"]] += line["quantity"]
            for res_id, qty in totals.items():
                pick.valid_reservation(c, doc, held, inventory, res_id, qty)
        entity["status"] = "PACKED" if action == "package.seal" else "CANCELLED"
        entity["version"] += 1
        c.execute(text("UPDATE wms.package SET status=:status,version=:version,reason=:reason WHERE id=:id"),
                  {**entity, "reason": payload.reason})
        return entity

    def prepare_post(self, c, doc_id, reservation_id, qty):
        """Called under the B02 SO/ISSUE + inventory/reservation lock boundary.

        A reservation with live fulfillment must ship from sealed packages. With
        all tasks explicitly cancelled, the B02 direct-issue workflow is retained.
        """
        tasks = [t for t in self.picking.tasks(c, doc_id) if t["reservation_id"] == reservation_id and t["status"] != "CANCELLED"]
        if any(t["target_quantity"] is None for t in tasks):
            raise DomainError("FULFILLMENT_ACTIVE", "Nhiệm vụ cũ chưa được đối soát; không tự suy ra lượng soạn.")
        active = [t for t in tasks if (t["picked_quantity"] if t["status"] == "DONE" else t["target_quantity"]) > t["consumed_quantity"]]
        if not active:
            return []
        rows = c.execute(text("""SELECT l.*,t.reservation_id FROM wms.package_line l
            JOIN wms.package p ON p.id=l.package_id JOIN wms.pick_task t ON t.id=l.pick_task_id
            JOIN wms.reservation r ON r.id=t.reservation_id
            WHERE p.document_id=:doc AND p.status='PACKED' AND t.status='DONE' AND t.target_quantity IS NOT NULL
              AND t.reservation_id=:res AND l.stock_item_id=r.stock_item_id AND l.document_line_id=r.line_id
              AND l.quantity>l.consumed_quantity ORDER BY l.id"""), {"doc": doc_id, "res": reservation_id}).mappings()
        allocations, left = [], qty
        for row in rows:
            take = min(left, row["quantity"] - row["consumed_quantity"])
            if take > 0:
                allocations.append(dict(line=row["id"], task=row["pick_task_id"], package=row["package_id"], quantity=take))
                left -= take
            if left == 0:
                break
        if left:
            raise DomainError("FULFILLMENT_INCOMPLETE", "Lượng xuất vượt lượng đã soạn và chốt kiện; hoàn tất hoặc hủy nhiệm vụ trước.")
        return allocations

    def consume(self, c, allocations, reservation_consumption_id):
        for row in allocations:
            c.execute(text("UPDATE wms.package_line SET consumed_quantity=consumed_quantity+:quantity WHERE id=:line"), row)
            c.execute(text("UPDATE wms.pick_task SET consumed_quantity=consumed_quantity+:quantity,version=version+1 WHERE id=:task"), row)
            c.execute(text("""INSERT INTO wms.fulfillment_consumption(id,package_line_id,reservation_consumption_id,quantity)
                VALUES (:id,:line,:consumption,:quantity)"""), {**row, "id": uuid4(), "consumption": reservation_consumption_id})
        for package_id in sorted({r["package"] for r in allocations}):
            c.execute(text("UPDATE wms.package SET version=version+1 WHERE id=:id"), {"id": package_id})
