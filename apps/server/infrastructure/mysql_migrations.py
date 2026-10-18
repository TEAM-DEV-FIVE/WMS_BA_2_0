"""Forward-only MySQL bootstrap with explicit DDL progress and fail-closed readiness."""

import hashlib
import json
from importlib.resources import files


def assets():
    root = files("mysql_migrations")
    names = ["001_schema.staging.json", "002_guards.staging.json", "003_seed.json", "004_runtime.json", "column_types.json", "column_order.json"]
    return [(name, hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest(),
             json.loads(root.joinpath(name).read_text(encoding="utf-8"))) for name in names]


def native(connection, sql, parameters=None):
    return connection.native(sql, parameters)


def is_ready(engine):
    with engine.connect() as c:
        exists = native(c, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='wms_schema_migration'").scalar_one()
        if not exists:
            return False
        actual = dict(native(c, "SELECT version,sha256 FROM wms_schema_migration WHERE state='COMPLETE'").tuples().all())
        return actual == {name: digest for name, digest, _ in assets()}


def migrate(engine):
    from apps.server.infrastructure.migrations import MigrationError

    source = assets()
    schema, guards, seed, runtime = [item[2] for item in source[:4]]
    with engine.connect() as c:
        driver = c.connection.driver_connection
        read_timeout = driver._read_timeout
        # Schema DDL may legitimately exceed the interactive query timeout.
        # This applies only to this bootstrap session, never runtime requests.
        driver._read_timeout = max(read_timeout or 0, 300)
        key = "wms:migration:" + hashlib.sha256(engine.url.database.encode()).hexdigest()[:32]
        acquired = False
        try:
            acquired = native(c, "SELECT GET_LOCK(:key,10)", {"key": key}).scalar_one() == 1
            if not acquired:
                raise MigrationError("Another MySQL migration owns the database lock")
            c.commit()
            tables = set(native(c, "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()").scalars())
            if tables:
                if "wms_schema_migration" not in tables:
                    raise MigrationError("Existing unmanaged/staging MySQL database; no automatic adoption")
                actual = dict(native(c, "SELECT version,sha256 FROM wms_schema_migration WHERE state='COMPLETE'").tuples().all())
                if actual == {name: digest for name, digest, _ in source}:
                    return []
                raise MigrationError("Incomplete or different MySQL schema; inspect DDL progress before recovery")
            native(c, "CREATE TABLE wms_schema_migration(version VARCHAR(100) PRIMARY KEY,sha256 CHAR(64) NOT NULL,state VARCHAR(20) NOT NULL,applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)) ENGINE=InnoDB")
            for name, digest, _ in source:
                native(c, "INSERT INTO wms_schema_migration(version,sha256,state) VALUES (:name,:hash,'INCOMPLETE')", {"name": name, "hash": digest})
            c.commit()
            for statement in schema["tables"]:
                native(c, statement)
            for table in seed:
                for row in table["rows"]:
                    values = {key: json.dumps(value, allow_nan=False) if isinstance(value, (dict, list)) else value for key, value in row.items()}
                    query = "INSERT INTO `"+table["table"]+"` ("+",".join("`"+col+"`" for col in values)+") VALUES ("+",".join(":"+col for col in values)+")"
                    native(c, query, values)
            c.commit()
            for statement in schema["foreign_keys"] + guards["procedures"] + guards["triggers"]:
                native(c, statement)
            for statement in runtime["tables"] + runtime.get("indexes", []) + runtime.get("triggers", []):
                native(c, statement)
            native(c, "UPDATE wms_schema_migration SET state='COMPLETE'")
            c.commit()
            return [name for name, _, _ in source]
        finally:
            driver._read_timeout = read_timeout
            if acquired and not c.invalidated:
                try:
                    c.rollback()
                    native(c, "SELECT RELEASE_LOCK(:key)", {"key": key})
                    c.commit()
                except Exception:
                    # Never return a connection with a session lock to the pool.
                    c.invalidate()
