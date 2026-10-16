"""Explicit SQL AST lowering for the application's PostgreSQL query vocabulary.

Values remain bound parameters. DDL, locks, upserts and RETURNING are handled by
the connection adapter, never silently approximated by the SQL generator.
"""

import re
from functools import lru_cache

import sqlglot
from sqlglot import exp


def unwrap(node):
    while isinstance(node, (exp.Paren, exp.Cast)):
        node = node.this
    return node


def parse(source):
    # Bind names such as :values and :grant are legal in SQLAlchemy, but SQL
    # parsers may interpret the word as SQL syntax. Rename tokens, not literals.
    tokens = sqlglot.tokenize(source, read="postgres")
    replacements, names = [], {}
    for left, right in zip(tokens, tokens[1:]):
        if left.token_type.name == "COLON" and left.end + 1 == right.start:
            if not right.text.replace("_", "").isalnum():
                raise ValueError("Invalid bind parameter name")
            alias = "__wms_bind_" + str(len(names))
            names[alias] = right.text
            replacements.append((right.start, right.end + 1, alias))
    for start, end, alias in reversed(replacements):
        source = source[:start] + alias + source[end:]
    statements = sqlglot.parse(source, read="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    if len(statements) != 1 or statements[0] is None or isinstance(statements[0], exp.Command):
        raise ValueError("Only one supported application SQL statement is permitted")
    tree = statements[0]
    for placeholder in tree.find_all(exp.Placeholder):
        if placeholder.name in names:
            placeholder.set("this", names[placeholder.name])
    return tree


def lower(tree):
    tree = tree.copy()
    for select in tree.find_all(exp.Select):
        table = select.args.get("from_")
        table = table.this if table else None
        order = select.args.get("order")
        queues = {"outbox_event": ("available_at", "ix_outbox_pending"),
                  "import_task": ("available_at", "ix_import_task_due"),
                  "export_task": ("available_at", "ix_export_task_queue"),
                  "print_task": ("available_at", "ix_print_task_claim"),
                  "auth_delivery": ("expires_at", "ix_auth_delivery_pending")}
        if (isinstance(table, exp.Table) and table.name in queues
                and select.args.get("limit") and any(lock.args.get("wait") is False for lock in select.args.get("locks") or [])
                and order and [item.this.name for item in order.expressions] == [queues[table.name][0], "id"]):
            # InnoDB locks scanned rows before filesort/LIMIT. Keep the claim on
            # the ordered queue index so one worker cannot lock the whole queue.
            table.set("hints", [exp.IndexTableHint(this="FORCE", expressions=[exp.to_identifier(queues[table.name][1])])])
            # These queue ordering columns are NOT NULL in the reviewed schema;
            # avoid synthetic NULL-order CASE expressions that require filesort.
            for item in order.expressions:
                item.set("nulls_first", not bool(item.args.get("desc")))
        leases = {"print_task": ("status", "ix_print_task_lease"),
                  "export_task": ("status", "ix_export_task_lease"),
                  "import_task": ("state", "ix_import_task_lease")}
        where = select.args.get("where")
        if isinstance(table, exp.Table) and table.name in leases and where and select.args.get("locks"):
            state_column, lease_index = leases[table.name]
            running = any(isinstance(predicate.this, exp.Column) and predicate.this.name == state_column
                          and isinstance(predicate.expression, exp.Literal) and predicate.expression.this == "RUNNING"
                          for predicate in where.find_all(exp.EQ))
            if running and not where.find(exp.Or) and any(column.name == "lease_until" for column in where.find_all(exp.Column)):
                # UPDATE ... RETURNING captures rows under a locking read. A
                # lease-only range must not wait on unrelated READY queue rows.
                table.set("hints", [exp.IndexTableHint(this="FORCE", expressions=[exp.to_identifier(lease_index)])])
        projections = []
        for projection in select.expressions:
            original = unwrap(projection)
            label = None
            if isinstance(projection, exp.Cast) and isinstance(original, exp.Column):
                label = original.name
            elif isinstance(projection, exp.Anonymous):
                label = projection.name.lower()
            elif isinstance(projection, exp.AggFunc):
                label = projection.sql_name().lower()
            projections.append(exp.alias_(projection, label) if label else projection)
        select.set("expressions", projections)
    if isinstance(tree, exp.Update):
        # PostgreSQL RHS expressions all see the pre-update row. MySQL evaluates
        # assignments from left to right. Readers of an updated column must run
        # before its writer; cycles require a reviewed explicit implementation.
        assignments = {item.this.name: item for item in tree.expressions}
        pending = list(assignments)
        ordered = []
        while pending:
            selected = None
            for candidate in pending:
                read_by_other = any(
                    candidate in {col.name for col in assignments[other].expression.find_all(exp.Column)}
                    for other in pending if other != candidate
                )
                if not read_by_other:
                    selected = candidate
                    break
            if selected is None:
                raise ValueError("Cyclic update assignments need explicit old-row semantics")
            ordered.append(assignments[selected])
            pending.remove(selected)
        tree.set("expressions", ordered)

    def transform(node):
        if isinstance(node, exp.JSONExtractScalar):
            extracted = exp.JSONExtract(this=node.this.copy(), expression=node.expression.copy())
            # MySQL's ->> accepts a column on the left, not an expression.
            # PostgreSQL also returns SQL NULL for a JSON null scalar.
            return exp.Case(ifs=[exp.If(
                this=exp.EQ(this=exp.Anonymous(this="JSON_TYPE", expressions=[extracted.copy()]), expression=exp.Literal.string("NULL")),
                true=exp.Null())], default=exp.Anonymous(this="JSON_UNQUOTE", expressions=[extracted]))
        if isinstance(node, exp.AtTimeZone):
            return exp.Anonymous(this="CONVERT_TZ", expressions=[node.this.copy(), exp.Literal.string("+00:00"), node.args["zone"].copy()])
        if isinstance(node, exp.Sub) and all(isinstance(value, exp.Cast) and value.to.this == exp.DataType.Type.DATE for value in (node.this, node.expression)):
            return exp.Anonymous(this="DATEDIFF", expressions=[node.this.copy(), node.expression.copy()])
        if isinstance(node, exp.In) and isinstance(node.args.get("field"), exp.Placeholder):
            value = node.args["field"]
            subquery = sqlglot.parse_one("SELECT value FROM JSON_TABLE(:" + value.name + ", '$[*]' COLUMNS(value VARCHAR(512) PATH '$')) AS _items", read="mysql")
            return exp.In(this=node.this.copy(), query=exp.Subquery(this=subquery))
        if isinstance(node, exp.Filter):
            aggregate = node.this.copy()
            if not isinstance(aggregate, (exp.Count, exp.Sum, exp.Min, exp.Max)):
                raise ValueError("Unsupported filtered aggregate")
            value = aggregate.this.copy()
            if isinstance(value, exp.Star):
                value = exp.Literal.number(1)
            predicate = node.expression.this.copy()
            aggregate.set("this", exp.Case(ifs=[exp.If(this=predicate, true=value)], default=exp.Null()))
            return aggregate
        if isinstance(node, exp.Extract) and node.this.name.upper() == "EPOCH":
            difference = node.expression
            if not isinstance(difference, exp.Sub):
                raise ValueError("Unsupported epoch extraction")
            return exp.Div(this=exp.Anonymous(this="TIMESTAMPDIFF", expressions=[exp.Var(this="MICROSECOND"), difference.expression.copy(), difference.this.copy()]), expression=exp.Literal.number(1000000))
        if isinstance(node, (exp.Table, exp.Column)) and node.db == "wms":
            node.set("db", None)
        if isinstance(node, exp.Collate):
            # The named PostgreSQL ICU collation is not a MySQL schema object.
            if node.expression.sql().lower() == "wms.catalog_unicode":
                return exp.Collate(this=node.this, expression=exp.Var(this="utf8mb4_0900_as_cs"))
        if isinstance(node, exp.DataType):
            if node.this == exp.DataType.Type.JSONB or node.this == exp.DataType.Type.ARRAY:
                return exp.DataType.build("JSON")
            if node.this == exp.DataType.Type.UUID:
                return exp.DataType.build("CHAR(36)")
        if isinstance(node, (exp.EQ, exp.NEQ)) and isinstance(node.expression, (exp.Any, exp.All)):
            value = unwrap(node.expression.this)
            if isinstance(value, exp.Array):
                members = exp.In(this=node.this.copy(), expressions=[x.copy() for x in value.expressions])
            elif isinstance(value, exp.Placeholder):
                subquery = sqlglot.parse_one(
                    "SELECT value FROM JSON_TABLE(:" + value.name + ", '$[*]' COLUMNS(value VARCHAR(512) PATH '$')) AS _items",
                    read="mysql",
                )
                members = exp.In(this=node.this.copy(), query=exp.Subquery(this=subquery))
            else:
                raise ValueError("Unsupported quantified comparison")
            if isinstance(node, exp.NEQ) and isinstance(node.expression, exp.All):
                return exp.Not(this=members)
            if isinstance(node, exp.EQ) and isinstance(node.expression, exp.Any):
                return members
            raise ValueError("Unsupported quantified comparison operator")
        if isinstance(node, exp.Mul) and isinstance(node.expression, exp.Interval):
            interval = node.expression.copy()
            interval.set("this", exp.Paren(this=exp.Mul(this=node.this.copy(), expression=exp.Literal.number(interval.this.this))))
            return interval
        if isinstance(node, exp.Anonymous):
            name = node.name.lower()
            if name == "all" and len(node.expressions) == 1:
                return exp.All(this=exp.Paren(this=node.expressions[0].copy()))
            if name == "jsonb_set":
                arguments = node.expressions
                if len(arguments) not in {3, 4} or not isinstance(arguments[1], exp.Literal) or not re.fullmatch(r"\{[A-Za-z_]\w*(?:,[A-Za-z_]\w*)*\}", arguments[1].this):
                    raise ValueError("JSON update requires a reviewed constant object path")
                function = "JSON_SET"
                if len(arguments) == 4:
                    if not isinstance(arguments[3], exp.Boolean):
                        raise ValueError("JSON create-missing flag must be constant")
                    function = "JSON_SET" if arguments[3].this else "JSON_REPLACE"
                path = "$" + "".join('."' + part + '"' for part in arguments[1].this[1:-1].split(","))
                return exp.Anonymous(this=function, expressions=[arguments[0].copy(), exp.Literal.string(path), exp.Cast(this=arguments[2].copy(), to=exp.DataType.build("JSON"))])
            if name in {"clock_timestamp", "now", "statement_timestamp"}:
                return exp.Anonymous(this="UTC_TIMESTAMP", expressions=[exp.Literal.number(6)])
            if name == "to_jsonb":
                return exp.Cast(this=node.expressions[0], to=exp.DataType.build("JSON"))
            if name == "cardinality":
                return exp.Anonymous(this="JSON_LENGTH", expressions=node.expressions)
            if name == "jsonb_typeof":
                return exp.Lower(this=exp.Anonymous(this="JSON_TYPE", expressions=node.expressions))
            if name == "jsonb_build_object":
                return exp.Anonymous(this="JSON_OBJECT", expressions=node.expressions)
            if name == "jsonb_agg":
                value = node.expressions[0].copy()
                # GROUP_CONCAT supports deterministic ordering and DISTINCT in 8.0.
                # CAST AS JSON rejects truncated/invalid output instead of accepting it.
                def encode(item):
                    if isinstance(item, exp.Order):
                        item.set("this", encode(item.this))
                        return item
                    if isinstance(item, exp.Distinct):
                        item.set("expressions", [encode(x) for x in item.expressions])
                        return item
                    if isinstance(item, exp.Anonymous) and item.name.lower() in {"jsonb_build_object", "json_object"}:
                        return item
                    # Current scalar aggregates collect text identifiers.
                    return exp.Coalesce(this=exp.Anonymous(this="JSON_QUOTE", expressions=[item]), expressions=[exp.Literal.string("null")])
                rendered = lower(encode(value))
                return sqlglot.parse_one("CAST(CONCAT('[', GROUP_CONCAT(" + rendered + " SEPARATOR ','), ']') AS JSON)", read="mysql")
            if name.startswith("pg_"):
                raise ValueError("PostgreSQL operation requires an explicit MySQL implementation")
        if isinstance(node, exp.CurrentTimestamp):
            return exp.Anonymous(this="UTC_TIMESTAMP", expressions=[exp.Literal.number(6)])
        if isinstance(node, exp.Lock):
            # MySQL locks the selected joined rows; never weaken to a plain read.
            node.set("expressions", None)
        return node

    for _ in range(3):
        tree = tree.transform(transform)
    for identifier in tree.find_all(exp.Identifier):
        identifier.set("quoted", True)
    if tree.find(exp.Any) or tree.find(exp.All) or tree.find(exp.OnConflict) or tree.find(exp.Returning):
        raise ValueError("Unhandled SQL feature; refusing execution")
    return tree.sql(dialect="mysql", unsupported_level=sqlglot.ErrorLevel.RAISE)


@lru_cache(maxsize=4096)
def translate(source):
    return lower(parse(source))
