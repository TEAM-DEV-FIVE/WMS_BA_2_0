"""Separate relational-volume stress. Never reported as API/workflow throughput."""

import json
import os
import platform
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from test_orders import ok

from scripts.b24_harness import reconcile, save_evidence

pytestmark = pytest.mark.integration


def test_synthetic_history_volume_and_independent_reconcile(request):
    f = request.getfixturevalue("receiving")
    profile = json.loads(Path(__file__).with_name("b24-stress.json").read_text())
    if os.environ.get("WMS_B24_STRESS_PROFILE") != "full":
        profile.update(name="synthetic-history-smoke", skus=100, moves=2000)
    assert f.engine.url.database.startswith("wms_test_")
    doc = f.receipt_approve()
    ok(f.post(doc, f.post_body(doc, "1")))
    started = time.monotonic()
    with f.engine.begin() as c:
        c.exec_driver_sql("SET LOCAL statement_timeout='180s'")
        # All rows derive from a real posted fixture. UUIDs differ per run; cardinality is fixed.
        template = {
            table: c.execute(
                text(f"SELECT to_jsonb(t) FROM wms.{table} t WHERE {where} LIMIT 1"), {"doc": doc["id"]}
            ).scalar_one()
            for table, where in {
                "product": "true",
                "stock_item": "true",
                "stock_balance": "true",
                "document_line": "document_id=:doc",
                "inventory_transaction": "document_id=:doc",
                "stock_move": "true",
                "audit_event": "after_data ? 'transaction_id'",
                "outbox_event": "payload ? 'transaction_id'",
            }.items()
        }
        c.execute(
            text("""CREATE TEMP TABLE b24_items ON COMMIT DROP AS
            SELECT n, CASE WHEN n=1 THEN CAST(:product AS uuid) ELSE gen_random_uuid() END product,
              CASE WHEN n=1 THEN CAST(:stock AS uuid) ELSE gen_random_uuid() END stock,
              CASE WHEN n=1 THEN CAST(:line AS uuid) ELSE gen_random_uuid() END line
            FROM generate_series(1,:skus) n"""),
            dict(
                product=template["product"]["id"],
                stock=template["stock_item"]["id"],
                line=template["document_line"]["id"],
                skus=profile["skus"],
            ),
        )
        patches = {
            "product": "jsonb_build_object('id',i.product,'sku','B24-STRESS-'||i.n,'name','Synthetic stress '||i.n)",
            "stock_item": "jsonb_build_object('id',i.stock,'product_id',i.product)",
            "document_line": "jsonb_build_object('id',i.line,'line_no',i.n,'product_id',i.product,'source_line_id',NULL)",
            "stock_balance": "jsonb_build_object('id',gen_random_uuid(),'stock_item_id',i.stock,'on_hand',:rounds,'reserved',0)",
        }
        for table, patch in patches.items():
            c.execute(
                text(f"""INSERT INTO wms.{table} SELECT p.* FROM b24_items i CROSS JOIN LATERAL
                jsonb_populate_record(NULL::wms.{table},CAST(:template AS jsonb)||{patch}) p WHERE i.n>1"""),
                dict(template=json.dumps(template[table]), rounds=profile["rounds"]),
            )
        c.execute(
            text("UPDATE wms.stock_balance SET on_hand=:rounds WHERE stock_item_id=:id"),
            dict(rounds=profile["rounds"], id=template["stock_item"]["id"]),
        )
        c.execute(
            text("""CREATE TEMP TABLE b24_transactions ON COMMIT DROP AS
            SELECT n, CASE WHEN n=1 THEN CAST(:tx AS uuid) ELSE gen_random_uuid() END id
            FROM generate_series(1,:rounds) n"""),
            dict(tx=template["inventory_transaction"]["id"], rounds=profile["rounds"]),
        )
        for table, patch in {
            "inventory_transaction": "jsonb_build_object('id',t.id,'execution_key',gen_random_uuid(),'request_hash',NULL,'response',NULL)",
            "audit_event": "jsonb_build_object('id',gen_random_uuid(),'request_id',gen_random_uuid(),'after_data',jsonb_build_object('transaction_id',t.id,'synthetic_b24',true))",
            "outbox_event": "jsonb_build_object('id',gen_random_uuid(),'payload',jsonb_build_object('transaction_id',t.id,'synthetic_b24',true))",
        }.items():
            c.execute(
                text(f"""INSERT INTO wms.{table} SELECT p.* FROM b24_transactions t CROSS JOIN LATERAL
                jsonb_populate_record(NULL::wms.{table},CAST(:template AS jsonb)||{patch}) p WHERE t.n>1"""),
                dict(template=json.dumps(template[table])),
            )
        # Bounded inserts, one round at a time. Do not disable triggers, constraints or indexes.
        for round_no in range(1, profile["rounds"] + 1):
            c.execute(
                text("""INSERT INTO wms.stock_move SELECT p.* FROM b24_items i CROSS JOIN b24_transactions t
                CROSS JOIN LATERAL jsonb_populate_record(NULL::wms.stock_move,CAST(:template AS jsonb)||
                jsonb_build_object('id',gen_random_uuid(),'transaction_id',t.id,'stock_item_id',i.stock,'line_id',i.line)) p
                WHERE t.n=:round AND NOT(t.n=1 AND i.n=1)"""),
                dict(template=json.dumps(template["stock_move"]), round=round_no),
            )
    seed_seconds = time.monotonic() - started
    with f.engine.begin() as c:
        c.exec_driver_sql("ANALYZE")
    started = time.monotonic()
    checks = reconcile(f.engine)
    reconcile_seconds = time.monotonic() - started
    with f.engine.connect() as c:
        counts = {
            table: c.exec_driver_sql(f"SELECT count(*) FROM wms.{table}").scalar_one()
            for table in ("product", "stock_move", "stock_balance", "inventory_transaction")
        }
        size = c.exec_driver_sql("SELECT pg_database_size(current_database())").scalar_one()
        pg = c.exec_driver_sql("SHOW server_version").scalar_one()
    assert counts["product"] == profile["skus"] and counts["stock_move"] == profile["moves"]
    save_evidence(
        "stress-" + profile["name"],
        dict(
            profile=profile,
            actual_dataset=counts,
            seed_seconds=seed_seconds,
            reconcile_seconds=reconcile_seconds,
            reconcile=checks,
            database_bytes=size,
            postgres=pg,
            os=platform.platform(),
            commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
            limitations=[
                "Direct SQL data-volume fixture: does not replay approval/posting/worker workflows",
                "No claim of 15 CCU or representative business mix for this dataset",
                "Expanded synthetic document lines exceed API document-size limits intentionally for storage stress",
            ],
        ),
    )
