"""Count the same authorized result set without its cursor or row limit."""
from sqlalchemy import text


def counted_rows(connection, statement, params):
    sql = str(statement).strip().rstrip(";")
    # All callers use a nullable `after` predicate and LIMIT :limit. Preserve
    # every search, warehouse and actor predicate in both reads.
    total = connection.execute(text(f"SELECT count(*) FROM ({sql}) AS matching_rows"),
                               {**params, "after": None, "limit": None}).scalar_one()
    rows = connection.execute(statement, params).mappings().all()
    return rows, total
