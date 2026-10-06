# Contract dùng khi bàn giao

Nguồn runtime: `apps/server/api/app.py` và DTO `packages/contracts`; chạy
`rtk proxy env PYTHONPATH=. python scripts/export_runtime_contract.py --check` với Python đã cài lock.
File OpenAPI sinh có tên tra trong script, không chỉnh tay để né khác biệt. Contract thiết kế/ví dụ cũ
giữ lại làm lịch sử; route trong runtime là cơ sở smoke client/server.

- Client chỉ gọi HTTPS API, không PostgreSQL. Cấu hình URL/CA/server/device đúng profile trước mở cache.
- Command nghiệp vụ giữ method/path/body/UUIDkey; server kiểm quyền hiện tại trước replay và version/SOD
  trước thay đổi. Schema PG001–024, cache001–003, client protocol1.
- Recovery `lookup-v1` chỉ tra; `send-v1` gửi chủ động. Phải kiểm proofACK/Rejected như
  [RECOVERY_ALL](../01_Tai_lieu/RECOVERY_ALL.md); không coi mọi2xx/404 là đủ quyết định gửi lại.
- IAM/upload/scan/preview có giới hạn journal riêng, xem
  [ma trận endpoint](../01_Tai_lieu/RECOVERY_ENDPOINTS.md). Không lưu token/TOTP/password trong command.
- Migration fail/mismatch → readiness fail closed. Nâng server hỗ trợ giao thức trước client;
  release cũ không chấp nhận revision dư chỉ vì cùng version0.1.0.
- Event B01/B17/B18 ghép registry B20; không thêm consumer hoặc đổi payload trên máy đang chạy.

Mọi thay đổi API/schema cần export/check và regression; không có route/migration mới trong B25.
