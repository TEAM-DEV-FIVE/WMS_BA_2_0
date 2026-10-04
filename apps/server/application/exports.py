"""Authorized asynchronous export commands; inventory is never mutated."""

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from apps.server.application.authorization import Authorization, Principal
from apps.server.application.commands import CommandResult
from apps.server.application.master_data import one
from apps.server.application.reports import serialize_actor, serialized
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.file_storage import FileStorage, ImportSettings
from packages.contracts.reports import ExportView

MIMES = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class ExportSettings(ImportSettings):
    model_config = {"env_prefix": "WMS_EXPORT_", "extra": "ignore"}
    storage_root: Path = Path(".wms-export-files")


class ExportService:
    def __init__(self, reports, storage=None):
        self.reports, self.identity = reports, reports.identity
        self.storage = storage or FileStorage(ExportSettings())

    def job(self, auth, job_id, lock=False):
        job = one(
            auth.connection,
            """SELECT * FROM wms.export_job
            WHERE id=:id AND requested_by=:actor AND snapshot_id IS NOT NULL"""
            + (" FOR UPDATE" if lock else ""),
            id=job_id,
            actor=auth.principal.user_id,
        )
        if not job:
            raise DomainError("NOT_FOUND", "Không tìm thấy export của bạn.")
        self.reports.snapshot(auth, job["snapshot_id"], export=True)
        if job["expires_at"] <= self.identity.clock():
            raise DomainError("REPORT_EXPIRED", "Export đã hết hạn.")
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
        return ExportView.model_validate(
            {**{k: job[k] for k in ExportView.model_fields if k in job}, **file}
        ).model_dump(mode="json")

    def effects(self, auth, job, request_id, action, enqueue=False):
        payload = dict(job_id=str(job["id"]), generation=job["generation"])
        auth.connection.execute(
            text("""INSERT INTO wms.audit_event
            (id,actor_id,action,entity_type,entity_id,after_data,request_id,occurred_at)
            VALUES (:id,:actor,:action,'export',:target,CAST(:payload AS jsonb),:request,:now)"""),
            dict(
                id=uuid4(),
                actor=auth.principal.user_id,
                action="export." + action,
                target=job["id"],
                payload=serialized(payload),
                request=request_id,
                now=self.identity.clock(),
            ),
        )
        if enqueue:
            auth.connection.execute(
                text("""INSERT INTO wms.outbox_event
                (id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
                VALUES (:id,'export.requested.v1',:job,CAST(:payload AS jsonb),:now,:now,0)"""),
                dict(id=uuid4(), job=job["id"], payload=serialized(payload), now=self.identity.clock()),
            )

    def create(self, access, key, payload, request_id):
        def handle(auth):
            snapshot = self.reports.snapshot(auth, payload.snapshot_id, export=True)
            serialize_actor(auth)
            existing = one(
                auth.connection,
                """SELECT id FROM wms.export_job WHERE snapshot_id=:id AND format=:format
                ORDER BY created_at,id LIMIT 1""",
                id=payload.snapshot_id,
                format=payload.format,
            )
            if existing:
                return CommandResult(self.read(auth, existing["id"]))
            quota = one(
                auth.connection,
                """SELECT count(*) AS files,
                COALESCE(sum(COALESCE(f.size_bytes,:maximum)),0) AS bytes
                FROM wms.export_job j LEFT JOIN wms.stored_file f ON f.id=j.file_id
                WHERE j.requested_by=:actor AND j.snapshot_id IS NOT NULL""",
                actor=auth.principal.user_id,
                maximum=self.storage.settings.max_file_bytes,
            )
            if (
                quota["files"] >= self.storage.settings.max_user_files
                or quota["bytes"] + self.storage.settings.max_file_bytes
                > self.storage.settings.max_user_bytes
            ):
                raise DomainError(
                    "FILE_LIMIT", "Đạt hạn mức export; cần dọn các job hết hạn theo quy trình vận hành."
                )
            job_id = uuid4()
            auth.connection.execute(
                text("""INSERT INTO wms.export_job
                (id,requested_by,report_code,filters,status,created_at,expires_at,snapshot_id,session_id,format)
                VALUES (:id,:actor,:code,CAST(:filters AS jsonb),'QUEUED',:now,:expires,:snapshot,:session,:format)"""),
                dict(
                    id=job_id,
                    actor=auth.principal.user_id,
                    code=snapshot["report_code"],
                    filters=serialized(snapshot["criteria"]),
                    now=self.identity.clock(),
                    expires=snapshot["expires_at"],
                    snapshot=payload.snapshot_id,
                    session=auth.principal.session_id,
                    format=payload.format,
                ),
            )
            self.effects(auth, dict(id=job_id, generation=1), request_id, "created", True)
            return CommandResult(self.read(auth, job_id), 201)

        return self.reports.command(
            access,
            key,
            "export.create",
            payload.snapshot_id,
            payload.model_dump(mode="json"),
            lambda auth: self.reports.snapshot(auth, payload.snapshot_id, export=True),
            handle,
        )

    def action(self, access, key, job_id, operation, payload, request_id):
        def handle(auth):
            job = self.job(auth, job_id, True)
            require_version(payload.expected_version, job["version"])
            if operation == "retry" and job["status"] != "FAILED":
                raise DomainError("INVALID_STATE", "Chỉ tạo lượt chạy mới khi job FAILED.")
            if operation == "retry" and job["generation"] >= 5:
                raise DomainError(
                    "EXPORT_RETRY_LIMIT", "Job đã đủ 5 lượt; tạo snapshot mới sau khi xử lý nguyên nhân lỗi."
                )
            if operation == "cancel" and job["status"] == "CANCELLED":
                raise DomainError("INVALID_STATE", "Job đã hủy.")
            auth.connection.execute(
                text("""UPDATE wms.export_job SET status=:status,version=version+1,
                generation=generation+1,error_code=NULL,session_id=:session WHERE id=:id"""),
                dict(
                    id=job_id,
                    status="QUEUED" if operation == "retry" else "CANCELLED",
                    session=auth.principal.session_id,
                ),
            )
            job = self.job(auth, job_id)
            self.effects(auth, job, request_id, operation, operation == "retry")
            return CommandResult(self.read(auth, job_id))

        return self.reports.command(
            access,
            key,
            "export." + operation,
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
            raise DomainError("FORBIDDEN", "Phiên yêu cầu export không còn hiệu lực.")
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
        self.reports.snapshot(auth, job["snapshot_id"], export=True)
        return auth

    def download(self, access, job_id):
        def metadata():
            with self.identity.engine.begin() as c:
                auth = self.identity.authorization(c, access)
                job = self.job(auth, job_id)
                if job["status"] != "READY":
                    raise DomainError("INVALID_STATE", "Tệp chưa sẵn sàng hoặc đã hủy.")
                return dict(one(c, "SELECT * FROM wms.stored_file WHERE id=:id", id=job["file_id"]))

        file = metadata()
        data = self.storage.read(file["storage_key"], file["sha256"], file["size_bytes"])
        current = metadata()  # New transaction after file I/O; revoke/cancel wins before response.
        if current["id"] != file["id"] or hashlib.sha256(data).hexdigest() != current["sha256"]:
            raise DomainError("FILE_HASH_MISMATCH", "Tệp thay đổi; tải lại.")
        return data, file["original_name"], file["mime_type"]
