# Tích hợp B18 — 05/10/2026

**18/26 nhánh đã tích hợp local (B01–B18), chưa nghiệm thu hệ thống.** Điều phối
`feat/application-foundation` fast-forward từ `933f4b773e6406c1f24d2646271f0dea6b24a228`
đến bàn giao `71b3821e1fe63b974e84b7a51ab415656ff46c29`.
Runtime đã kiểm chứng `684789f747244a23628e193792fca5d851dfed85`; chỉ docs/checksum thay đổi sau test.
Source worktree B18 giữ nguyên để review.

## Phần đã ghép

- Bốn mẫu phiếu A4/A5; hai mẫu tem 100×50/80×40 mm, font tiếng Việt, Code128/QR,
  PDF preview/save và spool adapter Windows GDI/Linux CUPS. HID vào 5 flow kho.
- Print snapshot/version/quyền hiện hành, audit/idempotency, durable enqueue, executor
  lease/fencing, TTL cleanup, retry/reprint không thay tồn. SUBMITTED không phải PRINTED.
- Sửa shared API dependency để commit trước phản hồi thành công, có test HTTP chặn/lỗi commit.
- Release 023 (dev026),001–022 và SQLite001–002 nguyên byte. Runtime 185 paths, 25 mục desktop,
  100 bảng/679 cột/211 FK, 58 quyền/125 mappings. Không backfill hay thay ledger.
- [Hướng dẫn/contract](../01_Tai_lieu/PRINTING_SCANNER.md) và
  [bàn giao chi tiết](../01_Tai_lieu/PHAN_CONG/BAN_GIAO/B18.md).

## Kiểm chứng

**1106 tests + 10 subtests PASS**, 0 failed/errors/skipped,1454.99 giây; 574 integration, 73 GUI
(có giao nhau). Linux x86_64/Python3.12.3/PostgreSQL16.15/HTTP/Tk/Xvfb. Commit runtime sạch
trong full run. JUnit ghi 1116 testcases do gồm 10 subtests; 3 deprecation warnings baseline.

Runner chuẩn `scripts/check_application.py --gui --expected-pg-major 16 --report .reports/b18-all.xml`
chạy qua systemd user unit `wms-b18-validation-20261005`, DB tạm riêng, không DB vận hành.
Bộ tập trung 71 PASS trước full. Ruff/whitespace/runtime contract/artifact checks PASS;
build sdist/wheel và cài prefix mới ngoài source PASS, gồm font/render PDF tiếng Việt.
Lượt wheel sandbox bị kẹt đã dừng, chỉ lượt `b18-wheel-verified` được ghi PASS.

Đã kiểm trực quan PDF đa trang/tem và screenshot 800×620; ZXing giải mã ảnh barcode/QR 300 dpi.
Mock spooler chỉ kiểm lỗi/ACK và không tự in lại, không thay bằng chứng thiết bị thật.
Evidence `.reports/b18-all.*`, `b18-all-console.log`, `b18-focused-gui-4.*`,
`b18-wheel-verified.*`, `b18-print-preview.png`, `b18-print-samples/` đã copy nguyên byte
sang điều phối; [JSON hash](B18_INTEGRATION_2026_10_05.json). Không tính copy là lượt chạy khác.
Đã so byte SQL cũ và runtime tree trên điều phối với bản được test; không cần chạy lại full
cho fast-forward không đổi code. Chỉ metadata/phân công/checksum được cập nhật sau đó. Kiểm lại 13 test hồ sơ/CI discovery
sau cập nhật: PASS; OpenAPI 185 paths và 690 SHA256 entries: PASS.

## Giới hạn và công việc tiếp

Người dùng yêu cầu triển khai phần mềm trước, thiết bị/mẫu Q06/Q08 bổ sung sau.
Windows 10/11, máy in USB/LAN, HID vật lý, mẫu doanh nghiệp: NEEDS_ENVIRONMENT/NOT_RUN.
T07/T22 có bằng chứng thành phần, T01–T28 vẫn PLANNED. Chưa chạy PG15/hosted CI/LAN/15 CCU/DR/UAT.
Không push/đóng issue hoặc triển khai vào máy vận hành.

B19 và B20 **READY_FOR_SYNC**, chưa đồng bộ worktree. B19 nối journal bền SQLite003, không
replay OS I/O. B20 ghép registry/factory/executor/cleanup; dev migration mới 027 thay 023 đã
phát hành cho B18. Còn 8 nhánh B19–B26 theo [phân công](../01_Tai_lieu/PHAN_CONG/README.md).
Venv B18 riêng đã có lock mới, venv điều phối cũ không bị thay để tránh ảnh hưởng agent khác.
Khi tạo môi trường chạy mới, cài `requirements-app-lock.txt` theo hướng dẫn repository.
