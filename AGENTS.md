# Quy tắc làm việc trong repository WMS

Đọc `/home/kien/.codex/RTK.md` nếu file có trên máy. Tất cả lệnh shell trong môi trường hiện tại phải bắt đầu bằng `rtk` (dùng `rtk proxy ...` để giữ nguyên output).
Khi được yêu cầu tạo ảnh/bản vẽ/CAD, ưu tiên công cụ MCP phù hợp; nếu thiếu phải nói rõ trước khi dùng phương án khác.

## Worktree và nhiệm vụ

Trước khi sửa mã, kiểm tra `pwd`, `git branch --show-current`, `git status --short` và đọc
[phân công worktree](01_Tai_lieu/PHAN_CONG/README.md). Mỗi agent chỉ làm trong worktree/nhánh được giao:

Đợt hiện tại có 26 nhánh `agent/b01-*` đến `agent/b26-*`; tra đúng tên trong
[catalog](01_Tai_lieu/PHAN_CONG/backlog.json) và [bảng toàn bộ phần còn lại](01_Tai_lieu/PHAN_CONG/KE_HOACH_CON_LAI.md).
Mỗi nhánh có brief Bxx riêng, phạm vi file/API/UI, dependency, kiểm thử và báo cáo bàn giao.
Đọc [quy trình agent](01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md) trước khi bắt đầu.

- Trạng thái READY trong catalog là mốc phân công ban đầu. Xem README phân công và sổ tích hợp mới nhất
  trước khi làm. B13/B16/B14 đã INTEGRATED; B07/B17 đã đồng bộ nền `101ef19`, READY để triển khai. Các nhánh đã tích hợp không làm lại.
  Worktree chờ phải đồng bộ giữ commit nghiên cứu trước khi triển khai phần phụ thuộc.
- Kiểm tra sổ `integration_log.json` trên nhánh điều phối mới nhất, không chỉ bản trong worktree cũ.
- `feat/application-foundation` là nhánh điều phối, review, tích hợp và kiểm thử tổng.
- `agent/opening`, `agent/outbox`, `agent/admin-ui` là hồ sơ đợt đã ghép; không tiếp tục giao việc mới
  trên ba nhánh này. Xem [lịch sử đợt trước](01_Tai_lieu/PHAN_CONG/DOT_1_DA_TICH_HOP.md).

Không switch/reset/rebase nhánh của agent khác, không sửa file ở worktree khác. Agent ở nhánh tính năng
không tự merge; agent điều phối tích hợp theo nhiệm vụ được giao. Không tự push, đóng issue hoặc gửi
thông báo GitHub. Có thể commit local phần việc đã được giao; bàn giao commit hash.
Nếu cần sửa ngoài phạm vi, ghi rõ đề xuất trong báo cáo bàn giao và tiếp tục phần độc lập còn làm được.

## Bất biến và kiểm thử

- Đọc `01_Tai_lieu/INVARIANTS.md`, hướng dẫn module liên quan và mã hiện có trước khi mở rộng.
- PostgreSQL là dữ liệu chính thức. Không ghi DB từ desktop. Không lưu credential vào SQLite/log.
- Lệnh ghi phải kiểm tra quyền hiện tại, version, chống trùng; ledger/balance/audit/outbox/ACK cùng transaction.
- Giữ migration đã tích hợp `001`–`020` bất biến; số mới chốt từ 021 trở đi khi tích hợp. Revision phát triển đã phân tên riêng trong catalog,
  chỉ dùng DB tạm riêng worktree. Điều phối chốt số tăng tiếp khi merge và kiểm thử upgrade từ mốc tổng;
  không sửa revision đã tích hợp/phát hành. Đọc quy tắc prefix migration trong quy trình agent.
- B19 sở hữu SQLite revision003 và recovery chung sau các domain; không ghi secret vào journal.
- Không đổi requirement/acceptance test sang PASS để né kiểm thử. T01–T28 vẫn PLANNED đến khi nghiệm thu đủ.
- Kiểm thử DB dùng runner tạo cluster/database tạm; không dùng `WMS_DATABASE_URL` vận hành.
- GUI và hủy tài nguyên Tk ở main thread; HTTP/SQLite qua worker và loại response thuộc phiên cũ.
- Kiểm thử tình huống lỗi/race/replay phù hợp thay đổi; không xóa/skip test cũ để có kết quả xanh.
- Không sửa tay `SHA256SUMS.txt`; sau khi review thay đổi, chạy `scripts/update_artifacts.py`, rồi `scripts/check_artifacts.py`.

Các file tổng hợp tiến độ/nghiệm thu do agent điều phối cập nhật sau tích hợp. Agent con ghi báo cáo riêng
theo file được giao. Cách chạy Python đúng nguồn worktree, phạm vi sở hữu và bàn giao nằm trong tài liệu phân công.
