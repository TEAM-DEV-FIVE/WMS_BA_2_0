from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract


class OutboxReplay(Contract):
    expected_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=10, max_length=500)


class OutboxEventView(Contract):
    id: UUID
    aggregate_id: UUID
    event_type: str
    version: int
    attempts: int
    replay_count: int
    occurred_at: datetime
    available_at: datetime
    processed_at: datetime | None
    replayed_at: datetime | None
    state: Literal["PROCESSED", "UNHANDLED", "DEAD_LETTER", "RETRY", "PENDING"]
    error_code: str | None


class OutboxPage(Contract):
    items: list[OutboxEventView]
    next_after: UUID | None


class OperationsJob(Contract):
    id: UUID
    status: str
    version: int
    generation: int
    attempts: int | None
    task_state: str | None
    error_code: str | None
    lease_until: datetime | None
    available_at: datetime | None


class OperationsJobPage(Contract):
    items: list[OperationsJob]
    next_after: UUID | None


class OperationsView(Contract):
    registry_hash: str
    subscriptions: dict[str, list[str]]
    outbox: dict[str, int | float]
    jobs: dict[str, dict[str, int]]
    tasks: dict[str, dict[str, int]]
    workers: list[dict]
    workers_truncated: bool
    ready_kinds: list[str]
    missing_kinds: list[str]
    ready: bool
    max_attempts: int
