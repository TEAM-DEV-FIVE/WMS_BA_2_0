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
2. Chọn **Yêu cầu chờ duyệt**, nhập UUID người nhận, mã role, scope, thời hạn và lý do.
   `GLOBAL` là phạm vi hệ thống; `WAREHOUSE` bắt buộc UUID của đúng một kho;
   `ALL_WAREHOUSES` là tất cả kho. GLOBAL/ALL_WAREHOUSES không nhận UUID kho.
3. UUID kho cần lấy từ người quản trị danh mục có thẩm quyền. UI kiểm tra định dạng UUID;
   server quyết định kho/user/role còn hoạt động và quyền phù hợp. Không cấp thêm quyền
   đọc kho chỉ để điền form. Người chỉ có `role.manage` nhập UUID user trực tiếp vì không có
   quyền xem danh sách tài khoản.
4. Thời hạn trống nghĩa là không thời hạn; nếu nhập phải là ISO 8601 có múi giờ,
   ví dụ `2027-01-31T17:00:00+07:00`. Server kiểm tra thời điểm đó còn ở tương lai.
5. Bấm **Lập yêu cầu**. Chưa có grant cho đến khi một quản trị viên khác đăng nhập/MFA,
   tải yêu cầu chờ, chọn dòng và **Duyệt dòng đã chọn**. Người yêu cầu và người nhận quyền
   không được duyệt. Cũng không được yêu cầu cấp quyền cho chính mình.
6. **Grant đã cấp** hiển thị cả grant đã hết hạn/thu hồi. Chọn grant, nhập lý do rồi bấm
   **Thu hồi grant đã chọn**. Server kiểm tra lại hiệu lực ở request kế tiếp.

Bảng có thanh cuộn ngang; vùng chi tiết có thể chọn/copy toàn bộ UUID, scope, kho, mốc thời
gian, người yêu cầu và lý do. Lý do có trên yêu cầu chờ. API danh sách grant chưa trả lý do
cấp/thu hồi; UI nêu rõ giới hạn này. API role cũng chưa trả danh sách permission của role.
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
Với thu hồi phiên, danh sách tài khoản không chứng minh các phiên đã bị thu hồi: cần xác minh
ở phiên bị thu hồi hoặc với quản trị vận hành. Khi còn nghi ngờ, dùng request ID nếu có để
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
chưa phải Windows UAT hoặc nghiệm thu toàn bộ T07/T11. Chưa có đổi mật khẩu/reset MFA,
quản lý từng phiên, permission chi tiết của role hoặc lịch sử audit trên UI vì thiếu API.
