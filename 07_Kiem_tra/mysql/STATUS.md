# WMS: chuyển dữ liệu sang MySQL

**Đã kích hoạt MySQL lúc 19:14:44 ngày 16/10/2026 (UTC+7)** trên máy triển khai.
Database vận hành: `wms_mysql`; driver `mysql+pymysql`.
PostgreSQL, bản sao lưu và cấu hình trước chuyển được giữ làm nguồn phục hồi.

| Kiểm tra | Kết quả |
| --- | --- |
| Đối chiếu dữ liệu trước kích hoạt | 108 bảng nghiệp vụ, 218,935 dòng; số dòng và SHA-256 từng bảng khớp |
| Đối soát nghiệp vụ | 25 truy vấn trên mỗi database nguồn PostgreSQL, WMS MySQL và KWS MySQL; không có sai lệch |
| Ràng buộc và khởi tạo | Khóa ngoại, trigger, sequence và readiness đã kiểm tra |
| Quyền tài khoản | Migration và runtime kết nối được; runtime dùng quyền riêng theo database |
| Bản sao lưu | PostgreSQL custom dump và MySQL SQL dump; đã kiểm tra lại SHA-256 |
| API và worker | Readiness đạt trước kích hoạt; dịch vụ khởi động, không tự khởi động lại trong khoảng quan sát |
| Công cụ chuyển dữ liệu/chuyển SQL không cần database | 23 kiểm thử đạt |
| Nhóm kiểm thử MySQL cuối trên database tạm | 42 đạt, không lỗi hoặc bỏ qua |
| Đóng gói | Wheel cài và chạy được ngoài checkout; 280 tệp Python/SQL/JSON khớp nguồn |
| Ruff và kiểm tra artifact | Đạt |
| Kiểm thử phục hồi của công cụ chuyển trên máy triển khai | 8 đạt, bao gồm ánh xạ cổng kết nối PostgreSQL |

[Bằng chứng tổng hợp](cutover.json) ghi kết quả tại thời điểm chuyển; báo cáo chi tiết,
credential và các bản dump được lưu riêng trên máy triển khai, không đưa vào Git.
Các báo cáo kiểm thử gốc ở `.reports/`. Kết quả này không phải tuyên bố toàn bộ
bộ kiểm thử đã chạy trên MySQL hoặc hosted CI đã đạt.

KWS giữ nguyên lịch sử, chứng từ đang mở và số dư WMS đã sao chép. Các sự kiện cũ
được lưu trong `migration_outbox_archive`, không chạy lại và không tạo ACK giả.
Phiên đăng nhập và mã phục hồi sao chép được thu hồi; người dùng đăng nhập lại KWS.

Sau khi MySQL nhận ghi mới, không đổi URL trở lại PostgreSQL một cách trực tiếp:
cần đối chiếu và bảo toàn các phát sinh mới trước khi phục hồi. Không chạy đồng
thời hai bộ ứng dụng ghi vào hai database như thể chúng được đồng bộ.

Quy trình: [triển khai MySQL](../../deploy/lan/mysql/README.md) và
[chuyển dữ liệu](../../mysql_migrations/README.md).
