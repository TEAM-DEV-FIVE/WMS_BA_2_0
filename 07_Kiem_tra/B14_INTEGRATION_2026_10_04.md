# Tích hợp B13, B16 và hoàn thiện B14 — 04/10/2026

**15/26 nhánh có code đã tích hợp local**, chưa nghiệm thu hệ thống. Nhánh điều phối: `feat/application-foundation`.
B13 nguồn `04250f3825111311dc5196297495ad0a76a87fad` → merge `3ae926483b1dc3ad84bca0eeea33545d93ea1bc9`; B16 nguồn `e0e94c74bdd4e5063d0b1a77aa1235624d1be728` → merge `f81d985cc0e288196a9cee457db3e69252dcd534`.
Bản B13/B16 đạt 906 tests + 10 subtests trước khi triển khai B14. Worktree agent nguồn được giữ nguyên.

B14 giữ nghiên cứu `d95bf75` rồi merge nền bằng `517f644`; implementation `2247c45`, rà soát bổ sung `6b92d2aec012073572e5b29a46039b6b46e10f7a`.
[Bàn giao B14](../01_Tai_lieu/PHAN_CONG/BAN_GIAO/B14.md) và [quy tắc/ma trận](../01_Tai_lieu/REVERSALS.md).

## Kết quả trên mã cuối

- **970 tests + 10 subtests PASS**, 0 failed/errors/skipped, 1171.89 giây.
- 486 tests integration và 64 GUI (có giao nhau).
- Lệnh: `rtk proxy xvfb-run -a env -u WMS_DATABASE_URL -u WMS_TEST_DATABASE_URL -u PYTEST_ADDOPTS PYTHONPATH=. '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui --expected-pg-major 16 --report .reports/b14-full-final.xml`.
- Nguồn chạy: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b14-reversal`, commit `6b92d2aec012073572e5b29a46039b6b46e10f7a`, working tree sạch. Dùng PostgreSQL 16 tạm, HTTP/Tk thật.
- Thời gian theo JUnit là 1171.89 giây; pytest báo 1171.97 giây. Có 3 cảnh báo deprecation từ dependency đã có ở baseline, không có test skip.
- Ruff, runtime OpenAPI/inventory, model/dictionary/DBML, checksum và whitespace PASS. 166 paths;
  89 bảng/584 cột/188 FK, 58 permissions/125 mappings. Chỉ thêm 020; byte migrations 001–019 nguyên vẹn.
- Build sdist/wheel, cài ngoài source, import module/entry points, HTTP health/OpenAPI và SQL resource checksums PASS.
  Evidence `.reports/b14-build-final.log`, `.reports/b14-wheel-final.*`; dependencies dùng venv đã khóa.
- Focused giữa các vòng: 120 tests PASS; vòng serial/QC 7 PASS. Vòng đầu phát hiện lỗi trigger trên connection mới,
  nguồn discrepancy, NEW record sai bảng và thứ tự UUID; đã sửa, giữ log lỗi. Lượt full đầu bị dừng chủ động
  để chốt lineage và audit event; không tính là PASS. Chỉ `b14-full-final` là hồi quy tổng của mã cuối.

## Phạm vi và giới hạn

B14 có API/desktop preview → draft → approval/SOD → post → ACK lookup, inverse từng move chính xác,
source/version/period/freeze/reservation/serial/owner checks; race, rollback, upgrade 010/019 và UI timeout.
Header/ledger/count/QC/consumption gốc được giữ, transfer và nguồn khác tính lượng ròng sau đảo.
Ký gửi/chưa phân loại bị chặn theo policy hiện có. Tồn NONE/LOT thiếu provenance bị chặn bảo thủ.

Các lần build/test không dùng DB vận hành. Không push, merge PR, đóng issue hay đổi GitHub. T01–T28 vẫn PLANNED.
Chưa chạy Windows/DPI/thiết bị/LAN mục tiêu/15 CCU/DR/UAT. B19 mới cung cấp recovery chung bền sau restart.

B07 và B17 **READY_FOR_SYNC**: đủ dependency, nhưng phải đồng bộ worktree rồi mới giao lập trình.
11 nhánh còn lại: B07 và B17–B26. [Sổ tích hợp](../01_Tai_lieu/PHAN_CONG/integration_log.json) là trạng thái hiện hành.
[JSON bằng chứng](B14_INTEGRATION_2026_10_04.json) ghi hash log/report. Evidence ignored được copy nguyên byte
sang `.reports/` điều phối; đây không phải lần chạy thêm. Các cập nhật sau mã kiểm chứng chỉ là tài liệu/metadata/checksum.
