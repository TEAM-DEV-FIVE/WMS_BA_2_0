# Mốc tích hợp phụ thuộc B11

Ngày 2026-10-03. Người dùng giao rõ review/tích hợp B09 rồi đồng bộ và triển khai B11.
Thực hiện trên `feat/application-foundation`, từ `0a31d654e82c005f4c5d1dd42710f5a3058a4994`.
B02/B03 đã INTEGRATED tại `bd15277c7142708b595ac9d16aa77b5a4db90745`.

## Phạm vi review/tích hợp

- B09 head `94bd7232173b60bf899ca5001f1687464011899a` chứa cả các tiền đề B01/B02/B03/B05/B06.
- Rà owner resolver/validator, snapshot/lifecycle và namespace sự kiện, inbound/QC/MOVE,
  guard DB, API/desktop/import và bộ kiểm thử bàn giao. Giữ contract COMPANY-only cho
  chuyển kho; hợp đồng ký gửi hiện thuộc một kho. Không mở thương mại/chuyển chủ/legacy classification.
- Đổi revision phát triển chưa phát hành `015_b09_consignment.sql` thành release
  `014_b09_consignment.sql`; đồng bộ model/DBML và tài liệu hiện hành. Báo cáo B09 cũ giữ
  tên phát triển làm bằng chứng lịch sử. Migration đã tích hợp 001–013 không thay nội dung.
- Bổ sung test upgrade có ledger legacy từ prefix 010 và 013, giữ UNCLASSIFIED, balance,
  move bất biến và checksum của lịch sử migration. Fresh install, policy và các upgrade khác
  được kiểm trong bộ hồi quy chung; chỉ dùng PostgreSQL tạm.

## Kiểm chứng

- Ruff toàn bộ apps/packages/tests/foundation và runner: đạt.
- Runtime OpenAPI: khớp 98 paths.
- Model/dictionary/DBML: 72 bảng, 491 cột, 148 FK; artifact/link/checksum/ZIP: đạt.
- Build sdist/wheel: đạt; kiểm nội dung wheel có đúng 14 migration release 001–014,
  byte nội dung migration và service B09 khớp nguồn hiện tại.
- `rtk proxy env PYTHONPATH="$PWD" xvfb-run -a .venv/bin/python scripts/check_application.py --gui`: **491 passed + 10 subtests**, 0 failed/skip, 547.42s. PostgreSQL tạm, Tk/HTTP thật trên Linux. XML local `.reports/b11-dependencies-full.xml`.
- Mốc merge chứa B09 và kiểm chứng được ghi trong sổ tích hợp, sau đó đồng bộ B11 có giữ nghiên cứu `a2fbf7c`/`5246f30`.

Không sửa worktree B09, không push/deploy, không dùng DB vận hành. Windows/hardware,
15 CCU, DR và nghiệm thu nghiệp vụ vẫn NOT_RUN; không đổi T01–T28 thành PASS.
