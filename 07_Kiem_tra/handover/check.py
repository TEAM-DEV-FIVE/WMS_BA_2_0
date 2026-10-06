"""Check current handover links and complete 49-requirement coverage without granting acceptance."""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ["HANDOVER", "USER_GUIDE", "OPERATIONS_RUNBOOK", "TRAINING"]


def main():
    requirements = json.loads((ROOT / "01_Tai_lieu/BA/requirements.json").read_text(encoding="utf-8"))
    with (ROOT / "07_Kiem_tra/handover/requirements.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {row["id"] for row in requirements}
    assert len(rows) == len(expected) == 49
    assert {row["id"] for row in rows} == expected
    with (ROOT / "07_Kiem_tra/acceptance_tests.csv").open(encoding="utf-8-sig", newline="") as stream:
        acceptance = {row["id"] for row in csv.DictReader(stream)}
    covered = set()
    for row in rows:
        for key in ("implementation", "tests", "guide", "evidence"):
            assert row[key], (row["id"], key)
            for relative in row[key].split(";"):
                assert (ROOT / relative).is_file(), (row["id"], relative)
        assert row["technical_owner"] and row["acceptance_owner_role"] and row["remaining"]
        assert row["acceptance_status"] == "PLANNED"
        targets = set(row["acceptance_tests"].split(","))
        assert targets <= acceptance
        covered |= targets
    assert covered == acceptance, acceptance - covered
    files = [ROOT / f"01_Tai_lieu/{name}.md" for name in GUIDES]
    files += [ROOT / "03_So_do/RUNTIME_GUIDE.md", ROOT / "05_API/RUNTIME_HANDOVER.md"]
    count = 0
    for path in files:
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if link.startswith(("http:", "https:", "#")):
                continue
            assert (path.parent / link.split("#")[0]).is_file(), (path, link)
            count += 1
    print(json.dumps({"requirements": len(rows), "acceptance_scenarios_mapped": len(covered),
                      "local_links_checked": count, "result": "PASS", "uat": "PLANNED"}))


if __name__ == "__main__":
    main()
