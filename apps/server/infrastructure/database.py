import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, create_engine, text

from apps.server.infrastructure.config import Settings


def make_engine(settings: Settings) -> Engine:
    timeout = settings.database_timeout_seconds
    return create_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True,
        pool_size=settings.pool_size, max_overflow=0, pool_timeout=timeout,
        hide_parameters=True,
        connect_args={"connect_timeout": timeout,
                      "options": f"-c statement_timeout={timeout * 1000} -c lock_timeout={timeout * 1000}"},
    )


class PostgresCommandRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def lock(self, actor_id: UUID, key: UUID) -> None:
        lock = int.from_bytes(hashlib.sha256(f"{actor_id}:{key}".encode()).digest()[:8], signed=True)
        self.connection.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    def get(self, actor_id: UUID, key: UUID) -> dict[str, Any] | None:
        row = self.connection.execute(text("""
            SELECT request_hash, response, http_status FROM wms.idempotency_record
            WHERE actor_id=:actor AND key=:key
        """), {"actor": actor_id, "key": key}).mappings().one_or_none()
        return dict(row) if row is not None else None

    def save(self, actor_id: UUID, key: UUID, command: str, request_hash: str,
             response: dict[str, Any], http_status: int) -> None:
        self.connection.execute(text("""
            INSERT INTO wms.idempotency_record
              (id, actor_id, key, command, request_hash, response, http_status, completed_at, expires_at)
            VALUES (:id, :actor, :key, :command, :hash, CAST(:response AS jsonb), :status,
                    clock_timestamp(), clock_timestamp() + interval '30 days')
        """), {"id": uuid4(), "actor": actor_id, "key": key, "command": command,
               "hash": request_hash, "response": json.dumps(response, allow_nan=False), "status": http_status})


class PostgresUnitOfWork:
    """One connection/transaction per command; rollback unless explicitly committed."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def __enter__(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.commands = PostgresCommandRepository(self.connection)
        return self

    def commit(self) -> None:
        self.transaction.commit()

    def rollback(self) -> None:
        if self.transaction.is_active:
            self.transaction.rollback()

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.rollback()
        finally:
            self.connection.close()
