"""Extract public bootstrap rows from immutable migrations in disposable PG."""

import getpass
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from apps.server.infrastructure.migrations import migrate

ROOT = Path(__file__).resolve().parents[1]


def serialize(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ")
    raise TypeError(type(value).__name__)


def main():
    binaries = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with tempfile.TemporaryDirectory(prefix="wms-mysql-seed-") as temporary:
        directory = Path(temporary)
        data = directory / "data"
        subprocess.run([binaries / "initdb", "-D", data, "--auth=trust", "--no-locale", "--encoding=UTF8"], check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run([binaries / "pg_ctl", "-D", data, "-l", directory / "postgres.log", "-o", f"-k '{temporary}' -c listen_addresses=''", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run([binaries / "createdb", "-h", temporary, "wms_test_mysql_seed"], check=True)
            engine = create_engine(URL.create("postgresql+psycopg", username=getpass.getuser(), database="wms_test_mysql_seed", query={"host": temporary}))
            migrate(engine)
            result = []
            schema = json.loads((ROOT / "02_CSDL/current/schema.json").read_text())
            with engine.connect() as connection:
                for table in schema["tables"]:
                    rows = connection.execute(text('SELECT * FROM wms."'+table['name']+'"')).mappings().all()
                    if rows:
                        result.append({"table": table["name"], "rows": [dict(r) for r in rows]})
            engine.dispose()
            (ROOT / "mysql_migrations/003_seed.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=serialize) + "\n")
            print("Bootstrap:", len(result), "tables;", sum(len(t["rows"]) for t in result), "rows")
        finally:
            if (data / "postmaster.pid").exists():
                subprocess.run([binaries / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
