# Agent 2 — Worker outbox

- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-outbox`
- Nhánh: `agent/outbox`
- Issue liên quan: #22 (QA03); bằng chứng thành phần T02/T24, chưa nghiệm thu toàn hệ thống.
- Đọc [quy tắc chung](README.md), [bất biến](../INVARIANTS.md), kiến trúc/audit trong hồ sơ,
  `outbox_event`, `consumer_receipt`, producers hiện có và `apps/server/application/commands.py`.

## Kết quả cần bàn giao

Worker chạy tách khỏi API, có chế độ chạy một lượt để vận hành/kiểm thử, xử lý batch giới hạn và dừng sạch.
Tận dụng schema outbox hiện tại: `available_at`, `attempts`, `processed_at`, `last_error` cùng
UNIQUE `(event_id, consumer)`. Ưu tiên consumer làm việc trong DB, handler và receipt commit cùng transaction.
Hai worker không nhận cùng event đồng thời; có retry/backoff hữu hạn và trạng thái lỗi quan sát được.

Phân biệt event được xử lý với event chưa có handler. Không đánh dấu processed cho no-op/unknown event;
không sửa ledger/tồn kho từ worker để diễn lại một giao dịch đã commit. Không gọi HTTP/email/in ấn trong
transaction nghiệp vụ. Giao hàng tới hệ thống ngoài và hiệu ứng ngoài DB chỉ được hứa at-least-once kèm
dedup phù hợp, không tuyên bố exactly-once khi chỉ có một cờ trong DB.

Xây interface/registry consumer rõ ràng và chứng minh bằng consumer kiểm thử tạo hiệu ứng DB thật.
Nếu chưa có consumer nghiệp vụ được định nghĩa trong yêu cầu, bàn giao engine/adapter được kiểm thử,
ghi rõ consumer triển khai thực tế còn thiếu; không dựng một handler giả rồi kết luận #22 hoàn tất.

## Phạm vi được sửa

- Module mới `apps/server/application/outbox.py`, `apps/server/infrastructure/outbox.py`,
  `apps/server/worker.py` và package worker riêng nếu cần.
- Chạy bằng `python -m apps.server.worker`; đặt settings worker riêng nếu cần, giữ cấu hình chung hiện tại.
- Test mới `tests/foundation/test_outbox.py`, fixture nội bộ test.
- Hướng dẫn `01_Tai_lieu/OUTBOX_WORKER.md`, báo cáo `07_Kiem_tra/AGENT_OUTBOX_REPORT.md`.

Không sửa migration, command kernel, event producers, API router, desktop, `pyproject.toml`, dependency lock,
CI hoặc fixture chung. Dùng schema sẵn có để tránh xung đột nhánh opening. Nếu phát hiện thiếu trường thiết yếu,
đề xuất DDL/lý do trong báo cáo và hoàn thiện phần độc lập; không tự thêm một migration trùng thứ tự.

## Kiểm thử bắt buộc

- Event chưa tới `available_at`, đã processed hoặc không có handler không được xử lý sai.
- Hai kết nối/worker tranh batch; cùng consumer/event không có hai hiệu ứng đã commit.
- Crash/failpoint giữa hiệu ứng và ACK: rollback, restart xử lý lại an toàn.
- Handler thất bại không ghi consumer_receipt thành công; backoff/attempts/last_error đúng và không lộ secret.
- Handler registry nhiều consumer và điều kiện đánh dấu event processed được quy định/kiểm thử rõ.
- Lỗi worker không sửa/xóa audit hoặc làm mất outbox của giao dịch nghiệp vụ.
- Chế độ một lượt, cấu hình sai, dừng sạch; có integration PostgreSQL thật, Ruff và full suite hồi quy.

Tài liệu cần nói rõ khởi động, quan sát/retry lỗi, giới hạn bảo đảm xử lý và chính sách event không có handler.
Commit local, trả hash và báo cáo; không chạy worker vào DB vận hành hoặc kết nối dịch vụ ngoài.
