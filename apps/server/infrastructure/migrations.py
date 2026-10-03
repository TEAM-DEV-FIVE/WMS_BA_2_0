"""Explicit forward-only runner; never called on API startup."""

import hashlib
from importlib.resources import files

from sqlalchemy import Engine, text

MIGRATION_LOCK = 871624920031


class MigrationError(RuntimeError):
    pass


def migration_sources() -> list[tuple[str, str, str]]:
    result = []
    for path in sorted(files("migrations").iterdir(), key=lambda p: p.name):
        if path.name.endswith(".sql"):
            raw = path.read_bytes()
            result.append((path.name, hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")))
    if not result:
        raise MigrationError("No packaged migrations found")
    return result


def expected_revisions() -> dict[str, str]:
    return {name: digest for name, digest, _ in migration_sources()}


def migrate(engine: Engine) -> list[str]:
    """Apply all pending revisions atomically under a database-wide advisory lock."""
    applied = []
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS public.wms_schema_migration (
              version text PRIMARY KEY, sha256 char(64) NOT NULL,
              applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )
        """))
        actual = dict(connection.execute(text("SELECT version, sha256 FROM public.wms_schema_migration")).tuples().all())
        sources = migration_sources()
        names = [name for name, _, _ in sources]
        if sorted(actual) != names[:len(actual)]:
            raise MigrationError("Migration history is not a prefix of this release; use the matching release")
        for name, digest, sql in sources:
            if name in actual:
                if actual[name] != digest:
                    raise MigrationError(f"Applied migration checksum changed: {name}")
                continue
            if not actual and not applied and connection.execute(
                text("SELECT to_regnamespace('wms')")
            ).scalar_one() is not None:
                raise MigrationError("Existing unmanaged wms schema: use a new development database; no automatic adoption")
            # The immutable design scripts include their own transaction wrapper.
            # Remove only the exact outer lines; runner owns the enclosing transaction.
            lines = sql.splitlines()
            meaningful = [i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("--")]
            if lines[meaningful[0]].strip() == "BEGIN;" and lines[meaningful[-1]].strip() == "COMMIT;":
                lines[meaningful[0]] = ""
                lines[meaningful[-1]] = ""
            connection.exec_driver_sql("\n".join(lines), execution_options={"no_parameters": True})
            connection.execute(text("INSERT INTO public.wms_schema_migration(version,sha256) VALUES (:v,:s)"),
                               {"v": name, "s": digest})
            applied.append(name)
    return applied


def is_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        if connection.execute(text("SELECT to_regclass('public.wms_schema_migration')")).scalar_one() is None:
            return False
        actual = dict(connection.execute(text("SELECT version,sha256 FROM public.wms_schema_migration")).tuples().all())
        return actual == expected_revisions()


def main() -> None:
    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    from apps.server.infrastructure.config import Settings
    from apps.server.infrastructure.database import make_engine

    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("Cấu hình không hợp lệ. Kiểm tra WMS_DATABASE_URL (PostgreSQL), port và timeout.") from None
    engine = make_engine(settings)
    try:
        applied = migrate(engine)
        print("Applied: " + ", ".join(applied) if applied else "Database is up to date.")
    except MigrationError as exc:
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit("Migration thất bại; transaction đã rollback. Kiểm tra kết nối/quyền và log PostgreSQL.") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
