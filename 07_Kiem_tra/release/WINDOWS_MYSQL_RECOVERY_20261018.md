# Windows MySQL: chặn phiên bản cũ và hướng dẫn cài lại

Ngày kiểm tra: 18/10/2026. Mã chạy kiểm thử: `ed52c2ef4dc3db1e2e3196f30c31bc33acbf6b21`.

## Vấn đề và thay đổi

Máy người dùng báo MySQL 8.0.11, root kết nối được, database wms_mysql đã tồn tại sau setup thất bại. Thông báo cũ chỉ ghi OperationalError, không có mã driver nên không kết luận được câu SQL đã thất bại. Schema WMS dùng collation utf8mb4_0900_bin và cột INVISIBLE, không tương thích với 8.0.11.

Setup mới kiểm tra phiên bản trước khi tạo thư mục, database hoặc user, từ chối MySQL 8.0 trước 8.0.23 và các dòng ngoài 8.0. Tài liệu chọn phiên bản Windows đã kiểm thử 8.0.46. Ngưỡng tính năng 8.0.23 không phải bằng chứng đã kiểm thử toàn bộ các patch 8.0.23–8.0.45.

Thông báo lỗi chỉ lấy mã số MySQL từ driver, không xuất câu SQL, tham số, URL hoặc mật khẩu. Không thêm tự động tiếp tục migration dở dang và không xóa/ghi đè database.

Hướng dẫn mới tạo bản riêng ở cổng 3307, home WMS-Server-Recovery; giữ bản cũ 3306. Đây là cài database mới, không phải chuyển dữ liệu hoặc sửa database dở dang tại chỗ. Hướng dẫn cài mới 3306 cũng được sửa đường dẫn Windows, bổ sung lệnh nạp SQL timezone và yêu cầu kiểm tra phiên bản server bằng SELECT VERSION().

## Bằng chứng

- Local: 50 kiểm thử qua, 17 integration được tách khỏi bước unit. Ruff và kiểm tra artifact đạt.
- [Native Windows CI](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39143422096): SUCCESS; cài wheel rồi chạy với MySQL thật trên Windows Server 2022. Bao gồm setup, quyền NTFS, sáu worker, API/đăng nhập/MFA, từ chối setup trùng, dừng và khởi động lại.
- 22 khối PowerShell trong hướng dẫn cài lại được parser PowerShell trên Windows kiểm tra cú pháp, không thực thi từng khối.
- [Validate WMS design](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39143422067): SUCCESS.

Các thay đổi tài liệu sau commit kiểm thử không đổi mã chạy trong wheel. Wheel tải từ artifact native CI được đối chiếu từng tệp payload với source trước khi đóng gói; checksum và số tệp có trong release-evidence.json của release.

## Giới hạn

Chưa thao tác trên máy Windows của người dùng; chưa chạy trọn bộ quy trình cài ZIP thủ công trên máy đó. Không khẳng định database cũ rỗng, không tự sửa marker INCOMPLETE thành COMPLETE, không đổi kết nối ứng dụng của người dùng. Kiểm thử native ở Windows Server 2022 không thay thế nghiệm thu Windows 10/11 và thiết bị thực tế.

[Hướng dẫn 16 bước](../../01_Tai_lieu/WINDOWS_MYSQL_RECOVERY.md)
