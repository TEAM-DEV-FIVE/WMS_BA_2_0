# Phân công phần còn lại — 26 nhánh

Đọc [bảng công việc đầy đủ](KE_HOACH_CON_LAI.md) để chọn nhiệm vụ; mỗi dòng liên kết tới brief riêng
có nhánh, worktree, phạm vi, dependency, kiểm thử và prompt giao agent.

- **Giao ngay:** B01, B02, B03, B04, B05, B06, B08, B15.
- **Chờ tích hợp dependency:** 18 nhánh còn lại; worktree được tạo sẵn nhưng chưa có code phụ thuộc.
- **Quy trình bắt buộc:** [QUY_TRINH_AGENT.md](QUY_TRINH_AGENT.md), đặc biệt migration/DB tạm, import đúng worktree và bàn giao.
- **Dữ liệu điều phối:** [backlog.json](backlog.json), [integration_log.json](integration_log.json).
- **Lịch sử:** [ba nhánh đợt trước đã tích hợp](DOT_1_DA_TICH_HOP.md); giữ nguyên worktree cũ để review.

Mốc mã trước khi chia nhánh: `06041b7`, 301 tests + 10 subtests local. Kế hoạch mới phủ 37 issue OPEN
trong snapshot local, 49 yêu cầu và 28 acceptance tests; đây không phải kết quả nghiệm thu hoặc trạng thái
GitHub vừa cập nhật. Các agent chỉ commit local, điều phối review/tích hợp; không tự push/đóng issue.
