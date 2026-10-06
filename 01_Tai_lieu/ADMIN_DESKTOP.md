# Desktop quản trị tài khoản và quyền

Tab **Quản trị tài khoản / quyền** dùng các API IAM hiện có; xem [IAM](IDENTITY.md).
Chọn tab từ ô **Chức năng** phía trên cửa sổ. Cả tám mục, kể cả đăng nhập, danh mục,
nhận hàng, phục hồi và kết nối đều truy cập được ở kích thước 900×690.

## Điều kiện sử dụng

Đăng nhập và xác thực MFA ở **Đăng nhập và kho**. Quyền GLOBAL `iam.manage` mở danh sách,
tạo tài khoản, khóa/mở và thu hồi phiên. Quyền GLOBAL `role.manage` mở role, grant,
yêu cầu cấp quyền, duyệt và thu hồi grant. Chỉ có một quyền thì chỉ thao tác được nhóm đó.
Chưa MFA thì mọi thao tác quản trị bị khóa. **Tải lại phiên** cập nhật quyền trên giao diện.

Mỗi thao tác tải/ghi còn đọc lại phiên trên worker trước khi gọi API; server kiểm tra quyền
hiện tại một lần nữa. Khi quyền/MFA không còn hợp lệ, tab xóa dữ liệu và khóa thao tác cho
đến khi tải lại phiên. Khi phát hiện phiên bị thu hồi, token và dữ liệu phiên trên các tab được
xóa. SYSADMIN không mặc nhiên có quyền đọc tồn/chứng từ hoặc danh sách kho.

## Tài khoản

1. Chọn **Tài khoản**, bấm **Tải lại từ đầu**. Các tài khoản được sắp theo username.
2. Nhập tài khoản mới (3–100 ký tự: chữ/số, dấu chấm, gạch dưới, gạch ngang; ký tự đầu
   là chữ/số), tên hiển thị và mật khẩu 12–128 ký tự, bấm **Tạo tài khoản**.
3. Chọn một dòng, nhập lý do 3–2000 ký tự rồi bấm **Khóa**, **Mở khóa** hoặc **Thu hồi phiên**.
   Không khóa/mở tài khoản đang đăng nhập. Mở lại tài khoản không hồi sinh phiên cũ.
4. Thu hồi phiên của chính mình kết thúc phiên desktop ngay khi server xác nhận thành công.

Mật khẩu được xóa khỏi ô nhập ngay khi gửi, kể cả khi form không hợp lệ. Không lưu mật khẩu,
token hoặc MFA vào nháp, SQLite hay log. Sau khi tạo tài khoản, UUID người nhận được điền
sẵn cho form yêu cầu cấp quyền; chọn một dòng tài khoản cũng thực hiện việc này.

## Role, scope và duyệt hai người

1. **Role** liệt kê toàn bộ role đang hoạt động mà endpoint hiện tại trả về (code và tên).
   Chọn dòng để điền mã role vào form yêu cầu; cũng có thể nhập trực tiếp mã role.
2. Chọn **Tra người nhận**, nhập tên/mã vào ô tìm và Enter, chọn dòng. Làm tương tự với **Tra kho**.
   Quay lại **Yêu cầu chờ duyệt**, chọn tên người/kho từ dropdown, mã role, scope, thời hạn và lý do.
   `GLOBAL` là phạm vi hệ thống; `WAREHOUSE` bắt buộc UUID của đúng một kho;
   `ALL_WAREHOUSES` là tất cả kho. GLOBAL/ALL_WAREHOUSES không nhận UUID kho.
3. Lookup dùng `role.manage` + MFA, kể cả quản trị viên không có `iam.manage` hoặc quyền kho.
   Chỉ trả danh tính user/kho đang hoạt động; không cấp thêm quyền đọc tồn/chứng từ.
   Server kiểm tra lại user/role/kho và quyền khi lập/duyệt yêu cầu.
4. Thời hạn trống nghĩa là không thời hạn; nếu nhập phải là ISO 8601 có múi giờ,
   ví dụ `2027-01-31T17:00:00+07:00`. Server kiểm tra thời điểm đó còn ở tương lai.
5. Bấm **Lập yêu cầu**. Chưa có grant cho đến khi một quản trị viên khác đăng nhập/MFA,
   tải yêu cầu chờ, chọn dòng và **Duyệt dòng đã chọn**. Người yêu cầu và người nhận quyền
   không được duyệt. Cũng không được yêu cầu cấp quyền cho chính mình.
6. **Grant đã cấp** hiển thị cả grant đã hết hạn/thu hồi. Chọn grant, nhập lý do rồi bấm
   **Thu hồi grant đã chọn**. Server kiểm tra lại hiệu lực ở request kế tiếp.

Bảng có thanh cuộn ngang; vùng chi tiết có thể chọn/copy toàn bộ UUID, scope, kho, mốc thời
gian, người yêu cầu và lý do. Lý do có trên yêu cầu chờ. API danh sách grant chưa trả lý do
cấp/thu hồi; xem **Lịch sử bảo mật** với GLOBAL `audit.security.read` + MFA để đối chiếu event và lý do. API role cũng chưa trả danh sách permission của role.
Thay đổi role, kho hoặc quyền người yêu cầu giữa lúc tải và lúc duyệt sẽ hiển thị lỗi thật
của server cùng request ID nếu có; UI không tự sửa scope hay bỏ qua lỗi SOD.

## Phân trang và kết quả chưa xác định

Tài khoản, grant và yêu cầu chờ được tải 100 dòng mỗi trang. **Trang sau** dùng username cuối
cho tài khoản, UUID cuối cho hai danh sách còn lại. Một trang đủ 100 dòng luôn cho phép đi
tiếp; có thể gặp trang rỗng cuối cùng khi tổng số dòng là bội của 100. **Tải lại từ đầu** bắt
đầu lại danh sách. Số dòng của trang không phải tổng số bản ghi. API dùng keyset hiện tại,
không phải snapshot: khi có người thay đổi dữ liệu đồng thời, tải lại từ đầu để đối chiếu.

Các lệnh IAM không đi qua CommandBus và không có idempotency cho toàn bộ thao tác. UI gửi
một lần, chặn nút khi bận, không tự retry hoặc giữ payload để phát lại. Timeout, mất kết nối
hay phản hồi ghi hỏng khiến kết quả **chưa rõ**: server có thể đã hoàn tất lệnh.

Tải lại danh sách liên quan, kiểm tra người dùng/yêu cầu/grant rồi bấm **Đã đối chiếu** để
mở thao tác mới. Nút này chỉ xác nhận bạn đã đối chiếu, không kết luận lệnh cũ chưa chạy.
Với thu hồi phiên, dùng **Lịch sử phiên** để kiểm tra hiệu lực và đối chiếu ở phiên bị thu hồi. Khi còn nghi ngờ, dùng request ID nếu có để
đối chiếu log server. Đăng xuất/đổi phiên xóa toàn bộ form và trạng thái chưa rõ trong RAM;
sau khi đăng nhập lại vẫn phải đối chiếu trước khi tự thực hiện thao tác mới.

## Phạm vi kiểm thử và giới hạn

HTTP chạy trên worker; cập nhật widget và hủy biến Tk trên main thread. Response của phiên
cũ bị loại; tác vụ còn chờ không được gửi dưới danh tính mới. Lệnh đã tới server trước khi
đăng xuất vẫn có thể hoàn tất, nên phải đối chiếu trạng thái sau đó.

Kiểm thử ở [test admin presenter](../tests/foundation/test_admin_presenter.py) và
[test admin desktop](../tests/foundation/test_admin_desktop.py) bao gồm Tk → HTTP loopback
→ PostgreSQL tạm, MFA/quyền/SOD, phân trang trên 200 dòng, revoke, lỗi thay đổi quyền/kho/role,
timeout không phát lại, dữ liệu phiên cũ và cleanup. Đây là bằng chứng Linux/Xvfb,
chưa phải Windows UAT hoặc nghiệm thu toàn bộ T07/T11. B04 đã bổ sung credential lifecycle,
lookup, lịch sử phiên và audit; thu hồi hiện thực theo toàn bộ phiên của user, chưa chọn một
phiên riêng để thu hồi. Permission chi tiết của role chưa có trên UI.


## B04 — thao tác mật khẩu và MFA

Trong **Đăng nhập và kho**, chọn **Mật khẩu / khôi phục** để mở form:

- **Đổi mật khẩu**: nhập mật khẩu hiện tại, TOTP mới nếu đã bật MFA và mật khẩu mới.
- **Dùng mã reset mật khẩu**: nhập username, mã do quản trị viên cấp và mật khẩu mới.
- **Tạo lại 8 mã khôi phục MFA**: nhập mật khẩu + TOTP mới. Bộ cũ hết hiệu lực; bộ mới chỉ
  hiển thị trong cửa sổ riêng tối đa 60 giây, không tự copy clipboard hoặc lưu file.
- **Reset MFA bằng mã TOTP**: nhập mật khẩu + TOTP mới; đăng nhập lại và bật MFA mới.
- **Mất TOTP: dùng mã khôi phục**: trước tiên login bằng mật khẩu để tới bước yêu cầu MFA,
  sau đó dùng một mã dự phòng. Toàn bộ bộ mã cũ hết hiệu lực; bật MFA rồi tạo bộ mới.

Ô nhập credential được xóa khi gửi/đóng form/đổi phiên. Khóa enrollment tự ẩn sau 5 phút.
Mã recovery/reset chỉ hiển thị ở cửa sổ cần thiết, đóng khi đổi phiên, tải lại hoặc hết thời
gian. Kết quả từ phiên cũ bị bỏ trước khi hiển thị; worker không trả exception traceback
chứa password/TOTP vào queue UI. Không lưu IAM payload vào SQLite/replay journal.

Trong tab quản trị, chọn **Đặt lại mật khẩu**, tải và chọn user, nhập mật khẩu/TOTP **của
quản trị viên đang đăng nhập** cùng lý do rồi cấp mã. Mã có hạn 15 phút; giao cho đúng người
qua kênh riêng. Không thể đọc lại mã qua danh sách/lịch sử. Khi timeout, desktop yêu cầu
đăng nhập lại; kiểm tra **Lịch sử bảo mật** trước khi chủ động cấp mã mới thay mã cũ.

**Lịch sử phiên** cần `iam.manage` + MFA; có user, thiết bị, lúc tạo/hết hạn/thu hồi, hiệu lực.
Chọn một dòng và nhập lý do để thu hồi **mọi phiên của user đó**. **Lịch sử bảo mật** cần
`audit.security.read` GLOBAL + MFA; có actor, hành động, đối tượng, thời điểm, request ID,
lý do nhưng không có credential hoặc payload audit đầy đủ. Hai danh sách phân trang 100
bản ghi theo UUID; thứ tự UUID không đại diện thứ tự thời gian, dùng cột thời điểm để đối chiếu.
