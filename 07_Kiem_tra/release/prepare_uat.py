"""Create unexecuted UAT record templates from the authoritative plan; never infer PASS."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GATES = {
    "T01": "Nhận/chất lượng trên Windows qua LAN; người dùng đối chiếu hàng/phiếu.",
    "T04": "Hai kho xác nhận dispatch/receive/chênh lệch qua desktop đích.",
    "T05": "Hai người đếm, hai approver và người nghiệm thu thật.",
    "T07": "Client Windows/LAN, thu hồi quyền ngay trong phiên thật.",
    "T08": "Windows10/11, crash process và restart cache trên bản cài đích.",
    "T09": "Máy DR/thiết bị backup độc lập, đủ dữ liệu và đoRPO/RTO toàn chuỗi.",
    "T10": "Vai trò trả/đảo trên desktop đích, đối chiếu nguồn và hàng thực.",
    "T12": "File/mapping thực được duyệt và thao tác Windows qua LAN.",
    "T14": "Hai phiên người dùng desktop đích, bằng chứng stale/SOD từng bước.",
    "T15": "Thiết bị quét/kiện và quy trình soạn-xuất của kho.",
    "T21": "Nghiệm thu số liệu R02/giá và thao tác lịch sử import/export trên Windows với người dùng kho.",
    "T22": "Q06/Q08 model in/HID, driver, khổ tem/lề/DPI, ảnh giấy và quét lại.",
    "T23": "Windows10/11 sạch, cài/nâng cấp/rollbackN-1, quyền cache, chữ ký phát hành.",
    "T26": "Host test độc lập, dữ liệu20GB/3năm, workload đại diện15CCU và soak; thống nhất công cụ đo.",
    "T27": "Policy/hợp đồng ký gửi thật; người nghiệp vụ kiểm tách10COMPANY+5CONSIGNED.",
    "T28": "Nguồn thời hạn bảo hành thực, người nghiệp vụ kiểm serial có/không có bằng chứng.",
}


def main():
    with (ROOT / "07_Kiem_tra/acceptance_tests.csv").open(encoding="utf-8-sig", newline="") as stream:
        source = list(csv.DictReader(stream))
    with (ROOT / "07_Kiem_tra/handover/requirements.csv").open(encoding="utf-8-sig", newline="") as stream:
        requirements = list(csv.DictReader(stream))
    records = []
    for case in source:
        related = [r for r in requirements if case["id"] in r["acceptance_tests"].split(",")]
        record = {"id": case["id"], "scenario": case["scenario"], "source_plan_status": case["status"],
                  "execution_status": "NOT_RUN", "acceptance_status": "PLANNED",
                  "fixture": case["fixture"], "precondition": case["precondition"], "steps": case["steps"],
                  "expected": case["expected"], "required_environment": case["environment"],
                  "requirements": [r["id"] for r in related],
                  "component_tests": sorted({p for r in related for p in r["tests"].split(";")}),
                  "component_evidence": sorted({r["evidence"] for r in related}),
                  "gap": GATES.get(case["id"], "Chạy đúng fixture/steps trên phiên bản đóng gói, lưu actual/log và reviewer thật; regression thành phần chưa là UAT."),
                  "technical_contact": "Trần Trung Kiên", "executor": None, "reviewer": None,
                  "started_at": None, "finished_at": None, "actual": None, "evidence": [],
                  "environment_record": None, "artifact_manifest_sha256": None, "commit": None,
                  "defects": [], "decision": None}
        records.append(record)
    assert len(records) == len({r["id"] for r in records}) == 28
    result = {"schema_version": 1, "source": "07_Kiem_tra/acceptance_tests.csv",
              "note": "Templates only; original scenarios preserved. Component evidence does not grant UAT PASS.",
              "cases": records}
    target = HERE / "uat-records.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        assert existing == result, "Refusing to overwrite changed/executed UAT records; preserve evidence"
    else:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS prepared 28 unexecuted records, original fixtures/steps/expected preserved")


if __name__ == "__main__":
    main()
