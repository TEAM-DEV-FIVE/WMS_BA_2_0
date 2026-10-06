"""PostgreSQL adapter: row lock, DB effects, receipts and ACK share a transaction."""

from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Uuid, bindparam, text

from apps.server.application.outbox import (
    ConsumerRegistry,
    Delivery,
    DeliveryState,
    HandlerResult,
    OutboxEvent,
    RetryPolicy,
)


class _NotApplied(Exception):
    pass


class PostgresOutboxStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def deliver_one(self, registry: ConsumerRegistry, retry: RetryPolicy,
                    exclude: tuple[UUID, ...] = ()) -> Delivery | None:
        if not registry.event_types:
            return None
        with self.engine.begin() as connection:
            # Lock is acquired OUTSIDE the savepoint, so a failed handler cannot
            # release it before attempts/backoff are durably recorded.
            row = connection.execute(text("""
                SELECT id, event_type, aggregate_id, payload, occurred_at, attempts
                FROM wms.outbox_event
                WHERE processed_at IS NULL AND available_at <= statement_timestamp()
                  AND attempts < :maximum AND event_type IN :types AND id NOT IN :exclude
                ORDER BY available_at, id
                LIMIT 1 FOR UPDATE SKIP LOCKED
            """).bindparams(bindparam("types", expanding=True),
                              bindparam("exclude", expanding=True, type_=Uuid)),
                {"maximum": retry.max_attempts, "types": registry.event_types, "exclude": exclude}
            ).mappings().one_or_none()
            if row is None:
                return None
            event = OutboxEvent(**{key: row[key] for key in (
                "id", "event_type", "aggregate_id", "payload", "occurred_at"
            )})
            attempt = row["attempts"] + 1
            error_code = None
            try:
                with connection.begin_nested():
                    for consumer in registry.consumers_for(event.event_type):
                        received = connection.execute(text("""
                            SELECT 1 FROM wms.consumer_receipt WHERE event_id=:event AND consumer=:consumer
                        """), {"event": event.id, "consumer": consumer.name}).scalar_one_or_none()
                        if received is not None:
                            continue
                        # One consumer must not mutate the payload seen by another.
                        outcome = consumer.handle(connection, replace(event, payload=deepcopy(event.payload)))
                        if outcome is not HandlerResult.APPLIED:
                            raise _NotApplied()
                        self._record_receipt(connection, event.id, consumer.name)
                    self._acknowledge(connection, event.id, attempt)
            except Exception as error:
                # Never persist/log exception text, SQL parameters, payloads or credentials.
                # A DB error also rolls back the savepoint before retry metadata is written.
                error_code = "HANDLER_NOT_APPLIED" if isinstance(error, _NotApplied) else "DELIVERY_FAILED"
            if error_code is None:
                state = DeliveryState.PROCESSED
            else:
                state = DeliveryState.EXHAUSTED if attempt >= retry.max_attempts else DeliveryState.RETRY
                connection.execute(text("""
                    UPDATE wms.outbox_event
                    SET attempts=:attempt, last_error=:error, version=version+1,
                        available_at=clock_timestamp() + :delay * interval '1 second'
                    WHERE id=:id
                """), {"attempt": attempt, "error": error_code, "delay": retry.delay_seconds(attempt),
                       "id": event.id})
        # Only report success after COMMIT. Connection loss/commit ambiguity escapes
        # to the supervisor; reconnecting will check the committed row/receipts.
        return Delivery(event.id, state)

    @staticmethod
    def _record_receipt(connection: Connection, event_id: UUID, consumer: str) -> None:
        connection.execute(text("""
            INSERT INTO wms.consumer_receipt(id,event_id,consumer,processed_at)
            VALUES (:id,:event,:consumer,clock_timestamp())
        """), {"id": uuid4(), "event": event_id, "consumer": consumer})

    @staticmethod
    def _acknowledge(connection: Connection, event_id: UUID, attempt: int) -> None:
        connection.execute(text("""
            UPDATE wms.outbox_event
            SET processed_at=clock_timestamp(), attempts=:attempt, last_error=NULL,version=version+1 WHERE id=:id
        """), {"id": event_id, "attempt": attempt})
