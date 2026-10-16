# WMS với MySQL

Yêu cầu: MySQL 8.0 có InnoDB, kiểm tra CHECK và bảng múi giờ; Python 3.12
với dependency trong `requirements-app-lock.txt`. Driver là `mysql+pymysql`.
Mỗi ứng dụng dùng database, tài khoản, thư mục tệp và cổng API riêng.

- WMS: `wms_mysql`, API loopback cổng 8000.
- KWS: `kws_mysql`, API loopback cổng 8001.
- Desktop KWS cùng máy cần `KWS_API_URL=http://127.0.0.1:8001/api/v1`.

## Quyền và khởi tạo

Tài khoản runtime chỉ cần SELECT, INSERT, UPDATE, DELETE và EXECUTE trên database
của ứng dụng. Không cấp SUPER, FILE, quyền toàn máy chủ hoặc DDL cho tài khoản này.
Tài khoản migration riêng dùng cho tạo bảng và kiểm tra. Trên MySQL bật binary log,
quản trị viên cài trigger/procedure; không bật `log_bin_trust_function_creators`
chỉ để bỏ qua yêu cầu quyền.

Nạp múi giờ bằng công cụ `mysql_tzinfo_to_sql` của MySQL và dữ liệu zoneinfo máy chủ.
Kết nối từ chối khởi động nếu thiếu múi giờ nghiệp vụ đã cấu hình.

Database mới và trống có thể dùng `python -m apps.server.infrastructure.migrations`
với tài khoản quản trị migration. Database đã sao chép dữ liệu phải đi qua
[quy trình staging](../../../mysql_migrations/README.md); bootstrap không tự nhận
một database có sẵn và không xóa dữ liệu.

## Chuyển dữ liệu và kết nối

1. Sao lưu PostgreSQL, khóa ghi bằng cách dừng API và worker nguồn.
2. Chuyển dữ liệu vào database MySQL staging trống. Đối chiếu số dòng, SHA-256,
   khóa ngoại, số thứ tự chứng từ và toàn bộ truy vấn đối soát.
3. Cài trigger và các bảng runtime bằng `scripts/prepare_mysql_stage.py`.
4. Kiểm tra readiness, API, phân quyền và worker với bản mã đã qua kiểm thử.
5. Cập nhật tệp môi trường riêng và khởi động ứng dụng. Desktop vẫn đi qua API.

KWS giữ lịch sử chứng từ và số dư WMS được chuyển. Sự kiện cũ được lưu trong
`migration_outbox_archive` để không chạy lại; không ghi ACK giả. Phiên đăng nhập
sao chép bị thu hồi, nên người dùng đăng nhập lại vào KWS.

## Phục hồi và sao lưu

Giữ nguyên cluster PostgreSQL, bản dump, phiên bản ứng dụng và cấu hình trước khi
chuyển. Không chạy hai bộ worker ghi vào hai database như thể chúng đồng bộ.
Trước khi có ghi mới trên MySQL, có thể quay lại bộ ứng dụng/cấu hình PostgreSQL
đã lưu. Sau khi có ghi mới, cần đối chiếu/chuyển các phát sinh trước khi phục hồi;
đổi URL đơn thuần sẽ bỏ mất các phát sinh đó.

Sao lưu MySQL phải gồm dữ liệu InnoDB, trigger, routine và các thư mục tệp của
ứng dụng. Công cụ backup/PITR PostgreSQL cũ không phải công cụ backup MySQL.
MySQL không có deferred constraint trigger: kiểm tra đảo giao dịch chạy trước
commit trong adapter ứng dụng. Không dùng công cụ ghi SQL ngoài ứng dụng để bỏ
qua quy trình này.

## Kết quả triển khai

Bản triển khai ngày 16/10/2026 đã dùng MySQL.
[Xem bằng chứng chuyển dữ liệu và đối soát](../../../07_Kiem_tra/mysql/STATUS.md).
