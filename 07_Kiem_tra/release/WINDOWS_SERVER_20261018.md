# Máy chủ WMS trên Windows

Phạm vi: cài mới MySQL 8.0 trên cùng máy Windows x64, API loopback và sáu worker
chạy trong cửa sổ launcher. Database/config đã tồn tại được từ chối thay thế.

Kiểm tra native đang được thực hiện trong workflow
`Native Windows standalone MySQL server`. Kết quả lần cuối và bộ phân phối sẽ
được cập nhật sau khi khởi tạo, đăng nhập/MFA, storage và dừng/khởi động lại đạt.

39 kiểm thử không cần database đã đạt trên Linux. Lần native đầu tiên phát hiện
đọc JSON migration theo bảng mã mặc định Windows; mã đọc đã được chuyển sang UTF-8.
Chưa dùng kết quả Linux để khẳng định server đã hoạt động trên Windows.
