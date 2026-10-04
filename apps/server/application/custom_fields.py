"""Descriptive metadata: immutable schemas, explicit migration, live object authorization."""

import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import text

from apps.server.application.commands import CommandResult
from apps.server.application.master_data import CATALOG_LOCK, one
from apps.server.domain.errors import DomainError, require_version
from packages.contracts.custom_fields import FieldDefinition, validate_value

SCHEMA_LOCK = 707025


def encode(value):
    return json.dumps(value, default=str, ensure_ascii=False, allow_nan=False)


def schema(connection, entity_type=None, revision_id=None):
    revision = one(connection, """SELECT r.id AS revision_id,s.entity_type,r.version
        FROM wms.custom_field_revision r JOIN wms.custom_field_schema s ON s.id=r.schema_id
        WHERE (CAST(:entity AS text) IS NULL OR s.entity_type=:entity)
          AND (CAST(:revision AS uuid) IS NULL OR r.id=:revision)
        ORDER BY r.version DESC LIMIT 1""", entity=entity_type, revision=revision_id)
    if not revision:
        if revision_id:
            raise DomainError("NOT_FOUND", "Không tìm thấy phiên bản bộ trường.")
        return dict(entity_type=entity_type, revision_id=None, version=0, fields=[])
    fields = connection.execute(text("""SELECT code,label,value_type,required,visibility,validation
        FROM wms.custom_field_definition WHERE revision_id=:id ORDER BY code"""),
        {"id": revision["revision_id"]}).mappings().all()
    return {**dict(revision), "fields": [dict(f) for f in fields]}


def binding(connection, target_type, target_id):
    column = "product_id" if target_type == "products" else "document_id"
    return one(connection, f"SELECT * FROM wms.custom_field_binding WHERE {column}=:id", id=target_id)


def snapshot(connection, doc_id):
    saved = binding(connection, "documents", doc_id)
    if not saved:
        # Preserve the exact approval snapshot of documents predating B07.
        return {}
    return {"custom_fields": {"schema": schema(connection, revision_id=saved["revision_id"]), "values": saved["values"]}}


class CustomFieldService:
    def __init__(self, orders):
        self.orders, self.identity, self.bus = orders, orders.identity, orders.bus

    def schema_read(self, auth, entity_type):
        auth.require("config.manage")
        return schema(auth.connection, entity_type)

    def effects(self, c, actor, target, warehouse, action, result, reason, request_id):
        now = self.identity.clock()
        c.execute(text("""INSERT INTO wms.audit_event
            (id,actor_id,warehouse_id,action,entity_type,entity_id,request_id,occurred_at,after_data,reason)
            VALUES (:id,:actor,:warehouse,:action,'custom_field',:target,:request,:now,CAST(:data AS jsonb),:reason)"""),
            dict(id=uuid4(), actor=actor, warehouse=warehouse, action=action, target=target,
                 request=request_id, now=now, data=encode(result), reason=reason))
        c.execute(text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,:event,:target,CAST(:data AS jsonb),:now,:now,0)"""),
            dict(id=uuid4(), event=action+".v1", target=target, data=encode(result), now=now))

    def command(self, access, key, name, target, payload, authorize, handle):
        with self.identity.engine.connect() as c:
            actor = self.identity.authenticate(c, access).user_id
        context = {}

        def check(uow):
            auth = self.identity.authorization(uow.connection, access)
            authorize(auth)
            context["auth"] = auth

        return self.bus.execute(actor_id=actor, key=key, command=name, resource_id=target,
            payload=payload.model_dump(mode="json"), authorize=check,
            handle=lambda uow: handle(context["auth"]))

    def publish(self, access, key, entity_type, payload, request_id):
        target = uuid5(NAMESPACE_URL, "wms.custom-fields." + entity_type)

        def handle(auth):
            c = auth.connection
            c.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK})
            current = schema(c, entity_type)
            require_version(current["version"], payload.expected_version)
            # Legacy rows have no provenance/version. Never silently reclassify them.
            if one(c, "SELECT id FROM wms.custom_field_definition WHERE entity_type=:entity AND revision_id IS NULL LIMIT 1", entity=entity_type):
                raise DomainError("LEGACY_CUSTOM_FIELDS", "Cần đối soát definition cũ trước khi tạo bộ trường có phiên bản.")
            private = self.price_codes(c, entity_type)
            if any(f.code in private and f.visibility != "PRICE" for f in payload.fields):
                raise DomainError("FORBIDDEN", "Không được hạ quyền trường đã phân loại giá.")
            version, revision = current["version"] + 1, uuid4()
            c.execute(text("""INSERT INTO wms.custom_field_schema(id,entity_type,version) VALUES (:id,:entity,:version)
                ON CONFLICT(entity_type) DO UPDATE SET version=EXCLUDED.version"""),
                dict(id=target, entity=entity_type, version=version))
            c.execute(text("""INSERT INTO wms.custom_field_revision(id,schema_id,version,created_by,created_at,reason)
                VALUES (:id,:schema,:version,:actor,:now,:reason)"""), dict(id=revision, schema=target, version=version,
                    actor=auth.principal.user_id, now=self.identity.clock(), reason=payload.reason))
            for field in payload.fields:
                c.execute(text("""INSERT INTO wms.custom_field_definition
                    (id,entity_type,code,value_type,required,validation,is_active,revision_id,label,visibility)
                    VALUES (:id,:entity,:code,:value_type,:required,CAST(:validation AS jsonb),true,:revision,:label,:visibility)"""),
                    {**field.model_dump(exclude={"validation"}), "id": uuid4(), "entity": entity_type,
                     "validation": encode(field.validation.model_dump()), "revision": revision})
            result = dict(id=str(target), version=version, revision_id=str(revision), request_id=str(request_id))
            self.effects(c, auth.principal.user_id, target, None, "custom_field.schema.published", result, payload.reason, request_id)
            return CommandResult(result)

        return self.command(access, key, "custom_field.schema."+entity_type, target, payload,
                            lambda auth: auth.require("config.manage"), handle)

    @staticmethod
    def price_codes(c, entity_type):
        return set(c.execute(text("""SELECT DISTINCT code FROM wms.custom_field_definition
            WHERE entity_type=:entity AND visibility='PRICE' AND revision_id IS NOT NULL"""),
            {"entity": entity_type}).scalars())

    def target(self, auth, target_type, target_id, *, lock=False, write=False):
        c = auth.connection
        if target_type == "products":
            auth.require("master.read", hidden=True)
            if write:
                auth.require("master.write")
            if lock:
                c.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_LOCK})
            product = one(c, "SELECT * FROM wms.product WHERE id=:id" + (" FOR UPDATE" if lock else ""), id=target_id)
            if not product:
                raise DomainError("NOT_FOUND", "Không tìm thấy sản phẩm.")
            return {**dict(product), "kind": "PRODUCT", "warehouse_id": None}
        doc = self.orders.document(auth, target_id, lock=lock)
        if write:
            self.orders.may_edit(auth, doc)
        return doc

    def price_read(self, auth, doc, warehouse):
        warehouses = [doc["warehouse_id"] or warehouse]
        if doc["kind"] == "ADJUSTMENT":
            parent = self.orders.transfers.loss_parent(auth, doc)[0]
            warehouses = [parent["warehouse_id"], parent["destination_warehouse_id"]]
        elif doc["kind"] == "REVERSAL":
            warehouses = self.orders.reversals.scope(auth, doc)
        elif doc.get("destination_warehouse_id"):
            warehouses.append(doc["destination_warehouse_id"])
        return all(w and auth.allows("price.read", w) for w in warehouses)

    def project(self, auth, doc, definition, values, warehouse):
        private = self.price_codes(auth.connection, doc["kind"])
        allowed = {f["code"] for f in definition["fields"] if f["code"] not in private or self.price_read(auth, doc, warehouse)}
        return ({**definition, "fields": [{**f, "visibility": "PRICE" if f["code"] in private else "BUSINESS"} for f in definition["fields"] if f["code"] in allowed]},
                {k: v for k, v in values.items() if k in allowed})

    def read(self, auth, target_type, target_id, warehouse=None, latest=False):
        doc = self.target(auth, target_type, target_id)
        saved = binding(auth.connection, target_type, target_id)
        definition = schema(auth.connection, doc["kind"], None if latest or not saved else saved["revision_id"])
        projected, values = self.project(auth, doc, definition, saved["values"] if saved else {}, warehouse)
        editable = True
        try:
            self.target(auth, target_type, target_id, write=True)
            if target_type == "documents" and doc["status"] not in {"DRAFT", "REJECTED"}:
                editable = False
        except DomainError:
            editable = False
        return dict(target_type=target_type, id=target_id, version=doc["version"], warehouse_id=doc["warehouse_id"],
                    revision_id=saved["revision_id"] if saved else None, schema=projected, values=values,
                    editable=editable, can_write_price=self.price_read(auth, doc, warehouse) and auth.allows("price.write"))

    def history(self, auth, target_type, target_id, warehouse=None, before=None, limit=50):
        doc = self.target(auth, target_type, target_id)
        saved = binding(auth.connection, target_type, target_id)
        if not saved:
            return dict(items=[], next_before=None)
        rows = auth.connection.execute(text("""SELECT * FROM wms.custom_field_change WHERE binding_id=:id
            AND (CAST(:before AS integer) IS NULL OR target_version<:before) ORDER BY target_version DESC LIMIT :limit"""),
            dict(id=saved["id"], before=before, limit=limit+1)).mappings().all()
        items = []
        for row in rows[:limit]:
            definition, values = self.project(auth, doc, schema(auth.connection, revision_id=row["revision_id"]), row["values"], warehouse)
            items.append(dict(target_version=row["target_version"], revision_id=row["revision_id"], schema=definition, values=values))
        return dict(items=items, next_before=items[-1]["target_version"] if len(rows)>limit else None)

    @staticmethod
    def validate(definition, values):
        fields = {f["code"]: FieldDefinition.model_validate(f) for f in definition["fields"]}
        if set(values) - fields.keys():
            raise DomainError("INVALID_CUSTOM_FIELDS", "Có trường không thuộc phiên bản bộ trường.")
        for code, field in fields.items():
            try:
                validate_value(field, values.get(code))
            except (ValueError, TypeError):
                # A generic error also prevents revealing hidden required fields.
                raise DomainError("INVALID_CUSTOM_FIELDS", "Thiếu trường bắt buộc hoặc giá trị không đúng kiểu/ràng buộc.") from None

    def save(self, auth, target_type, doc, saved, definition, values, target_version, reason):
        c, record_id = auth.connection, saved["id"] if saved else uuid4()
        column = "product_id" if target_type == "products" else "document_id"
        c.execute(text(f"""INSERT INTO wms.custom_field_binding(id,{column},revision_id,values)
            VALUES (:id,:target,:revision,CAST(:values AS jsonb)) ON CONFLICT ({column})
            DO UPDATE SET revision_id=EXCLUDED.revision_id,values=EXCLUDED.values"""),
            dict(id=record_id, target=doc["id"], revision=definition["revision_id"], values=encode(values)))
        c.execute(text("""INSERT INTO wms.custom_field_change
            (id,binding_id,revision_id,target_version,values,changed_by,changed_at,reason)
            VALUES (:id,:binding,:revision,:version,CAST(:values AS jsonb),:actor,:now,:reason)"""),
            dict(id=uuid4(), binding=record_id, revision=definition["revision_id"], version=target_version,
                 values=encode(values), actor=auth.principal.user_id, now=self.identity.clock(), reason=reason))

    def prepare(self, auth, target_type, target_id, payload, warehouse, *, lock=False):
        doc = self.target(auth, target_type, target_id, lock=lock, write=True)
        if target_type == "documents" and doc["status"] not in {"DRAFT", "REJECTED"}:
            raise DomainError("INVALID_STATE", "Chỉ sửa trường mở rộng trên bản nháp; dùng quy trình sửa lại chứng từ đã duyệt.")
        require_version(doc["version"], payload.expected_version)
        if lock:
            auth.connection.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": SCHEMA_LOCK})
        saved = binding(auth.connection, target_type, target_id)
        if (saved["revision_id"] if saved else None) != payload.expected_revision_id:
            raise DomainError("STALE_VERSION", "Phiên bản bộ trường gắn với đối tượng đã đổi.")
        definition = schema(auth.connection, doc["kind"], payload.revision_id)
        current = schema(auth.connection, doc["kind"])
        if payload.revision_id != (saved["revision_id"] if saved else None) and payload.revision_id != current["revision_id"]:
            raise DomainError("STALE_VERSION", "Chỉ được chuyển sang bộ trường mới nhất.")
        old_values = saved["values"] if saved else {}
        upgrading = saved and saved["revision_id"] != payload.revision_id
        private = self.price_codes(auth.connection, doc["kind"])
        touched = set(payload.values) | (set(old_values) if upgrading else set())
        if touched & private and not (self.price_read(auth, doc, warehouse) and auth.allows("price.write")):
            raise DomainError("FORBIDDEN", "Không có quyền thay đổi trường giá.")
        codes = {f["code"] for f in definition["fields"]}
        values = {k: v for k, v in old_values.items() if k in codes}
        values.update(payload.values)
        self.validate(definition, values)
        return doc, saved, definition, {k: v for k, v in values.items() if v is not None}

    def preview(self, auth, target_type, target_id, payload, warehouse=None):
        # The import contract is this exact typed command. Preview is never an authorization token.
        doc, saved, definition, values = self.prepare(auth, target_type, target_id, payload, warehouse)
        projected, values = self.project(auth, doc, definition, values, warehouse)
        return dict(target_type=target_type, id=target_id, version=doc["version"], warehouse_id=doc["warehouse_id"],
                    revision_id=saved["revision_id"] if saved else None, schema=projected, values=values,
                    editable=True, can_write_price=self.price_read(auth, doc, warehouse) and auth.allows("price.write"))

    def write(self, access, key, target_type, target_id, payload, request_id, warehouse=None):
        def authorize(auth):
            doc = self.target(auth, target_type, target_id, write=True)
            private = self.price_codes(auth.connection, doc["kind"])
            # Replay must not return an ACK after price access has been revoked.
            touched = set(payload.values)
            if payload.expected_revision_id and payload.expected_revision_id != payload.revision_id:
                previous = schema(auth.connection, doc["kind"], payload.expected_revision_id)
                touched.update(f["code"] for f in previous["fields"])
            if touched & private and not (self.price_read(auth, doc, warehouse) and auth.allows("price.write")):
                raise DomainError("FORBIDDEN", "Không có quyền thay đổi trường giá.")

        def handle(auth):
            c = auth.connection
            doc, saved, definition, values = self.prepare(auth, target_type, target_id, payload, warehouse, lock=True)
            if target_type == "documents":
                self.orders.no_dependencies(c, target_id, edit=True)
                self.orders.invalidate(c, target_id)
            self.save(auth, target_type, doc, saved, definition, values, doc["version"]+1, payload.reason)
            table = "product" if target_type == "products" else "document"
            state = ",status='DRAFT'" if target_type == "documents" else ""
            c.execute(text(f"UPDATE wms.{table} SET version=version+1{state} WHERE id=:id"), {"id": target_id})
            result = dict(id=str(target_id), version=doc["version"]+1, revision_id=str(payload.revision_id), request_id=str(request_id))
            self.effects(c, auth.principal.user_id, target_id, doc["warehouse_id"], "custom_field.values.updated", result, payload.reason, request_id)
            return CommandResult(result)

        # Include the optional price scope in the command identity/hash.
        return self.command(access, key, f"custom_field.{target_type}.{warehouse}", target_id, payload, authorize, handle)

    def pin_for_submit(self, auth, doc, reason):
        c = auth.connection
        c.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": SCHEMA_LOCK})
        saved = binding(c, "documents", doc["id"])
        definition = schema(c, doc["kind"], saved["revision_id"] if saved else None)
        if not definition["revision_id"]:
            return
        values = saved["values"] if saved else {}
        self.validate(definition, values)
        if not saved:
            self.save(auth, "documents", doc, None, definition, values, doc["version"]+1, reason)
