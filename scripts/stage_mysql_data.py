"""Copy a read-only PostgreSQL snapshot to a NEW, EMPTY MySQL staging database.

No application settings are changed. Runtime activation is deliberately separate.
Never disables foreign-key checking: foreign keys are added and validated after
the complete copy, supporting the cycles in the document/stock graph.
"""

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pymysql
from sqlalchemy import create_engine, text

from scripts.build_mysql_schema import quote


def canonical(value, kind):
    if value is None:
        return None
    if kind in {"jsonb", "uuid[]"}:
        if isinstance(value, str):
            value = json.loads(value, parse_float=Decimal)
        return json_value(value)
    if kind == "boolean":
        return bool(value)
    if kind == "timestamp with time zone":
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    return value


def json_value(value):
    if isinstance(value, dict):
        return ["object", [[k, json_value(v)] for k, v in sorted(value.items())]]
    if isinstance(value, list):
        return ["array", [json_value(x) for x in value]]
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, (Decimal, int)):
        # No Decimal.normalize(): the default context would round >28 digits.
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError("Non-finite JSON number")
        sign, digits, exponent = number.as_tuple()
        digits = list(digits)
        while len(digits) > 1 and digits[-1] == 0:
            digits.pop()
            exponent += 1
        return ["number", [sign, digits, exponent] if number else [0, [0], 0]]
    if isinstance(value, UUID):
        value = str(value)
    if isinstance(value, str):
        return ["string", value]
    raise ValueError("Unsupported JSON value type")


def update_digest(digest, record, columns):
    values = [canonical(value, column["type"]) for value, column in zip(record, columns, strict=True)]
    raw = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)


def mysql_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def available_bytes(path):
    location = Path(path)
    while True:
        try:
            return shutil.disk_usage(location).free
        except PermissionError:
            if location == location.parent:
                raise
            location = location.parent


def verify_schema(connection, schema):
    actual = connection.execute(text("""
        SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), NOT a.attnotnull
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='wms' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum
    """)).all()
    expected = [(t["name"], c["name"], c["type"], c["nullable"])
                for t in sorted(schema["tables"], key=lambda t: t["name"]) for c in t["columns"]]
    if actual != expected:
        raise ValueError("Source column types/order/nullability differ from reviewed schema")


def stage(source_url, credentials, database, schema, manifest, report_path):
    if database not in credentials["databases"] or database not in {"wms_mysql", "kws_mysql"}:
        raise ValueError("Destination must be one of the two explicitly configured staging databases")
    target = pymysql.connect(user=credentials["user"], password=credentials["password"],
                             unix_socket=credentials["unix_socket"], database=database,
                             charset="utf8mb4", autocommit=True)
    source = create_engine(source_url, hide_parameters=True, isolation_level="REPEATABLE READ")
    report = {"destination": database, "state": "INCOMPLETE", "started_at": datetime.now(UTC).isoformat(),
              "runtime_activated": False, "tables": [],
              "schema_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    try:
        with target.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()")
            if cursor.fetchone()[0]:
                raise ValueError("Refusing to overwrite a nonempty destination")
            cursor.execute("SET time_zone='+00:00', foreign_key_checks=1, unique_checks=1")
            cursor.execute("SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
        with source.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            report["source_snapshot"] = connection.execute(text("SELECT txid_current_snapshot()::text")).scalar_one()
            # Sequences are deliberately outside MVCC. The final transfer must
            # quiesce writers before capturing this value and activating MySQL.
            sequence = connection.execute(text("SELECT last_value,is_called FROM wms.order_number_seq")).mappings().one()
            report["sequences"] = {"order_number_seq": {"last_value": sequence["last_value"], "is_called": sequence["is_called"],
                "next_value": sequence["last_value"] + (1 if sequence["is_called"] else 0)}}
            # Reject schema drift; copying a schema revision the port did not review is unsafe.
            names = connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='wms' AND table_type='BASE TABLE' ORDER BY table_name")).scalars().all()
            if names != sorted(t["name"] for t in schema["tables"]):
                raise ValueError("Source tables differ from reviewed schema")
            verify_schema(connection, schema)
            size = connection.execute(text("SELECT COALESCE(SUM(pg_total_relation_size(c.oid)),0) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wms' AND c.relkind='r'")).scalar_one()
            with target.cursor() as cursor:
                cursor.execute("SELECT @@datadir,@@tmpdir")
                directories = cursor.fetchone()
            required = max(1024 ** 3, int(size) * 3)
            free = min(available_bytes(path) for path in directories)
            report["disk_preflight"] = {"source_bytes": int(size), "required_free_bytes": required, "available_bytes": free}
            if free < required:
                raise ValueError("Insufficient disk space for staging and verification; no tables created")
            for bound in manifest["bounded_text"]:
                actual = connection.execute(text('SELECT max(length("'+bound['column']+'")) FROM wms."'+bound['table']+'"')).scalar_one() or 0
                if actual > bound["max_length"]:
                    raise ValueError("Source identity exceeds reviewed MySQL index length")
            with target.cursor() as cursor:
                for statement in manifest["tables"]:
                    cursor.execute(statement)
            target.begin()
            for table in schema["tables"]:
                columns = table["columns"]
                name = table["name"]
                keys = next(c["columns"] for c in table["constraints"] if c["kind"] == "p")
                select = []
                for col in columns:
                    item = '"'+col['name']+'"'
                    if col["type"] == "jsonb":
                        item += "::text"
                    elif col["type"] == "uuid[]":
                        item = "to_json(" + item + ")::text"
                    select.append(item)
                statement = 'SELECT ' + ','.join(select) + ' FROM wms."' + name + '" ORDER BY ' + ','.join('"'+x+'"' for x in keys)
                digest, count = hashlib.sha256(), 0
                rows = connection.execution_options(stream_results=True).execute(text(statement))
                insert = f"INSERT INTO {quote(name)} ("+','.join(quote(x['name']) for x in columns)+") VALUES ("+','.join(['%s']*len(columns))+")"
                for batch in rows.partitions(500):
                    for row in batch:
                        update_digest(digest, row, columns)
                    with target.cursor() as cursor:
                        cursor.executemany(insert, [tuple(mysql_value(v) for v in row) for row in batch])
                    count += len(batch)
                rows.close()
                report["tables"].append({"table": name, "source_rows": count, "source_sha256": digest.hexdigest()})
            target.commit()
        # DDL commits implicitly in MySQL; this stage is kept explicitly separate.
        with target.cursor() as cursor:
            for statement in manifest["foreign_keys"]:
                cursor.execute(statement)
        for table, result in zip(schema["tables"], report["tables"], strict=True):
            columns = table["columns"]
            keys = next(c["columns"] for c in table["constraints"] if c["kind"] == "p")
            query = "SELECT " + ','.join(quote(c['name']) for c in columns) + " FROM " + quote(table['name']) + " ORDER BY " + ','.join(quote(x) for x in keys)
            digest, count = hashlib.sha256(), 0
            with target.cursor(pymysql.cursors.SSCursor) as cursor:
                cursor.execute(query)
                for row in cursor:
                    update_digest(digest, row, columns)
                    count += 1
            with target.cursor() as cursor:
                cursor.execute("SHOW CREATE TABLE " + quote(table["name"]))
                ddl = cursor.fetchone()[1]
            result.update(target_rows=count, target_sha256=digest.hexdigest(), ddl_sha256=hashlib.sha256(ddl.encode()).hexdigest())
            result["matches"] = count == result["source_rows"] and digest.hexdigest() == result["source_sha256"]
        if not all(x["matches"] for x in report["tables"]):
            raise ValueError("Data comparison failed; destination must not be activated")
        report.update(state="DATA_VERIFIED_RUNTIME_NOT_READY", foreign_keys_validated=len(manifest["foreign_keys"]),
                      completed_at=datetime.now(UTC).isoformat())
        return report
    finally:
        target.rollback()
        target.close()
        source.dispose()
        report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, choices=["wms_mysql", "kws_mysql"])
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    values = {}
    for line in args.source_env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().strip("\"'")
    root = Path(__file__).resolve().parents[1]
    try:
        result = stage(values["WMS_DATABASE_URL"], json.loads(args.credentials.read_text()), args.database,
                       json.loads((root / "02_CSDL/current/schema.json").read_text()),
                       json.loads((root / "mysql_migrations/001_schema.staging.json").read_text()), args.report)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # Database errors may embed source values; do not dump credentials/data.
        raise SystemExit(f"Staging failed ({type(error).__name__}); target is NOT ready. See the private report.") from None
    print(result["state"], len(result["tables"]), "tables;", sum(t["target_rows"] for t in result["tables"]), "rows")


if __name__ == "__main__":
    main()
