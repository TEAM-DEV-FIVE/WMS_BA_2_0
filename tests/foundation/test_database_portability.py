"""Database behavior shared by both supported engines; disposable DBs only."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration


def test_bootstrap_can_be_rechecked_without_changes(database):
    from apps.server.infrastructure.migrations import is_ready, migrate
    assert is_ready(database)
    assert migrate(database) == []
    assert is_ready(database)


def test_invalidated_connection_closes_without_reconnecting(database):
    connection = database.connect()
    connection.execute(text("SELECT 1"))
    connection.invalidate()
    connection.close()


def test_sequence_allocation_survives_rollback(database):
    with database.connect() as c:
        first = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
        c.rollback()
        second = c.execute(text("SELECT nextval('wms.order_number_seq')")).scalar_one()
        assert second > first
        c.commit()


def test_implicit_insert_defaults_and_unlimited_page(database):
    identifier = uuid4()
    with database.begin() as c:
        c.execute(text("INSERT INTO wms.uom VALUES (:id,'PORTABLE','Unit',0)"), {"id": identifier})
        result = c.execute(text("SELECT id,version,is_active FROM wms.uom LIMIT :limit"), {"limit": None}).mappings().one()
        assert result == {"id": identifier, "version": 1, "is_active": True}


def test_conflict_does_not_hide_invalid_row(database):
    with database.begin() as c:
        c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,'PORTABLE','Unit',0)"), {"id": uuid4()})
    with pytest.raises(IntegrityError), database.begin() as c:
        c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,'OTHER','Unit',-1) ON CONFLICT DO NOTHING"), {"id": uuid4()})


def test_snapshot_engine_retains_database_protocol(database):
    snapshot = database.execution_options(isolation_level="REPEATABLE READ").execution_options(stream_results=False)
    with snapshot.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 94102})
        assert c.execute(text("SELECT count(*) FROM wms.role")).scalar_one() > 0


def test_storage_shared_and_exclusive_fences(database):
    from apps.server.application.export_retention import storage_fence
    from apps.server.domain.errors import DomainError

    with storage_fence(database, shared=True):
        with storage_fence(database, shared=True):
            with pytest.raises(DomainError):
                with storage_fence(database, shared=False):
                    pytest.fail("An exclusive writer entered while readers held the fence")
    with storage_fence(database, shared=False):
        with pytest.raises(DomainError):
            with storage_fence(database, shared=True):
                pytest.fail("A reader entered while an exclusive writer held the fence")
    with storage_fence(database, shared=True):
        pass


def test_calendar_days_cross_month_in_business_timezone(database):
    from datetime import UTC, date, datetime

    with database.connect() as c:
        days = c.execute(text("SELECT CAST(:today AS date)-(CAST(:at AS timestamptz) AT TIME ZONE :zone)::date AS age"),
                         {"today": date(2026, 3, 1), "at": datetime(2026, 2, 28, 18, tzinfo=UTC), "zone": "Asia/Ho_Chi_Minh"}).scalar_one()
        assert days == 0


def test_report_guard_rejects_a_stale_repeatable_read_snapshot(database, actor):
    with database.begin() as c:
        c.execute(text("INSERT INTO wms.report_request_guard(user_id) VALUES (:actor)"), {"actor": actor})
    with database.execution_options(isolation_level="REPEATABLE READ").connect() as stale:
        stale.execute(text("SELECT version FROM wms.report_request_guard WHERE user_id=:actor"), {"actor": actor}).scalar_one()
        with database.begin() as current:
            current.execute(text("UPDATE wms.report_request_guard SET version=version+1 WHERE user_id=:actor"), {"actor": actor})
        with pytest.raises(DBAPIError) as error:
            stale.execute(text("INSERT INTO wms.report_request_guard(user_id) VALUES (:actor) ON CONFLICT(user_id) DO UPDATE SET version=wms.report_request_guard.version+1"), {"actor": actor})
        assert error.value.orig.sqlstate == "40001"
        stale.rollback()


def test_json_nested_scalar_and_json_null_are_portable(database):
    with database.connect() as c:
        row = c.execute(text("SELECT (CAST(:value AS jsonb)->0)->>'code' AS code, (CAST(:value AS jsonb)->1)->>'code' AS missing, (CAST(:value AS jsonb)->2)->>'code' AS literal"),
                        {"value": '[{"code":"X"},{"code":null},{"code":"null"}]'}).mappings().one()
        assert row == {"code": "X", "missing": None, "literal": "null"}



def test_upsert_resolves_the_requested_key_not_the_first_reported_index(database):
    first, second = uuid4(), uuid4()
    with database.begin() as c:
        for identifier, code in [(first, "UPSERT-A"), (second, "UPSERT-B")]:
            c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,:code,'Original',0)"), {"id": identifier, "code": code})
        for code, name in [("UPSERT-A", "Same row"), ("UPSERT-B", "Target row")]:
            c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,:code,:name,0) ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name"), {"id": first, "code": code, "name": name})
        rows = c.execute(text("SELECT id,code,name FROM wms.uom ORDER BY code")).all()
        assert rows == [(first,"UPSERT-A","Same row"),(second,"UPSERT-B","Target row")]
    with pytest.raises(IntegrityError), database.begin() as c:
        c.execute(text("INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:id,'UPSERT-C','Invalid target',0) ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name"), {"id": first})
