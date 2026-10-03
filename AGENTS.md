# Quy tắc làm việc trong repository WMS

Đọc `/home/kien/.codex/RTK.md` nếu file có trên máy. Tất cả lệnh shell trong môi trường hiện tại phải bắt đầu bằng `rtk` (dùng `rtk proxy ...` để giữ nguyên output).
Khi được yêu cầu tạo ảnh/bản vẽ/CAD, ưu tiên công cụ MCP phù hợp; nếu thiếu phải nói rõ trước khi dùng phương án khác.

## Worktree và nhiệm vụ

Trước khi sửa mã, kiểm tra `pwd`, `git branch --show-current`, `git status --short` và đọc
[phân công worktree](01_Tai_lieu/PHAN_CONG/README.md). Mỗi agent chỉ làm trong worktree/nhánh được giao:

| Nhánh | Nhiệm vụ |
| --- | --- |
| `agent/opening` | [Backend tồn đầu kỳ](01_Tai_lieu/PHAN_CONG/AGENT_OPENING.md) |
| `agent/outbox` | [Worker outbox](01_Tai_lieu/PHAN_CONG/AGENT_OUTBOX.md) |
| `agent/admin-ui` | [Desktop quản trị](01_Tai_lieu/PHAN_CONG/AGENT_ADMIN_UI.md) |
| `feat/application-foundation` | Điều phối, review, tích hợp và kiểm thử tổng |

Không switch/reset/rebase nhánh của agent khác, không sửa file ở worktree khác. Không tự push, merge,
đóng issue hoặc gửi thông báo GitHub. Có thể commit local phần việc đã được giao; bàn giao commit hash.
Nếu cần sửa ngoài phạm vi, ghi rõ đề xuất trong báo cáo bàn giao và tiếp tục phần độc lập còn làm được.

## Bất biến và kiểm thử

- Đọc `01_Tai_lieu/INVARIANTS.md`, hướng dẫn module liên quan và mã hiện có trước khi mở rộng.
- PostgreSQL là dữ liệu chính thức. Không ghi DB từ desktop. Không lưu credential vào SQLite/log.
- Lệnh ghi phải kiểm tra quyền hiện tại, version, chống trùng; ledger/balance/audit/outbox/ACK cùng transaction.
- Giữ migration `001`–`009` bất biến. Đợt này chỉ nhánh opening được thêm `010_opening.sql`.
- Không đổi requirement/acceptance test sang PASS để né kiểm thử. T01–T28 vẫn PLANNED đến khi nghiệm thu đủ.
- Kiểm thử DB dùng runner tạo cluster/database tạm; không dùng `WMS_DATABASE_URL` vận hành.
- GUI và hủy tài nguyên Tk ở main thread; HTTP/SQLite qua worker và loại response thuộc phiên cũ.
- Kiểm thử tình huống lỗi/race/replay phù hợp thay đổi; không xóa/skip test cũ để có kết quả xanh.
- Không sửa tay `SHA256SUMS.txt`; sau khi review thay đổi, chạy `scripts/update_artifacts.py`, rồi `scripts/check_artifacts.py`.

Các file tổng hợp tiến độ/nghiệm thu do agent điều phối cập nhật sau tích hợp. Agent con ghi báo cáo riêng
theo file được giao. Cách chạy Python đúng nguồn worktree, phạm vi sở hữu và bàn giao nằm trong tài liệu phân công.
