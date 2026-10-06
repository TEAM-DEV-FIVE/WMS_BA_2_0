"""Global operator visibility and bounded, authorized outbox replay."""

import json
from uuid import uuid4

from sqlalchemy import text

from apps.server.application.commands import CommandBus, CommandResult
from apps.server.consumers.registry import fingerprint
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.database import PostgresUnitOfWork
from packages.contracts.operations import OutboxEventView

KINDS = ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")


class OperationsService:
    def __init__(self, identity, registry, max_attempts=5):
        self.identity, self.registry, self.max_attempts = identity, registry, max_attempts
        self.bus = CommandBus(lambda: PostgresUnitOfWork(identity.engine))

    def view(self, row):
        state = (
            "PROCESSED"
            if row["processed_at"]
            else "UNHANDLED"
            if row["event_type"] not in self.registry.event_types
            else "DEAD_LETTER"
            if row["attempts"] >= self.max_attempts
            else "RETRY"
            if row["attempts"]
            else "PENDING"
        )
        code = row["last_error"]
        if code not in (None, "HANDLER_NOT_APPLIED", "DELIVERY_FAILED"):
            code = "DELIVERY_FAILED"
        data = {k: row[k] for k in OutboxEventView.model_fields if k in row}
        return OutboxEventView.model_validate({**data, "state": state, "error_code": code}).model_dump(
            mode="json"
        )

    def events(self, auth, after=None, limit=50):
        auth.require("config.manage")
        rows = (
            auth.connection.execute(
                text("""SELECT * FROM wms.outbox_event
            WHERE (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid))
            ORDER BY id LIMIT :limit"""),
                dict(after=after, limit=limit + 1),
            )
            .mappings()
            .all()
        )
        return dict(
            items=[self.view(r) for r in rows[:limit]],
            next_after=rows[limit - 1]["id"] if len(rows) > limit else None,
        )

    def snapshot(self, auth):
        auth.require("config.manage")
        c = auth.connection
        stats = dict(
            c.execute(
                text("""SELECT
            count(*) FILTER(WHERE processed_at IS NOT NULL) AS processed,
            count(*) FILTER(WHERE processed_at IS NULL AND event_type<>ALL(:types)) AS unhandled,
            count(*) FILTER(WHERE processed_at IS NULL AND event_type=ANY(:types) AND attempts>=:max) AS dead_letter,
            count(*) FILTER(WHERE processed_at IS NULL AND event_type=ANY(:types) AND attempts<:max) AS pending,
            count(*) FILTER(WHERE processed_at IS NULL AND event_type=ANY(:types) AND attempts>0 AND attempts<:max) AS retry,
            COALESCE(sum(attempts),0) AS attempts_current_cycles,
            COALESCE(sum(replay_count),0) AS replays,
            COALESCE(EXTRACT(EPOCH FROM clock_timestamp()-min(occurred_at)
              FILTER(WHERE processed_at IS NULL AND event_type=ANY(:types))),0) AS lag_seconds
            FROM wms.outbox_event"""),
                dict(types=list(self.registry.event_types), max=self.max_attempts),
            )
            .mappings()
            .one()
        )
        stats = {k: max(0, float(v)) if k == "lag_seconds" else int(v) for k, v in stats.items()}
        jobs, tasks = {}, {}
        for kind in ("import", "export", "print"):
            jobs[kind] = dict(
                c.execute(text(f"SELECT status,count(*) FROM wms.{kind}_job GROUP BY status")).all()
            )
            state = "state" if kind == "import" else "status"
            tasks[kind] = dict(
                c.execute(text(f"SELECT {state},count(*) FROM wms.{kind}_task GROUP BY {state}")).all()
            )
            tasks[kind].update(
                dict(
                    c.execute(
                        text(f"""SELECT
                COALESCE(sum(attempts),0) AS attempts,
                count(*) FILTER(WHERE {state}='RUNNING' AND lease_until<=clock_timestamp()) AS expired_leases
                FROM wms.{kind}_task""")
                    )
                    .mappings()
                    .one()
                )
            )
        digest = fingerprint(self.registry)
        workers = (
            c.execute(
                text("""SELECT *, heartbeat_at>clock_timestamp()-interval '120 seconds' AS fresh
            FROM wms.worker_status ORDER BY heartbeat_at DESC,id LIMIT 201""")
            )
            .mappings()
            .all()
        )
        # Readiness uses all rows, independent of the bounded display page.
        ready = set(
            c.execute(
                text("""SELECT DISTINCT kind FROM wms.worker_status
            WHERE state IN ('IDLE','BUSY') AND registry_hash=:hash
              AND heartbeat_at>clock_timestamp()-interval '120 seconds'"""),
                dict(hash=digest),
            ).scalars()
        )
        return dict(
            registry_hash=digest,
            subscriptions={
                t: [x.name for x in self.registry.consumers_for(t)] for t in self.registry.event_types
            },
            outbox=stats,
            jobs=jobs,
            tasks=tasks,
            workers=[dict(w) for w in workers[:200]],
            workers_truncated=len(workers) > 200,
            ready_kinds=sorted(ready),
            missing_kinds=sorted(set(KINDS) - ready),
            ready=set(KINDS) <= ready,
            max_attempts=self.max_attempts,
        )

    def jobs(self, auth, kind, after=None, limit=50):
        auth.require("config.manage")
        if kind not in ("import", "export", "print"):
            raise DomainError("NOT_FOUND", "Không tìm thấy loại job.")
        error = "t.last_error" if kind == "import" else "j.error_code"
        state = "t.state" if kind == "import" else "t.status"
        rows = (
            auth.connection.execute(
                text(f"""SELECT j.id,j.status,j.version,j.generation,
            t.attempts,{state} AS task_state,{error} AS error_code,t.lease_until,t.available_at
            FROM wms.{kind}_job j LEFT JOIN wms.{kind}_task t ON t.job_id=j.id AND t.generation=j.generation
            WHERE (CAST(:after AS uuid) IS NULL OR j.id>CAST(:after AS uuid)) ORDER BY j.id LIMIT :limit"""),
                dict(after=after, limit=limit + 1),
            )
            .mappings()
            .all()
        )
        return dict(
            items=[dict(r) for r in rows[:limit]],
            next_after=rows[limit - 1]["id"] if len(rows) > limit else None,
        )

    def replay(self, access, key, event_id, payload, request_id):
        with self.identity.engine.begin() as c:
            actor = self.identity.authorization(c, access).principal.user_id

        def authorize(uow):
            self.identity.authorization(uow.connection, access).require("config.manage")

        def handle(uow):
            c = uow.connection
            row = (
                c.execute(text("SELECT * FROM wms.outbox_event WHERE id=:id FOR UPDATE"), dict(id=event_id))
                .mappings()
                .one_or_none()
            )
            if not row:
                raise DomainError("NOT_FOUND", "Không tìm thấy sự kiện.")
            require_version(payload.expected_version, row["version"])
            if row["event_type"] not in self.registry.event_types:
                raise DomainError("OUTBOX_VERSION_UNSUPPORTED", "Chưa triển khai consumer cho phiên bản này.")
            if row["processed_at"] or row["attempts"] < self.max_attempts:
                raise DomainError("INVALID_STATE", "Chỉ replay sự kiện đã hết lượt thử.")
            if row["replay_count"] >= 3:
                raise DomainError("OUTBOX_REPLAY_LIMIT", "Đã đủ ba lượt replay; cần điều tra nguyên nhân.")
            cooldown = c.execute(
                text("SELECT :at > clock_timestamp()-interval '60 seconds'"), dict(at=row["replayed_at"])
            ).scalar_one()
            if cooldown:
                raise DomainError("OUTBOX_REPLAY_COOLDOWN", "Chờ ít nhất 60 giây giữa các lượt replay.")
            c.execute(
                text("""UPDATE wms.outbox_event SET attempts=0,available_at=clock_timestamp(),
                last_error=NULL,version=version+1,replay_count=replay_count+1,replayed_at=clock_timestamp()
                WHERE id=:id"""),
                dict(id=event_id),
            )
            # Preserve every consumer receipt; already committed effects must never be run again.
            data = dict(
                previous_attempts=row["attempts"],
                replay_count=row["replay_count"] + 1,
                previous_version=row["version"],
                reason=payload.reason,
            )
            c.execute(
                text("""INSERT INTO wms.audit_event
                (id,actor_id,action,entity_type,entity_id,after_data,request_id,occurred_at)
                VALUES (:id,:actor,'outbox.replay','outbox_event',:entity,CAST(:data AS jsonb),:request,clock_timestamp())"""),
                dict(id=uuid4(), actor=actor, entity=event_id, data=json.dumps(data), request=request_id),
            )
            updated = (
                c.execute(text("SELECT * FROM wms.outbox_event WHERE id=:id"), dict(id=event_id))
                .mappings()
                .one()
            )
            return CommandResult(self.view(updated))

        return self.bus.execute(
            actor_id=actor,
            key=key,
            command="outbox.replay",
            resource_id=event_id,
            payload=payload.model_dump(mode="json"),
            authorize=authorize,
            handle=handle,
        )
