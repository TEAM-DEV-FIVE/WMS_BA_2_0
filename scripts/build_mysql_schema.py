"""Build reviewable MySQL DDL from the immutable PostgreSQL schema inventory.

This is a build tool, not a runtime SQL translator. It never connects to a DB.
The generated schema is staging-only until triggers and application checks pass.
"""

import hashlib
import json
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", value):
        raise ValueError(f"Unexpected SQL identifier: {value!r}")
    return f"`{value}`"


def unwrap(node):
    while isinstance(node, (exp.Paren, exp.Cast)):
        node = node.this
    return node


def expression(source):
    tree = sqlglot.parse_one(source, read="postgres")

    def convert(node):
        if isinstance(node, exp.DataType) and node.this == exp.DataType.Type.JSONB:
            return exp.DataType.build("JSON")
        if isinstance(node, exp.EQ) and isinstance(node.expression, exp.Any):
            values = unwrap(node.expression.this)
            if not isinstance(values, exp.Array):
                raise ValueError("Only constant arrays are allowed in schema expressions")
            return exp.In(this=node.this.copy(), expressions=[unwrap(x).copy() for x in values.expressions])
        if isinstance(node, exp.Cast) and node.to.this in {exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR}:
            # PostgreSQL catalog casts around text comparisons are redundant.
            if not any(isinstance(x, exp.Column) and x.name in {"values"} for x in node.this.walk()):
                return node.this.copy()
        if isinstance(node, exp.Anonymous):
            if node.name.lower() == "jsonb_typeof":
                return exp.Lower(this=exp.Anonymous(this="JSON_TYPE", expressions=node.expressions))
            if node.name.lower() == "clock_timestamp":
                return exp.Anonymous(this="CURRENT_TIMESTAMP", expressions=[exp.Literal.number(6)])
        return node

    # Revisit copied child nodes after rewriting an ANY expression.
    for _ in range(3):
        tree = tree.transform(convert)
    for node in tree.find_all(exp.Identifier):
        node.set("quoted", True)
    if tree.find(exp.Any) or tree.find(exp.Array):
        raise ValueError(f"Unsupported array in {source}")
    return tree.sql(dialect="mysql", unsupported_level=sqlglot.ErrorLevel.RAISE)


def column_type(column):
    kind = column["type"]
    simple = {"uuid": "CHAR(36) CHARACTER SET ascii COLLATE ascii_bin",
              "uuid[]": "JSON", "jsonb": "JSON", "text": "LONGTEXT",
              "boolean": "BOOLEAN", "integer": "INT", "bigint": "BIGINT",
              "date": "DATE", "timestamp with time zone": "DATETIME(6)"}
    if kind in simple:
        return simple[kind]
    for source, target in [("character varying", "VARCHAR"), ("character", "CHAR"), ("numeric", "DECIMAL")]:
        if kind.startswith(source + "("):
            return target + kind[len(source):]
    raise ValueError(f"Unmapped type: {kind}")


def short_name(name):
    return name if len(name) <= 64 else name[:51] + "_" + hashlib.sha256(name.encode()).hexdigest()[:12]


def build(schema):
    tables, foreign_keys, inventory = [], [], []
    for table in schema["tables"]:
        name = table["name"]
        columns = {c["name"]: c for c in table["columns"]}
        entries = []
        for c in columns.values():
            part = quote(c["name"]) + " " + column_type(c)
            if not c["nullable"]:
                part += " NOT NULL"
            if c["default"] is not None:
                part += " DEFAULT (" + expression(c["default"]) + ")"
            entries.append(part)
            if c["type"] == "boolean":
                entries.append(f"CONSTRAINT {quote(short_name(name+'_'+c['name']+'_bool'))} CHECK ({quote(c['name'])} IN (0,1))")
        primary = next(c for c in table["constraints"] if c["kind"] == "p")
        entries.append("PRIMARY KEY (" + ",".join(quote(c) for c in primary["columns"]) + ")")
        for constraint in table["constraints"]:
            kind = constraint["kind"]
            cname = short_name(constraint["name"])
            if kind == "c":
                entries.append(f"CONSTRAINT {quote(cname)} CHECK {expression(constraint['definition'][6:])}")
            elif kind == "f":
                keys = ",".join(quote(x) for x in constraint["columns"])
                targets = ",".join(quote(x) for x in constraint["target_columns"])
                action = re.search(r" ON DELETE (RESTRICT|CASCADE|SET NULL|NO ACTION)", constraint["definition"])
                statement = f"ALTER TABLE {quote(name)} ADD CONSTRAINT {quote(cname)} FOREIGN KEY ({keys}) REFERENCES {quote(constraint['target'])} ({targets})"
                if action:
                    statement += action.group(0)
                foreign_keys.append(statement)
        for source in table["indexes"]:
            if source.split()[3 if source.startswith("CREATE UNIQUE") else 2] == primary["name"]:
                continue
            not_distinct = " NULLS NOT DISTINCT" in source
            tree = sqlglot.parse_one(source.replace(" NULLS NOT DISTINCT", ""), read="postgres")
            if not isinstance(tree, exp.Create) or not isinstance(tree.this, exp.Index):
                raise ValueError(f"Unparsed index: {source}")
            index = tree.this
            params = index.args["params"]
            predicate = params.args.get("where")
            fields = []
            for ordinal, ordered in enumerate(params.args["columns"]):
                col = ordered.this
                if not isinstance(col, exp.Column):
                    raise ValueError(f"Expression index requires manual mapping: {source}")
                meta = columns[col.name]
                if tree.args.get("unique") and (predicate is not None or not_distinct or meta["type"] == "text"):
                    if meta["type"] == "text":
                        # Text identities have no finite SQL length in PostgreSQL.
                        # A hash alone would silently change equality semantics.
                        raise ValueError(f"Explicit reviewed length needed for indexed text: {name}.{col.name}")
                    generated = short_name("_uq_" + index.name + "_" + str(ordinal))
                    value = quote(col.name)
                    typ = column_type(meta)
                    if not_distinct and meta["nullable"]:
                        # Prefix distinguishes NULL from every valid non-NULL value.
                        value = f"IF({value} IS NULL,'0',CONCAT('1',{value}))"
                        typ = "VARCHAR(37) CHARACTER SET ascii COLLATE ascii_bin" if meta["type"] == "uuid" else "VARCHAR(250) COLLATE utf8mb4_0900_bin"
                    if predicate is not None:
                        value = f"CASE WHEN {expression(predicate.this.sql(dialect='postgres'))} THEN {value} ELSE NULL END"
                    entries.append(f"{quote(generated)} {typ} GENERATED ALWAYS AS ({value}) STORED INVISIBLE")
                    fields.append(quote(generated))
                else:
                    fields.append(quote(col.name))
            entries.append(("UNIQUE " if tree.args.get("unique") else "") + "KEY " + quote(short_name(index.name)) + " (" + ",".join(fields) + ")")
        tables.append(f"CREATE TABLE {quote(name)} (\n  " + ",\n  ".join(entries) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin")
        inventory.append({"table": name, "columns": list(columns), "primary_key": primary["columns"]})
    return {"format": 1, "status": "STAGING_ONLY", "tables": tables, "foreign_keys": foreign_keys, "inventory": inventory}


if __name__ == "__main__":
    schema = json.loads((ROOT / "02_CSDL/current/schema.json").read_text())
    (ROOT / "mysql_migrations/column_types.json").write_text(json.dumps({t["name"]: {c["name"]: c["type"] for c in t["columns"]} for t in schema["tables"]}, indent=2, sort_keys=True) + "\n")
    (ROOT / "mysql_migrations/column_order.json").write_text(json.dumps({t["name"]: [c["name"] for c in t["columns"]] for t in schema["tables"]}, indent=2) + "\n")
    # Bounds match protocol identities, checked against source before copying.
    bounds = {("auth_contact", "kind"): 10, ("auth_contact", "value"): 512,
              ("auth_google_identity", "subject"): 255, ("auth_session", "refresh_hash"): 64,
              ("stored_file", "storage_key"): 240}
    for table in schema["tables"]:
        for column in table["columns"]:
            bound = bounds.get((table["name"], column["name"]))
            if bound:
                column["type"] = f"character varying({bound})"
    result = build(schema)
    result["bounded_text"] = [{"table": t, "column": c, "max_length": n} for (t, c), n in bounds.items()]
    (ROOT / "mysql_migrations/001_schema.staging.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
