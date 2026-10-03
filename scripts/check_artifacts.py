"""Validate repository artifacts; this does not run WMS business acceptance tests."""

import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile

from update_artifacts import ROOT, repository_files


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def read_csv(name):
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def unique_ids(rows, key="id"):
    ids = [row[key] for row in rows]
    require(len(ids) == len(set(ids)), f"Duplicate {key}")
    return set(ids)


def check_files():
    counts = {}
    for relative in repository_files():
        path = ROOT / relative
        suffix = path.suffix
        counts[suffix] = counts.get(suffix, 0) + 1
        if suffix == ".json":
            read_json(relative)
        elif suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream, strict=True))
            require(bool(rows), f"Empty CSV: {relative}")
            require(all(len(row) == len(rows[0]) for row in rows), f"CSV columns: {relative}")
        elif suffix in {".svg", ".drawio", ".bpmn"}:
            xml = ET.parse(path).getroot()
            if suffix == ".drawio":
                for diagram in xml.findall("diagram"):
                    cells = diagram.findall(".//mxCell")
                    ids = [cell.get("id") for cell in cells]
                    require(len(ids) == len(set(ids)), f"Duplicate draw.io ID: {relative}")
                    for cell in cells:
                        for attribute in ("source", "target", "parent"):
                            reference = cell.get(attribute)
                            require(reference is None or reference in ids, f"Broken draw.io reference: {relative}")
            elif suffix == ".bpmn":
                ids = [element.get("id") for element in xml.iter() if element.get("id")]
                require(len(ids) == len(set(ids)), f"Duplicate BPMN ID: {relative}")
                for element in xml.iter():
                    for attribute in ("sourceRef", "targetRef", "processRef", "bpmnElement"):
                        reference = element.get(attribute)
                        require(reference is None or reference in ids, f"Broken BPMN reference: {relative}")
        elif suffix in {".zip", ".xlsx"}:
            with zipfile.ZipFile(path) as archive:
                require(archive.testzip() is None, f"Corrupt archive: {relative}")
                if suffix == ".xlsx":
                    for member in archive.namelist():
                        if member.endswith(".xml"):
                            ET.fromstring(archive.read(member))
        elif suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if not re.match(r"[a-z]+:|#", target):
                    require((path.parent / target.split("#")[0]).exists(), f"Broken Markdown link: {relative}: {target}")
    print("PASS file formats:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if k))


def check_model():
    tables = read_json("02_CSDL/model.json")
    unique_ids(tables, "name")
    columns = {(t["name"], c["name"]): c for t in tables for c in t["cols"]}
    require(len(columns) == sum(len(t["cols"]) for t in tables), "Duplicate model column")
    dictionary = read_csv("02_CSDL/data_dictionary.csv")
    require(len(dictionary) == len(columns), "Dictionary column count differs")
    for row in dictionary:
        column = columns[(row["table"], row["column"])]
        require(row["data_type"] == column["type"], "Dictionary type differs")
        require(row["nullable"] == ("YES" if column["null"] else "NO"), "Dictionary nullability differs")
        require(row["references"] == (column["ref"] or ""), "Dictionary FK differs")
    refs = {(table, name, *column["ref"].split(".")) for (table, name), column in columns.items() if column["ref"]}
    require(all((r[2], r[3]) in columns for r in refs), "Unknown FK target")
    sql = (ROOT / "02_CSDL/001_schema.sql").read_text(encoding="utf-8")
    sql_tables = set(re.findall(r"CREATE TABLE (\w+) \(", sql))
    require(sql_tables == {t["name"] for t in tables}, "SQL table set differs")
    sql_refs = set(re.findall(r"ALTER TABLE (\w+) ADD FOREIGN KEY \((\w+)\) REFERENCES (\w+)\((\w+)\)", sql))
    require(sql_refs == refs, "SQL FK set differs")
    dbml = (ROOT / "02_CSDL/wms.dbml").read_text(encoding="utf-8")
    require(set(re.findall(r"Table (\w+) \{", dbml)) == sql_tables, "DBML table set differs")
    require(set(re.findall(r"Ref: (\w+)\.(\w+) > (\w+)\.(\w+)", dbml)) == refs, "DBML FK set differs")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript((ROOT / "02_CSDL/local_drafts.sql").read_text(encoding="utf-8"))
        require(connection.execute("PRAGMA integrity_check").fetchone() == ("ok",), "SQLite integrity")
    finally:
        connection.close()
    print(f"PASS model: {len(tables)} tables, {len(columns)} columns, {len(refs)} FKs; SQLite schema")


def check_policy_and_traceability():
    policy = read_json("04_Phan_quyen/policy.json")
    roles = unique_ids(read_csv("04_Phan_quyen/roles.csv"), "code")
    permissions = unique_ids(policy["permissions"], "code")
    require(roles == set(policy["roles"]), "Roles differ")
    require(permissions == unique_ids(read_csv("04_Phan_quyen/permissions.csv"), "code"), "Permissions differ")
    matrix = {row["permission"]: row for row in read_csv("04_Phan_quyen/role_permission_matrix.csv")}
    require(set(matrix) == permissions, "Permission matrix differs")
    for permission in policy["permissions"]:
        require(set(permission["roles"]) <= roles, "Unknown permission role")
        for role in roles:
            require(matrix[permission["code"]][role] == ("ALLOW" if role in permission["roles"] else "DENY"), "Role matrix differs")
    requirements = unique_ids(read_json("01_Tai_lieu/BA/requirements.json"))
    use_cases = unique_ids(read_json("01_Tai_lieu/BA/use_cases.json"))
    rules = unique_ids(read_json("01_Tai_lieu/BA/business_rules.json"))
    tests = unique_ids(read_csv("07_Kiem_tra/acceptance_tests.csv"))
    api = read_json("05_API/openapi_core.json")
    for row in read_json("07_Kiem_tra/BA/traceability.json"):
        require(row["requirement"] in requirements and row["use_case"] in use_cases, "Unknown traceability ID")
        require(set(row["rules"]) <= rules, "Unknown business rule")
        require(set(re.findall(r"T\d+", row["tests"])) <= tests, "Unknown acceptance test")
        require(set(row["api_paths"]) <= set(api["paths"]), "Unknown API path")
    for row in read_json("04_Phan_quyen/uc_permissions.json"):
        require(row["use_case"] in use_cases, "Unknown use case")
        for action in row["actions"]:
            require(action["permission"] in permissions, "Unknown UC permission")
            require(set(action["eligible_roles"]) <= roles, "Unknown UC role")
    from openapi_spec_validator import validate
    validate(api)
    print(f"PASS RBAC, traceability and OpenAPI: {len(roles)} roles, {len(permissions)} permissions, {len(api['paths'])} paths")


def check_extensions():
    baseline = read_json("02_CSDL/model.json")
    combined = {(table["name"], col["name"]): col for table in baseline for col in table["cols"]}
    for path in sorted((ROOT / "02_CSDL").glob("*_extension_model.json")):
        extension = read_json(path.relative_to(ROOT))
        require((ROOT / "migrations" / extension["revision"]).exists(), "Unknown extension migration")
        columns = {(t["name"], c["name"]): c for t in extension["tables"] for c in t["cols"]}
        for col in extension["added_columns"]:
            key = (col["table"], col["name"])
            require(key not in columns, "Duplicate extension column")
            columns[key] = col
        require(not (combined.keys() & columns.keys()), "Extension redefines an existing column")
        dictionary = read_csv(path.relative_to(ROOT).as_posix().replace("_model.json", "_dictionary.csv"))
        require(len(dictionary) == len(columns), "Extension dictionary count differs")
        require({(r["table"], r["column"]) for r in dictionary} == set(columns), "Extension dictionary fields differ")
        dbml = path.with_name(path.name.replace("_model.json", ".dbml")).read_text(encoding="utf-8")
        for row in dictionary:
            col = columns[(row["table"], row["column"])]
            require(row["data_type"] == col["type"], "Extension dictionary type differs")
            require(row["nullable"] == ("YES" if col["null"] else "NO"), "Extension dictionary nullability differs")
            require(row["references"] == (col["ref"] or ""), "Extension dictionary FK differs")
            require(re.search(r"\b" + re.escape(col["name"]) + r"\s+" + re.escape(col["type"]), dbml), "Extension DBML declaration missing")
        combined.update(columns)
    require(all(tuple(c["ref"].split(".")) in combined for c in combined.values() if c["ref"]), "Unknown runtime FK target")
    print(f"PASS additive models/dictionaries/DBML: {len({key[0] for key in combined})} tables, {len(combined)} columns")


def check_distribution():
    with zipfile.ZipFile(ROOT / "06_Nhap_lieu/CSV_mau_va_vi_du.zip") as archive:
        expected = {
            p.relative_to("06_Nhap_lieu").as_posix()
            for p in repository_files() if p.parts[:2] == ("06_Nhap_lieu", "imports")
        }
        require(set(archive.namelist()) == expected, "Import ZIP file set differs")
        for name in archive.namelist():
            require(archive.read(name) == (ROOT / "06_Nhap_lieu" / name).read_bytes(), f"Stale ZIP member: {name}")
    entries = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        require(name not in entries, f"Duplicate checksum: {name}")
        entries[name] = digest
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, f"Checksum mismatch: {name}")
    expected = {p.as_posix() for p in repository_files()} - {"SHA256SUMS.txt"}
    require(set(entries) == expected, "Checksum inventory differs; review changes, then run scripts/update_artifacts.py")
    print(f"PASS distribution: import ZIP matches source; {len(entries)} SHA-256 checksums")


if __name__ == "__main__":
    try:
        check_files()
        check_model()
        check_extensions()
        check_policy_and_traceability()
        check_distribution()
    except (ValueError, KeyError, OSError, ImportError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
