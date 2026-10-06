"""Print commands: durable snapshots; explicit spool attempts never post stock."""

import hashlib
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandResult
from apps.server.application.master_data import one
from apps.server.application.print_sources import current_snapshot_scope, source
from apps.server.application.reports import ReportService, serialize_actor, serialized
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.file_storage import FileStorage, ImportSettings
from packages.contracts.printing import PrintJob


class PrintSettings(ImportSettings):
    model_config = {"env_prefix": "WMS_PRINT_", "extra": "ignore"}
    storage_root: Path = Path(".wms-print-files")
    max_file_bytes: int = Field(default=5*1024*1024,ge=1024,le=16*1024*1024)
    issuer_name: str = Field(default="", max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")
    issuer_address: str = Field(default="", max_length=160, pattern=r"^[^\x00-\x1f\x7f]*$")
    issuer_tax_code: str = Field(default="", max_length=20, pattern=r"^[0-9-]*$")
    issuer_phone: str = Field(default="", max_length=30, pattern=r"^[0-9+() .-]*$")
    issuer_signer: str = Field(default="", max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")


class PrintService:
    def __init__(self, orders, counting, traceability, storage=None):
        self.orders, self.identity = orders, orders.identity
        self.counting, self.traceability = counting, traceability
        self.commands = ReportService(self.identity)
        self.storage = storage or FileStorage(PrintSettings())

    def job(self, auth, job_id, lock=False):
        job = one(
            auth.connection,
            "SELECT * FROM wms.print_job WHERE id=:id AND requested_by=:actor"
            + (" FOR UPDATE" if lock else ""),
            id=job_id,
            actor=auth.principal.user_id,
        )
        if not job:
            raise DomainError("NOT_FOUND", "Không tìm thấy lệnh in của bạn.")
        current_snapshot_scope(self, auth, job)
        if job["expires_at"] <= self.identity.clock():
            raise DomainError("PRINT_EXPIRED", "Bản in hết hạn sau một giờ; tạo bản mới.")
        return job

    def read(self, auth, job_id):
        job = self.job(auth, job_id)
        file = (
            one(
                auth.connection,
                "SELECT sha256,size_bytes FROM wms.stored_file WHERE id=:id",
                id=job["file_id"],
            )
            or {}
        )
        attempt = one(
            auth.connection,
            """SELECT id,printer,driver,copies,status,spool_id,error_code,created_at,finished_at
                    FROM wms.print_attempt WHERE job_id=:id AND generation=:generation""",
            id=job_id,
            generation=job["generation"],
        )
        return PrintJob.model_validate(
            {
                **{k: job[k] for k in PrintJob.model_fields if k in job},
                **file,
                "attempt": dict(attempt) if attempt else None,
            }
        ).model_dump(mode="json")

    def effects(self, auth, job, request_id, action, reason=None, enqueue=False):
        data = serialized(dict(job_id=job["id"], generation=job["generation"]))
        auth.connection.execute(
            text("""INSERT INTO wms.audit_event
        (id,actor_id,warehouse_id,action,entity_type,entity_id,after_data,request_id,occurred_at,reason)
        VALUES (:id,:actor,:wh,:action,'print',:target,CAST(:data AS jsonb),:request,:now,:reason)"""),
            dict(
                id=uuid4(),
                actor=auth.principal.user_id,
                wh=job["warehouse_id"],
                action="print." + action,
                target=job["id"],
                data=data,
                request=request_id,
                now=self.identity.clock(),
                reason=reason,
            ),
        )
        if enqueue:
            auth.connection.execute(
                text("""INSERT INTO wms.outbox_event
            (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
            VALUES (:id,'print.requested.v1',:job,CAST(:data AS jsonb),:now,:now,0)"""),
                dict(id=uuid4(), job=job["id"], data=data, now=self.identity.clock()),
            )

    def create(self, access, key, payload, request_id):
        def handle(auth):
            snapshot = source(self, auth, payload, capture=True)
            data = serialized(snapshot)
            if len(data.encode()) > 2 * 1024 * 1024:
                raise DomainError("PRINT_LIMIT", "Bản in vượt giới hạn 2 MiB dữ liệu.")
            serialize_actor(auth)
            count = one(
                auth.connection,
                """SELECT count(*) AS n FROM wms.print_job
                WHERE requested_by=:actor AND expires_at>:now""",
                actor=auth.principal.user_id,
                now=self.identity.clock(),
            )
            if count["n"] >= 20:
                raise DomainError("PRINT_LIMIT", "Tối đa 20 bản in mỗi giờ.")
            job_id, now = uuid4(), self.identity.clock()
            auth.connection.execute(
                text("""INSERT INTO wms.print_job
            (id,requested_by,session_id,warehouse_id,source_id,source_version,template,paper,include_price,
             criteria,snapshot,snapshot_hash,created_at,expires_at)
            VALUES (:id,:actor,:session,:wh,:source,:version,:template,:paper,:price,CAST(:criteria AS jsonb),
            CAST(:snapshot AS jsonb),:hash,:now,:expires)"""),
                dict(
                    id=job_id,
                    actor=auth.principal.user_id,
                    session=auth.principal.session_id,
                    wh=payload.warehouse_id,
                    source=payload.source_id,
                    version=payload.expected_version,
                    template=payload.template,
                    paper=payload.paper,
                    price=payload.include_price,
                    criteria=serialized(payload.model_dump(mode="json")),
                    snapshot=data,
                    hash=hashlib.sha256(data.encode()).hexdigest(),
                    now=now,
                    expires=now + timedelta(hours=1),
                ),
            )
            job = self.job(auth, job_id)
            self.effects(auth, job, request_id, "created", enqueue=True)
            return CommandResult(self.read(auth, job_id), 201)

        return self.commands.command(
            access,
            key,
            "print.create",
            payload.source_id,
            payload.model_dump(mode="json"),
            lambda auth: source(self, auth, payload),
            handle,
        )

    def action(self, access, key, job_id, operation, payload, request_id):
        def handle(auth):
            c = auth.connection
            job = self.job(auth, job_id, True)
            require_version(payload.expected_version, job["version"])
            attempt = one(
                c,
                "SELECT * FROM wms.print_attempt WHERE job_id=:id AND generation=:g",
                id=job_id,
                g=job["generation"],
            )
            if operation in {"retry", "reprint"}:
                if (operation == "retry" and job["status"] != "FAILED") or (
                    operation == "reprint" and (job["status"] != "READY" or not attempt)
                ):
                    raise DomainError(
                        "INVALID_STATE", "Chỉ chạy lại lỗi render hoặc in lại sau lượt gửi máy in."
                    )
                if job["generation"] >= 10:
                    raise DomainError("PRINT_LIMIT", "Tối đa 10 lượt; tạo bản mới sau khi đối soát.")
                c.execute(
                    text("""UPDATE wms.print_job SET status='QUEUED',generation=generation+1,
                    version=version+1,error_code=NULL,session_id=:session WHERE id=:id"""),
                    dict(id=job_id, session=auth.principal.session_id),
                )
            elif operation == "cancel":
                if job["status"] == "CANCELLED":
                    raise DomainError("INVALID_STATE", "Đã hủy bản in.")
                c.execute(
                    text("UPDATE wms.print_job SET status='CANCELLED',version=version+1 WHERE id=:id"),
                    dict(id=job_id),
                )
            elif operation == "spool":
                if job["status"] != "READY" or attempt:
                    raise DomainError("INVALID_STATE", "Lượt này chưa sẵn sàng hoặc đã được nhận gửi máy in.")
                c.execute(
                    text("""INSERT INTO wms.print_attempt
                    (id,job_id,generation,actor_id,session_id,printer,driver,copies,created_at)
                    VALUES (:id,:job,:g,:actor,:session,:printer,:driver,:copies,:now)"""),
                    dict(
                        id=payload.attempt_id,
                        job=job_id,
                        g=job["generation"],
                        actor=auth.principal.user_id,
                        session=auth.principal.session_id,
                        printer=payload.printer,
                        driver=payload.driver,
                        copies=payload.copies,
                        now=self.identity.clock(),
                    ),
                )
                c.execute(text("UPDATE wms.print_job SET version=version+1 WHERE id=:id"), dict(id=job_id))
            elif operation == "result":
                if not attempt or attempt["id"] != payload.attempt_id or attempt["finished_at"]:
                    raise DomainError("INVALID_STATE", "Lượt in không khớp hoặc đã xác nhận kết quả.")
                if attempt["session_id"] != auth.principal.session_id:
                    raise DomainError("FORBIDDEN", "Chỉ phiên nhận lượt in được báo kết quả.")
                c.execute(
                    text("""UPDATE wms.print_attempt SET status=:status,spool_id=:spool,error_code=:error,
                    finished_at=:now WHERE id=:id"""),
                    dict(
                        id=payload.attempt_id,
                        status=payload.outcome,
                        spool=payload.spool_id,
                        error=payload.error_code,
                        now=self.identity.clock(),
                    ),
                )
                c.execute(text("UPDATE wms.print_job SET version=version+1 WHERE id=:id"), dict(id=job_id))
            job = self.job(auth, job_id)
            self.effects(
                auth,
                job,
                request_id,
                operation,
                getattr(payload, "reason", None),
                operation in {"retry", "reprint"},
            )
            return CommandResult(self.read(auth, job_id))

        return self.commands.command(
            access,
            key,
            "print." + operation,
            job_id,
            payload.model_dump(mode="json"),
            lambda auth: self.job(auth, job_id),
            handle,
        )

    def worker_authorization(self, c, job):
        user = one(
            c,
            """SELECT u.id,u.username,u.display_name,s.id AS session_id,s.mfa_verified_at
            FROM wms.app_user u JOIN wms.auth_session s ON s.user_id=u.id
            WHERE s.id=:session AND u.id=:actor AND u.is_active AND u.auth_version=s.auth_version
            AND s.revoked_at IS NULL AND s.expires_at>:now""",
            session=job["session_id"],
            actor=job["requested_by"],
            now=self.identity.clock(),
        )
        if not user:
            raise DomainError("FORBIDDEN", "Phiên in đã hết hiệu lực.")
        auth = Authorization(
            c,
            Principal(
                user["id"],
                user["session_id"],
                user["username"],
                user["display_name"],
                user["mfa_verified_at"],
            ),
            self.identity.clock(),
        )
        self.job(auth, job["id"])
        return auth

    def download(self, access, job_id, attempt_id=None):
        def metadata():
            with self.identity.engine.begin() as c:
                auth = self.identity.authorization(c, access)
                job = self.job(auth, job_id)
                if job["status"] != "READY":
                    raise DomainError("INVALID_STATE", "Bản in chưa sẵn sàng hoặc đã hủy.")
                if attempt_id:
                    attempt = one(
                        c,
                        """SELECT id FROM wms.print_attempt WHERE id=:id AND job_id=:job
                        AND generation=:g AND session_id=:session AND finished_at IS NULL""",
                        id=attempt_id,
                        job=job_id,
                        g=job["generation"],
                        session=auth.principal.session_id,
                    )
                    if not attempt:
                        raise DomainError("INVALID_STATE", "Lượt gửi máy in không còn hiệu lực.")
                return dict(one(c, "SELECT * FROM wms.stored_file WHERE id=:id", id=job["file_id"]))

        file = metadata()
        data = self.storage.read(file["storage_key"], file["sha256"], file["size_bytes"])
        if metadata()["id"] != file["id"]:
            raise DomainError("FILE_HASH_MISMATCH", "Bản in thay đổi; tải lại.")
        return data, file["original_name"], "application/pdf"
