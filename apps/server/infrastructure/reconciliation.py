"""Execute every read-only reconciliation query on either supported database."""

import re

import sqlglot
from sqlalchemy import text
from sqlglot import exp


def reconciliation_results(connection, source):
    source = re.sub(r"(?im)^\s*SET search_path TO wms, public;\s*$", "", source)
    statements = [statement for statement in sqlglot.parse(source, read="postgres") if statement is not None]
    if not statements or not all(isinstance(statement, exp.Query) for statement in statements):
        raise ValueError("Reconciliation scripts must contain read-only queries")
    if connection.dialect.name == "postgresql":
        connection.execute(text("SET LOCAL search_path TO wms, public"))
    return [connection.execute(text(statement.sql(dialect="postgres"))).all() for statement in statements]
