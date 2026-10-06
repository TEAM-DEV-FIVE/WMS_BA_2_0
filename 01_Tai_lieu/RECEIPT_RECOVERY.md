# Phục hồi ghi sổ nhận hàng — UI08 / TL03 / UI06

Cập nhật 03/10/2026. Desktop lưu lệnh `receipt.post` vào SQLite trước khi gọi API.
Khi mất phản hồi hoặc đóng process, đăng nhập lại cùng tài khoản trên cùng máy và máy chủ để tra cứu
hoặc gửi lại đúng lệnh. PostgreSQL vẫn là nguồn tồn kho chính thức.

## Cách sử dụng

1. Nhận hàng theo [RECEIVING.md](RECEIVING.md). Trước mỗi lần ghi sổ, desktop lưu HTTP key,
   `execution_key`, endpoint, version và toàn bộ payload; hoàn tất checkpoint `SENDING` rồi mới gửi HTTP.
2. Nếu chưa rõ kết quả, mở tab **Phục hồi nhận hàng**. Mở lại ứng dụng chỉ đọc dữ liệu cục bộ,
   không tự gửi lại lệnh. Danh sách tối đa 200 lệnh, ưu tiên lệnh chưa rõ kết quả.
3. Chọn lệnh và bấm **Tra kết quả máy chủ**. Nếu server trả xác nhận đã commit, desktop lưu kết quả
   `COMMITTED` và tải lại phiếu ở tab Nhận hàng. Tồn kho không tăng thêm do thao tác tra cứu.
4. Nếu vẫn chưa tra được, bấm **Gửi lại đúng lệnh đã chọn** khi muốn thử tiếp. Desktop tra cứu một lần nữa;
   chỉ khi chưa tìm thấy mới POST với cùng HTTP key, `execution_key`, endpoint và payload đã lưu.
   Nội dung đang nhập trên form không thay thế lệnh cũ. Server kiểm tra quyền hiện tại và chống ghi trùng.
5. Sau khi lệnh được xác nhận hoặc bị từ chối rõ ràng, tải lại phiếu trước khi nhập lần nhận tiếp theo.
   Lệnh mới có key mới và dùng version/lượng còn lại hiện tại từ server.

HTTP 404 khi tra cứu **không chứng minh lệnh chưa commit**: quyền nguồn/phiếu có thể đã đổi.
Timeout, lỗi máy chủ, thiếu quyền hoặc kết quả không khớp đều giữ lệnh để đối chiếu; không tạo key thay thế.
Khi còn lệnh chưa rõ kết quả hoặc không đọc/lưu được SQLite, desktop khóa lệnh ghi mới ở tab Nhận hàng.
Lỗi quyền cần được giải quyết trên máy chủ trước khi thử lại.

| Trạng thái lưu | Ý nghĩa và xử lý |
| --- | --- |
| `READY` | Đã lưu nội dung; chưa hoàn tất checkpoint gửi. Có thể tra cứu hoặc gửi lại cùng key. |
| `SENDING` | Đã checkpoint trước HTTP; có thể đã commit ở server. Mở lại chuyển thành `UNKNOWN`. |
| `UNKNOWN` | Chưa có xác nhận chắc chắn. Tra cứu hoặc chủ động gửi lại đúng lệnh. |
| `COMMITTED` | Có ACK hợp lệ, khớp phiếu và version; lưu ID giao dịch và request ID gốc. |
| `CONFLICT` | Server từ chối rõ ràng, ví dụ stale version, vượt lượng hoặc kỳ đóng. Giữ lỗi để đối chiếu; tải lại phiếu. |

## Dữ liệu cục bộ và nâng cấp

`WMS_LOCAL_DATA_DIR` chọn thư mục lưu trên ổ đĩa máy desktop; không đặt SQLite trên network share.
Nếu không cấu hình:

- Windows: `%LOCALAPPDATA%/wms-lan`, dự phòng `~/AppData/Local/wms-lan`.
- Linux: `$XDG_DATA_HOME/wms-lan`, dự phòng `~/.local/share/wms-lan`.

Thư mục có `device.sqlite3` giữ UUID thiết bị bền qua restart và `receipts/` chứa các file được phân vùng
theo URL máy chủ, user và thiết bị. Giữ **cả hai** khi cập nhật ứng dụng. Đổi URL/profile OS/thư mục dữ liệu
sẽ chọn phân vùng khác; hiện chưa có công cụ gộp/chuyển phân vùng. Khi sao lưu cục bộ, đóng desktop trước.
Không xóa file để bỏ qua một lệnh chưa rõ kết quả. File hỏng hoặc version mới hơn được giữ lại và báo lỗi,
không tự khởi tạo đè dữ liệu cũ.

SQLite runtime nâng từ `user_version=1` lên `2` trong một transaction, thêm metadata hiển thị và index;
giữ nguyên key, payload, hash và execution key. Migration lỗi rollback toàn bộ. Store dùng `synchronous=FULL`,
kiểm tra hash/nội dung trước phục hồi và khóa OS để một cửa sổ sở hữu mỗi phân vùng. Khóa được giải phóng
khi process chết; không xóa file `.lock` khi ứng dụng khác còn mở.

Không lưu password, access/refresh token hoặc mã MFA vào SQLite. UUID thiết bị không phải credential.
File SQLite được tạo với quyền `0600` trên POSIX; Windows dùng quyền truy cập của profile người dùng.
Logout xóa dữ liệu đang hiển thị nhưng giữ nhật ký trên ổ đĩa. User khác không được nạp phân vùng của user trước.
SQLite và HTTP chạy trên worker; widget chỉ cập nhật trên main thread. Đóng bình thường chờ lệnh đang chạy
lưu kết quả; bị dừng đột ngột thì lần mở sau tra cứu lại.

## Bằng chứng và giới hạn

[test_receipt_recovery.py](../tests/foundation/test_receipt_recovery.py) kiểm tra migration/rollback,
khóa file, process chết sau checkpoint, timeout, thiếu quyền/404, giữ nguyên key/body khi retry,
file/context hỏng, disk full trước gửi hoặc lúc lưu ACK, đổi phiên và đóng cửa sổ khi HTTP đang chạy.

[test_receipts.py](../tests/foundation/test_receipts.py) chạy PostgreSQL và HTTP thật: process con ghi sổ 40/100,
bị dừng ngay sau server commit trước khi lưu ACK; desktop mới đăng nhập, nạp `UNKNOWN`, tra đúng giao dịch,
đối chiếu chỉ một transaction/move và tồn 40, PO còn 60. Logout và đổi user xóa dữ liệu phiên khỏi giao diện.
Đã xem bố cục 900×690 trên Linux/Xvfb. Kết quả tổng ở
[IMPLEMENTATION_REVIEW.md](../07_Kiem_tra/IMPLEMENTATION_REVIEW.md).

Đợt này chỉ phục hồi bền **ghi sổ nhận hàng**. Tạo/sửa/gửi duyệt/duyệt phiếu, PO/SO và danh mục vẫn giữ
yêu cầu chưa rõ kết quả trong RAM; nháp nghiệp vụ chưa tự lưu/phục hồi qua giao diện. Chưa có ghi sổ offline,
recovery cho nghiệp vụ khác, Windows UAT hay bộ cài EXE. Issue #18 vẫn PARTIAL và T01–T28 vẫn PLANNED
cho nghiệm thu toàn hệ thống.
