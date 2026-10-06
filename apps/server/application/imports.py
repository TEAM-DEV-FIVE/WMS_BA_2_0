"""Private files and atomic, explicitly confirmed import commands."""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandBus, CommandResult
from apps.server.application.import_targets import MAPPING_VERSION, ImportTargets, check_snapshot, digest
from apps.server.application.master_data import one
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.database import PostgresUnitOfWork
from apps.server.infrastructure.file_storage import FileStorage, safe_name
from packages.contracts.imports import FileView, ImportView

SCOPED = {"04_locations", "11_opening", "12_open_orders"}
PERMISSION = {
    "03_warehouses": "warehouse.configure",
    "04_locations": "warehouse.configure",
    "08_partners": "partner.write",
    "14_prices": "price.write",
}


def authorize_kind(auth, kind, warehouse):
    if (kind in SCOPED) != (warehouse is not None):
        raise DomainError("INVALID_SCOPE", "Loại import cần đúng phạm vi kho hoặc danh mục toàn hệ thống.")
    if warehouse:
        auth.require("document.read", warehouse, hidden=True)
        if not one(auth.connection, "SELECT id FROM wms.warehouse WHERE id=:id AND is_active", id=warehouse):
            raise DomainError("NOT_FOUND", "Không tìm thấy kho đang hoạt động.")
    if kind == "11_opening":
        auth.require("opening.draft", warehouse)
    elif kind == "12_open_orders":
        # Actual PO/SO permission is checked per group by OrderService as well.
        if not any(auth.allows(p, warehouse) for p in ["po.draft", "so.draft"]):
            raise DomainError("FORBIDDEN", "Cần quyền lập PO hoặc SO tại kho.")
    else:
        auth.require(PERMISSION.get(kind, "master.write"))


def job_authorization(identity, connection, job):
    user = one(connection, "SELECT * FROM wms.app_user WHERE id=:id FOR SHARE", id=job["requested_by"])
    if not user or not user["is_active"] or user["auth_version"] != job["auth_version"]:
        raise DomainError("FORBIDDEN", "Danh tính của người yêu cầu đã bị thu hồi; cần chạy lại dry-run.")
    principal = Principal(user["id"], UUID(int=0), user["username"], user["display_name"], None)
    auth = Authorization(connection, principal, identity.clock())
    authorize_kind(auth, job["kind"], job["warehouse_id"])
    return auth


def stage_digest(job, rows, snapshots):
    return digest(
        [
            job["file_hash"],
            job["kind"],
            job["mapping_version"],
            job["options"],
            job["generation"],
            job["auth_version"],
            rows,
            snapshots,
        ]
    )


class ImportService:
    def __init__(self, identity, storage=None):
        self.identity = identity
        self.storage = storage or FileStorage()
        self.bus = CommandBus(lambda: PostgresUnitOfWork(identity.engine))

    def file(self, auth, file_id):
        row = one(
            auth.connection,
            """SELECT f.*,i.kind,i.warehouse_id,i.ready FROM wms.stored_file f
            JOIN wms.import_file i ON i.file_id=f.id WHERE f.id=:id AND i.actor_id=:actor""",
            id=file_id,
            actor=auth.principal.user_id,
        )
        if not row:
            raise DomainError("NOT_FOUND", "Không tìm thấy tệp của bạn.")
        authorize_kind(auth, row["kind"], row["warehouse_id"])
        if row["kind"] == "12_open_orders":
            kinds = auth.connection.execute(
                text("""SELECT DISTINCT r.payload->>'kind' FROM wms.import_row r
                JOIN wms.import_job j ON j.id=r.job_id WHERE j.file_id=:file"""),
                {"file": file_id},
            ).scalars()
            for kind in kinds:
                if kind in {"PO", "SO"}:
                    auth.require({"PO": "po.draft", "SO": "so.draft"}[kind], row["warehouse_id"])
        return row

    def job(self, auth, job_id, *, lock=False):
        row = one(
            auth.connection,
            "SELECT * FROM wms.import_job WHERE id=:id AND requested_by=:actor"
            + (" FOR UPDATE" if lock else ""),
            id=job_id,
            actor=auth.principal.user_id,
        )
        if not row or row["auth_version"] is None:
            raise DomainError("NOT_FOUND", "Không tìm thấy import của bạn.")
        authorize_kind(auth, row["kind"], row["warehouse_id"])
        self.file(auth, row["file_id"])
        return row

    def history(self, auth, kind, warehouse_id=None, **filters):
        from apps.server.application.job_history import history_page

        authorize_kind(auth, kind, warehouse_id)
        return history_page(auth, "import_job",
            "kind=:kind AND warehouse_id IS NOT DISTINCT FROM CAST(:warehouse AS uuid) AND auth_version IS NOT NULL",
            dict(kind=kind, warehouse=warehouse_id), lambda j: self.job(auth, j["id"]),
            lambda j: dict(id=j["id"], kind=j["kind"], status=j["status"], created_at=j["created_at"]), **filters)

    def read(self, auth, job_id):
        job = self.job(auth, job_id)
        return ImportView.model_validate({k: job[k] for k in ImportView.model_fields})

    @staticmethod
    def file_view(file):
        return FileView.model_validate({k: file[k] for k in FileView.model_fields})

    def rows(self, auth, job_id, after, limit):
        self.job(auth, job_id)
        rows = [
            dict(r)
            for r in auth.connection.execute(
                text("""SELECT row_no,payload,errors,target_id,status
            FROM wms.import_row WHERE job_id=:id AND row_no>:after ORDER BY row_no LIMIT :limit"""),
                dict(id=job_id, after=after, limit=limit + 1),
            ).mappings()
        ]
        return dict(items=rows[:limit], next_after=rows[limit - 1]["row_no"] if len(rows) > limit else None)

    def effects(self, c, actor, target, action, request_id, reason, payload=None):
        payload = payload or dict(id=str(target))
        c.execute(
            text("""INSERT INTO wms.audit_event
            (id,actor_id,action,entity_type,entity_id,after_data,reason,request_id,occurred_at)
            VALUES (:id,:actor,:action,'import',:target,CAST(:payload AS jsonb),:reason,:request,:now)"""),
            dict(
                id=uuid4(),
                actor=actor,
                action=action,
                target=target,
                payload=json.dumps(payload),
                reason=reason,
                request=request_id,
                now=self.identity.clock(),
            ),
        )
        c.execute(
            text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,:event,:target,CAST(:payload AS jsonb),:now,:now,0)"""),
            dict(
                id=uuid4(),
                event=action + ".v1",
                target=target,
                payload=json.dumps(payload),
                now=self.identity.clock(),
            ),
        )

    def command(self, access, key, command, resource, body, authorize, handler):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id

        def check(uow):
            authorize(self.identity.authorization(uow.connection, access))

        def handle(uow):
            return handler(self.identity.authorization(uow.connection, access))

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command=command,
            resource_id=resource,
            payload=body,
            authorize=check,
            handle=handle,
        )

    def upload(self, access, key, kind, warehouse, name, data, request_id):
        safe_name(name)
        if not data or len(data) > self.storage.settings.max_file_bytes:
            raise DomainError("FILE_LIMIT", "Tệp rỗng hoặc vượt hạn mức upload.")
        if name.lower().endswith(".xlsx") != data.startswith(b"PK"):
            raise DomainError("INVALID_FILE", "Nội dung không khớp định dạng CSV/XLSX trong tên tệp.")
        sha = hashlib.sha256(data).hexdigest()
        body = dict(
            kind=kind, warehouse=str(warehouse) if warehouse else None, name=name, sha256=sha, size=len(data)
        )
        request_hash = digest(body)
        # Durable reservation is counted in quota, even when upload dies before finalization.
        # Same actor/key/hash resumes this reservation and uses the same immutable object.
        with self.identity.engine.begin() as c:
            auth = self.identity.authorization(c, access)
            authorize_kind(auth, kind, warehouse)
            actor = auth.principal.user_id
            c.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(hashlib.sha256(f"upload:{actor}".encode()).digest()[:8], signed=True)},
            )
            existing = one(
                c,
                "SELECT * FROM wms.import_file WHERE actor_id=:actor AND upload_key=:key",
                actor=actor,
                key=key,
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    raise DomainError("IDEMPOTENCY_MISMATCH", "Key upload đã dùng với tệp khác.")
                file = self.file(auth, existing["file_id"])
            else:
                usage = one(
                    c,
                    "SELECT count(*) AS count,COALESCE(sum(size_bytes),0) AS bytes FROM wms.stored_file WHERE uploaded_by=:actor",
                    actor=actor,
                )
                settings = self.storage.settings
                if (
                    usage["count"] >= settings.max_user_files
                    or usage["bytes"] + len(data) > settings.max_user_bytes
                ):
                    raise DomainError(
                        "FILE_QUOTA", "Đã hết hạn mức lưu tệp của người dùng; liên hệ quản trị."
                    )
                file_id, storage_key = uuid4(), hashlib.sha256(uuid4().bytes).hexdigest()
                mime = (
                    "text/csv"
                    if name.lower().endswith(".csv")
                    else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                c.execute(
                    text("""INSERT INTO wms.stored_file
                    (id,storage_key,original_name,mime_type,sha256,size_bytes,uploaded_by,created_at)
                    VALUES (:id,:storage,:name,:mime,:hash,:size,:actor,:now)"""),
                    dict(
                        id=file_id,
                        storage=storage_key,
                        name=name,
                        mime=mime,
                        hash=sha,
                        size=len(data),
                        actor=actor,
                        now=self.identity.clock(),
                    ),
                )
                c.execute(
                    text("""INSERT INTO wms.import_file(file_id,actor_id,warehouse_id,kind,upload_key,request_hash)
                    VALUES (:id,:actor,:warehouse,:kind,:key,:hash)"""),
                    dict(id=file_id, actor=actor, warehouse=warehouse, kind=kind, key=key, hash=request_hash),
                )
                file = self.file(auth, file_id)
        self.storage.put(data, sha, file["storage_key"])  # File I/O is outside every command transaction.

        def handle(auth):
            c = auth.connection
            c.execute(text("UPDATE wms.import_file SET ready=true WHERE file_id=:id"), {"id": file["id"]})
            result = self.file_view(self.file(auth, file["id"])).model_dump(mode="json")
            self.effects(
                c,
                actor,
                file["id"],
                "import.file.uploaded",
                request_id,
                "Tải tệp nhập liệu",
                dict(id=str(file["id"]), sha256=sha),
            )
            return CommandResult(result, 201)

        return self.command(
            access, key, "POST /files", UUID(int=0), body, lambda auth: self.file(auth, file["id"]), handle
        )

    def create(self, access, key, payload, request_id):
        def handle(auth):
            c = auth.connection
            file = self.file(auth, payload.file_id)
            if not file["ready"]:
                raise DomainError("FILE_UNAVAILABLE", "Upload chưa hoàn tất; gửi lại cùng key.")
            if file["kind"] == "11_opening" and not payload.signed_count_reference:
                raise DomainError(
                    "SIGNED_COUNT_REQUIRED", "Tồn đầu kỳ cần tham chiếu biên bản kiểm đếm đã ký."
                )
            options = payload.model_dump(mode="json", exclude={"file_id"})
            c.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {
                    "key": int.from_bytes(
                        hashlib.sha256(
                            f"import:{auth.principal.user_id}:{file['kind']}:{file['warehouse_id']}:{file['sha256']}".encode()
                        ).digest()[:8],
                        signed=True,
                    )
                },
            )
            old = one(
                c,
                """SELECT * FROM wms.import_job WHERE requested_by=:actor AND kind=:kind
                AND warehouse_id IS NOT DISTINCT FROM CAST(:warehouse AS uuid) AND file_hash=:hash AND auth_version IS NOT NULL""",
                actor=auth.principal.user_id,
                kind=file["kind"],
                warehouse=file["warehouse_id"],
                hash=file["sha256"],
            )
            if old:
                if old["options"] != options:
                    raise DomainError(
                        "IMPORT_EXISTS", "Cùng nội dung đã có job với tùy chọn khác; sử dụng job đã tạo."
                    )
                return CommandResult(self.ack(old, request_id), 200)
            target = uuid4()
            version = one(c, "SELECT auth_version FROM wms.app_user WHERE id=:id", id=auth.principal.user_id)[
                "auth_version"
            ]
            c.execute(
                text("""INSERT INTO wms.import_job(id,kind,file_id,requested_by,status,file_hash,
                mapping_version,operation_key,created_at,warehouse_id,auth_version,options)
                VALUES (:id,:kind,:file,:actor,'QUEUED',:hash,:mapping,:key,:now,:warehouse,:auth,CAST(:options AS jsonb))"""),
                dict(
                    id=target,
                    kind=file["kind"],
                    file=file["id"],
                    actor=auth.principal.user_id,
                    hash=file["sha256"],
                    mapping=MAPPING_VERSION,
                    key=uuid4(),
                    now=self.identity.clock(),
                    warehouse=file["warehouse_id"],
                    auth=version,
                    options=json.dumps(options),
                ),
            )
            self.effects(
                c,
                auth.principal.user_id,
                target,
                "import.validation.requested",
                request_id,
                payload.reason,
                dict(job_id=str(target), generation=1),
            )
            return CommandResult(self.ack(self.job(auth, target), request_id), 201)

        return self.command(
            access,
            key,
            "POST /imports",
            payload.file_id,
            payload.model_dump(mode="json"),
            lambda auth: self.file(auth, payload.file_id),
            handle,
        )

    @staticmethod
    def ack(job, request_id):
        return dict(
            id=str(job["id"]),
            status=job["status"],
            version=job["version"],
            request_id=str(request_id),
            targets=(job["result"] or {}).get("targets", []),
        )

    def action(self, access, key, job_id, action, payload, request_id):
        if action == "commit":
            with self.identity.engine.begin() as c:
                auth = self.identity.authorization(c, access)
                job = self.job(auth, job_id)
                file = self.file(auth, job["file_id"])
            # Staging is immutable during commit; rehash before opening the write transaction.
            # Committed retries return the durable ACK even after archival/storage outage.
            if job["status"] != "COMMITTED":
                self.storage.read(file["storage_key"], file["sha256"], file["size_bytes"])

        def handle(auth):
            c = auth.connection
            job = self.job(auth, job_id, lock=True)
            if action == "commit" and job["status"] == "COMMITTED":
                if (
                    str(job["commit_token"]) != str(payload.commit_token)
                    or job["file_hash"] != payload.file_hash
                    or payload.expected_version != job["version"] - 1
                ):
                    raise DomainError("STALE_VERSION", "Import đã commit bằng phiên bản khác.")
                return CommandResult(job["result"])
            require_version(job["version"], payload.expected_version)
            if job["status"] == "COMMITTED":
                raise DomainError("INVALID_STATE", "Import đã commit; không thể hủy hoặc kiểm tra lại.")
            if action == "commit":
                user = one(c, "SELECT auth_version FROM wms.app_user WHERE id=:id", id=auth.principal.user_id)
                if (
                    job["status"] != "VALIDATED"
                    or str(job["commit_token"]) != str(payload.commit_token)
                    or job["file_hash"] != payload.file_hash
                    or job["token_expires_at"] <= self.identity.clock()
                    or job["mapping_version"] != MAPPING_VERSION
                    or job["auth_version"] != user["auth_version"]
                ):
                    raise DomainError(
                        "STALE_IMPORT", "Token/hash/phiên bản đã hết hiệu lực; chạy lại dry-run."
                    )
                rows = [
                    dict(r)
                    for r in c.execute(
                        text("SELECT row_no,payload FROM wms.import_row WHERE job_id=:id ORDER BY row_no"),
                        {"id": job_id},
                    ).mappings()
                ]
                if stage_digest(job, rows, job["data_snapshot"]) != job["stage_hash"]:
                    raise DomainError("STALE_IMPORT", "Staging đã đổi; không thể commit token cũ.")
                check_snapshot(c, job["data_snapshot"])
                targets, _, _ = ImportTargets(self.identity, auth, job, request_id).run(rows, preview=False)
                for item in targets:
                    c.execute(
                        text(
                            "UPDATE wms.import_row SET target_id=:id,status='COMMITTED' WHERE job_id=:job AND row_no=:row_no"
                        ),
                        {**item, "job": job_id},
                    )
                result = dict(
                    id=str(job_id),
                    status="COMMITTED",
                    version=job["version"] + 1,
                    request_id=str(request_id),
                    targets=targets,
                )
                c.execute(
                    text(
                        "UPDATE wms.import_job SET status='COMMITTED',version=version+1,result=CAST(:result AS jsonb) WHERE id=:id"
                    ),
                    dict(id=job_id, result=json.dumps(result)),
                )
                self.effects(
                    c,
                    auth.principal.user_id,
                    job_id,
                    "import.committed",
                    request_id,
                    payload.reason,
                    dict(id=str(job_id), rows=len(targets)),
                )
                return CommandResult(result)
            if action == "cancel":
                c.execute(
                    text(
                        "UPDATE wms.import_job SET status='CANCELLED',version=version+1,commit_token=NULL,token_expires_at=NULL WHERE id=:id"
                    ),
                    {"id": job_id},
                )
                event, data = "import.cancelled", dict(id=str(job_id))
            else:
                auth_version = one(
                    c, "SELECT auth_version FROM wms.app_user WHERE id=:id", id=auth.principal.user_id
                )["auth_version"]
                c.execute(
                    text("""UPDATE wms.import_job SET status='QUEUED',version=version+1,generation=generation+1,
                    auth_version=:auth,mapping_version=:mapping,commit_token=NULL,token_expires_at=NULL,stage_hash=NULL,
                    errors='[]',data_snapshot='[]',total_rows=0,processed_rows=0 WHERE id=:id"""),
                    dict(id=job_id, auth=auth_version, mapping=MAPPING_VERSION),
                )
                c.execute(text("DELETE FROM wms.import_row WHERE job_id=:id"), {"id": job_id})
                event, data = (
                    "import.validation.requested",
                    dict(job_id=str(job_id), generation=job["generation"] + 1),
                )
            self.effects(c, auth.principal.user_id, job_id, event, request_id, payload.reason, data)
            return CommandResult(self.ack(self.job(auth, job_id), request_id))

        return self.command(
            access,
            key,
            f"POST /imports/{action}",
            job_id,
            payload.model_dump(mode="json"),
            lambda auth: self.job(auth, job_id),
            handle,
        )
