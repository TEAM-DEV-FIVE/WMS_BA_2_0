"""Regression checks for false-success and malformed import input."""

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "06_Nhap_lieu/imports/validate_csv.py"
spec = importlib.util.spec_from_file_location("validate_csv", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ValidateCSVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_csv(self, name, rows):
        with (self.directory / name).open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(rows)

    def test_bundled_examples_and_templates(self):
        self.assertEqual(validator.validate(SCRIPT.parent / "examples"), (22, []))
        self.assertEqual(validator.validate(SCRIPT.parent / "templates"), (0, []))

    def test_missing_directory_fails_cli(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.directory / "missing")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["errors"])

    def test_empty_directory_fails(self):
        self.assertTrue(validator.validate(self.directory)[1])

    def test_unknown_filename_fails(self):
        self.write_csv("uom_typo.csv", [["code", "name", "decimal_places"]])
        self.assertTrue(validator.validate(self.directory)[1])

    def test_partial_import_with_known_filename_passes(self):
        self.write_csv("01_uom.csv", [["code", "name", "decimal_places"], ["CAI", "Cái", "0"]])
        self.assertEqual(validator.validate(self.directory), (1, []))

    def test_short_row_with_missing_optional_column_fails(self):
        template = next(t for t in json.loads(
            (SCRIPT.parent / "template_manifest.json").read_text(encoding="utf-8")
        )["templates"] if t["name"] == "02_categories")
        self.assertFalse(template["columns"][-1]["required"])
        self.write_csv("02_categories.csv", [
            [column["name"] for column in template["columns"]], ["CAT", "Danh mục"],
        ])
        self.assertEqual(validator.validate(self.directory)[1][0][2], "ROW")

    def test_extra_columns_fail(self):
        self.write_csv("01_uom.csv", [["code", "name", "decimal_places"], ["CAI", "Cái", "0", "extra"]])
        self.assertEqual(validator.validate(self.directory)[1][0][2], "ROW")

    def test_required_and_invalid_types_fail(self):
        self.write_csv("01_uom.csv", [["code", "name", "decimal_places"], ["", "Cái", "0.5"]])
        codes = {error[3] for error in validator.validate(self.directory)[1]}
        self.assertEqual(codes, {"REQUIRED", "INVALID_TYPE"})

    def test_malformed_quotes_fail(self):
        (self.directory / "01_uom.csv").write_text('code,name,decimal_places\nCAI,"unclosed,0', encoding="utf-8")
        self.assertTrue(validator.validate(self.directory)[1])

    def test_invalid_utf8_fails(self):
        (self.directory / "01_uom.csv").write_bytes(b"code,name,decimal_places\n\xff")
        self.assertTrue(validator.validate(self.directory)[1])

    def test_header_order_fails(self):
        self.write_csv("01_uom.csv", [["name", "code", "decimal_places"]])
        self.assertEqual(validator.validate(self.directory)[1][0][2], "HEADER")

    def test_missing_argument_shows_usage(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
