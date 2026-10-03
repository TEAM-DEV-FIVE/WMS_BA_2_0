# Tích hợp B11 vào nhánh điều phối

Ngày 2026-10-04. Người dùng giao trực tiếp “tích hợp B11”.
Nhánh thực hiện: `feat/application-foundation`, worktree `WMS_BA_2_0`.

## Mốc ghép và phạm vi

- Base điều phối: `ef99946038539483ed3e740b2dbd60594c7394c5`.
- Code B11: `cc45621be81249e229655b1899f76bf1dbf4b313` trên `agent/b11-transfer`.
- B02/B03 tích hợp tại `bd15277c7142708b595ac9d16aa77b5a4db90745`, B09 tại
  `97f9d02796a01fabd6974eec5ff741981c45eb00`; đều là tổ tiên của code B11.
- Merge không xung đột, giữ nguyên toàn bộ code/test nghiệp vụ đã bàn giao.
  Review lại hooks router/shell, lifecycle/snapshot/quyền hai kho, ARRIVE → QC/MOVE,
  khóa parent/location/product, idempotency/remaining/owner và rollback.
- Commit merge được ghi vào sổ tích hợp sau khi các kiểm tra dưới đây đạt.
  Báo cáo [B11.md](B11.md) giữ bằng chứng của nhánh tính năng, bổ sung source hash
  cố định và ghi đường dẫn log local thay vì hyperlink tới file bị Git ignore
  (để checkout mới kiểm tra Markdown không lỗi). Số migration và bằng chứng
  kiểm thử trên nhánh điều phối dùng báo cáo này.

## Migration release

Đổi revision phát triển chưa phát hành `017_b11_transfer.sql` thành
**`015_b11_transfer.sql`**, số kế tiếp release 014. Ngoài comment mô tả release,
DDL không đổi. Đồng bộ tên trong model, DBML và tài liệu runtime/migration.
Dictionary giữ nguyên vì không chứa tên revision. Catalog/brief vẫn giữ số
phát triển 017 để bảo toàn phân công ban đầu.

Đã so byte 001–014 với base `ef99946`: không thay đổi. Tổng schema 76 bảng,
509 cột, 159 FK; thêm 4 bảng typed và policy/route/append-only guards của B11.
Test nâng cấp có dữ liệu từ prefix 005/010/013/**014**, giữ ledger, balance,
UNCLASSIFIED owner và checksum lịch sử; fresh/readiness/serial/warranty được
kiểm chứng trong bộ hồi quy thật. Không tái dùng DB tạm từng chạy tên 017,
không đổi lịch sử hoặc chạy migration vào DB vận hành.

## Kết quả trên bản ghép

Môi trường Linux, Python 3.12, PostgreSQL 16.15, Tk/Xvfb và HTTP thật.
PYTHONPATH/import đã xác nhận trỏ worktree điều phối, không cài lại dependency.

- Full regression: **523 passed + 10 subtests passed, 0 failed, 0 skipped**,
  566.64 giây; gồm PostgreSQL/API/Tk/HTTP thật, fresh install và upgrade có dữ liệu
  từ prefix 005/010/013/014. JUnit: `.reports/b11-integration-full.xml`.
  Ba cảnh báo deprecation có sẵn của Starlette/httpx và jsonschema.RefResolver;
  không đổi dependency trong lần tích hợp.
- Ruff apps/packages/tests/foundation/runner: PASS.
- Runtime OpenAPI check: PASS, 110 paths.
- Build sdist + wheel: PASS; log `.reports/b11-integration-build.log`, gói ở
  `.reports/b11-integration-dist/`. Cả hai chứa đúng 15 migration release 001–015,
  không có revision phát triển 017. Byte migration và 6 module B11 trong wheel khớp nguồn.
- Năm log/XML trong báo cáo nhánh B11 đã sao chép nguyên byte từ worktree B11 vào
  `.reports/` điều phối để giữ bằng chứng lịch sử; đây không phải bằng chứng chạy
  trên bản ghép. Kết quả integration có tiền tố `b11-integration-` riêng.
- Artifacts/model/dictionary/DBML/checksum: PASS, 514 SHA-256 entries; SQL smoke
  xác nhận 76 bảng/509 cột/159 FK. `git diff --check`: PASS.

Lệnh tái lập từ gốc worktree điều phối:

```bash
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a .venv/bin/python scripts/check_application.py --gui
rtk proxy env PYTHONPATH="$PWD" .venv/bin/python -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" .venv/bin/python scripts/export_runtime_contract.py --check
rtk proxy env PYTHONPATH="$PWD" .venv/bin/python -m build --no-isolation --outdir .reports/b11-integration-dist
rtk proxy env PYTHONPATH="$PWD" .venv/bin/python scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" .venv/bin/python scripts/check_artifacts.py
rtk proxy git diff --check
```

## Trạng thái và giới hạn

Sau merge, ghi B11 **INTEGRATED** với source/merge hash thực vào
`integration_log.json`; không tự kích hoạt hoặc sửa worktree nhánh khác.
Worktree B11 giữ nguyên commit bàn giao để tra cứu.

Chỉ COMPANY được chuyển; nhận thiếu giữ transit, mất cần ADJUSTMENT được duyệt
riêng. B10 picking, B13 điều chỉnh chung, B14 reversal, B17 report UI và B19
journal restart tiếp tục theo DAG/contract của từng nhánh, không được coi đã
hoàn thành chỉ vì B11 được ghép. Kho đích thứ hai trong test là fixture.

Windows, thiết bị, LAN mục tiêu, 15 CCU, DR, hosted CI và UAT vẫn **NOT_RUN**.
T01–T28 giữ trạng thái nghiệm thu hiện có; không push/deploy hoặc thay trạng thái GitHub.
