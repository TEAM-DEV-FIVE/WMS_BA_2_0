import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.commands import CommandBus, CommandResult
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.database import PostgresUnitOfWork
from packages.contracts.master_data import (
    BarcodeData,
    CategoryData,
    LocationData,
    PartnerData,
    ProductData,
    UomData,
    WarehouseData,
    entity_models,
)
from packages.contracts.traceability import AgreementData, OwnerData


@dataclass(frozen=True)
class Entity:
    table: str
    data: type
    read_permission: str
    write_permission: str

    @property
    def columns(self):
        return ["id", *self.data.model_fields, "version"]


# Identifiers in SQL come only from this registry, never from a request.
ENTITIES = {
    "uoms": Entity("uom", UomData, "master.read", "master.write"),
    "categories": Entity("product_category", CategoryData, "master.read", "master.write"),
    "products": Entity("product", ProductData, "master.read", "master.write"),
    "partners": Entity("partner", PartnerData, "partner.read", "partner.write"),
    "warehouses": Entity("warehouse", WarehouseData, "warehouse.configure", "warehouse.configure"),
    "locations": Entity("location", LocationData, "warehouse.configure", "warehouse.configure"),
    "barcodes": Entity("barcode", BarcodeData, "master.read", "master.write"),
    "stock-owners": Entity("stock_owner", OwnerData, "partner.write", "partner.write"),
    "consignment-agreements": Entity("consignment_agreement", AgreementData, "partner.write", "partner.write"),
}
MODELS = {name: entity_models(entity.data) for name, entity in ENTITIES.items()}
CATALOG_LOCK = 6458301  # Global low-volume catalogue mutation lock; acquired after command-key lock.


def one(connection, sql, **params):
    value = connection.execute(text(sql), params).mappings().one_or_none()
    return dict(value) if value is not None else None


def invalid(field, message, code="INVALID_REFERENCE"):
    raise DomainError(code, message, field=field)


def active_reference(connection, table, value, field):
    result = one(connection, f"SELECT * FROM wms.{table} WHERE id=:id AND is_active FOR SHARE", id=value)
    if result is None:
        invalid(field, "Không tìm thấy danh mục đang hoạt động.")
    return result


def page(connection, sql, params, limit):
    records = [dict(row) for row in connection.execute(text(sql), {**params, "limit": limit + 1}).mappings()]
    return {"items": records[:limit], "next_after": str(records[limit-1]["id"]) if len(records) > limit else None}


class MasterDataService:
    def __init__(self, identity):
        self.identity = identity
        self.bus = CommandBus(lambda: PostgresUnitOfWork(identity.engine))

    def list(self, auth, name, *, after=None, q="", limit=50, active=None, warehouse_id=None):
        entity = ENTITIES[name]
        auth.require(entity.read_permission)
        code = "sku" if name == "products" else "code"
        search = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        predicate = f"({code} COLLATE wms.catalog_unicode ILIKE :q ESCAPE '!'"
        predicate += " OR name COLLATE wms.catalog_unicode ILIKE :q ESCAPE '!')" if "name" in entity.data.model_fields else ")"
        where = ""
        if name == "locations":
            # Virtual/system locations are not user-editable master records.
            where = " AND warehouse_id IS NOT NULL AND (CAST(:warehouse AS uuid) IS NULL OR warehouse_id=:warehouse)"
        return page(auth.connection, f"""SELECT {','.join(entity.columns)} FROM wms.{entity.table}
            WHERE (CAST(:after AS uuid) IS NULL OR id>:after) AND {predicate}
              AND (CAST(:active AS boolean) IS NULL OR is_active=:active) {where}
            ORDER BY id LIMIT :limit""",
                    {"after": after, "q": f"%{search}%", "active": active, "warehouse": warehouse_id}, limit)

    def read(self, auth, name, entity_id):
        entity = ENTITIES[name]
        auth.require(entity.read_permission)
        result = one(auth.connection, f"SELECT {','.join(entity.columns)} FROM wms.{entity.table} WHERE id=:id", id=entity_id)
        if result is None or (name == "locations" and result["warehouse_id"] is None):
            raise DomainError("NOT_FOUND", "Không tìm thấy danh mục.")
        return result

    def command(self, access, key, command, resource_id, payload, permission, handle):
        # Resolve actor; authorization is checked again inside the command transaction, including replay.
        with self.identity.engine.begin() as connection:
            actor = self.identity.authorization(connection, access).principal.user_id

        def authorize(uow):
            auth = self.identity.authorization(uow.connection, access)
            auth.require(permission)

        def execute(uow):
            uow.connection.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": CATALOG_LOCK})
            auth = self.identity.authorization(uow.connection, access)
            auth.require(permission)
            return handle(uow.connection, auth.principal.user_id)

        return self.bus.execute(actor_id=actor, key=key, command=command, resource_id=resource_id,
                                payload=payload, authorize=authorize, handle=execute)

    def write(self, access, key, name, payload, request_id, entity_id=None):
        entity = ENTITIES[name]
        creating = entity_id is None
        body = payload.model_dump(mode="json")

        def handle(connection, actor):
            target = entity_id or uuid4()
            old = None if creating else one(connection, f"SELECT * FROM wms.{entity.table} WHERE id=:id FOR UPDATE", id=target)
            if not creating:
                if old is None or (name == "locations" and old["warehouse_id"] is None):
                    raise DomainError("NOT_FOUND", "Không tìm thấy danh mục.")
                require_version(old["version"], payload.expected_version)
            values = payload.model_dump(include=set(entity.data.model_fields))
            code = "sku" if name == "products" else "code"
            same_code = not old or (values[code] == old[code] if name == "barcodes" else values[code].upper() == old[code].upper())
            if not same_code:
                invalid(code, "Mã định danh không đổi; ngừng dùng bản ghi cũ nếu cần mã mới.", "IMMUTABLE_FIELD")
            if old:
                values[code] = old[code]
                if name == "partners":
                    # Older clients omit these newly exposed import fields; preserve them.
                    for field in ("tax_code", "address"):
                        if field not in payload.model_fields_set:
                            values[field] = old[field]
            equality = "code=:code" if name == "barcodes" else f"upper({code})=upper(:code)"
            if one(connection, f"SELECT id FROM wms.{entity.table} WHERE {equality} AND id<>:id", code=values[code], id=target):
                invalid(code, "Mã đã tồn tại, kể cả danh mục đã ngừng dùng.", "DUPLICATE_CODE")
            self.validate(connection, name, target, values, old)
            values.update(id=target, version=(old["version"] + 1) if old else 1)
            if creating:
                columns = list(values)
                placeholders = [":" + field for field in columns]
                if name == "products":
                    columns.append("attributes")
                    placeholders.append("'{}'::jsonb")
                connection.execute(text(f"INSERT INTO wms.{entity.table} ({','.join(columns)}) VALUES ({','.join(placeholders)})"), values)
            else:
                connection.execute(text(f"UPDATE wms.{entity.table} SET " +
                                        ",".join(f"{field}=:{field}" for field in values if field != "id") + " WHERE id=:id"), values)
            if name == "products" and (creating or values["base_uom_id"] != old["base_uom_id"]):
                # Keep old conversion revisions; active barcodes never silently change pack size.
                self.replace_base_conversion(connection, target, values["base_uom_id"], old)
            result = MODELS[name][2].model_validate(values).model_dump(mode="json")
            self.effects(connection, actor, name, target, result, old, payload.reason, request_id)
            return CommandResult(result, 201 if creating else 200)

        return self.command(access, key, ("POST" if creating else "PUT") + f" /master/{name}",
                            entity_id or UUID(int=0), body, entity.write_permission, handle)

    def validate(self, connection, name, target, values, old):
        if name == "products":
            uom = active_reference(connection, "uom", values["base_uom_id"], "base_uom_id")
            if values["category_id"]:
                active_reference(connection, "product_category", values["category_id"], "category_id")
            if values["tracking"] == "SERIAL" and uom["decimal_places"] != 0:
                invalid("base_uom_id", "Hàng SERIAL cần đơn vị cơ sở nguyên.", "INVALID_UOM")
            if old and any(values[k] != old[k] for k in ["base_uom_id", "tracking", "expiry_required"]):
                for table in ["document_line", "stock_item", "lot", "serial"]:
                    if one(connection, f"SELECT id FROM wms.{table} WHERE product_id=:id LIMIT 1", id=target):
                        invalid("tracking", "Tracking, UOM và quy tắc hạn dùng đã khóa sau phát sinh.", "PRODUCT_IN_USE")
                if values["tracking"] == "SERIAL" and one(connection, """SELECT id FROM wms.product_uom
                    WHERE product_id=:id AND is_active AND factor<>trunc(factor) LIMIT 1""", id=target):
                    invalid("tracking", "Quy đổi SERIAL phải ra số nguyên đơn vị cơ sở.", "INVALID_UOM")
        elif name == "uoms" and old:
            if values["decimal_places"] != old["decimal_places"] or not values["is_active"]:
                if one(connection, """SELECT id FROM wms.product WHERE base_uom_id=:id
                    UNION ALL SELECT product_id FROM wms.product_uom WHERE uom_id=:id LIMIT 1""", id=target):
                    invalid("decimal_places", "Đơn vị đã được tham chiếu; không đổi độ chính xác/ngừng dùng.", "UOM_IN_USE")
        elif name == "categories":
            parent = values["parent_id"]
            seen = {target}
            while parent:
                if parent in seen:
                    invalid("parent_id", "Cây nhóm hàng không được có chu kỳ.", "INVALID_TREE")
                seen.add(parent)
                parent = active_reference(connection, "product_category", parent, "parent_id")["parent_id"]
            if not values["is_active"] and one(connection, """SELECT id FROM wms.product_category WHERE parent_id=:id AND is_active
                UNION ALL SELECT id FROM wms.product WHERE category_id=:id AND is_active LIMIT 1""", id=target):
                invalid("is_active", "Nhóm còn danh mục đang dùng.", "CATEGORY_IN_USE")
        elif name == "barcodes":
            if old and values["product_uom_id"] != old["product_uom_id"]:
                invalid("product_uom_id", "Barcode không được gán lại quy cách/SKU.", "IMMUTABLE_FIELD")
            if values["is_active"]:
                conversion = active_reference(connection, "product_uom", values["product_uom_id"], "product_uom_id")
                active_reference(connection, "product", conversion["product_id"], "product_uom_id")
                active_reference(connection, "uom", conversion["uom_id"], "product_uom_id")
        elif name == "warehouses" and not values["is_active"]:
            if one(connection, "SELECT id FROM wms.location WHERE warehouse_id=:id AND is_active LIMIT 1", id=target):
                invalid("is_active", "Kho còn vị trí đang hoạt động.", "WAREHOUSE_IN_USE")
        elif name == "stock-owners":
            if values["kind"] != "CONSIGNOR" or values["partner_id"] is None:
                invalid("kind", "Chỉ được tạo/sửa chủ hàng ký gửi; danh tính hệ thống không thay đổi.")
            if old and (old["partner_id"], old["kind"]) != (values["partner_id"], values["kind"]):
                invalid("partner_id", "Không đổi danh tính chủ hàng.", "IMMUTABLE_FIELD")
            partner = active_reference(connection, "partner", values["partner_id"], "partner_id")
            if not partner["is_supplier"]:
                invalid("partner_id", "Chủ hàng ký gửi phải gắn nhà cung cấp.")
            if one(connection, "SELECT id FROM wms.stock_owner WHERE partner_id=:partner AND id<>:id",
                   partner=values["partner_id"], id=target):
                invalid("partner_id", "Đối tác đã có danh tính chủ hàng.", "DUPLICATE_OWNER")
        elif name == "consignment-agreements":
            owner = active_reference(connection, "stock_owner", values["owner_id"], "owner_id")
            if owner["kind"] != "CONSIGNOR":
                invalid("owner_id", "Hợp đồng cần chủ hàng ký gửi.")
            active_reference(connection, "warehouse", values["warehouse_id"], "warehouse_id")
            if old and any(old[k] != values[k] for k in ["owner_id", "warehouse_id", "valid_from", "valid_until", "source_ref"]):
                if one(connection, """SELECT id FROM wms.stock_item WHERE consignment_id=:id
                    UNION ALL SELECT id FROM wms.document_line WHERE consignment_id=:id LIMIT 1""", id=target):
                    invalid("owner_id", "Hợp đồng đã dùng; tạo hợp đồng mới để thay điều khoản.", "AGREEMENT_IN_USE")
        elif name == "locations":
            self.validate_location(connection, target, values, old)

    def validate_location(self, connection, target, values, old):
        active_reference(connection, "warehouse", values["warehouse_id"], "warehouse_id")
        if old and old["warehouse_id"] != values["warehouse_id"]:
            invalid("warehouse_id", "Không chuyển vị trí sang kho khác.", "IMMUTABLE_FIELD")
        parents, parent_id, seen = [], values["parent_id"], {target}
        while parent_id:
            if parent_id in seen:
                invalid("parent_id", "Cây vị trí không được có chu kỳ.", "INVALID_TREE")
            seen.add(parent_id)
            parent = active_reference(connection, "location", parent_id, "parent_id")
            if parent["warehouse_id"] != values["warehouse_id"] or parent["kind"] != "GROUP":
                invalid("parent_id", "Vị trí cha phải là nhóm trong cùng kho.", "INVALID_TREE")
            parents.append(parent)
            parent_id = parent["parent_id"]
        depth = len(parents)
        if ((values["kind"] == "GROUP" and depth > 1) or
                (values["kind"] == "STORAGE" and depth != 2) or
                (values["kind"] not in {"GROUP", "STORAGE"} and depth > 1)):
            invalid("parent_id", "Cây lưu trữ phải theo Kho → Zone → Rack → Bin; khu vận hành ở kho/zone.", "INVALID_TREE")
        structural_change = old and any(old[k] != values[k] for k in ["parent_id", "kind"])
        if old and (structural_change or not values["is_active"]):
            child_filter = "" if structural_change else " AND is_active"
            if one(connection, "SELECT id FROM wms.location WHERE parent_id=:id" + child_filter + " LIMIT 1", id=target):
                invalid("parent_id", "Vị trí còn con; chuyển/ngừng từng vị trí con trước.", "LOCATION_IN_USE")
            used = one(connection, """SELECT id FROM wms.stock_move WHERE :structural AND (source_location_id=:id OR destination_location_id=:id)
                UNION ALL SELECT id FROM wms.stock_balance WHERE location_id=:id AND (on_hand>0 OR reserved>0)
                UNION ALL SELECT id FROM wms.reservation WHERE location_id=:id AND quantity>consumed+released
                UNION ALL SELECT id FROM wms.count_location_lock WHERE location_id=:id AND released_at IS NULL LIMIT 1""", id=target, structural=bool(structural_change))
            if used:
                invalid("kind", "Vị trí đã có phát sinh/tồn/giữ chỗ/khóa kiểm kê.", "LOCATION_IN_USE")

    def replace_base_conversion(self, connection, product, base_uom, old):
        if old:
            connection.execute(text("""UPDATE wms.barcode SET is_active=false,version=version+1
                WHERE is_active AND product_uom_id IN (SELECT id FROM wms.product_uom WHERE product_id=:product)"""), {"product": product})
            connection.execute(text("UPDATE wms.product_uom SET is_active=false WHERE product_id=:product"), {"product": product})
        revision = connection.execute(text("SELECT COALESCE(max(revision),0)+1 FROM wms.product_uom WHERE product_id=:product AND uom_id=:uom"),
                                      {"product": product, "uom": base_uom}).scalar_one()
        connection.execute(text("""INSERT INTO wms.product_uom(id,product_id,uom_id,factor,revision,is_active)
            VALUES (:id,:product,:uom,1,:revision,true)"""), {"id": uuid4(), "product": product, "uom": base_uom, "revision": revision})

    def conversion(self, access, key, payload, request_id):
        def handle(connection, actor):
            product = one(connection, "SELECT * FROM wms.product WHERE id=:id AND is_active FOR UPDATE", id=payload.product_id)
            if not product:
                invalid("product_id", "Không tìm thấy SKU đang hoạt động.")
            require_version(product["version"], payload.expected_product_version)
            active_reference(connection, "uom", payload.uom_id, "uom_id")
            factor = Decimal(payload.factor)
            if product["base_uom_id"] == payload.uom_id and factor != 1:
                invalid("factor", "Đơn vị cơ sở phải có hệ số 1.", "INVALID_UOM")
            if product["tracking"] == "SERIAL" and factor != factor.to_integral_value():
                invalid("factor", "Quy đổi SERIAL phải ra số nguyên đơn vị cơ sở.", "INVALID_UOM")
            previous = one(connection, "SELECT * FROM wms.product_uom WHERE product_id=:product AND uom_id=:uom ORDER BY revision DESC LIMIT 1",
                           product=payload.product_id, uom=payload.uom_id)
            if previous:
                connection.execute(text("UPDATE wms.product_uom SET is_active=false WHERE product_id=:product AND uom_id=:uom"),
                                   {"product": payload.product_id, "uom": payload.uom_id})
                connection.execute(text("""UPDATE wms.barcode SET is_active=false,version=version+1
                    WHERE is_active AND product_uom_id IN (SELECT id FROM wms.product_uom WHERE product_id=:product AND uom_id=:uom)"""),
                                   {"product": payload.product_id, "uom": payload.uom_id})
            result = {"id": str(uuid4()), "product_id": str(payload.product_id), "uom_id": str(payload.uom_id),
                      "factor": payload.factor, "revision": previous["revision"] + 1 if previous else 1, "is_active": True}
            connection.execute(text("""INSERT INTO wms.product_uom(id,product_id,uom_id,factor,revision,is_active)
                VALUES (:id,:product_id,:uom_id,:factor,:revision,:is_active)"""), result)
            connection.execute(text("UPDATE wms.product SET version=version+1 WHERE id=:id"), {"id": payload.product_id})
            self.effects(connection, actor, "product-uoms", result["id"], result, previous, payload.reason, request_id)
            return CommandResult(result, 201)
        return self.command(access, key, "POST /master/product-uoms", payload.product_id,
                            payload.model_dump(mode="json"), "master.write", handle)

    def price(self, access, key, product_id, payload, request_id):
        def handle(connection, actor):
            active_reference(connection, "product", product_id, "product_id")
            if one(connection, "SELECT id FROM wms.reference_price WHERE product_id=:id AND effective_on=:day", id=product_id, day=payload.effective_on):
                invalid("effective_on", "Đã có giá tại ngày hiệu lực này.", "DUPLICATE_PRICE")
            result = {"id": str(uuid4()), "product_id": str(product_id), **payload.model_dump(mode="json")}
            connection.execute(text("""INSERT INTO wms.reference_price(id,product_id,effective_on,amount,currency,source,created_by)
                VALUES (:id,:product_id,:effective_on,:amount,:currency,:source,:actor)"""), {**result, "actor": actor})
            self.effects(connection, actor, "reference-prices", result["id"], result, None, payload.source, request_id)
            # A writer need not have price.read; mutation acknowledgement doesn't reveal a stored price.
            return CommandResult({"id": result["id"], "status": "CREATED"}, 201)
        return self.command(access, key, "POST /master/products/prices", product_id,
                            payload.model_dump(mode="json"), "price.write", handle)

    def effects(self, connection, actor, name, target, after, before, reason, request_id):
        now = self.identity.clock()
        action = f"master.{name}.{'updated' if before else 'created'}"
        connection.execute(text("""INSERT INTO wms.audit_event
            (id,actor_id,action,entity_type,entity_id,before_data,after_data,reason,request_id,occurred_at)
            VALUES (:id,:actor,:action,:entity,:target,CAST(:before AS jsonb),CAST(:after AS jsonb),:reason,:request,:now)"""),
                           {"id": uuid4(), "actor": actor, "action": action, "entity": name, "target": target,
                            "before": json.dumps(before, default=str) if before else None, "after": json.dumps(after),
                            "reason": reason, "request": request_id, "now": now})
        connection.execute(text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,:event,:target,CAST(:payload AS jsonb),:now,:now,0)"""),
                           {"id": uuid4(), "event": action + ".v1", "target": target, "now": now,
                            "payload": json.dumps({"id": str(target), "version": after.get("version"), "request_id": str(request_id)})})
