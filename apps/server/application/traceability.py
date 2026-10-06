import json
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from apps.server.application.commands import CommandBus, CommandResult
from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.database import PostgresUnitOfWork
from packages.contracts.traceability import SerialWarranty, WarrantyResult


def warranty_status(starts_on, ends_on, evidence, as_of):
    if not starts_on or not ends_on or not evidence or as_of < starts_on:
        return "UNKNOWN"
    return "EXPIRED" if as_of > ends_on else "VALID"


def quantity(value):
    return format(value or Decimal(0), '.6f')


class TraceabilityService:
    def __init__(self, identity):
        self.identity = identity
        self.bus = CommandBus(lambda: PostgresUnitOfWork(identity.engine))

    def warehouse(self, auth, warehouse_id, permission):
        auth.require("stock.read", warehouse_id, hidden=True)
        auth.require(permission, warehouse_id, hidden=True)
        if not one(auth.connection, "SELECT id FROM wms.warehouse WHERE id=:id AND is_active", id=warehouse_id):
            raise DomainError("NOT_FOUND", "Không tìm thấy kho.")

    def ownership(self, auth, warehouse_id, location_id, stock_item_id):
        self.warehouse(auth, warehouse_id, "ownership.read")
        location = one(auth.connection, """SELECT id FROM wms.location WHERE id=:id AND warehouse_id=:warehouse
            AND kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING')""", id=location_id, warehouse=warehouse_id)
        if not location:
            raise DomainError("NOT_FOUND", "Không tìm thấy vị trí trong kho.")
        # Require the anchor to exist at this location; do not reveal an identity from another warehouse.
        rows = auth.connection.execute(text("""SELECT o.id AS owner_id,o.kind,o.partner_id,SUM(b.on_hand) AS qty
            FROM wms.stock_item anchor JOIN wms.stock_balance ab ON ab.stock_item_id=anchor.id AND ab.location_id=:location
            JOIN wms.stock_item i ON i.product_id=anchor.product_id
              AND i.lot_id IS NOT DISTINCT FROM anchor.lot_id AND i.serial_id IS NOT DISTINCT FROM anchor.serial_id
            JOIN wms.stock_balance b ON b.stock_item_id=i.id AND b.location_id=:location
            JOIN wms.stock_owner o ON o.id=i.owner_id WHERE anchor.id=:item
            GROUP BY o.id,o.kind,o.partner_id ORDER BY o.id"""), {"location": location_id, "item": stock_item_id}).mappings().all()
        if not rows:
            raise DomainError("NOT_FOUND", "Không tìm thấy hàng tại vị trí.")
        totals = {kind: sum((r["qty"] for r in rows if r["kind"] == kind), Decimal(0))
                  for kind in ["COMPANY", "CONSIGNOR", "UNCLASSIFIED"]}
        return {"warehouse_id": warehouse_id, "location_id": location_id, "stock_item_id": stock_item_id,
                "physical_base": quantity(sum(totals.values())), "owned_base": quantity(totals["COMPANY"]),
                "unclassified_base": quantity(totals["UNCLASSIFIED"]), "as_of": self.identity.clock(),
                "consigned_by_owner": [{"owner_id": r["owner_id"], "owner_partner_id": r["partner_id"],
                                        "quantity_base": quantity(r["qty"])} for r in rows if r["kind"] == "CONSIGNOR" and r["qty"] > 0]}

    def receipt(self, connection, serial_id, move_id=None):
        return one(connection, """SELECT m.id AS move_id,d.id AS document_id,d.number AS receipt_number,d.warehouse_id,d.partner_id,
            supplier.code AS supplier_code,supplier.name AS supplier_name,t.business_date AS received_on FROM wms.stock_move m
            JOIN wms.stock_item i ON i.id=m.stock_item_id AND i.serial_id=:serial
            JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='RECEIVE'
            JOIN wms.document d ON d.id=t.document_id AND d.kind='RECEIPT'
            JOIN wms.document_line l ON l.id=m.line_id AND l.document_id=d.id AND l.product_id=i.product_id
            LEFT JOIN wms.partner supplier ON supplier.id=d.partner_id
            WHERE (CAST(:move AS uuid) IS NULL OR m.id=:move)
              AND NOT EXISTS (SELECT 1 FROM wms.stock_move reversed WHERE reversed.reverses_move_id=m.id)
            ORDER BY t.posted_at,m.id LIMIT 1""", serial=serial_id, move=move_id)

    def visible_serial(self, auth, serial_id, warehouse_id):
        self.warehouse(auth, warehouse_id, "serial.read")
        serial = one(auth.connection, """SELECT s.id,s.code,s.product_id,s.warranty_version,p.sku FROM wms.serial s
            JOIN wms.product p ON p.id=s.product_id WHERE s.id=:serial AND (
              EXISTS (SELECT 1 FROM wms.stock_item i JOIN wms.stock_balance b ON b.stock_item_id=i.id
                JOIN wms.location l ON l.id=b.location_id WHERE i.serial_id=s.id AND b.on_hand>0 AND l.warehouse_id=:warehouse)
              OR EXISTS (SELECT 1 FROM wms.stock_item i JOIN wms.stock_move m ON m.stock_item_id=i.id
                JOIN wms.inventory_transaction t ON t.id=m.transaction_id AND t.operation='RECEIVE'
                JOIN wms.document d ON d.id=t.document_id AND d.kind='RECEIPT' AND d.warehouse_id=:warehouse
                WHERE i.serial_id=s.id AND NOT EXISTS(SELECT 1 FROM wms.stock_move r WHERE r.reverses_move_id=m.id)))""",
                     serial=serial_id, warehouse=warehouse_id)
        if not serial:
            raise DomainError("NOT_FOUND", "Không tìm thấy serial trong phạm vi được phép.")
        return serial

    def warranty(self, auth, serial_id, warehouse_id):
        serial = self.visible_serial(auth, serial_id, warehouse_id)
        record = one(auth.connection, "SELECT * FROM wms.serial_warranty_record WHERE serial_id=:id ORDER BY revision DESC LIMIT 1", id=serial_id)
        receipt = self.receipt(auth.connection, serial_id, record["receipt_move_id"] if record else None)
        if receipt:
            auth.require("serial.read", receipt["warehouse_id"], hidden=True)
            auth.document(receipt["document_id"])
        else:
            record = None  # Reversed/unverifiable source does not prove coverage.
        today = self.identity.clock().astimezone(ZoneInfo(self.identity.settings.business_timezone)).date()
        starts, ends, evidence = (record["starts_on"], record["ends_on"], record["evidence_ref"]) if record else (None, None, None)
        return SerialWarranty(serial_id=serial_id, product_id=serial["product_id"], sku=serial["sku"], serial_code=serial["code"],
                              warehouse_id=warehouse_id, receipt_id=receipt["document_id"] if receipt else None,
                              receipt_number=receipt["receipt_number"] if receipt else None,
                              receipt_move_id=receipt["move_id"] if receipt else None,
                              supplier_partner_id=receipt["partner_id"] if receipt else None,
                              supplier_code=receipt["supplier_code"] if receipt else None,
                              supplier_name=receipt["supplier_name"] if receipt else None,
                              received_on=receipt["received_on"] if receipt else None,
                              warranty_start_on=starts, warranty_ends_on=ends, warranty_evidence_ref=evidence,
                              status=warranty_status(starts, ends, evidence, today), as_of=today,
                              version=serial["warranty_version"], evidence_record_id=record["id"] if record else None)

    def lookup(self, auth, warehouse_id, code, sku=None):
        self.warehouse(auth, warehouse_id, "serial.read")
        candidates = auth.connection.execute(text("""SELECT s.id FROM wms.serial s JOIN wms.product p ON p.id=s.product_id
            WHERE s.code=:code AND (CAST(:sku AS text) IS NULL OR upper(p.sku)=upper(:sku)) ORDER BY s.id LIMIT 201"""),
                                             {"code": code.strip(), "sku": sku}).scalars().all()
        result = []
        for serial in candidates:
            try:
                result.append(self.warranty(auth, serial, warehouse_id))
            except DomainError as error:
                if error.code != "NOT_FOUND":
                    raise
        if len(candidates) > 200:
            # Require an explicit SKU for codes reused widely; never expose hidden IDs or counts.
            raise DomainError("REFINE_SEARCH", "Nhập thêm SKU để thu hẹp mã serial.")
        return result

    def record_warranty(self, access, key, serial_id, payload, request_id):
        with self.identity.engine.begin() as connection:
            actor = self.identity.authorization(connection, access).principal.user_id

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            receipt = self.receipt(uow.connection, serial_id, payload.receipt_move_id)
            if not receipt:
                raise DomainError("NOT_FOUND", "Không tìm thấy nguồn nhận đã ghi sổ cho serial.")
            self.warehouse(auth, receipt["warehouse_id"], "serial.read")
            auth.document(receipt["document_id"])
            auth.require("warranty.write", receipt["warehouse_id"])

        def handle(uow):
            connection = uow.connection
            receipt = self.receipt(connection, serial_id, payload.receipt_move_id)
            if not receipt:
                raise DomainError("INVALID_SOURCE", "Nguồn nhận đã bị đảo; tải lại serial.")
            # Same order as future posting: document before serial; recheck reversal after acquiring the locks.
            connection.execute(text("SELECT id FROM wms.document WHERE id=:id FOR SHARE"), {"id": receipt["document_id"]})
            serial = one(connection, "SELECT warranty_version FROM wms.serial WHERE id=:id FOR UPDATE", id=serial_id)
            if not self.receipt(connection, serial_id, payload.receipt_move_id):
                raise DomainError("INVALID_SOURCE", "Nguồn nhận đã bị đảo; tải lại serial.")
            require_version(serial["warranty_version"], payload.expected_version)
            record_id = uuid4()
            revision = serial["warranty_version"] + 1
            now = self.identity.clock()
            connection.execute(text("""INSERT INTO wms.serial_warranty_record
                (id,serial_id,receipt_move_id,revision,starts_on,ends_on,evidence_ref,recorded_by,recorded_at,reason)
                VALUES (:id,:serial,:move,:revision,:start,:end,:evidence,:actor,:now,:reason)"""),
                               {"id": record_id, "serial": serial_id, "move": payload.receipt_move_id, "revision": revision,
                                "start": payload.starts_on, "end": payload.ends_on, "evidence": payload.evidence_ref,
                                "actor": actor, "now": now, "reason": payload.reason})
            connection.execute(text("UPDATE wms.serial SET warranty_version=:version WHERE id=:id"), {"id": serial_id, "version": revision})
            result = WarrantyResult(id=record_id, serial_id=serial_id, version=revision).model_dump(mode="json")
            self.effects(connection, actor, receipt["warehouse_id"], serial_id, result, payload.reason, request_id, now)
            return CommandResult(result, 201)
        return self.bus.execute(actor_id=actor, key=key, command="POST /serials/warranty-records", resource_id=serial_id,
                                payload=payload.model_dump(mode="json"), authorize=authorize, handle=handle)

    def effects(self, connection, actor, warehouse, serial, result, reason, request_id, now):
        connection.execute(text("""INSERT INTO wms.audit_event
            (id,actor_id,warehouse_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
            VALUES (:id,:actor,:warehouse,'serial.warranty.recorded','serial',:serial,:request,:now,CAST(:result AS jsonb),:reason)"""),
                           {"id": uuid4(), "actor": actor, "warehouse": warehouse, "serial": serial,
                            "request": request_id, "now": now, "result": json.dumps(result), "reason": reason})
        connection.execute(text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,'serial.warranty.recorded.v1',:serial,CAST(:result AS jsonb),:now,:now,0)"""),
                           {"id": uuid4(), "serial": serial, "result": json.dumps(result), "now": now})
