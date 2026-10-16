"""Build native MySQL triggers from the reviewed, limited PL/pgSQL guard subset.

Build-time only. Unsupported procedural syntax fails rather than dropping a guard.
Deferred reversal checking needs the MySQL connection commit protocol as well.
"""

import json
import re
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.simplify import simplify

from scripts.build_mysql_schema import column_type, short_name

ROOT = Path(__file__).resolve().parents[1]


class BodyParser:
    def __init__(self, source):
        self.source = source
        self.tokens = sqlglot.tokenize(source, read="postgres")
        self.index = 0

    def peek(self):
        return self.tokens[self.index].text.upper() if self.index < len(self.tokens) else ""

    def take(self, expected):
        if self.peek() != expected:
            raise ValueError(f"Expected {expected}, got {self.peek()}")
        self.index += 1

    def until(self, terminal):
        start, depth = self.tokens[self.index].start, 0
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if depth == 0 and token.text.upper() == terminal and token.token_type.name != "STRING":
                result = self.source[start:token.start].strip()
                self.index += 1
                return result
            if token.text == "(":
                depth += 1
            elif token.text == ")":
                depth -= 1
            self.index += 1
        raise ValueError(f"Unterminated statement before {terminal}")

    def block(self):
        nodes = []
        while self.peek() and self.peek() not in {"END", "ELSE", "ELSIF"}:
            if self.peek() == "IF":
                self.take("IF")
                branches = [(self.until("THEN"), self.block())]
                while self.peek() == "ELSIF":
                    self.take("ELSIF")
                    branches.append((self.until("THEN"), self.block()))
                otherwise = []
                if self.peek() == "ELSE":
                    self.take("ELSE")
                    otherwise = self.block()
                self.take("END")
                self.take("IF")
                self.take(";")
                nodes.append(("if", branches, otherwise))
            else:
                nodes.append(("statement", self.until(";")))
        return nodes


class Guard:
    def __init__(self, function, tables, event, table, *, procedure=False):
        self.event, self.table, self.procedure = event, table, procedure
        self.locals, self.records, self.declarations = {}, {}, []
        body = function.split("AS $function$", 1)[1].rsplit("$function$", 1)[0].strip()
        declaration, body = re.split(r"\bBEGIN\b", body, maxsplit=1)
        declaration = re.sub(r"^DECLARE\s*", "", declaration.strip())
        for item in declaration.split(";"):
            if not item.strip():
                continue
            variable, kind = item.strip().split(None, 1)
            kind = kind.removeprefix("wms.")
            if kind in tables:
                self.records[variable] = tables[kind]["columns"]
                for col in self.records[variable]:
                    self.declarations.append(f"DECLARE v_{variable}_{col['name']} {column_type(col)};")
            else:
                self.locals[variable] = kind
                self.declarations.append(f"DECLARE v_{variable} {column_type({'type': kind})};")
        self.declarations.append("DECLARE v_unused CHAR(36);")
        parser = BodyParser(body)
        self.nodes = parser.block()
        parser.take("END")
        if parser.peek() == ";":
            parser.take(";")
        if parser.peek():
            raise ValueError("Unexpected trailing guard statements")

    def native(self, sql):
        tree = sqlglot.parse_one(sql, read="postgres")

        def visit(node):
            if isinstance(node, exp.Table) and node.db == "wms":
                node.set("db", None)
            if isinstance(node, exp.Column):
                if node.table in self.records:
                    return exp.column("v_" + node.table + "_" + node.name)
                if not node.table and node.name in self.locals:
                    return exp.column("v_" + node.name)
                if not node.table and node.name.upper() in {"TG_OP", "TG_TABLE_NAME"}:
                    return exp.Literal.string(self.event if node.name.upper() == "TG_OP" else self.table)
                if self.procedure and node.table.upper() == "NEW":
                    if node.name != "id":
                        raise ValueError("Deferred procedure references a non-transaction field")
                    return exp.column("p_id")
            return node

        tree = tree.transform(visit)
        tree = simplify(tree)
        for identifier in tree.find_all(exp.Identifier):
            if identifier.name.upper() not in {"NEW", "OLD"}:
                identifier.set("quoted", True)
        return tree.sql(dialect="mysql", unsupported_level=sqlglot.ErrorLevel.RAISE)

    def render(self, nodes):
        output = []
        for node in nodes:
            if node[0] == "if":
                branches, otherwise = node[1:]
                branches_native = []
                for condition, children in branches:
                    # Specialize TG_OP/TG_TABLE_NAME before rendering NEW/OLD references.
                    condition = condition.replace("TG_OP", "'"+self.event+"'").replace("TG_TABLE_NAME", "'"+self.table+"'")
                    reduced = simplify(sqlglot.parse_one(condition, read="postgres"))
                    if isinstance(reduced, exp.Boolean):
                        if reduced.this:
                            otherwise = children
                            break
                        continue
                    branches_native.append((self.native(reduced.sql(dialect="postgres")), children))
                else:
                    pass
                if not branches_native:
                    chunk, stops = self.render(otherwise)
                    output.extend(chunk)
                    if stops:
                        return output, True
                    continue
                all_stop = True
                for number, (condition, children) in enumerate(branches_native):
                    output.append(("IF " if number == 0 else "ELSEIF ") + condition + " THEN")
                    chunk, stops = self.render(children)
                    output.extend(chunk)
                    all_stop = all_stop and stops
                if otherwise:
                    output.append("ELSE")
                    chunk, stops = self.render(otherwise)
                    output.extend(chunk)
                    all_stop = all_stop and stops
                else:
                    all_stop = False
                output.append("END IF;")
                if all_stop:
                    return output, True
                continue
            statement = node[1]
            if statement.startswith("RETURN "):
                output.append("LEAVE guard_body;")
                return output, True
            if statement.startswith("RAISE EXCEPTION "):
                match = re.match(r"RAISE EXCEPTION ('(?:[^']|'')*')", statement)
                if not match:
                    raise ValueError("Unparsed exception")
                output.append("SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT=" + match[1] + ";")
                return output, True
            assignment = re.fullmatch(r"(\w+)\s*:=\s*(.*)", statement, re.S)
            if assignment:
                if assignment[1] not in self.locals:
                    raise ValueError("Unmapped assignment variable")
                output.append("SET v_"+assignment[1]+" = "+self.native(assignment[2])+";")
                continue
            if statement.startswith("PERFORM "):
                native = self.native("SELECT "+statement[8:])
                point = native.index(" FROM ")
                output.append(native[:point]+" INTO v_unused"+native[point:]+";")
                continue
            select = re.fullmatch(r"SELECT\s+(.*?)\s+INTO\s+([\w,]+)\s+FROM\s+(.*)", statement, re.S)
            if select:
                fields, variables, rest = select.groups()
                if variables in self.records:
                    if fields != "*":
                        raise ValueError("Partial record selection")
                    fields = ",".join('"'+x['name']+'"' for x in self.records[variables])
                    targets = ["v_"+variables+"_"+x['name'] for x in self.records[variables]]
                else:
                    targets = ["v_"+x for x in variables.split(",")]
                native = self.native("SELECT "+fields+" FROM "+rest)
                point = native.index(" FROM ")
                output.append(native[:point]+" INTO "+",".join(targets)+native[point:]+";")
                continue
            raise ValueError(f"Unsupported guard statement: {statement[:100]}")
        return output, False

    def body(self):
        lines, _ = self.render(self.nodes)
        return "guard_body: BEGIN\n" + "\n".join(self.declarations + lines) + "\nEND"


def main():
    schema = json.loads((ROOT / "02_CSDL/current/schema.json").read_text())
    tables = {t["name"]: t for t in schema["tables"]}
    routines = {r["proname"]: r["sql"] for r in json.loads((ROOT / "mysql_migrations/postgresql_guard_source.json").read_text())}
    sources = json.loads((ROOT / "mysql_migrations/postgresql_trigger_source.json").read_text())
    result = {"status": "STAGING_ONLY", "triggers": [], "procedures": [], "source_trigger_count": len(sources)}
    for trigger in sources:
        sql = trigger["sql"]
        match = re.fullmatch(r"CREATE (CONSTRAINT )?TRIGGER (\w+) (BEFORE|AFTER) ([A-Z ]+) ON wms\.(\w+) (?:DEFERRABLE INITIALLY DEFERRED )?FOR EACH ROW EXECUTE FUNCTION wms\.(\w+)\(\)", sql)
        if not match:
            raise ValueError("Unparsed trigger declaration")
        deferred, name, timing, events, table, routine = match.groups()
        if deferred:
            field = "id" if table == "inventory_transaction" else "transaction_id"
            result["triggers"].append(f"CREATE TRIGGER `{name}` AFTER INSERT ON `{table}` FOR EACH ROW SET @wms_pending_transactions=JSON_ARRAY_APPEND(COALESCE(@wms_pending_transactions,JSON_ARRAY()),'$',NEW.`{field}`)")
            continue
        for event in events.split(" OR "):
            guard = Guard(routines[routine], tables, event, table)
            statement = f"CREATE TRIGGER `{short_name(name+'_'+event.lower())}` {timing} {event} ON `{table}` FOR EACH ROW " + guard.body()
            result["triggers"].append(statement)
    guard = Guard(routines["check_reversal_integrity"], tables, "INSERT", "inventory_transaction", procedure=True)
    result["procedures"].append("CREATE PROCEDURE assert_reversal_integrity(IN p_id CHAR(36)) " + guard.body())
    (ROOT / "mysql_migrations/002_guards.staging.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
