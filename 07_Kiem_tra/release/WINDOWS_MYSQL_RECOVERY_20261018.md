# Windows MySQL: chặn phiên bản cũ và hướng dẫn cài lại

Ngày kiểm tra: 18/10/2026. Mã runtime: `a82a0ad75a29cc951f04ff75cec2b6a9c3f9cbe6`. Native CI chạy tại commit `4bf0e27cccc478612b24f48786aae9780506fbeb`, có cùng mã runtime và thêm hướng dẫn dùng MySQL đang có.

## Vấn đề và thay đổi

Máy người dùng báo MySQL 8.0.11, root kết nối được, database wms_mysql đã tồn tại sau setup thất bại. Thông báo cũ chỉ ghi OperationalError, không có mã driver nên không kết luận được câu SQL đã thất bại. Schema WMS dùng collation utf8mb4_0900_bin và cột INVISIBLE, không tương thích với 8.0.11.

Setup mới hỗ trợ dòng MySQL 8.0 từ 8.0.23 và 8.4 LTS. Trước khi tạo thư mục, database hoặc user WMS, công cụ kiểm tra phiên bản, múi giờ và thử collation, INVISIBLE, CHECK bằng một bảng tạm của phiên kết nối rồi tự xóa. Không bỏ qua CHECK để hỗ trợ MySQL cũ. Ngưỡng tính năng 8.0.23 không phải bằng chứng đã kiểm thử toàn bộ các patch của hai dòng MySQL.

Lệnh `preflight --mysql-port PORT` thực hiện độc lập kiểm tra này, không tạo database WMS hoặc đổi cấu hình ứng dụng. Hướng dẫn ưu tiên dùng instance đã có nếu phù hợp; không bắt cài đúng 8.0.46.

Thông báo lỗi chỉ lấy mã số MySQL từ driver, không xuất câu SQL, tham số, URL hoặc mật khẩu. Không thêm tự động tiếp tục migration dở dang và không xóa/ghi đè database.

Hướng dẫn kết nối dùng database mới wms_mysql_recovery trên instance tương thích đang có. Phương án cài riêng ở 3307 dành cho bản cũ không tương thích hoặc nhu cầu tách biệt, giữ bản cũ 3306. Cả hai đều không chuyển dữ liệu hoặc sửa database dở dang tại chỗ. Hướng dẫn cài mới 3306 cũng được sửa đường dẫn Windows, bổ sung lệnh nạp SQL timezone và yêu cầu kiểm tra phiên bản server bằng SELECT VERSION().

## Bằng chứng

- Local: 58 kiểm thử qua, 17 integration được tách khỏi bước unit. Ruff và kiểm tra artifact đạt.
- [Native Windows CI](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39144420922): SUCCESS ở cả **MySQL 8.0.46** và **8.4.11**. Mỗi job cài wheel rồi chạy với MySQL thật trên Windows Server 2022. Bao gồm preflight, setup, quyền NTFS, sáu worker, API/đăng nhập/MFA, từ chối setup trùng, dừng và khởi động lại; 58 kiểm thử hồi quy ở mỗi job.
- 31 khối PowerShell của hai hướng dẫn được parser PowerShell trên Windows kiểm tra cú pháp, không thực thi từng khối.
- [Validate WMS design](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39144205881): SUCCESS.
- [Bộ kiểm thử nghiệp vụ MySQL 8.0/8.4 mở rộng](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39144205692) là pipeline riêng; đang chạy lúc lập hồ sơ này, không tính là đã đạt trong bằng chứng native nêu trên. Kết quả hiện hành xem trực tiếp tại CI.

Các thay đổi tài liệu sau commit kiểm thử không đổi mã chạy trong wheel. Wheel tải từ artifact native CI được đối chiếu từng tệp payload với source trước khi đóng gói; checksum và số tệp có trong release-evidence.json của release.

## Giới hạn

Chưa thao tác trên máy Windows của người dùng; chưa chạy trọn bộ quy trình cài ZIP thủ công trên máy đó. Không khẳng định database cũ rỗng, không tự sửa marker INCOMPLETE thành COMPLETE, không đổi kết nối ứng dụng của người dùng. Kiểm thử native ở Windows Server 2022 không thay thế nghiệm thu Windows 10/11 và thiết bị thực tế.

[Dùng MySQL hiện có](../../01_Tai_lieu/WINDOWS_MYSQL_CONNECT.md) · [Cài riêng theo 16 bước](../../01_Tai_lieu/WINDOWS_MYSQL_RECOVERY.md)
