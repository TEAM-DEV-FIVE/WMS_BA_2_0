"""MySQL connection semantics for typed rows and atomic application commands.

The adapter keeps PostgreSQL available for recovery. MySQL executes native SQL,
uses InnoDB transaction locks and validates deferred reversal evidence before
commit. Unsupported constructs fail closed.
"""

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

import pymysql
from sqlalchemy import Connection, text
from sqlalchemy.engine.base import OptionEngine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.sql.elements import TextClause
from sqlglot import exp

from apps.server.infrastructure.mysql_sql import lower, parse, translate

COLUMN_TYPES = json.loads(files("mysql_migrations").joinpath("column_types.json").read_text())
COLUMN_ORDER = json.loads(files("mysql_migrations").joinpath("column_order.json").read_text())


def parameter(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    if isinstance(value, (list, tuple)):
        return json.dumps(value, default=str, allow_nan=False)
    return value


class TypedCursor(pymysql.cursors.Cursor):
    def execute(self, query, args=None):
        try:
            result = super().execute(query, args)
            if self.warning_count:
                with pymysql.cursors.Cursor(self.connection) as warnings:
                    warnings.execute("SHOW WARNINGS")
                    codes = {row[1] for row in warnings.fetchall()}
                if codes & {1260, 1264, 1265, 1292, 1365, 1366}:
                    raise pymysql.DataError(1265, "MySQL conversion/truncation warning rejected", sqlstate="22000")
            return result
        except pymysql.MySQLError as error:
            if error.args and error.args[0] in {3819, 4025}:
                raise pymysql.IntegrityError(*error.args, sqlstate="23000") from error
            raise

    def _do_get_result(self):
        super()._do_get_result()
        if not self._rows:
            return
        kinds = [COLUMN_TYPES.get(field.org_table, {}).get(field.org_name) for field in self._result.fields]
        fields = self._result.fields
        converted = []
        for row in self._rows:
            values = []
            for value, kind, field in zip(row, kinds, fields, strict=True):
                if value is not None:
                    if kind == "uuid":
                        value = UUID(value)
                    elif kind == "uuid[]":
                        value = [UUID(v) for v in json.loads(value)]
                    elif field.type_code == 245:
                        value = json.loads(value)
                    elif kind == "boolean":
                        value = bool(value)
                    elif isinstance(value, datetime):
                        value = value.replace(tzinfo=UTC)
                values.append(value)
            converted.append(tuple(values))
        self._rows = tuple(converted)


class MySQLConnection(Connection):
    def native(self, sql, values=None):
        return super().execute(text(sql), {key: parameter(value) for key, value in (values or {}).items()})

    def execute(self, statement, parameters=None, *, execution_options=None):
        if not isinstance(statement, TextClause):
            return super().execute(statement, parameters, execution_options=execution_options)
        if parameters is not None and not isinstance(parameters, dict):
            tree = parse(statement.text)
            if not isinstance(parameters, list) or not parameters or not all(isinstance(row, dict) for row in parameters):
                raise ValueError("Batch SQL requires a nonempty list of parameter mappings")
            if not isinstance(tree, exp.Insert) or not isinstance(tree.this, exp.Schema) or tree.args.get("conflict") or tree.args.get("returning"):
                raise ValueError("Only plain explicit-column INSERT supports batch execution")
            defaults = {key: bind.value for key, bind in statement._bindparams.items()}
            rows = [{key: parameter(value) for key, value in (defaults | row).items()} for row in parameters]
            return super().execute(text(lower(tree)), rows, execution_options=execution_options)
        values = {key: bind.value for key, bind in statement._bindparams.items()}
        values.update(parameters or {})
        tree = parse(statement.text)
        changed = False
        for query in tree.find_all(exp.Select):
            limit = query.args.get("limit")
            if limit and isinstance(limit.expression, exp.Placeholder) and values.get(limit.expression.name) is None:
                query.set("limit", None)
                changed = True
        if isinstance(tree, exp.Insert) and isinstance(tree.this, exp.Table) and isinstance(tree.expression, exp.Values):
            # PostgreSQL permits omitted trailing columns with defaults even
            # without an explicit column list; MySQL requires that list.
            count = len(tree.expression.expressions[0].expressions)
            columns = COLUMN_ORDER.get(tree.this.name)
            if columns is not None:
                if count > len(columns):
                    raise ValueError("Invalid implicit insert column count")
                tree.set("this", exp.Schema(this=tree.this.copy(), expressions=[exp.to_identifier(name) for name in columns[:count]]))
                changed = True
        if isinstance(tree, exp.Select) and len(tree.expressions) == 1:
            function = tree.expressions[0]
            if isinstance(function, exp.Anonymous) and function.name.lower() == "nextval":
                if len(function.expressions) != 1 or not isinstance(function.expressions[0], exp.Literal) or function.expressions[0].this != "wms.order_number_seq":
                    raise ValueError("Unknown sequence")
                allocated = self.native("INSERT INTO order_number_sequence(value) VALUES (NULL)").lastrowid
                self.native("DELETE FROM order_number_sequence WHERE value=:value", {"value": allocated})
                return self.native("SELECT :value", {"value": allocated})
            if isinstance(function, exp.Anonymous) and function.name.lower().startswith("pg_"):
                return self.lock_function(function, values)
        if isinstance(tree, exp.Insert) and tree.args.get("conflict"):
            return self.insert_conflict(tree, values)
        if tree.args.get("returning"):
            return self.update_returning(tree, values)
        return self.native(lower(tree) if changed else translate(statement.text), values)

    def lock_function(self, function, values):
        name = function.name.lower()
        argument = function.expressions[0]
        key = values[argument.name] if isinstance(argument, exp.Placeholder) else argument.this
        namespace = hashlib.sha256(f"{self.engine.url.database}:{key}".encode()).hexdigest()[:32]
        if name in {"pg_advisory_xact_lock", "pg_advisory_xact_lock_shared"}:
            # Conservative exclusive serialization includes shared callers; locks
            # are owned by InnoDB and released only after commit/rollback.
            self.native("INSERT INTO transaction_lock(lock_key) VALUES (:key) ON DUPLICATE KEY UPDATE lock_key=VALUES(lock_key)", {"key": namespace})
            self.native("SELECT lock_key FROM transaction_lock WHERE lock_key=:key FOR UPDATE", {"key": namespace})
            return self.native("SELECT 1")
        if name.startswith("pg_try_advisory_lock"):
            shared = name.endswith("_shared")
            acquired = self.acquire_fence(namespace, shared)
            return self.native("SELECT :acquired", {"acquired": acquired})
        if name.startswith("pg_advisory_unlock"):
            self.release_fence(namespace)
            return self.native("SELECT 1")
        raise ValueError("Unsupported PostgreSQL lock operation")

    def acquire_fence(self, namespace, shared):
        gate = namespace + ":gate"
        if self.native("SELECT GET_LOCK(:name,0)", {"name": gate}).scalar_one() != 1:
            return False
        retained = False
        try:
            readers = self.native("SELECT reader_key FROM session_lock_reader WHERE lock_key=:key", {"key": namespace}).scalars().all()
            active = []
            for reader in readers:
                if self.native("SELECT IS_USED_LOCK(:name)", {"name": reader}).scalar_one() is not None:
                    active.append(reader)
                else:
                    self.native("DELETE FROM session_lock_reader WHERE reader_key=:reader", {"reader": reader})
            if not shared and active:
                return False
            if shared:
                reader = namespace + ":r:" + uuid4().hex[:24]
                if self.native("SELECT GET_LOCK(:name,0)", {"name": reader}).scalar_one() != 1:
                    return False
                try:
                    self.native("INSERT INTO session_lock_reader(lock_key,reader_key) VALUES (:key,:reader)", {"key": namespace, "reader": reader})
                except Exception:
                    self.native("SELECT RELEASE_LOCK(:name)", {"name": reader})
                    raise
                self.info.setdefault("mysql_fences", {})[namespace] = reader
                # Publish the reader registry while the gate is held.
                self.commit()
            else:
                self.info.setdefault("mysql_fences", {})[namespace] = gate
                retained = True
            return True
        finally:
            if not retained:
                self.native("SELECT RELEASE_LOCK(:name)", {"name": gate})

    def release_fence(self, namespace):
        name = self.info.get("mysql_fences", {}).pop(namespace, None)
        if name is not None:
            self.native("SELECT RELEASE_LOCK(:name)", {"name": name})
            if ":r:" in name:
                self.native("DELETE FROM session_lock_reader WHERE reader_key=:reader", {"reader": name})

    def insert_conflict(self, tree, values):
        conflict = tree.args["conflict"]
        target = tree.this
        guard_actor = guard_version = None
        if isinstance(target, exp.Schema) and target.this.name == "report_request_guard":
            actor = tree.expression.expressions[0].expressions[0]
            if not isinstance(actor, exp.Placeholder):
                raise ValueError("Report guard requires a bound actor")
            guard_actor = values[actor.name]
            guard_version = self.native("SELECT version FROM report_request_guard WHERE user_id=:actor", {"actor": guard_actor}).scalar_one_or_none()
        statement = tree.copy()
        statement.set("conflict", None)
        try:
            return self.native(lower(statement), values)
        except IntegrityError as error:
            if not error.orig.args or error.orig.args[0] != 1062:
                raise
            duplicate = error
        if guard_actor is not None:
            current = self.native("SELECT version FROM report_request_guard WHERE user_id=:actor FOR UPDATE", {"actor": guard_actor}).scalar_one()
            if current != guard_version:
                # PostgreSQL aborts an RR writer if this row changed after its
                # snapshot. InnoDB normally updates the latest row; force the
                # same whole-command retry so report quotas use a fresh view.
                raise OperationalError(None, None, pymysql.OperationalError(1213, "Report snapshot changed; retry transaction", sqlstate="40001"))
        if not isinstance(target, exp.Schema) or not isinstance(tree.expression, exp.Values) or len(tree.expression.expressions) != 1:
            raise ValueError("Unsupported conflict insert form") from duplicate
        table = target.this.name
        incoming = dict(zip([col.name for col in target.expressions], tree.expression.expressions[0].expressions, strict=True))
        keys = [key.this.name for key in conflict.args.get("conflict_keys") or []]
        if keys:
            indexes = {}
            rows = self.native("SELECT INDEX_NAME,COLUMN_NAME FROM information_schema.statistics WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table AND NON_UNIQUE=0 ORDER BY INDEX_NAME,SEQ_IN_INDEX", {"table": table}).all()
            for index, column in rows:
                indexes.setdefault(index, []).append(column)
            if not any(len(columns) == len(keys) and set(columns) == set(keys) for columns in indexes.values()):
                raise ValueError("Conflict target is not a reviewed unique key") from duplicate
            predicate = exp.and_(*[exp.EQ(this=exp.column(key), expression=incoming[key].copy()) for key in keys])
            target_row = exp.Select(expressions=[exp.Literal.number(1)]).from_(target.this.copy()).where(predicate)
            target_row.set("locks", [exp.Lock(update=True)])
            # MySQL may report PRIMARY even when the requested unique key also
            # conflicts. PostgreSQL resolves the explicitly targeted key; only
            # propagate the other duplicate if that target row does not exist.
            if self.native(lower(target_row), values).first() is None:
                raise duplicate
        if conflict.args["action"].name == "DO NOTHING":
            return self.native("SELECT 1 WHERE FALSE")
        if not keys or conflict.args.get("where") or conflict.args.get("index_predicate"):
            raise ValueError("Unsupported conditional upsert") from duplicate

        def excluded(node):
            if isinstance(node, exp.Column) and node.table.lower() == "excluded":
                return incoming[node.name].copy()
            return node

        updates = [value.transform(excluded) for value in conflict.expressions]
        predicate = exp.and_(*[exp.EQ(this=exp.column(key), expression=incoming[key].copy()) for key in keys])
        update = exp.Update(this=target.this.copy(), expressions=updates, where=exp.Where(this=predicate))
        return self.native(lower(update), values)

    def update_returning(self, tree, values):
        if not isinstance(tree, exp.Update) or tree.args.get("from_"):
            raise ValueError("RETURNING is supported only for reviewed simple updates")
        if "id" not in COLUMN_TYPES[tree.this.name]:
            raise ValueError("Returning update requires an id primary key")
        selected = exp.Select(expressions=[exp.column("id")]).from_(tree.this.copy())
        selected.set("where", tree.args.get("where").copy() if tree.args.get("where") else None)
        selected.set("locks", [exp.Lock(update=True)])
        ids = self.native(lower(selected), values).scalars().all()
        captured = exp.In(this=exp.column("id"), expressions=[exp.Literal.string(str(x)) for x in ids]) if ids else exp.false()
        update = tree.copy()
        update.set("returning", None)
        # A time-based predicate may match more rows between the two statements.
        # Update exactly the captured, locked set so every changed row is returned.
        update.set("where", exp.Where(this=captured.copy()))
        self.native(lower(update), values)
        projection = exp.Select(expressions=[x.copy() for x in tree.args["returning"].expressions]).from_(tree.this.copy())
        projection = projection.where(captured)
        return self.native(lower(projection))

    def _commit_impl(self):
        try:
            pending = self.native("SELECT @wms_pending_transactions").scalar_one()
            if pending:
                ids = sorted(set(json.loads(pending) if isinstance(pending, str) else pending))
                for transaction in ids:
                    if self.native("SELECT id FROM inventory_transaction WHERE id=:id", {"id": transaction}).first():
                        self.native("CALL assert_reversal_integrity(:id)", {"id": transaction}).close()
        except BaseException:
            # RootTransaction deactivates itself on commit failure, even when
            # our validation failed before DBAPI.commit. Roll back explicitly
            # now so an invalid transaction can never survive in a pooled session.
            try:
                self._rollback_impl()
            except BaseException:
                self.invalidate()
            raise
        super()._commit_impl()
        with self.connection.cursor() as cursor:
            cursor.execute("SET @wms_pending_transactions=NULL")

    def _rollback_impl(self):
        try:
            super()._rollback_impl()
        finally:
            if not self.invalidated:
                with self.connection.cursor() as cursor:
                    cursor.execute("SET @wms_pending_transactions=NULL")

    def close(self):
        if not self.closed and not self.invalidated and self.info.get("mysql_fences"):
            # A pooled session must never retain a publication lock on failure.
            self.invalidate()
        super().close()


class MySQLOptionEngine(OptionEngine):
    """Isolation-level views must retain the connection's transaction protocol."""

    _connection_cls = MySQLConnection


MySQLOptionEngine._option_cls = MySQLOptionEngine
