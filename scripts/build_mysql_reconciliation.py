"""Generate native read-only MySQL reconciliation scripts from reviewed queries."""

import re
from pathlib import Path

import sqlglot
from sqlglot import exp

from apps.server.infrastructure.mysql_sql import lower

ROOT = Path(__file__).resolve().parents[1]


def build():
    target = ROOT / "02_CSDL/mysql"
    target.mkdir(exist_ok=True)
    for path in sorted((ROOT / "02_CSDL").glob("reconcile*.sql")):
        source = re.sub(r"(?im)^\s*SET search_path TO wms, public;\s*$", "", path.read_text())
        statements = [item for item in sqlglot.parse(source, read="postgres") if item is not None]
        if not statements or not all(isinstance(item, exp.Query) for item in statements):
            raise ValueError("Only read-only reconciliation queries are accepted")
        (target / path.name).write_text(";\n\n".join(lower(item) for item in statements) + ";\n")


if __name__ == "__main__":
    build()
