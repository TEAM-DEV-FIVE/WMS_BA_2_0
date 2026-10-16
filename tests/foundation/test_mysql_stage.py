"""Exercise preparation only inside the socket-only disposable MySQL runner."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from apps.server.infrastructure.mysql_migrations import assets
from scripts.build_mysql_schema import quote
from scripts.prepare_mysql_stage import prepare
from scripts.stage_mysql_data import update_digest

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def test_prepare_rejects_tampering_then_installs_guards_and_archives_copy(empty_database):
    if empty_database.dialect.name != "mysql":
        pytest.skip("Native MySQL preparation")
    socket = empty_database.url.query.get("unix_socket", "")
    if not Path(socket).parent.name.startswith("wms-mysql-test-"):
        pytest.fail("Preparation test requires scripts/check_mysql.py private instance")
    connection = pymysql.connect(user="root", unix_socket=socket, autocommit=True)
    database = "kws_mysql"
    try:
        with connection.cursor() as c:
            c.execute("CREATE DATABASE kws_mysql")
            c.execute("USE kws_mysql")
        manifest = assets()[0][2]
        schema = json.loads((Path(__file__).resolve().parents[2] / "02_CSDL/current/schema.json").read_text())
        with connection.cursor() as c:
            for statement in manifest["tables"] + manifest["foreign_keys"]:
                c.execute(statement)
            c.execute("INSERT INTO outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts) VALUES (%s,'copy.test.v1',%s,'{}',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),0)", (str(uuid4()),str(uuid4())))
        report = dict(destination=database, state="DATA_VERIFIED_RUNTIME_NOT_READY", runtime_activated=False,
                      schema_manifest_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                      sequences={"order_number_seq": {"next_value": 73}}, tables=[])
        with connection.cursor() as c:
            for table in schema["tables"]:
                c.execute("SHOW CREATE TABLE " + quote(table["name"]))
                ddl = hashlib.sha256(c.fetchone()[1].encode()).hexdigest()
                keys = next(x["columns"] for x in table["constraints"] if x["kind"] == "p")
                c.execute("SELECT " + ",".join(quote(x["name"]) for x in table["columns"]) + " FROM " + quote(table["name"]) + " ORDER BY " + ",".join(map(quote,keys)))
                rows=c.fetchall()
                digest=hashlib.sha256()
                for row in rows:
                    update_digest(digest,row,table["columns"])
                report["tables"].append(dict(table=table["name"],matches=True,source_rows=len(rows),source_sha256=digest.hexdigest(),ddl_sha256=ddl))
        credentials=dict(user="root",password="",unix_socket=socket,databases=[database])
        admin=["mysql","--no-defaults", "--socket="+socket,"--user=root"]
        original=report["tables"][0]["source_sha256"]
        report["tables"][0]["source_sha256"]="0"*64
        with pytest.raises(ValueError, match="data changed"):
            prepare(credentials,database,report,schema,admin_prefix=admin)
        with connection.cursor() as c:
            c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='wms_schema_migration'")
            assert c.fetchone()[0] == 0
        report["tables"][0]["source_sha256"]=original
        result=prepare(credentials,database,report,schema,admin_prefix=admin)
        assert result["runtime_activated"] is False
        assert result["adjustments"]["archived_outbox_rows"] == 1
        with connection.cursor() as c:
            c.execute("INSERT INTO order_number_sequence(value) VALUES (NULL)")
            assert c.lastrowid == 73
            c.execute("SELECT COUNT(*) FROM outbox_event WHERE processed_at IS NULL")
            assert c.fetchone()[0] == 1
            with pytest.raises(pymysql.MySQLError):
                c.execute("UPDATE outbox_event SET processed_at=UTC_TIMESTAMP(6)")
            c.execute("SELECT COUNT(*) FROM wms_schema_migration WHERE state='COMPLETE'")
            assert c.fetchone()[0] == len(assets())
    finally:
        with connection.cursor() as c:
            c.execute("DROP DATABASE IF EXISTS kws_mysql")
        connection.close()


def test_mysql_imported_outbox_is_history_without_fabricating_ack(database):
    if database.dialect.name != "mysql":
        pytest.skip("MySQL staging archive is not part of the immutable PostgreSQL schema")
    from apps.server.application.outbox import Consumer, ConsumerRegistry, HandlerResult, RetryPolicy
    from apps.server.infrastructure.outbox import PostgresOutboxStore
    archived, current = uuid4(), uuid4()
    with database.begin() as c:
        for identifier in (archived, current):
            c.execute(text("INSERT INTO wms.outbox_event(id,event_type,aggregate_id,payload,occurred_at,available_at,attempts) VALUES (:id,'migration.test.v1',:id,'{}',now(),now(),0)"), {"id": identifier})
        c.native("INSERT INTO migration_outbox_archive(event_id,reason) VALUES (:id,'WMS_HISTORY')", {"id": archived})
    delivered = []
    def consume(connection, event):
        delivered.append(event.id)
        return HandlerResult.APPLIED
    registry = ConsumerRegistry([Consumer("archive_test", "migration.test.v1", consume)])
    store = PostgresOutboxStore(database)
    assert store.deliver_one(registry, RetryPolicy()).event_id == current
    assert store.deliver_one(registry, RetryPolicy()) is None
    assert delivered == [current]
    with database.connect() as c:
        assert c.execute(text("SELECT processed_at FROM wms.outbox_event WHERE id=:id"), {"id": archived}).scalar_one() is None
    with pytest.raises(IntegrityError), database.begin() as c:
        c.execute(text("UPDATE wms.outbox_event SET available_at=now() WHERE id=:id"), {"id": archived})
