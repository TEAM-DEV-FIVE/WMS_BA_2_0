# Máy chủ WMS trên Windows

Phạm vi: cài mới MySQL 8.0 trên cùng máy Windows x64, API loopback và sáu worker
chạy trong cửa sổ launcher. Database/config đã tồn tại được từ chối thay thế.

## Kết quả native

[Workflow 39136675716](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/39136675716)
đạt trên **Windows Server 2022 x64**, Python **3.12.10**, MySQL **8.0.46**.
Commit mã chạy: `3aca79a4344466db058ed4acdaa1096ecb1d3448`.

- 39 kiểm thử PDF tiếng Việt/barcode, worker và cấu hình đạt; 17 kiểm thử cần
  database được loại khỏi nhóm unit này theo marker, không được tính là PASS.
- Khởi tạo một MySQL riêng trong thư mục tạm, TCP loopback 3307; không dùng
  database WMS đang vận hành.
- Cài wheel, chạy ngoài source checkout với `python -I`, nạp schema và seed thật.
- Từ chối thiếu múi giờ, database/thư mục đã tồn tại; không thay mật khẩu/cấu hình
  khi chạy lại setup.
- Quyền runtime bị từ chối CREATE TABLE. Kiểm tra DACL cấu hình và tệp thực trên
  NTFS, đường dẫn tiếng Việt, lưu/đọc và ghi lại cùng nội dung bất biến.
- Tạo hai SYSADMIN; đăng nhập qua HTTP, chặn quản trị trước MFA, đăng ký/xác nhận
  TOTP, truy cập quản trị sau MFA và đăng xuất. SYSADMIN không tự có quyền kho.
- API health/ready, sáu worker có trạng thái hoạt động; launcher thứ hai bị chặn.
- Lệnh stop kết thúc API/worker, cả sáu worker ghi STOPPED. Mở lại với cùng
  database/khóa MFA và dừng lần thứ hai thành công.

Lỗi đọc JSON theo bảng mã Windows và lỗi thông báo khi đọc byte đã khóa được sửa
trước lần kiểm chứng trên. Không sửa nội dung migration đã phát hành.

## Bộ cài và tài liệu

[Bản Windows Standalone](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-windows-server.20261018)
gồm wheel lấy từ chính workflow trên, dependency lock, Word và lệnh PowerShell.
Tệp `release-evidence.json` ghi commit/run và SHA-256 wheel; `SHA256SUMS.txt` đi kèm
kiểm tra bộ ZIP. Desktop tiếp tục dùng bộ `efa4df60261a` đã kiểm chứng riêng.

[Hướng dẫn 15 bước](../../01_Tai_lieu/WINDOWS_STANDALONE.md) mô tả cài mới,
khởi tạo tài khoản, phân quyền, nghiệp vụ, dừng an toàn và sao lưu.

## Giới hạn

Đây là chạy server trong phiên đăng nhập Windows, chưa đăng ký API/worker thành
Windows Service. Kiểm thử không xác nhận Win10/11 trên máy người dùng, máy in thật,
phục hồi sau mất điện hoặc mức tải production. NTFS không cung cấp directory fsync
như POSIX; tệp được flush trước khi liên kết và cần chính sách backup phù hợp.
Hướng dẫn tạo database mới, không tự chuyển dữ liệu Linux hoặc thay kết nối máy
đang vận hành. Quy trình phục hồi và phân quyền nghiệp vụ hiện hành vẫn áp dụng.
