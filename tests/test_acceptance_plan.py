# -*- coding: utf-8 -*-
"""Static validation tests for Acceptance Test Plan (QA01 / T01–T28)."""

import csv
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AcceptancePlanStaticTests(unittest.TestCase):
    """Static checks for acceptance plan, fixtures, role references, and test expectations."""

    @classmethod
    def setUpClass(cls):
        cls.csv_path = ROOT / "07_Kiem_tra/acceptance_tests.csv"
        cls.fixtures_path = ROOT / "07_Kiem_tra/fixtures/acceptance_fixtures.json"
        cls.roles_path = ROOT / "04_Phan_quyen/roles.csv"

        with cls.csv_path.open(encoding="utf-8-sig", newline="") as f:
            cls.tests_rows = list(csv.DictReader(f))

        with cls.roles_path.open(encoding="utf-8-sig", newline="") as f:
            cls.valid_roles = {row["code"] for row in csv.DictReader(f)}

        with cls.fixtures_path.open(encoding="utf-8") as f:
            cls.fixtures_data = json.load(f)

    def test_28_tests_unique_and_planned(self):
        """Verify that all 28 acceptance tests (T01-T28) exist, are unique, and marked PLANNED."""
        ids = [row["id"] for row in self.tests_rows]
        self.assertEqual(len(ids), 28, "Must contain exactly 28 acceptance tests")
        self.assertEqual(len(ids), len(set(ids)), "All test IDs must be unique")
        expected_ids = [f"T{i:02d}" for i in range(1, 29)]
        self.assertEqual(ids, expected_ids, "Test IDs must be ordered T01 through T28")

        for row in self.tests_rows:
            self.assertEqual(row["status"], "PLANNED", f"{row['id']} must remain PLANNED until executed")
            self.assertTrue(bool(row["owner"]), f"{row['id']} must have an assigned owner")
            tiers = row["tier"].split("/")
            for t in tiers:
                self.assertIn(t, {"Local", "CI", "UAT"}, f"{row['id']} invalid tier: {t}")

    def test_role_codes_are_official(self):
        """Verify no ad-hoc roles exist in fixtures or test specifications."""
        prohibited = {"KHO_QUANLY", "KHO_NHANVIEN", "KETOAN_KHO", "KIEMKE_VIEN"}
        fixtures_text = self.fixtures_path.read_text(encoding="utf-8")
        csv_text = self.csv_path.read_text(encoding="utf-8")

        for bad in prohibited:
            self.assertNotIn(bad, fixtures_text, f"Prohibited role '{bad}' found in fixtures")
            self.assertNotIn(bad, csv_text, f"Prohibited role '{bad}' found in acceptance_tests.csv")

        for user in self.fixtures_data["users_and_grants"]:
            if "role" in user:
                self.assertIn(user["role"], self.valid_roles, f"Unknown role {user['role']} for {user['username']}")
            if "grants" in user:
                for g in user["grants"]:
                    self.assertIn(g["role"], self.valid_roles, f"Unknown grant role {g['role']}")

    def test_task_mappings_against_scope_baseline(self):
        """Verify task assignments match implementation workstreams in SCOPE_BASELINE.md."""
        tests_by_id = {row["id"]: row for row in self.tests_rows}

        # T01 must match inbound workstream (TL05 / BE08)
        t01_tasks = tests_by_id["T01"]["task"]
        self.assertTrue("TL05" in t01_tasks or "BE08" in t01_tasks, f"T01 must map to TL05/BE08, got: {t01_tasks}")

        # T28 must match serial warranty workstream (BE05 / UI04)
        t28_tasks = tests_by_id["T28"]["task"]
        self.assertTrue("BE05" in t28_tasks or "UI04" in t28_tasks, f"T28 must map to BE05/UI04, got: {t28_tasks}")

        # All tasks must follow naming convention
        for row in self.tests_rows:
            task_codes = [t.strip() for t in row["task"].split(",") if t.strip()]
            self.assertTrue(bool(task_codes), f"{row['id']} has no task codes")
            for tc in task_codes:
                self.assertTrue(
                    re.match(r"^(TL|BE|UI|QA)\d{2}$", tc),
                    f"{row['id']} has invalid task code format: '{tc}'"
                )

    def test_t01_expects_three_stock_moves(self):
        """T01 must expect exactly 3 stock_moves for receiving + storage + quarantine legs."""
        t01 = {r["id"]: r for r in self.tests_rows}["T01"]
        self.assertIn("3 stock_move", t01["expected"], "T01 expected must state 3 stock_move explicitly")
        self.assertIn("WH01-QUARANTINE", t01["fixture"], "T01 fixture must include quarantine location")

    def test_t02_idempotency_uuid_and_execution_key(self):
        """T02 must test valid UUID keys and deduplication by execution_key."""
        t02 = {r["id"]: r for r in self.tests_rows}["T02"]
        # Check valid UUID in fixture
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        self.assertTrue(re.search(uuid_pattern, t02["fixture"]), "T02 fixture must use standard UUID format")
        self.assertIn("execution_key", t02["fixture"], "T02 must reference execution_key")
        self.assertIn("execution_key", t02["steps"], "T02 steps must test execution_key uniqueness")
        self.assertIn("409", t02["expected"], "T02 expected must include 409 Conflict for payload mismatch")

    def test_t05_two_step_approval_and_sod(self):
        """T05 must verify 2-step approval with distinct approvers and SOD enforcement."""
        t05 = {r["id"]: r for r in self.tests_rows}["T05"]
        self.assertIn("user_controller_wh01", t05["fixture"])
        self.assertIn("user_director", t05["fixture"])
        self.assertIn("SOD", t05["steps"], "T05 steps must test SOD block for counters/requester")
        self.assertIn("2 bước", t05["expected"], "T05 expected must require 2 approval steps")

    def test_t07_multi_grant_scope_and_error_codes(self):
        """T07 must test multi-grant isolation, distinguishing 403 and 404."""
        t07 = {r["id"]: r for r in self.tests_rows}["T07"]
        self.assertIn("WH01", t07["fixture"])
        self.assertIn("WH02", t07["fixture"])
        self.assertIn("WH03", t07["fixture"])
        self.assertIn("403", t07["expected"], "T07 expected must include 403 Forbidden for action mismatch")
        self.assertIn("404", t07["expected"], "T07 expected must include 404 Not Found for out-of-scope warehouse")
        self.assertIn("report_wh01.xlsx", t07["fixture"], "T07 must generate export before revoking")

    def test_t09_rto_definition_synchronization(self):
        """T09 steps and expected must measure RTO until DB is open, reconcile passes, and client logs in."""
        t09 = {r["id"]: r for r in self.tests_rows}["T09"]
        self.assertIn("reconcile.sql", t09["steps"], "T09 steps must include running reconcile.sql")
        self.assertIn("đăng nhập thành công", t09["steps"], "T09 steps must include client login")
        self.assertIn("0 dòng lệch", t09["expected"], "T09 expected must assert 0 discrepancy rows")

    def test_t27_consignment_fixture(self):
        """T27 fixture must specify 10 owned and 5 consigned items at the same location."""
        t27 = {r["id"]: r for r in self.tests_rows}["T27"]
        self.assertIn("10", t27["fixture"])
        self.assertIn("5", t27["fixture"])
        self.assertIn("PARTNER-CONSIGN", t27["fixture"])
        self.assertIn("15", t27["expected"])

    def test_t28_serial_warranty_three_states(self):
        """T28 fixture and expected must cover active, expired, and undefined warranty states."""
        t28 = {r["id"]: r for r in self.tests_rows}["T28"]
        self.assertIn("Còn bảo hành", t28["expected"])
        self.assertIn("Hết hạn", t28["expected"])
        self.assertIn("Chưa xác định", t28["expected"])


if __name__ == "__main__":
    unittest.main()
