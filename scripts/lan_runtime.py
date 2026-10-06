"""LAN service entry point. Copy beside the immutable release, outside site-packages.

Config is deliberately NOT a shell script. Credentials arrive through systemd.
No migration on service startup, no exception values in operational output.
"""

import argparse
import json
import logging
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

KINDS = ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")
FACTORY = "apps.server.consumers.registry:consumer_factory"


def read_config(path, *, secret=False):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & (0o077 if secret else 0o022):
            raise ValueError("Unsafe config permissions")
        result = {}
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or not re.fullmatch(r"WMS_[A-Z0-9_]+", key) or key in result or not value:
                raise ValueError("Invalid config")
            # Values are literal: no quote removal, interpolation, eval or shell source.
            if any(ord(c) < 32 for c in value):
                raise ValueError("Invalid config")
            result[key] = value
    return result


def configure(config, credential):
    values = read_config(config)
    secrets = read_config(credential, secret=True)
    if set(secrets) != {"WMS_MFA_ENCRYPTION_KEY"} or "WMS_MFA_ENCRYPTION_KEY" in values:
        raise ValueError("Separate the MFA credential")
    # Ignore inherited settings, including unexpected storage/registry overrides.
    for key in list(os.environ):
        if key.startswith("WMS_"):
            del os.environ[key]
    os.environ.update(values | secrets)
    os.umask(0o077)


def validate_config(*, migration=False):
    from sqlalchemy.engine import make_url

    from apps.server.application.exports import ExportSettings
    from apps.server.application.printing import PrintSettings
    from apps.server.infrastructure.config import Settings
    from apps.server.infrastructure.file_storage import ImportSettings
    from apps.server.worker import WorkerSettings

    settings = Settings()
    allowed = {"WMS_" + name.upper() for name in Settings.model_fields}
    for prefix, model in (("WMS_OUTBOX_", WorkerSettings), ("WMS_IMPORT_", ImportSettings),
                          ("WMS_EXPORT_", ExportSettings), ("WMS_PRINT_", PrintSettings)):
        allowed.update(prefix + name.upper() for name in model.model_fields)
    if any(key.startswith("WMS_") and key not in allowed for key in os.environ):
        raise ValueError("Unknown deployment setting")
    url = make_url(settings.database_url.get_secret_value())
    # This profile uses peer auth over a local Unix socket, with separate OS/DB users.
    expected = "wms_owner" if migration else "wms_app"
    if (url.username != expected or url.password is not None or url.host or url.port
            or dict(url.query) != {"host": "/var/run/postgresql"} or url.database != "wms"):
        raise ValueError("Use the LAN peer-auth database profile")
    if settings.host != "127.0.0.1" or settings.port != 8000 or settings.mfa_encryption_key is None:
        raise ValueError("API must remain private and MFA key configured")
    worker = WorkerSettings()
    if worker.consumer_factory != FACTORY:
        raise ValueError("Use the release registry")
    roots = [s.storage_root for s in (ImportSettings(), ExportSettings(), PrintSettings())]
    for root in roots:
        if (not root.is_absolute() or root.is_symlink() or root.resolve() != root
                or not root.is_dir() or root.stat().st_mode & 0o077):
            raise ValueError("Storage must be an existing private canonical directory")
    if len(set(roots)) != 3 or any(a in b.parents for a in roots for b in roots if a != b):
        raise ValueError("Storage roots overlap")
    return settings, worker, roots


def database_check(engine, *, migration=False):
    from sqlalchemy import text

    from apps.server.infrastructure.migrations import is_ready

    with engine.connect() as c:
        version = int(c.execute(text("SHOW server_version_num")).scalar_one()) // 10000
        role = c.execute(text("""SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls
            FROM pg_roles WHERE rolname=current_user""")).one()
        if version != 16 or any(role):
            raise ValueError("Unsupported PostgreSQL or privileged role")
        if not migration:
            unsafe = c.execute(text("""SELECT
                has_database_privilege(current_database(), 'CREATE') OR
                has_schema_privilege('public', 'CREATE') OR
                has_schema_privilege('wms', 'CREATE') OR
                EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles
                  WHERE rolname=current_user)) OR
                EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                  WHERE n.nspname IN ('wms','public') AND c.relowner=(SELECT oid FROM pg_roles
                  WHERE rolname=current_user))""")).scalar_one()
            if unsafe:
                raise ValueError("Runtime must not own or create schema objects")
    if not migration and not is_ready(engine):
        raise ValueError("Schema is not the exact release")


def check(settings, roots):
    from apps.server.infrastructure.database import make_engine

    engine = make_engine(settings)
    try:
        database_check(engine)
        # Probe real write/fsync/unlink permissions, without retaining an object.
        for root in roots:
            with tempfile.NamedTemporaryFile(prefix=".wms-probe-", dir=root) as f:
                f.write(b"wms readiness\n")
                f.flush()
                os.fsync(f.fileno())
    finally:
        engine.dispose()


def workers_ready(engine, registry_hash):
    from sqlalchemy import text

    with engine.connect() as c:
        rows = c.execute(text("""SELECT kind,registry_hash FROM wms.worker_status
            WHERE state IN ('IDLE','BUSY') AND heartbeat_at > clock_timestamp()-interval '120 seconds'
        """)).all()
    return set(KINDS) <= {r.kind for r in rows if r.registry_hash == registry_hash} and all(
        r.registry_hash == registry_hash for r in rows
    )


def api_ready():
    import urllib.request

    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with client.open("http://127.0.0.1:8000/api/v1/ready", timeout=5) as response:
        return response.status == 200 and json.loads(response.read(4096)).get("status") == "ready"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "api", "worker", "migrate", "bootstrap", "monitor"))
    parser.add_argument("--config", type=Path, default=Path("/etc/wms/runtime.env"))
    parser.add_argument("--credential", type=Path)
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    args = parser.parse_args(argv)
    try:
        credential = args.credential or Path(os.environ["CREDENTIALS_DIRECTORY"]) / "mfa.env"
        configure(args.config, credential)
        settings, worker, roots = validate_config(migration=args.action == "migrate")
        if args.action == "migrate":
            from apps.server.infrastructure.database import make_engine
            from apps.server.infrastructure.migrations import migrate

            engine = make_engine(settings)
            try:
                database_check(engine, migration=True)
                applied = migrate(engine)
                print(json.dumps({"event": "migration_complete", "revisions": applied}))
            finally:
                engine.dispose()
            return 0
        check(settings, roots)
        if args.action == "check":
            print('{"event":"preflight","ready":true}')
            return 0
        if args.action == "monitor":
            from apps.server.consumers.registry import fingerprint
            from apps.server.infrastructure.database import make_engine
            from apps.server.worker import load_registry

            engine = make_engine(settings)
            try:
                ready = workers_ready(engine, fingerprint(load_registry(worker.consumer_factory))) and api_ready()
            finally:
                engine.dispose()
            print(json.dumps({"event": "worker_readiness", "ready": ready}))
            return 0 if ready else 1
        if args.action == "api":
            import uvicorn

            from apps.server.api.app import create_app

            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
            uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False,
                        proxy_headers=False, timeout_graceful_shutdown=60)
            return 0
        if args.action == "bootstrap":
            if not args.username or not args.display_name or not sys.stdin.isatty():
                raise ValueError("Bootstrap requires a terminal and user name")
            from apps.server.bootstrap import main as bootstrap

            sys.argv = ["bootstrap", "--username", args.username, "--display-name", args.display_name]
            bootstrap()
            return 0
        if not args.kind:
            raise ValueError("Worker kind required")
        if args.kind == "outbox":
            from apps.server.worker import main as run

            return run([])
        from apps.server.operations_worker import main as run

        return run(["--kind", args.kind])
    except Exception:
        # Never render validation/SQL/OS exceptions: they can contain DSN, keys or payloads.
        print('{"event":"lan_start_failed","code":"CHECK_CONFIG_DB_STORAGE"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
