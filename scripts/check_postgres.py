"""Test SQL in a temporary local PostgreSQL cluster (Linux/macOS, non-root)."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    result = subprocess.run([str(arg) for arg in args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bindir", type=Path, help="Select PG15/16 binaries explicitly")
    parser.add_argument("--expected-pg-major", type=int, choices=(15, 16))
    args = parser.parse_args()
    if not args.pg_bindir and not shutil.which("pg_config"):
        raise RuntimeError("Install PostgreSQL 15+ server tools (pg_config, initdb, pg_ctl, psql).")
    binaries = args.pg_bindir or Path(run("pg_config", "--bindir"))
    with tempfile.TemporaryDirectory(prefix="wms-sql-") as temporary:
        data = Path(temporary) / "data"
        log = Path(temporary) / "postgres.log"
        run(binaries / "initdb", "-D", data, "--auth=trust", "--no-locale", "--encoding=UTF8")
        try:
            run(binaries / "pg_ctl", "-D", data, "-l", log, "-o",
                f"-k '{temporary}' -c listen_addresses=''", "-w", "start")
            psql = [binaries / "psql", "-X", "-qAt", "-h", temporary, "-d", "postgres", "-v", "ON_ERROR_STOP=1"]
            print(run(*psql, "-c", "SELECT version()"))
            major = int(run(*psql, "-c", "SHOW server_version_num")) // 10000
            if major < 15 or (args.expected_pg_major and major != args.expected_pg_major):
                raise RuntimeError(f"Unexpected PostgreSQL major {major}")
            for name in ("02_CSDL/001_schema.sql", "02_CSDL/002_seed_permissions.sql", "tests/sql/schema_smoke.sql"):
                run(*psql, "-f", ROOT / name)
                print(f"PASS {name}")
            # Compare real PostgreSQL columns with the source model, not only counts.
            rows = run(*psql, "-c", """
                SELECT json_build_array(c.relname,a.attname,format_type(a.atttypid,a.atttypmod),NOT a.attnotnull)
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                WHERE c.relnamespace='wms'::regnamespace AND c.relkind='r'
                  AND a.attnum>0 AND NOT a.attisdropped;
            """)
            actual = {tuple(json.loads(row)) for row in rows.splitlines()}
            aliases = {"varchar": "character varying", "char": "character", "timestamptz": "timestamp with time zone"}
            def pg_type(value):
                for short, full in aliases.items():
                    if value == short or value.startswith(short + "("):
                        return full + value[len(short):]
                return value
            model = json.loads((ROOT / "02_CSDL/model.json").read_text(encoding="utf-8"))
            expected = {(t["name"], c["name"], pg_type(c["type"]), c["null"]) for t in model for c in t["cols"]}
            if actual != expected:
                raise RuntimeError(f"SQL/model columns differ: missing={expected-actual}, extra={actual-expected}")
            policy = json.loads((ROOT / "04_Phan_quyen/policy.json").read_text(encoding="utf-8"))
            rows = run(*psql, "-c", """
                SELECT json_build_array(r.code,p.code) FROM wms.role_permission rp
                JOIN wms.role r ON r.id=rp.role_id JOIN wms.permission p ON p.id=rp.permission_id;
            """)
            actual = {tuple(json.loads(row)) for row in rows.splitlines()}
            expected = {(role, p["code"]) for p in policy["permissions"] for role in p["roles"]}
            if actual != expected:
                raise RuntimeError("PostgreSQL RBAC seed differs from policy.json")
            if run(*psql, "-f", ROOT / "02_CSDL/reconcile.sql"):
                raise RuntimeError("Reconciliation returned unexpected rows after fixture rollback")
            print("PASS PostgreSQL/model columns, RBAC policy and empty-database reconciliation")
        finally:
            if (data / "postmaster.pid").exists():
                run(binaries / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as exc:
        raise SystemExit(f"FAIL: {exc}")
