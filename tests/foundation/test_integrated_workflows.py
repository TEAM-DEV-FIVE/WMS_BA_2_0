"""Exercise a real producer from opening stock through the separately delivered worker."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from test_openings import inventory, opening, orders  # noqa: F401
from test_orders import ok

from apps.server.application.outbox import Consumer, ConsumerRegistry, HandlerResult, OutboxProcessor
from apps.server.infrastructure.outbox import PostgresOutboxStore

pytestmark = pytest.mark.integration


def test_opening_event_retry_and_replay_preserve_committed_inventory(opening):  # noqa: F811
    f = opening
    doc = f.open_approve()
    payload, key = f.open_post_body(doc), uuid4()
    ack = ok(f.open_post(doc, payload, key))
    with f.engine.begin() as c:
        # No uniqueness constraint: dedup must come from worker receipts.
        c.execute(text("CREATE TABLE wms.integration_projection(event_id uuid, transaction_id uuid)"))
        original = dict(
            c.execute(
                text("""SELECT * FROM wms.outbox_event
            WHERE event_type='opening.post.v1' AND aggregate_id=:doc"""),
                {"doc": doc["id"]},
            )
            .mappings()
            .one()
        )
        assert original["payload"] == ack
        # IAM fixture time is fixed, while the worker schedules using the DB clock.
        c.execute(
            text("UPDATE wms.outbox_event SET available_at=clock_timestamp() WHERE id=:id"),
            {"id": original["id"]},
        )

    fail = True

    def project(connection, event):
        assert event.aggregate_id == UUID(doc["id"])
        connection.execute(
            text("INSERT INTO wms.integration_projection VALUES (:event,:transaction)"),
            {"event": event.id, "transaction": event.payload["transaction_id"]},
        )
        if fail:
            raise RuntimeError("Simulated projection failure after inserting effect")
        return HandlerResult.APPLIED

    registry = ConsumerRegistry([Consumer("integration-opening-projection", "opening.post.v1", project)])
    processor = OutboxProcessor(PostgresOutboxStore(f.engine), registry)
    first = processor.run_batch()
    assert (first.attempted, first.processed, first.retry) == (1, 0, 1)
    assert inventory(f) == (1, 1, 10, 0)
    with f.engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM wms.integration_projection")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM wms.consumer_receipt")).scalar_one() == 0
        pending = (
            c.execute(text("SELECT * FROM wms.outbox_event WHERE id=:id"), {"id": original["id"]})
            .mappings()
            .one()
        )
        assert pending["processed_at"] is None and pending["attempts"] == 1
        assert pending["payload"] == ack
        c.execute(
            text("UPDATE wms.outbox_event SET available_at=clock_timestamp() WHERE id=:id"),
            {"id": original["id"]},
        )
    assert ok(f.open_post(doc, payload, key)) == ack
    lookup = ok(f.client.get(f"/api/v1/openings/operations/{key}", headers=f.headers["buyer"]))
    assert lookup["transaction_id"] == ack["transaction_id"]

    fail = False
    second = processor.run_batch()
    assert (second.attempted, second.processed, second.retry) == (1, 1, 0)
    assert ok(f.open_post(doc, payload, key)) == ack
    assert processor.run_batch().attempted == 0
    assert inventory(f) == (1, 1, 10, 0)
    with f.engine.connect() as c:
        projection = c.execute(text("SELECT * FROM wms.integration_projection")).one()
        assert tuple(projection) == (original["id"], UUID(ack["transaction_id"]))
        assert c.execute(text("SELECT count(*) FROM wms.consumer_receipt")).scalar_one() == 1
        assert (
            c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action='opening.post'")).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM wms.outbox_event WHERE event_type='opening.post.v1'")
            ).scalar_one()
            == 1
        )
        # Lifecycle/master events without a registered consumer remain pending.
        assert (
            c.execute(
                text("""SELECT count(*) FROM wms.outbox_event
            WHERE event_type<>'opening.post.v1' AND processed_at IS NOT NULL""")
            ).scalar_one()
            == 0
        )
