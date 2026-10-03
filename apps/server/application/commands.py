import hashlib
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from apps.server.application.ports import UnitOfWork
from apps.server.domain.errors import DomainError


@dataclass(frozen=True)
class CommandResult:
    body: dict[str, Any]
    http_status: int = 200


def payload_hash(command: str, resource_id: UUID, payload: dict[str, Any]) -> str:
    """Caller passes the full validated body, including expected_version/execution_key."""
    encoded = json.dumps(
        [command, str(resource_id), payload], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CommandBus:
    """Internal command kernel. Each handler owns resource locks and domain rules.

    Authorization is mandatory, including replay, and must check current scope in
    this UoW. Do not expose a route until its real authorization/handler exists.
    No I/O outside the database is allowed in authorization or the handler.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self.uow_factory = uow_factory

    def execute(self, *, actor_id: UUID, key: UUID, command: str, resource_id: UUID,
                payload: dict[str, Any], authorize: Callable[[UnitOfWork], None],
                handle: Callable[[UnitOfWork], CommandResult]) -> CommandResult:
        for attempt in range(3):
            try:
                return self._execute(actor_id=actor_id, key=key, command=command, resource_id=resource_id,
                                     payload=payload, authorize=authorize, handle=handle)
            except DBAPIError as error:
                # Connection loss/commit ambiguity must never start a different command.
                if getattr(error.orig, "sqlstate", None) not in {"40P01", "40001"}:
                    raise
                if attempt == 2:
                    raise DomainError("DATABASE_BUSY", "Giao dịch đang tranh chấp; gửi lại cùng key.", retryable=True) from None
                time.sleep(random.uniform(0.01, 0.03) * (attempt + 1))

    def _execute(self, *, actor_id, key, command, resource_id, payload, authorize, handle):
        digest = payload_hash(command, resource_id, payload)
        with self.uow_factory() as uow:
            uow.commands.lock(actor_id, key)
            authorize(uow)
            record = uow.commands.get(actor_id, key)
            if record is not None:
                if record["request_hash"] != digest:
                    raise DomainError("IDEMPOTENCY_MISMATCH", "Key đã được dùng với nội dung khác.")
                return CommandResult(record["response"], record["http_status"])
            result = handle(uow)
            if not 200 <= result.http_status < 300:
                raise ValueError("Only committed successful commands may be recorded")
            uow.commands.save(actor_id, key, command, digest, result.body, result.http_status)
            uow.commit()
            return result
