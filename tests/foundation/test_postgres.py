import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from apps.server.application.commands import CommandBus, CommandResult
from apps.server.domain.errors import DomainError, require_version
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import PostgresUnitOfWork
from apps.server.infrastructure.migrations import MigrationError, is_ready, migrate, migration_sources

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_migrations_seed_schema_smoke_and_reconciliation(database):
    assert migrate(database) == []
    assert is_ready(database)
    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM wms.role")).scalar_one() == 10
        assert connection.execute(text("SELECT count(*) FROM wms.permission")).scalar_one() == 58
        actual = set(connection.execute(text("""
            SELECT r.code, p.code FROM wms.role_permission rp
            JOIN wms.role r ON r.id=rp.role_id JOIN wms.permission p ON p.id=rp.permission_id
        """)).tuples().all())
        policy = json.loads((ROOT / "04_Phan_quyen/policy.json").read_text())
        expected = {(role, p["code"]) for p in policy["permissions"] for role in p["roles"]}
        assert actual == expected
        baseline = json.loads((ROOT / "02_CSDL/model.json").read_text())
        extensions = [json.loads(path.read_text()) for path in sorted((ROOT / "02_CSDL").glob("*_extension_model.json"))]
        def pg_type(value):
            for short, full in {"varchar": "character varying", "char": "character", "timestamptz": "timestamp with time zone"}.items():
                if value == short or value.startswith(short + "("):
                    return full + value[len(short):]
            return value
        columns = {(table["name"], col["name"], pg_type(col["type"]), col["null"])
                   for table in baseline + [t for e in extensions for t in e["tables"]] for col in table["cols"]}
        columns.update((c["table"], c["name"], pg_type(c["type"]), c["null"]) for e in extensions for c in e["added_columns"])
        actual_columns = set(connection.execute(text("""SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),NOT a.attnotnull
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            WHERE c.relnamespace='wms'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        """)).tuples().all())
        assert actual_columns == columns
    raw = database.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute("SET wms.test.expected_tables='93'; SET wms.test.expected_columns='609'; SET wms.test.expected_fks='197';")
            cursor.execute("SET wms.test.expected_permissions='58'; SET wms.test.expected_role_permissions='125';")
            cursor.execute((ROOT / "tests/sql/schema_smoke.sql").read_text())
            while cursor.nextset():
                pass
            cursor.execute((ROOT / "02_CSDL/reconcile.sql").read_text())
            while True:
                if cursor.description:
                    assert cursor.fetchall() == []
                if not cursor.nextset():
                    break
    finally:
        raw.close()


def test_concurrent_migration_runners_serialize(empty_database):
    gate = Barrier(2)
    def run():
        gate.wait(timeout=5)
        return migrate(empty_database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(map(len, results)) == [0, len(migration_sources())]
    assert is_ready(empty_database)


def test_upgrade_from_foundation_preserves_existing_data(empty_database, monkeypatch):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:2])
        assert len(migrate(empty_database)) == 2
    user_id, factor_id = uuid4(), uuid4()
    with empty_database.begin() as connection:
        connection.execute(text("""INSERT INTO wms.app_user
            VALUES (:id,'existing-user','Existing','fixture-placeholder',true,0,now())"""), {"id": user_id})
        connection.execute(text("""INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext)
            VALUES (:id,:user,'TOTP','existing-fixture-ciphertext')"""), {"id": factor_id, "user": user_id})
    assert migrate(empty_database) == [source[0] for source in sources[2:]]
    assert is_ready(empty_database)
    with empty_database.connect() as connection:
        factor = connection.execute(text("SELECT last_counter,credential_ciphertext FROM wms.mfa_factor WHERE id=:id"), {"id": factor_id}).one()
        assert tuple(factor) == (-1, "existing-fixture-ciphertext")
        assert connection.execute(text("SELECT username FROM wms.app_user WHERE id=:id"), {"id": user_id}).scalar_one() == "existing-user"


def test_migration_failure_rolls_back_schema_and_history(empty_database, monkeypatch):
    import apps.server.infrastructure.migrations as migrations
    source = migrations.migration_sources()
    monkeypatch.setattr(migrations, "migration_sources", lambda: source + [("999_broken.sql", "0" * 64, "SELECT no_such_column;")])
    with pytest.raises(ProgrammingError, match="no_such_column"):
        migrate(empty_database)
    with empty_database.connect() as connection:
        assert connection.execute(text("SELECT to_regnamespace('wms')")).scalar_one() is None
        assert connection.execute(text("SELECT to_regclass('public.wms_schema_migration')")).scalar_one() is None


def test_master_upgrade_preserves_catalog_and_adds_versions(empty_database, monkeypatch):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:4])
        migrate(empty_database)
    uom, category = uuid4(), uuid4()
    with empty_database.begin() as connection:
        connection.execute(text("INSERT INTO wms.uom VALUES (:id,'legacy-unit','Chiếc',0)"), {"id": uom})
        connection.execute(text("INSERT INTO wms.product_category VALUES (:id,'LEGACY','Thiết bị',NULL)"), {"id": category})
    assert migrate(empty_database) == [source[0] for source in sources[4:]]
    with empty_database.connect() as connection:
        assert tuple(connection.execute(text("SELECT code,name,version,is_active FROM wms.uom WHERE id=:id"), {"id": uom}).one()) == ("legacy-unit", "Chiếc", 1, True)
        assert tuple(connection.execute(text("SELECT code,version,is_active FROM wms.product_category WHERE id=:id"), {"id": category}).one()) == ("LEGACY", 1, True)


@pytest.mark.parametrize("prefix_length", [5, 10, 13, 14, 15, 16, 17])
def test_ownership_upgrade_preserves_legacy_ledger_without_assuming_company(empty_database, monkeypatch, prefix_length):
    import apps.server.infrastructure.migrations as migrations
    from packages.contracts.traceability import UNCLASSIFIED_OWNER
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:5])
        migrate(empty_database)
    ids = {name: uuid4() for name in ['user','warehouse','external','location','uom','product','item','doc','line','txn','move','balance']}
    with empty_database.begin() as c:
        statements = [
            "INSERT INTO wms.app_user VALUES (:user,'legacy','Legacy','fixture-only',true,0,now())",
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'OLD','Legacy',true)",
            "INSERT INTO wms.location(id,code,name,kind,is_active) VALUES (:external,'EXT','External','OPENING',true)",
            "INSERT INTO wms.location(id,warehouse_id,code,name,kind,is_active) VALUES (:location,:warehouse,'BIN','Bin','STORAGE',true)",
            "INSERT INTO wms.uom(id,code,name,decimal_places) VALUES (:uom,'EA','Unit',0)",
            "INSERT INTO wms.product VALUES (:product,'OLD-PRODUCT','Legacy',NULL,:uom,'NONE',false,true,1,'{}')",
            "INSERT INTO wms.stock_item VALUES (:item,:product,NULL,NULL)",
            "INSERT INTO wms.document VALUES (:doc,'OLD-OPEN','OPENING','COMPLETED',:warehouse,NULL,NULL,NULL,current_date,:user,now(),1,NULL,'{}')",
            "INSERT INTO wms.document_line VALUES (:line,:doc,1,:product,:uom,10,1,10,NULL,NULL)",
            "INSERT INTO wms.inventory_transaction VALUES (:txn,:doc,:txn,'OPEN',current_date,now(),:user,NULL)",
            "INSERT INTO wms.stock_move VALUES (:move,:txn,:line,:item,:external,:location,10,:uom,NULL)",
            "INSERT INTO wms.stock_balance VALUES (:balance,:item,:location,10,0,1)",
        ]
        for sql in statements:
            c.execute(text(sql), ids)
        original_move = dict(c.execute(text('SELECT * FROM wms.stock_move')).mappings().one())
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix_length])
        migrate(empty_database)
    with empty_database.connect() as c:
        before = c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()
    assert migrate(empty_database) == [source[0] for source in sources[prefix_length:]]
    with empty_database.connect() as c:
        assert c.execute(text("SELECT version,sha256 FROM public.wms_schema_migration ORDER BY version")).all()[:prefix_length] == before
    with empty_database.connect() as c:
        assert dict(c.execute(text('SELECT * FROM wms.stock_move')).mappings().one()) == original_move
        for table in ['stock_item','document_line']:
            assert c.execute(text(f'SELECT owner_id FROM wms.{table}')).scalar_one() == UNCLASSIFIED_OWNER
        assert c.execute(text('SELECT on_hand FROM wms.stock_balance')).scalar_one() == 10
        assert c.execute(text('SELECT count(*) FROM wms.serial_warranty_record')).scalar_one() == 0


def test_changed_or_unknown_migrations_are_refused(database):
    with database.begin() as connection:
        connection.execute(text("UPDATE public.wms_schema_migration SET sha256=:hash WHERE version='001_schema.sql'"), {"hash": "0" * 64})
    with pytest.raises(MigrationError, match="checksum"):
        migrate(database)
    assert not is_ready(database)


def test_existing_unmanaged_schema_is_not_overwritten(empty_database):
    with empty_database.begin() as connection:
        connection.execute(text("CREATE SCHEMA wms"))
    with pytest.raises(MigrationError, match="unmanaged"):
        migrate(empty_database)


def test_readiness_changes_only_after_explicit_migration(empty_database):
    from apps.server.api.app import create_app
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"), engine=empty_database)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/ready").status_code == 503
        migrate(empty_database)
        assert client.get("/api/v1/ready").json()["status"] == "ready"


def write_effects(uow, actor, entity):
    uow.connection.execute(text("""
        INSERT INTO wms.organization(id,code,name,timezone,currency)
        VALUES (:id,:code,'Fixture','Asia/Ho_Chi_Minh','VND')
    """), {"id": entity, "code": str(entity)})
    uow.connection.execute(text("""
        INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at)
        VALUES (:id,:actor,'fixture.create','organization',:entity,:request,now())
    """), {"id": uuid4(), "actor": actor, "entity": entity, "request": uuid4()})
    uow.connection.execute(text("""
        INSERT INTO wms.outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts)
        VALUES (:id,'fixture.created.v1',:entity,'{}',now(),now(),0)
    """), {"id": uuid4(), "entity": entity})


def command_args(actor, entity):
    return dict(actor_id=actor, key=uuid4(), command="POST /fixture/{id}", resource_id=entity,
                payload={"expected_version": 1, "execution_key": str(uuid4())}, authorize=lambda uow: None)


def test_command_retry_concurrency_payload_and_authorization(database, actor):
    entity = uuid4()
    args = command_args(actor, entity)
    bus = CommandBus(lambda: PostgresUnitOfWork(database))
    gate = Barrier(2)
    def handle(uow):
        write_effects(uow, actor, entity)
        return CommandResult({"id": str(entity), "status": "CREATED", "request_id": str(uuid4())}, 201)
    def run():
        gate.wait(timeout=5)
        return bus.execute(**args, handle=handle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1]
    assert bus.execute(**args, handle=handle) == results[0]
    with database.connect() as connection:
        for table in ["organization", "audit_event", "outbox_event", "idempotency_record"]:
            assert connection.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 1
    with pytest.raises(DomainError, match="Key"):
        bus.execute(**{**args, "payload": {**args["payload"], "expected_version": 2}}, handle=handle)
    def revoked(uow):
        raise DomainError("FORBIDDEN", "Revoked")
    with pytest.raises(DomainError, match="Revoked"):
        bus.execute(**{**args, "authorize": revoked}, handle=handle)


def test_failure_rolls_back_effect_audit_outbox_and_operation(database, actor):
    entity = uuid4()
    args = command_args(actor, entity)
    bus = CommandBus(lambda: PostgresUnitOfWork(database))
    def handle(uow):
        write_effects(uow, actor, entity)
        raise RuntimeError("injected failure after outbox")
    with pytest.raises(RuntimeError, match="injected"):
        bus.execute(**args, handle=handle)
    with database.connect() as connection:
        for table in ["organization", "audit_event", "outbox_event", "idempotency_record"]:
            assert connection.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 0


def test_uncommitted_uow_and_stale_version_leave_no_effect(database, actor):
    with PostgresUnitOfWork(database) as uow:
        write_effects(uow, actor, uuid4())
    with PostgresUnitOfWork(database) as uow:
        assert uow.connection.execute(text("SELECT count(*) FROM wms.organization")).scalar_one() == 0
    bus = CommandBus(lambda: PostgresUnitOfWork(database))
    def stale(uow):
        require_version(2, 1)
    with pytest.raises(DomainError) as error:
        bus.execute(**command_args(actor, uuid4()), handle=stale)
    assert error.value.code == "STALE_VERSION"


def test_foreign_key_failure_cannot_leave_idempotency_result(database, actor):
    bus = CommandBus(lambda: PostgresUnitOfWork(database))
    args = command_args(uuid4(), uuid4())  # actor does not exist
    with pytest.raises(IntegrityError):
        bus.execute(**args, handle=lambda uow: CommandResult({"id": "fixture"}))
    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM wms.idempotency_record")).scalar_one() == 0


@pytest.mark.gui
def test_desktop_reads_readiness_from_real_http_and_postgres(database):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell
    from apps.server.api.app import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"), engine=database)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{port}/api/v1"))
        shell.presenter.check(readiness=True)
        deadline = time.monotonic() + 5
        while "đã sẵn sàng" not in shell.status.get() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert shell.status.get() == "Máy chủ và cơ sở dữ liệu đã sẵn sàng."
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_order_upgrade_preserves_existing_policy_and_legacy_approval(empty_database, monkeypatch):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'migration_sources', lambda: sources[:7])
        migrate(empty_database)
    ids = {name: uuid4() for name in ['user', 'warehouse', 'document', 'policy', 'step', 'request']}
    with empty_database.begin() as c:
        statements = [
            "INSERT INTO wms.app_user VALUES (:user,'legacy-approver','Legacy','fixture-only',true,0,now())",
            "INSERT INTO wms.warehouse(id,code,name,is_active) VALUES (:warehouse,'OLD-PO','Legacy',true)",
            "INSERT INTO wms.document(id,number,kind,status,warehouse_id,business_date,created_by,created_at,version,attributes) VALUES (:document,'OLD-PO','PO','SUBMITTED',:warehouse,current_date,:user,now(),2,'{}')",
            "INSERT INTO wms.approval_policy VALUES (:policy,'PO',7,true)",
            "INSERT INTO wms.approval_policy_step(id,policy_id,step_no,role_id) SELECT :step,:policy,1,id FROM wms.role WHERE code='CONTROLLER'",
            "INSERT INTO wms.approval_request VALUES (:request,:document,2,:policy,:user,'PENDING',now())",
        ]
        for sql in statements:
            c.execute(text(sql), ids)
    assert migrate(empty_database) == [source[0] for source in sources[7:]]
    with empty_database.connect() as c:
        assert tuple(c.execute(text("SELECT revision,is_active FROM wms.approval_policy WHERE document_kind='PO'")).one()) == (7, True)
        assert tuple(c.execute(text('SELECT document_version,status,content_snapshot FROM wms.approval_request WHERE id=:request'),ids).one()) == (2,'PENDING',None)
        assert c.execute(text('SELECT alternative_role_id FROM wms.approval_policy_step WHERE id=:step'),ids).scalar_one() is None
        assert c.execute(text('SELECT status FROM wms.document WHERE id=:document'),ids).scalar_one() == 'SUBMITTED'
