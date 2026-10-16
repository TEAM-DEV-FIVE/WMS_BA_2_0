"""Prepare a verified, quiescent staging database; never change app connections.

Requires a fresh staging report containing sequence and DDL evidence. MySQL DDL
is not transactional: an interrupted preparation remains INCOMPLETE and must be
investigated, never automatically adopted by application bootstrap.
"""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pymysql

from apps.server.infrastructure.mysql_migrations import assets
from scripts.build_mysql_schema import quote
from scripts.stage_mysql_data import update_digest


def verify_stage(target, database, report, schema, manifest):
    if database not in {"wms_mysql", "kws_mysql"} or report.get("destination") != database:
        raise ValueError("Destination does not match the staging evidence")
    if report.get("state") != "DATA_VERIFIED_RUNTIME_NOT_READY" or report.get("runtime_activated") is not False:
        raise ValueError("Only a verified, inactive stage may be prepared")
    if report.get("schema_manifest_sha256") != hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest():
        raise ValueError("Schema asset differs from the staged schema")
    sequence = report.get("sequences", {}).get("order_number_seq", {}).get("next_value")
    if type(sequence) is not int or not 1 <= sequence < 2**63:
        raise ValueError("A fresh document sequence capture is required")
    expected = {t["name"]: t for t in schema["tables"]}
    evidence = {t["table"]: t for t in report["tables"]}
    if set(expected) != set(evidence):
        raise ValueError("Incomplete staging evidence")
    with target.cursor() as c:
        c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")
        if {row[0] for row in c} != set(expected):
            raise ValueError("Stage contains unexpected tables or has already been prepared")
        c.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
        if c.fetchone()[0]:
            raise ValueError("Stage already contains runtime triggers")
        c.execute("SELECT COUNT(*) FROM information_schema.referential_constraints WHERE constraint_schema=DATABASE()")
        if c.fetchone()[0] != len(manifest["foreign_keys"]):
            raise ValueError("Foreign-key count differs from the reviewed manifest")
    for name, table in expected.items():
        row = evidence[name]
        if row.get("matches") is not True:
            raise ValueError("Stage contains an unmatched table")
        with target.cursor() as c:
            c.execute("SHOW CREATE TABLE " + quote(name))
            if hashlib.sha256(c.fetchone()[1].encode()).hexdigest() != row.get("ddl_sha256"):
                raise ValueError("Stage DDL changed after verification")
        keys = next(c["columns"] for c in table["constraints"] if c["kind"] == "p")
        query = "SELECT " + ",".join(quote(c["name"]) for c in table["columns"]) + " FROM " + quote(name) + " ORDER BY " + ",".join(map(quote, keys))
        digest, count = hashlib.sha256(), 0
        with target.cursor(pymysql.cursors.SSCursor) as c:
            c.execute(query)
            for values in c:
                update_digest(digest, values, table["columns"])
                count += 1
        if count != row["source_rows"] or digest.hexdigest() != row["source_sha256"]:
            raise ValueError("Stage data changed after verification")
    return sequence


def prepare(credentials, database, report, schema, *, admin_prefix):
    if database not in credentials["databases"]:
        raise ValueError("Destination is not authorized by the credentials file")
    source = assets()
    manifest, guards, _, runtime = [item[2] for item in source[:4]]
    target = pymysql.connect(user=credentials["user"], password=credentials["password"],
                             unix_socket=credentials["unix_socket"], database=database,
                             charset="utf8mb4", autocommit=True)
    key = "wms:migration:" + hashlib.sha256(database.encode()).hexdigest()[:32]
    try:
        with target.cursor() as c:
            c.execute("SET time_zone='+00:00'")
            c.execute("SELECT GET_LOCK(%s,10)", (key,))
            if c.fetchone()[0] != 1:
                raise ValueError("Another migration is preparing this database")
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            c.execute("START TRANSACTION READ ONLY")
        sequence = verify_stage(target, database, report, schema, manifest)
        target.commit()
        with target.cursor() as c:
            c.execute("CREATE TABLE wms_schema_migration(version VARCHAR(100) PRIMARY KEY,sha256 CHAR(64) NOT NULL,state VARCHAR(20) NOT NULL,applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB")
            c.executemany("INSERT INTO wms_schema_migration(version,sha256,state) VALUES (%s,%s,'INCOMPLETE')", [(name, digest) for name, digest, _ in source])
        statements = guards["procedures"] + guards["triggers"] + runtime["tables"] + runtime.get("indexes", []) + runtime.get("triggers", [])
        # The administrative client installs DDL only, never row payloads or secrets.
        sql = "USE " + quote(database) + ";\nDELIMITER $$\n" + "\n".join(statement + "$$" for statement in statements) + "\n"
        completed = subprocess.run([*admin_prefix, "--batch", "--binary-mode", "--skip-column-names"], input=sql, text=True, capture_output=True)
        if completed.returncode:
            raise RuntimeError("Administrative DDL failed; stage remains INCOMPLETE")
        with target.cursor() as c:
            c.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
            if c.fetchone()[0] != len(guards["triggers"]) + len(runtime.get("triggers", [])):
                raise ValueError("Native trigger installation is incomplete")
            c.execute("SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema=DATABASE() AND routine_type='PROCEDURE'")
            if c.fetchone()[0] != len(guards["procedures"]):
                raise ValueError("Native procedure installation is incomplete")
            c.execute("ALTER TABLE order_number_sequence AUTO_INCREMENT=" + str(sequence))
        target.begin()
        adjustments = {}
        with target.cursor() as c:
            if database == "kws_mysql":
                c.execute("INSERT INTO migration_outbox_archive(event_id,reason) SELECT id,'COPIED_WMS_HISTORY' FROM outbox_event")
                adjustments["archived_outbox_rows"] = c.rowcount
                c.execute("UPDATE auth_session SET revoked_at=UTC_TIMESTAMP(6) WHERE revoked_at IS NULL")
                adjustments["revoked_copied_sessions"] = c.rowcount
                for name in ["auth_challenge", "auth_contact_challenge", "auth_google_flow", "auth_password_reset", "auth_self_reset", "auth_delivery", "auth_token"]:
                    c.execute("UPDATE " + quote(name) + " SET expires_at=UTC_TIMESTAMP(6) WHERE expires_at>UTC_TIMESTAMP(6)")
                    adjustments["expired_" + name] = c.rowcount
                c.execute("UPDATE auth_recovery_code SET revoked_at=UTC_TIMESTAMP(6) WHERE revoked_at IS NULL")
                adjustments["revoked_copied_recovery_codes"] = c.rowcount
            c.execute("UPDATE wms_schema_migration SET state='COMPLETE'")
        target.commit()
        return dict(destination=database, state="RUNTIME_PREPARED_NOT_ACTIVATED", runtime_activated=False,
                    prepared_at=datetime.now(UTC).isoformat(), next_document_number=sequence,
                    verified_tables=len(schema["tables"]), adjustments=adjustments,
                    assets={name: digest for name, digest, _ in source})
    finally:
        target.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, choices=["wms_mysql", "kws_mysql"])
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sudo-local-admin", action="store_true", help="Use authorized local sudo -n mysql for native trigger DDL")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = prepare(json.loads(args.credentials.read_text()), args.database, json.loads(args.stage_report.read_text()),
                         json.loads((root / "02_CSDL/current/schema.json").read_text()),
                         admin_prefix=["sudo", "-n", "mysql"] if args.sudo_local_admin else ["mysql"])
    except Exception as error:
        raise SystemExit(f"Preparation failed ({type(error).__name__}); application connections were not changed.") from None
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2)
    print(result["state"], result["verified_tables"], "verified tables")


if __name__ == "__main__":
    main()
