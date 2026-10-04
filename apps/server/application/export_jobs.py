"""Outbox handler performs DB work only; leased executor owns file I/O."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.export_files import render
from apps.server.application.export_retention import storage_fence
from apps.server.application.exports import MIMES
from apps.server.application.master_data import one
from apps.server.application.outbox import Consumer, ConsumerRegistry, HandlerResult
from apps.server.application.reports import serialized
from apps.server.domain.errors import DomainError


def enqueue(connection, event):
    payload = event.payload
    if (
        not isinstance(payload, dict)
        or set(payload) != {"job_id", "generation"}
        or type(payload["generation"]) is not int
        or payload["generation"] < 1
    ):
        raise ValueError("Invalid export event v1")
    job_id = UUID(payload["job_id"])
    job = one(connection, "SELECT * FROM wms.export_job WHERE id=:id FOR UPDATE", id=job_id)
    if not job or event.aggregate_id != job_id or payload["generation"] > job["generation"]:
        raise ValueError("Unknown export request")
    if payload["generation"] < job["generation"] or job["status"] in {"CANCELLED", "READY"}:
        return HandlerResult.APPLIED
    if not job["snapshot_id"]:
        raise ValueError("Unknown export snapshot")
    connection.execute(
        text("""INSERT INTO wms.export_task(id,job_id,generation)
        VALUES (:id,:job,:generation) ON CONFLICT(job_id,generation) DO NOTHING"""),
        dict(id=uuid4(), job=job_id, generation=payload["generation"]),
    )
    return HandlerResult.APPLIED


def consumer_factory():
    return ConsumerRegistry([Consumer("export.enqueue.v1", "export.requested.v1", enqueue)])


class ExportExecutor:
    def __init__(self, service):
        self.service, self.engine, self.settings = service, service.identity.engine, service.storage.settings

    def claim(self):
        with self.engine.begin() as c:
            exhausted = (
                c.execute(
                    text("""UPDATE wms.export_task SET status='EXHAUSTED',lease_token=NULL
                WHERE status='RUNNING' AND lease_until<=clock_timestamp() AND attempts>=:maximum
                RETURNING job_id,generation"""),
                    {"maximum": self.settings.max_attempts},
                )
                .mappings()
                .all()
            )
            for task in exhausted:
                c.execute(
                    text("""UPDATE wms.export_job SET status='FAILED',version=version+1,error_code='LEASE_EXHAUSTED'
                    WHERE id=:job AND generation=:generation AND status='RUNNING'"""),
                    dict(job=task["job_id"], generation=task["generation"]),
                )
            task = one(
                c,
                """SELECT * FROM wms.export_task WHERE attempts<:maximum AND
                ((status='READY' AND available_at<=clock_timestamp()) OR (status='RUNNING' AND lease_until<=clock_timestamp()))
                ORDER BY available_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                maximum=self.settings.max_attempts,
            )
            if not task:
                return None
            token = uuid4()
            c.execute(
                text("""UPDATE wms.export_task SET status='RUNNING',attempts=attempts+1,lease_token=:token,
                lease_until=clock_timestamp()+:seconds*interval '1 second' WHERE id=:id"""),
                dict(id=task["id"], token=token, seconds=self.settings.lease_seconds),
            )
            c.execute(
                text("""UPDATE wms.export_job SET status='RUNNING' WHERE id=:job
                AND generation=:generation AND status IN ('QUEUED','RUNNING')"""),
                dict(job=task["job_id"], generation=task["generation"]),
            )
            return {**task, "lease_token": token, "attempts": task["attempts"] + 1}

    @staticmethod
    def owned(c, task):
        return one(
            c,
            """SELECT id FROM wms.export_task WHERE id=:id AND lease_token=:token
            AND status='RUNNING' AND lease_until>clock_timestamp() FOR UPDATE""",
            id=task["id"],
            token=task["lease_token"],
        )

    @staticmethod
    def done(c, task):
        c.execute(
            text("UPDATE wms.export_task SET status='DONE',lease_token=NULL,lease_until=NULL WHERE id=:id"),
            {"id": task["id"]},
        )

    def execute(self, task):
        try:
            with storage_fence(self.engine, shared=True):
                return self.execute_owned(task)
        except Exception as error:
            return self.fail(task, error)

    def execute_owned(self, task):
        try:
            with self.engine.begin() as c:
                if not self.owned(c, task):
                    return "LOST_LEASE"
                job = one(c, "SELECT * FROM wms.export_job WHERE id=:id", id=task["job_id"])
                if job["generation"] != task["generation"] or job["status"] != "RUNNING":
                    self.done(c, task)
                    return "OBSOLETE"
                auth = self.service.worker_authorization(c, job)
                snapshot = self.service.reports.snapshot(auth, job["snapshot_id"], export=True)
                rows = (
                    c.execute(
                        text("""SELECT payload FROM wms.report_snapshot_row
                    WHERE snapshot_id=:id ORDER BY ordinal"""),
                        {"id": job["snapshot_id"]},
                    )
                    .scalars()
                    .all()
                )
                if (
                    len(rows) != snapshot["row_count"]
                    or hashlib.sha256(serialized(rows).encode()).hexdigest() != snapshot["sha256"]
                ):
                    raise DomainError("REPORT_HASH_MISMATCH", "Snapshot không còn toàn vẹn.")
            # Serialization and durable file publication intentionally outside all DB transactions.
            data = render(snapshot, rows, job["format"], self.settings.max_file_bytes)
            digest = hashlib.sha256(data).hexdigest()
            # Same immutable snapshot/format yields the same object across crash/retry generations.
            key = hashlib.sha256(f"{job['id']}:{digest}".encode()).hexdigest()
            self.service.storage.put(data, digest, key)
            with self.engine.begin() as c:
                if not self.owned(c, task):
                    return "LOST_LEASE"
                job = one(c, "SELECT * FROM wms.export_job WHERE id=:id FOR UPDATE", id=task["job_id"])
                if job["generation"] != task["generation"] or job["status"] != "RUNNING":
                    self.done(c, task)
                    return "OBSOLETE"
                self.service.worker_authorization(c, job)
                file_id = uuid4()
                c.execute(
                    text("""INSERT INTO wms.stored_file
                    (id,storage_key,original_name,mime_type,sha256,size_bytes,uploaded_by,created_at)
                    VALUES (:id,:key,:name,:mime,:hash,:size,:actor,:now)"""),
                    dict(
                        id=file_id,
                        key=key,
                        name=f"{job['report_code']}-{job['id']}.{job['format']}",
                        mime=MIMES[job["format"]],
                        hash=digest,
                        size=len(data),
                        actor=job["requested_by"],
                        now=self.service.identity.clock(),
                    ),
                )
                c.execute(
                    text("""UPDATE wms.export_job SET status='READY',file_id=:file,version=version+1,error_code=NULL
                    WHERE id=:id"""),
                    dict(id=job["id"], file=file_id),
                )
                self.done(c, task)
            return "READY"
        except Exception as error:
            return self.fail(task, error)

    def fail(self, task, error):
        code = error.code if isinstance(error, DomainError) else "EXECUTION_FAILED"
        retry = (not isinstance(error, DomainError) or error.retryable) and task[
            "attempts"
        ] < self.settings.max_attempts
        with self.engine.begin() as c:
            if not self.owned(c, task):
                return "LOST_LEASE"
            c.execute(
                text("""UPDATE wms.export_task SET status=:status,lease_token=NULL,lease_until=NULL,
                available_at=clock_timestamp()+:delay*interval '1 second' WHERE id=:id"""),
                dict(
                    id=task["id"],
                    status="READY" if retry else "EXHAUSTED",
                    delay=min(300, 5 * 2 ** (task["attempts"] - 1)),
                ),
            )
            c.execute(
                text("""UPDATE wms.export_job SET status=:status,error_code=:error,version=version+1
                WHERE id=:job AND generation=:generation AND status='RUNNING'"""),
                dict(
                    job=task["job_id"],
                    generation=task["generation"],
                    status="QUEUED" if retry else "FAILED",
                    error=code,
                ),
            )
        return "RETRY" if retry else "FAILED"

    def run_one(self):
        task = self.claim()
        return self.execute(task) if task else None
