"""DB-only outbox enqueue, then a separate leased file executor."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from apps.server.application.import_parser import issue, parse
from apps.server.application.import_targets import ImportTargets
from apps.server.application.imports import job_authorization, stage_digest
from apps.server.application.master_data import one
from apps.server.application.outbox import Consumer, ConsumerRegistry, HandlerResult
from apps.server.domain.errors import DomainError


def enqueue(connection, event):
    payload = event.payload
    if (
        not isinstance(payload, dict)
        or set(payload) != {"job_id", "generation"}
        or type(payload["generation"]) is not int
        or payload["generation"] < 1
    ):
        raise ValueError("Invalid import event v1")
    job_id = UUID(payload["job_id"])
    job = one(connection, "SELECT * FROM wms.import_job WHERE id=:id FOR UPDATE", id=job_id)
    if (
        not job
        or event.aggregate_id != job_id
        or payload["generation"] > job["generation"]
        or job["auth_version"] is None
    ):
        raise ValueError("Unknown import request")
    if payload["generation"] < job["generation"] or job["status"] in {"CANCELLED", "COMMITTED"}:
        return HandlerResult.APPLIED  # Verified obsolete request; never resurrect a cancelled job.
    connection.execute(
        text("""INSERT INTO wms.import_task(id,job_id,generation,state,available_at)
        VALUES (:id,:job,:generation,'READY',clock_timestamp()) ON CONFLICT(job_id,generation) DO NOTHING"""),
        dict(id=uuid4(), job=job_id, generation=payload["generation"]),
    )
    return HandlerResult.APPLIED


def consumer_factory():
    return ConsumerRegistry([Consumer("import.enqueue.v1", "import.validation.requested.v1", enqueue)])


class ImportExecutor:
    def __init__(self, service):
        self.service = service
        self.engine = service.identity.engine
        self.settings = service.storage.settings

    def claim(self):
        with self.engine.begin() as c:
            # A crash on the final attempt must still become a visible terminal failure.
            exhausted = (
                c.execute(
                    text("""UPDATE wms.import_task SET state='EXHAUSTED',last_error='LEASE_EXHAUSTED'
                WHERE state='RUNNING' AND lease_until<=clock_timestamp() AND attempts>=:maximum
                RETURNING job_id,generation"""),
                    {"maximum": self.settings.max_attempts},
                )
                .mappings()
                .all()
            )
            for task in exhausted:
                c.execute(
                    text("""UPDATE wms.import_job SET status='FAILED',version=version+1,errors=CAST(:errors AS jsonb)
                    WHERE id=:job AND generation=:generation AND status='VALIDATING'"""),
                    dict(
                        job=task["job_id"],
                        generation=task["generation"],
                        errors=json.dumps(
                            [
                                issue(
                                    0,
                                    "file",
                                    "LEASE_EXHAUSTED",
                                    "Worker hết lượt phục hồi; chạy lại dry-run.",
                                )
                            ]
                        ),
                    ),
                )
            row = one(
                c,
                """SELECT * FROM wms.import_task WHERE attempts<:maximum AND
                ((state='READY' AND available_at<=clock_timestamp()) OR (state='RUNNING' AND lease_until<=clock_timestamp()))
                ORDER BY available_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                maximum=self.settings.max_attempts,
            )
            if not row:
                return None
            token = uuid4()
            c.execute(
                text("""UPDATE wms.import_task SET state='RUNNING',attempts=attempts+1,lease_token=:token,
                lease_until=clock_timestamp()+:lease*interval '1 second' WHERE id=:id"""),
                dict(id=row["id"], token=token, lease=self.settings.lease_seconds),
            )
            c.execute(
                text("""UPDATE wms.import_job SET status='VALIDATING' WHERE id=:job
                AND generation=:generation AND status IN ('QUEUED','VALIDATING')"""),
                dict(job=row["job_id"], generation=row["generation"]),
            )
            return {**row, "lease_token": token, "attempts": row["attempts"] + 1}

    def owned(self, c, task):
        return one(
            c,
            """SELECT * FROM wms.import_task WHERE id=:id AND lease_token=:token
            AND state='RUNNING' AND lease_until>clock_timestamp() FOR UPDATE""",
            id=task["id"],
            token=task["lease_token"],
        )

    def execute(self, task):
        try:
            # No file I/O in the outbox or staging transaction.
            with self.engine.begin() as c:
                job = one(c, "SELECT * FROM wms.import_job WHERE id=:id", id=task["job_id"])
                if job["generation"] != task["generation"] or job["status"] != "VALIDATING":
                    return self.obsolete(task)
                auth = job_authorization(self.service.identity, c, job)
                file = self.service.file(auth, job["file_id"])
            data = self.service.storage.read(file["storage_key"], file["sha256"], file["size_bytes"])
            rows, errors = parse(data, file["original_name"], job["kind"])
            with self.engine.begin() as c:
                if not self.owned(c, task):
                    return "LOST_LEASE"
                c.execute(
                    text("""UPDATE wms.import_job SET total_rows=:total,processed_rows=0
                    WHERE id=:job AND generation=:generation AND status='VALIDATING'"""),
                    dict(total=len(rows), job=task["job_id"], generation=task["generation"]),
                )
            with self.engine.begin() as c:
                if not self.owned(c, task):
                    return "LOST_LEASE"
                job = one(c, "SELECT * FROM wms.import_job WHERE id=:id FOR UPDATE", id=task["job_id"])
                if job["generation"] != task["generation"] or job["status"] != "VALIDATING":
                    self.done(c, task)
                    return "OBSOLETE"
                auth = job_authorization(self.service.identity, c, job)
                snapshots = []
                if not errors:
                    # All real domain effects, audit, outbox and source dedup are rolled back.
                    preview = c.begin_nested()
                    try:
                        _, errors, snapshots = ImportTargets(self.service.identity, auth, job).run(
                            rows, preview=True
                        )
                    finally:
                        preview.rollback()
                c.execute(text("DELETE FROM wms.import_row WHERE job_id=:id"), {"id": job["id"]})
                for row in rows:
                    row_errors = [e for e in errors if e["row_no"] == row["row_no"]]
                    c.execute(
                        text("""INSERT INTO wms.import_row(id,job_id,row_no,payload,errors,status)
                        VALUES (:id,:job,:row,CAST(:payload AS jsonb),CAST(:errors AS jsonb),:status)"""),
                        dict(
                            id=uuid4(),
                            job=job["id"],
                            row=row["row_no"],
                            payload=json.dumps(row["payload"]),
                            errors=json.dumps(row_errors),
                            status="INVALID" if row_errors else "STAGED",
                        ),
                    )
                now = self.service.identity.clock()
                c.execute(
                    text("""UPDATE wms.import_job SET status=:status,version=version+1,total_rows=:total,
                    processed_rows=:total,errors=CAST(:errors AS jsonb),data_snapshot=CAST(:snapshots AS jsonb),
                    stage_hash=:hash,commit_token=:token,token_expires_at=:expires WHERE id=:id"""),
                    dict(
                        id=job["id"],
                        status="INVALID" if errors else "VALIDATED",
                        total=len(rows),
                        errors=json.dumps(errors),
                        snapshots=json.dumps(snapshots),
                        hash=stage_digest(job, rows, snapshots),
                        token=None if errors else uuid4(),
                        expires=None if errors else now + timedelta(hours=1),
                    ),
                )
                self.done(c, task)
            return "INVALID" if errors else "VALIDATED"
        except Exception as error:
            return self.fail(task, error)

    @staticmethod
    def done(c, task):
        c.execute(
            text(
                "UPDATE wms.import_task SET state='DONE',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=:id"
            ),
            {"id": task["id"]},
        )

    def obsolete(self, task):
        with self.engine.begin() as c:
            if self.owned(c, task):
                self.done(c, task)
        return "OBSOLETE"

    def fail(self, task, error):
        # Persist only bounded codes, never SQL, file content, credentials or exception text.
        code = error.code if isinstance(error, DomainError) else "EXECUTION_FAILED"
        retryable = not isinstance(error, DomainError) or error.retryable
        retry = retryable and task["attempts"] < self.settings.max_attempts
        with self.engine.begin() as c:
            if not self.owned(c, task):
                return "LOST_LEASE"
            c.execute(
                text("""UPDATE wms.import_task SET state=:state,last_error=:error,lease_token=NULL,lease_until=NULL,
                available_at=clock_timestamp()+:delay*interval '1 second' WHERE id=:id"""),
                dict(
                    id=task["id"],
                    state="READY" if retry else "EXHAUSTED",
                    error=code,
                    delay=min(300, 5 * 2 ** (task["attempts"] - 1)),
                ),
            )
            c.execute(
                text("""UPDATE wms.import_job SET status=:state,version=version+1,errors=CAST(:errors AS jsonb)
                WHERE id=:job AND generation=:generation AND status='VALIDATING' """),
                dict(
                    job=task["job_id"],
                    generation=task["generation"],
                    state="QUEUED" if retry else "FAILED",
                    errors=json.dumps(
                        [
                            issue(
                                0,
                                "file",
                                code,
                                "Không xử lý được job; worker sẽ thử lại hoặc cần chạy lại dry-run.",
                            )
                        ]
                    ),
                ),
            )
        return "RETRY" if retry else "FAILED"

    def run_one(self):
        task = self.claim()
        return self.execute(task) if task else None
