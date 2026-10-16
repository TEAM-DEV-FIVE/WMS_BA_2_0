"""Offline tests for staging tools; these do not prove MySQL runtime readiness."""

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from scripts.build_mysql_schema import build, expression, quote
from scripts.stage_mysql_data import canonical, mysql_value, update_digest


class MySQLStagingTests(unittest.TestCase):
    def test_identifiers_reject_sql_injection(self):
        with self.assertRaises(ValueError):
            quote("x`; DROP DATABASE x; --")

    def test_check_array_becomes_membership(self):
        result = expression("kind = ANY ((ARRAY['PO'::text, 'SO'::text])::text[])")
        self.assertEqual(result, "`kind` IN ('PO', 'SO')")

    def test_json_type_case_matches_postgres(self):
        self.assertIn("LOWER(JSON_TYPE(`payload`))", expression("jsonb_typeof(payload)='object'"))

    def test_json_default_uses_native_type(self):
        self.assertEqual(expression("'{}'::jsonb"), "CAST('{}' AS JSON)")

    def test_reject_dynamic_schema_arrays(self):
        with self.assertRaises(ValueError):
            expression("id=ANY(:ids)")

    def test_utc_normalization_preserves_microseconds(self):
        source = datetime(2026, 10, 15, 8, 0, 1, 123456, timezone(timedelta(hours=7)))
        target = mysql_value(source)
        self.assertEqual(target, datetime(2026, 10, 15, 1, 0, 1, 123456))
        self.assertEqual(canonical(source, "timestamp with time zone"), canonical(target, "timestamp with time zone"))

    def test_decimal_is_never_float(self):
        value = Decimal("99999999999999.123456")
        self.assertIs(mysql_value(value), value)
        self.assertEqual(canonical(value, "numeric(20,6)"), "99999999999999.123456")

    def test_uuid_is_lossless(self):
        value = UUID("00000000-0000-4000-8000-000000000001")
        self.assertEqual(mysql_value(value), str(value))

    def test_json_order_does_not_change_digest(self):
        columns = [{"type": "jsonb"}]
        left, right = hashlib.sha256(), hashlib.sha256()
        update_digest(left, ['{"b":2,"a":1.000000000001}'], columns)
        update_digest(right, ['{"a":1.000000000001,"b":2}'], columns)
        self.assertEqual(left.digest(), right.digest())

    def test_json_numeric_precision_changes_digest(self):
        columns = [{"type": "jsonb"}]
        left, right = hashlib.sha256(), hashlib.sha256()
        update_digest(left, ['{"x":1.00000000000000001}'], columns)
        update_digest(right, ['{"x":1.00000000000000002}'], columns)
        self.assertNotEqual(left.digest(), right.digest())

    def test_json_null_and_string_are_distinct(self):
        self.assertNotEqual(canonical('null', 'jsonb'), canonical('"null"', 'jsonb'))

    def test_json_numbers_cannot_collide_with_tag_like_objects(self):
        self.assertNotEqual(canonical('1.0', 'jsonb'), canonical('{"$decimal":"1"}', 'jsonb'))

    def test_json_numbers_preserve_more_than_28_digits(self):
        self.assertNotEqual(canonical('1.000000000000000000000000000001', 'jsonb'),
                            canonical('1.000000000000000000000000000002', 'jsonb'))

    def test_json_numeric_notation_is_normalized_exactly(self):
        self.assertEqual(canonical('100', 'jsonb'), canonical('1.00e2', 'jsonb'))

    def test_all_reviewed_tables_and_foreign_keys_are_present(self):
        root = Path(__file__).resolve().parents[2]
        source = json.loads((root / "02_CSDL/current/schema.json").read_text())
        manifest = json.loads((root / "mysql_migrations/001_schema.staging.json").read_text())
        self.assertEqual(len(manifest["tables"]), len(source["tables"]))
        self.assertEqual(len(manifest["foreign_keys"]), sum(c["kind"] == "f" for t in source["tables"] for c in t["constraints"]))
        self.assertEqual(manifest["status"], "STAGING_ONLY")

    def test_nulls_not_distinct_has_unambiguous_encoding(self):
        table = {"name": "sample", "columns": [
            {"name": "id", "type": "uuid", "nullable": False, "default": None},
            {"name": "dimension", "type": "uuid", "nullable": True, "default": None}],
            "constraints": [{"name": "sample_pkey", "kind": "p", "columns": ["id"]}],
            "indexes": ["CREATE UNIQUE INDEX uq_dimensions ON wms.sample USING btree (dimension) NULLS NOT DISTINCT"]}
        sql = build({"tables": [table]})["tables"][0]
        self.assertIn("IF(`dimension` IS NULL,'0',CONCAT('1',`dimension`))", sql)
        self.assertIn("STORED INVISIBLE", sql)


if __name__ == "__main__":
    unittest.main()
