# WMS MySQL Local — Windows x64

Bản cài riêng, dùng lại nguyên giao diện và nghiệp vụ của bản thuyết trình.

## Lần đầu

1. Chạy `WMS-MySQL-Setup-…-x64.exe`, mở shortcut **WMS MySQL Local**.
2. App kiểm tra MySQL trên máy. Một dịch vụ MySQL đang tắt sẽ được tự khởi động.
   Nếu Windows hỏi UAC, chọn **Yes**. Chỉ lệnh bật dịch vụ được nâng quyền.
   Nếu có nhiều dịch vụ, chọn đúng dịch vụ và cổng rồi bấm **Kiểm tra / bật MySQL**.
3. Nếu chưa phát hiện Server, app mở https://dev.mysql.com/downloads/mysql/8.4.html.
   Cài MySQL Server 8.4 LTS, hoàn thành MySQL Configurator và ghi nhớ mật khẩu root.
   Quay lại app, bấm **Kiểm tra / bật MySQL**. Workbench riêng không thay thế Server.
4. Nhập cổng (thường 3306), mật khẩu MySQL root, tài khoản quản trị app và mật khẩu app.
   Mật khẩu root chỉ dùng trong lần thiết lập, không lưu lại.
5. Bấm **Thiết lập và mở**. App tạo `wms_mysql` mới, user runtime có quyền hạn chế,
   cấu trúc dữ liệu và một tài khoản quản trị. Không nạp hàng, kho, chứng từ hay dữ liệu demo.
6. Đăng nhập, thiết lập MFA và phân quyền theo quy trình hiện tại, sau đó nhập dữ liệu trong app.

MySQL được hỗ trợ: 8.0 từ 8.0.23 hoặc 8.4 LTS; không tự coi MariaDB/MySQL 9 là tương thích.
Nếu thiếu UTC/Asia/Ho_Chi_Minh, tùy chọn mặc định chỉ bổ sung hai múi giờ thiếu từ dữ liệu
MySQL chính thức đã đóng gói. Không thay thế các múi giờ hiện có. Nếu MySQL đã cache kết quả
múi giờ thiếu, thông báo kiểm tra sẽ xuất hiện; người quản trị cần lên lịch khởi động lại Server.
Ứng dụng không tự khởi động lại hoặc tắt MySQL đang chạy.

## Lần sau và dữ liệu cũ

Mở cùng shortcut: tự bật MySQL nếu cần, khởi động API/worker tại máy rồi mở giao diện.
Database và tài khoản đã tồn tại không được tự xóa, thay mật khẩu hay nhận làm database mới.
Nếu gặp trùng tên database/user hoặc cấu hình dở dang, giữ nguyên dữ liệu để kiểm tra.
Bản dùng máy chủ cũ vẫn mở được qua **Mở bản dùng máy chủ đã cấu hình trước**.

Cấu hình riêng: `%LOCALAPPDATA%\WMS-Server\runtime.json` (ACL riêng cho tài khoản Windows).
Tệp này có mật khẩu runtime và khóa MFA: không gửi/chia sẻ công khai.
Cổng API riêng: 8765, chỉ lắng nghe 127.0.0.1.
Cache giao diện bản local nằm trong thư mục server riêng, không ghi đè cache bản thuyết trình.
Sao lưu cả database, khóa/cấu hình và thư mục tệp nếu cần chuyển máy; không chỉ chép EXE.

Đóng cửa sổ kho trước, sau đó đóng cửa sổ quản lý máy chủ. Các worker đợi giao dịch kết thúc;
MySQL vẫn chạy để phục vụ chương trình khác. Gỡ bộ cài không xóa database/cấu hình người dùng.

## Kiểm chứng bản phát hành

Đối chiếu `SHA256SUMS.txt`, `local-smoke.json` và `release-evidence.json` đi cùng bộ cài.
`NOT_RUN` không có nghĩa là đã kiểm thử đạt. Bộ cài thử nghiệm hiện chưa có chữ ký nhà phát hành
được Windows tin cậy; Smart App Control có thể chặn. Không tắt bảo vệ Windows để vượt qua việc chặn.
Cần chứng thư ký mã tin cậy trước khi coi đây là bản phát hành công khai.

## Build

Trên Windows x64 có Python 3.12 và Inno Setup 6.7.3, dùng checkout sạch đã commit:

```powershell
./packaging/windows/Build-Local.ps1 -Unsigned
```

Bộ cài chứa hai phần tách biệt: `desktop` (client gốc, chỉ API) và `server` (launcher/API/worker).
Không đóng gói MySQL Server, mật khẩu, database hay dữ liệu người dùng. Quy trình CI nằm trong
`.github/workflows/windows-local.yml`; chạy trên nhánh build riêng sau khi được phép push.
