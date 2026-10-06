"""Contracts for database-only outbox consumers and bounded worker batches."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy import Connection


@dataclass(frozen=True)
class OutboxEvent:
    id: UUID
    event_type: str
    aggregate_id: UUID
    payload: Any
    occurred_at: datetime


class HandlerResult(Enum):
    APPLIED = "applied"


class DatabaseHandler(Protocol):
    """Use only the supplied transaction; never commit, rollback or perform external I/O.

    Return APPLIED only after a real DB effect (or verified business deduplication).
    A missing return/unsupported payload is a failure, never a successful no-op.
    """

    def __call__(self, connection: "Connection", event: OutboxEvent) -> HandlerResult: ...


@dataclass(frozen=True)
class Consumer:
    name: str
    event_type: str
    handle: DatabaseHandler = field(repr=False)

    def __post_init__(self):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", self.name):
            raise ValueError("Consumer name must be a stable identifier of at most 100 characters")
        if len(self.event_type) > 100 or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\.v[1-9][0-9]*", self.event_type
        ):
            raise ValueError("Event type must be an explicit versioned identifier, e.g. receipt.posted.v1")
        if not callable(self.handle):
            raise ValueError("Consumer handler must be callable")


class ConsumerRegistry:
    """Immutable routing snapshot; every worker must deploy the same subscriptions.

    All consumers for a type are required. No wildcard or implicit fallback handler.
    Changing subscriptions requires a coordinated deployment/replay plan.
    """

    def __init__(self, consumers: Iterable[Consumer] = ()):
        routes: dict[str, list[Consumer]] = {}
        for consumer in consumers:
            group = routes.setdefault(consumer.event_type, [])
            if any(existing.name == consumer.name for existing in group):
                raise ValueError("Duplicate consumer/event subscription")
            group.append(consumer)
        self._routes = MappingProxyType({
            event_type: tuple(sorted(group, key=lambda consumer: consumer.name))
            for event_type, group in sorted(routes.items())
        })

    @property
    def event_types(self) -> tuple[str, ...]:
        return tuple(self._routes)

    def consumers_for(self, event_type: str) -> tuple[Consumer, ...]:
        return self._routes.get(event_type, ())


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_seconds: int = 5
    max_seconds: int = 300

    def __post_init__(self):
        if not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if not 1 <= self.base_seconds <= self.max_seconds <= 86400:
            raise ValueError("Retry delays must satisfy 1 <= base <= maximum <= 86400")

    def delay_seconds(self, attempt: int) -> int:
        if not 1 <= attempt <= self.max_attempts:
            raise ValueError("Attempt outside retry budget")
        return min(self.base_seconds * (2 ** (attempt - 1)), self.max_seconds)


class DeliveryState(Enum):
    PROCESSED = "processed"
    RETRY = "retry"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class Delivery:
    event_id: UUID
    state: DeliveryState


class OutboxStore(Protocol):
    def deliver_one(self, registry: ConsumerRegistry, retry: RetryPolicy,
                    exclude: tuple[UUID, ...]) -> Delivery | None: ...


@dataclass
class BatchResult:
    attempted: int = 0
    processed: int = 0
    retry: int = 0
    exhausted: int = 0


class OutboxProcessor:
    def __init__(self, store: OutboxStore, registry: ConsumerRegistry, *,
                 batch_size: int = 100, retry: RetryPolicy | None = None):
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        self.store = store
        self.registry = registry
        self.batch_size = batch_size
        self.retry = retry or RetryPolicy()

    def run_batch(self, should_stop: Callable[[], bool] = lambda: False) -> BatchResult:
        result = BatchResult()
        attempted: list[UUID] = []
        if not self.registry.event_types:
            return result
        for _ in range(self.batch_size):
            if should_stop():
                break
            delivery = self.store.deliver_one(self.registry, self.retry, tuple(attempted))
            if delivery is None:
                break
            attempted.append(delivery.event_id)
            result.attempted += 1
            if delivery.state is DeliveryState.PROCESSED:
                result.processed += 1
            elif delivery.state is DeliveryState.RETRY:
                result.retry += 1
            else:
                result.exhausted += 1
        return result
