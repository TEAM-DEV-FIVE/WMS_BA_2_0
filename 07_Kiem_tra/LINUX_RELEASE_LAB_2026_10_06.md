# Chứng thư thử và phiếu/tem InternTechLead - 06/10/2026

CODE_READY local tại commit `4d192ea7ea5dbad8c47459cc3b2e2484df545565`, checkout sạch khi test.
Base `6480be4`, nhánh `feat/linux-release-validation`. Không sửa công việc B22/B24.
[Hướng dẫn sử dụng, phương án Win/Mac và giới hạn](../01_Tai_lieu/LINUX_RELEASE_LAB.md).

## Đã làm

- Thêm cấu hình server cho đơn vị, địa chỉ, MST, điện thoại, tên người ký. Dữ liệu được chụp vào
  header tùy chọn của snapshot v1; không đổi migration, API hoặc constraint template_version.
- Phiếu có đủ thông tin InternTechLead do người dùng cung cấp; tem có đơn vị/địa chỉ/điện thoại.
  Chỗ ký để trống; không có chữ ký mô phỏng. Không thay quyền giá hoặc quy tắc đếm mù.
- Công cụ tạo 12 PDF mẫu bằng production renderer và catalog 13 trang, giữ khổ giấy thật.
- Công cụ Linux tạo CA/serverAuth HTTPS và chứng thư Code Signing/PFX TEST ONLY, hết hạn tối đa 30 ngày;
  thư mục 0700/file 0600, từ chối overwrite/symlink, không lưu CA private key, không thay trust store.
- Runbook Linux / Windows lab / Mac từ xa; chưa cài VM, chưa thuê dịch vụ hoặc phát hành bộ cài.

## Bằng chứng

Lệnh chạy từ worktree, interpreter B18 chỉ đọc và PYTHONPATH trỏ đúng mã mới:

```bash
rtk proxy env PYTHONPATH=. ../wms-b18-printing-scanner/.venv/bin/python scripts/check_application.py \
  --test-path tests/foundation/test_printing.py \
  --test-path tests/foundation/test_print_render_scanner.py \
  --test-path tests/foundation/test_linux_release_validation.py \
  --test-path deploy/lan/tests/test_runtime.py \
  --report .reports/linux-release-final.xml
```

**76 passed, 0 failed/errors/skipped, 44,57 giây**. Linux/Python 3.12.3/PostgreSQL 16.15 tạm riêng.
Gồm 15 ca tích hợp in, 18 ca renderer/HID cũ, 17 ca bổ sung và 26 ca runtime LAN.
Đây là hồi quy theo phạm vi, không phải chạy lại toàn bộ 1210 ca của mốc B21/B23.
Cảnh báo deprecation Starlette/httpx có sẵn, không gây lỗi test.

- PDF: deterministic, tiếng Việt, thông tin đơn vị, giá ẩn, kiểm kê mù, kích thước trang native;
  decode Code128/QR từ ảnh 300 dpi. Render Poppler và xem 13 trang, không chồng/cắt chữ trên mẫu.
- Luồng API → snapshot DB → outbox → PDF: cấu hình thay sau capture không thay nội dung;
  payload client giả thông tin đơn vị bị từ chối. Quyền, rollback, race/reprint cũ vẫn đạt.
- PKI: PFX giải mã đúng khóa, sai mật khẩu bị từ chối; EKU Code Signing, TLS serverAuth tách biệt;
  OpenSSL verify đúng DNS/IP đạt, sai hostname và sai mục đích sslclient bị từ chối;
  quyền filesystem và chống ghi đè/symlink được kiểm tra.
- So sánh renderer trước/sau trên 12 snapshot không có issuer: **byte-for-byte identical**.
- Ruff toàn bộ apps/packages/tests/scripts/deploy tests; runtime contract 189 paths; artifact checks đạt.

JUnit/log/collection nằm trong `.reports/linux-release-final.*` của worktree.
Môi trường được lưu kèm [JSON](LINUX_RELEASE_LAB_2026_10_06.environment.json).
PDF sinh local tại `output/pdf/wms-phieu-tem-mau.pdf`, SHA-256:
`b389bdeed31dc035f6254a547cd0ecac7edaef101dcebf8b59936271d5fd3cfb`.
PKI ở `.local-test-pki/`, không đưa private material vào Git hoặc bằng chứng test.

## Còn chờ

- Chứng thư công khai và native Authenticode/installer Windows: NOT_RUN.
- Build/Developer ID/notarization và kiểm thử macOS: NOT_RUN; không có package macOS trong thay đổi này.
- Áp dụng cấu hình vào dịch vụ đích, máy in/quét, đo khổ giấy và xác nhận mẫu nghiệp vụ: NOT_RUN.
- Không đổi trạng thái nghiệm thu T01–T28 hoặc đóng issue GitHub từ kết quả này.
