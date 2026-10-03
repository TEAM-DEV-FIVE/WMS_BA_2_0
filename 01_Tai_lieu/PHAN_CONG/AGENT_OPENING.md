# Agent 1 — Backend tồn đầu kỳ

- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-opening`
- Nhánh: `agent/opening`
- Issue liên quan: #24 (TL05); hỗ trợ nền cho #31 và T20, chưa hoàn tất import/T20 toàn luồng.
- Đọc [quy tắc chung](README.md), [bất biến](../INVARIANTS.md), [nhận hàng](../RECEIVING.md),
  [PO/SO và duyệt](../ORDERS_APPROVAL.md), các UC22/UC23 trong hồ sơ BA và ma trận quyền.

## Kết quả cần bàn giao

API tồn đầu kỳ doanh nghiệp chạy trên PostgreSQL thật: tạo/sửa/đọc/danh sách OPENING, gửi/duyệt theo
policy đã có trong hồ sơ, rồi ghi sổ có chống trùng. Ghi ledger/balance/serial/audit/outbox/ACK nguyên tử.
Tái sử dụng các lớp hiện có, không dựng cơ chế ghi tồn trực tiếp từ client.

Tự đối chiếu `opening.draft`, `opening.approve`, `opening.post`, SOD và yêu cầu nhiều cấp duyệt từ tài liệu;
không suy policy OPENING từ RECEIPT. Bảo toàn policy tùy chỉnh khi migration. Dùng version/snapshot duyệt,
kiểm tra kỳ/vị trí/precision/owner/tracking và nguồn đối ứng OPENING; không cache balance tại đối ứng.
Khóa và execution/idempotency phải ngăn cùng phiếu/lô/serial tạo hiệu ứng trùng khi cạnh tranh.
Không tạo chứng cứ NCC/bảo hành giả từ tồn đầu kỳ.

Contract đề xuất theo pattern runtime: `/api/v1/openings`, `/api/v1/openings/{id}` và
`POST /api/v1/openings/{id}/post`, workflow documents chung khi phù hợp. Đọc code receipt/order để chọn
DTO chính xác; không dùng nguyên DTO core lịch sử. Mỗi lệnh ghi kiểm tra lại quyền khi replay.

## Phạm vi được sửa

- Module mới `apps/server/application/openings.py`, `apps/server/api/openings.py`, `packages/contracts/openings.py`.
- `apps/server/api/app.py`, `apps/server/application/orders.py`, `apps/server/api/orders.py` và
  `apps/server/application/authorization.py`: chỉ tích hợp OPENING cần thiết, giữ hành vi PO/SO/RECEIPT.
- `apps/server/application/stock_identity.py` nếu cần mở rộng resolver an toàn; tránh sửa command kernel/receipt service.
- Chỉ thêm migration `migrations/010_opening.sql`; không đổi `001`–`009` hoặc baseline `02_CSDL/001_schema.sql`.
- Model/từ điển/DBML bổ sung `02_CSDL/opening_extension*`, `scripts/check_artifacts.py`,
  `tests/foundation/test_postgres.py` để phản ánh schema mới, giữ kiểm tra baseline.
- Test mới `tests/foundation/test_openings.py`; cập nhật test workflow/contract hiện có khi hành vi được mở rộng hợp lệ.
- `05_API/openapi_runtime.json` sinh từ code; `01_Tai_lieu/OPENING.md` hướng dẫn riêng;
  báo cáo `07_Kiem_tra/AGENT_OPENING_REPORT.md`.

Đợt này chưa làm UI, import file/batch pipeline, ký gửi, xuất kho hoặc worker. Seed quyền mới nếu thật sự
cần phải ghi đề xuất trước trong báo cáo; ưu tiên quyền đang có, không mở rộng quyền để tiện viết test.
Không tự sửa báo cáo tổng, dependency/CI, fixture chung hoặc task của agent khác.

## Kiểm thử bắt buộc

- API qua IAM thật: đúng/sai kho, thiếu quyền, thu hồi quyền trước replay; tự duyệt bị chặn, duyệt đúng role/thứ tự.
- Draft/submit/approve/post, stale version, snapshot lệch, kỳ đóng, vị trí khóa và precision sai.
- NONE/LOT/SERIAL, serial trùng khác vị trí, hai kết nối cùng post/execution/key; chỉ một hiệu ứng.
- Failpoint sau ghi ledger/balance/audit/outbox: rollback toàn bộ; gửi lại đúng yêu cầu không nhân tồn.
- Đối soát ledger–balance–owner, kiểm chứng không tạo warranty evidence từ OPENING.
- Migration từ 009 giữ dữ liệu cũ, fresh/re-run/concurrent runners; full suite không làm hỏng receipt/recovery.
- Export runtime contract, Ruff, build và artifact check theo quy tắc chung.

Nếu yêu cầu chặn khởi tạo tồn theo kho/batch chưa rõ, ghi cách hiểu và dẫn nguồn; không tự đánh dấu
T20 hoàn tất bằng test API vì test gốc còn yêu cầu pipeline import và chống nhập lại batch.

Commit local, trả hash và báo cáo. Nêu rõ những ca chưa chạy, không chỉ liệt kê số test.
