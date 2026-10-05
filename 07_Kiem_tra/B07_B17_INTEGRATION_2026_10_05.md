# Tích hợp B07 và B17 — 05/10/2026

**17/26 nhánh đã tích hợp local (B01–B17), chưa nghiệm thu hệ thống.** Điều phối `feat/application-foundation`.
B07 nguồn `cef3d9013e1e86057f50a3b3cfd39a964b028948`; B17 nguồn `b131b30cf7ea855ee22e696f786d11648d7c90a2`. Hai source worktree được giữ nguyên để review.
B17 merge `81e87e4e7f2274e96984d944d19017167ee8bbdb`; bản ghép B07 `005f4c81f78c3b30fef652e221a1ad01bc429faf`. Base trước tích hợp `9e07731`.

## Phần đã ghép

- B07: trường TEXT/INTEGER/DECIMAL/BOOLEAN/DATE/ENUM với revision bất biến; metadata, validation,
  lịch sử, approval snapshot, quyền giá hiện hành và desktop. [Hướng dẫn](../01_Tai_lieu/CUSTOM_FIELDS.md).
- B17: R01–R08, snapshot/paging ổn định, CSV/XLSX có phân quyền, outbox enqueue/executor tách I/O,
  lease/retry/cancel/TTL cleanup và desktop. [Hướng dẫn](../01_Tai_lieu/REPORTS_EXPORT.md).
- Ghép cả service/router và lifecycle hai tab; desktop 24 mục, 177 API paths.
- B17 giữ migration 021; B07 đổi dev 025 → release 022, chỉ đổi revision chưa phát hành và đã dùng DB tạm.
  Migrations 001–020 nguyên byte. Runtime 97 bảng/638 cột/203 FK, 58 quyền/125 mappings; SQLite 001–002 nguyên vẹn.
- Xung đột router/shell/schema assertions và OpenAPI/checksum được giải quyết theo cả hai chức năng;
  artifacts sinh lại, không xóa/skip test cũ. Thêm nâng cấp 021→022 giữ report data và ca chung metadata →
  duyệt receipt → post → snapshot/export → reversal, kiểm snapshot bất biến và không lộ metadata giá.

## Kiểm chứng bản ghép

- **1060 tests + 10 subtests PASS**, 0 failed/errors/skipped; JUnit 1498.52 giây.
- Pytest báo 1498.62 giây và 3 cảnh báo deprecation từ dependency đã có ở baseline.
- 554 integration tests; 68 GUI tests (có giao nhau).
- Mã `005f4c81f78c3b30fef652e221a1ad01bc429faf`, working tree sạch; Python 3.12.3, PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), HTTP/Tk/Xvfb thật.
- Lệnh tại `/home/kien/Đồ án KHMT2_2/worktrees/wms-integrate-b07-b17`: `rtk proxy xvfb-run -a env -u WMS_DATABASE_URL -u WMS_TEST_DATABASE_URL -u PYTEST_ADDOPTS PYTHONPATH=. '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -u scripts/check_application.py --gui --expected-pg-major 16 --report .reports/b07-b17-full.xml`.
- Lượt đầu bị gián đoạn trước JUnit/kết quả cuối, KHÔNG tính PASS; giữ `b07-b17-interrupted*`.
  Lượt chạy lại dùng tác vụ systemd user tạm `wms-b07-b17-validation-20261005`, tự kết thúc sau runner,
  console ghi file để không mất log khi phiên công cụ đổi. Đây vẫn là runner chuẩn toàn bộ test trên cùng commit.
- 8 ca focused/schema/upgrade/navigation PASS trước hồi quy tổng (`b07-b17-scoped.*`).
- Ruff, runtime export, model/dictionary/DBML, artifact checksum và whitespace PASS. Build sdist/wheel và
  cài wheel vào prefix mới ngoài source PASS: imports/entry points, health/OpenAPI, PG SQL/SQLite checksums.
- Evidence `.reports/b07-b17-full.*`, `.reports/b07-b17-full-console.log`, `.reports/b07-b17-build.log`,
  `.reports/b07-b17-wheel.*`; [JSON bằng chứng](B07_B17_INTEGRATION_2026_10_05.json) ghi hashes.
  Đã copy nguyên byte sang `.reports/` điều phối; không coi bản copy là một lượt chạy thêm.
- Kết quả agent giữ trong bàn giao: B07 full trước chỉnh sửa cuối rồi focused 106; B17 full chia shard và UI bổ sung.
  Chúng không thay thế lần full bản ghép trên đây.

## Giới hạn và phân công tiếp

Không push/đóng issue GitHub/dùng DB vận hành. T01–T28 vẫn PLANNED; Windows/PG15/hosted CI/LAN/thiết bị/15 CCU/DR/UAT chưa chạy.
R01–R08 xuất các cột nghiệp vụ định nghĩa sẵn, không tự xuất custom JSON. B07 có contract projection kiểm quyền;
bulk import/export metadata cần tiếp nhận theo contract khi bổ sung. Journal bền thuộc B19; registry/cleanup scheduler thuộc B20.
Báo cáo tạm có TTL/quota, chưa chứng minh tải hoặc retention mục tiêu.

B18 **READY_FOR_SYNC**, chưa đồng bộ worktree. Migration phát triển mới `026_b18_printing_scanner.sql` vì release 022 đã thuộc B07;
release B18 do điều phối chốt khi ghép. B19/B20 còn chờ B18. Còn 9 nhánh: B18–B26.
[Sổ tích hợp](../01_Tai_lieu/PHAN_CONG/integration_log.json). Sau mã kiểm chứng chỉ cập nhật tài liệu/metadata/checksum.
