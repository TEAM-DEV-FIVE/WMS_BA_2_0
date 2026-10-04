# Màn hình tồn đầu kỳ thủ công — B06

Chọn **Tồn đầu kỳ** trong thanh Chức năng. Màn hình dùng các API OPENING đã tích hợp
ở migration 010, không ghi DB và không tạo migration. Quy tắc nghiệp vụ đầy đủ ở
[OPENING.md](OPENING.md).

## Lập và duyệt phiếu

1. Đăng nhập, chọn kho được cấp quyền rồi **Tải phiếu**. Danh sách lọc theo trạng thái,
   25 phiếu/trang. Người chỉ có quyền duyệt vẫn xem và duyệt được khi không có quyền danh mục GLOBAL.
2. Người có `opening.draft` chọn **Tạo mới**. Batch UUID sinh một lần cho nháp mới,
   có thể nhập batch nguồn trước khi lưu; sau khi tạo không đổi batch hoặc kho của phiếu.
3. Nhập ngày nghiệp vụ, tham chiếu biên bản kiểm kê đã ký và lý do. Tìm SKU/vị trí;
   mỗi danh mục tìm kiếm/phân trang 100 mục. SKU đọc đơn vị cơ sở từ server, không nhập factor.
   Nhập lượng decimal dạng chuỗi, thêm dòng; chọn dòng để cập nhật hoặc bỏ dòng.
4. NONE không nhập lô/serial; LOT nhập lô, NSX/HSD nếu có; SERIAL mỗi dòng lượng 1.
   Mã lô/serial giữ nguyên hoa/thường và số 0 đầu. Form kiểm tra lượng dương, precision
   khi đã tải UOM, trùng serial, ngày và giới hạn 1–200 dòng trước gửi. Server kiểm tra lại toàn bộ.
   B09 thêm selector Chủ/HĐ: COMPANY hoặc chủ CONSIGNOR kèm hợp đồng. Cùng SKU khác owner
   được hiển thị thành dòng riêng; server kiểm lại owner/hợp đồng khi gửi và ghi sổ. Import B01
   chạy riêng qua staging. Màn **Nhận ký gửi** dùng cùng cơ chế form/ACK, chứng từ giao nhận
   và vị trí nhận/cách ly, không áp dụng cutover; xem [B09](CONSIGNMENT.md).
5. **Lưu nháp** → **Gửi duyệt**. Người khác có `opening.approve` theo đúng role/bước
   của policy chọn **Duyệt** hoặc **Từ chối**, nhập lý do. Lịch sử hiển thị phiên bản,
   vai trò từng bước, người quyết định và nhận xét. Nút thao tác lấy từ `allowed_actions`;
   server luôn kiểm tra SOD/quyền hiện hành.
6. Có thể sửa phiếu nháp/từ chối. Phiếu đã duyệt cần **Sửa lại**, lưu và gửi duyệt lại.
   Nếu máy chủ trả stale version/approval, màn hình tự đọc phiên bản mới và báo STALE;
   người dùng kiểm tra lại nội dung trước thao tác tiếp, không tự gửi lại lệnh stale.
7. Người có `opening.post` chọn **Ghi sổ** sau duyệt. Một kho chỉ ghi toàn bộ một lần
   khi chưa có lịch sử tồn; không chia nhiều phiếu để vượt 200 dòng.

## Trạng thái và mất phản hồi

- **DRAFT**: nội dung trên màn hình chưa lưu server; chưa có lưu nháp SQLite.
- **SYNCED**: đã đọc/lưu phiếu trên server; chưa khẳng định lệnh post đang chờ đã thành công.
- **UNKNOWN**: timeout, mất LAN hoặc phản hồi không hợp lệ. Giữ nguyên method/path/body,
  HTTP key, execution key và batch. Nút tạo/ghi bị khóa cho người dùng + kho có lệnh chờ.
- **POSTED**: đã nhận ACK hợp lệ của post hoặc operation lookup, có transaction ID và request ID.
  Chỉ thấy phiếu `COMPLETED` từ GET chưa thay cho ACK của yêu cầu chưa rõ kết quả.

Chọn **Tra trạng thái / ACK** trước retry. Với post, gọi `GET /openings/operations/{HTTP key}`.
404 không chứng minh lệnh cũ chưa commit: nút **Gửi lại nguyên yêu cầu đã tra** chỉ gửi
đúng yêu cầu cũ, không sinh key/execution/batch mới. Có ACK thì kết thúc chờ, không gửi lại post.
Với create, tra các trang phiếu trong kho và đọc batch của từng phiếu; với sửa/workflow,
đọc phiếu hiện hành. Các API này không cung cấp ACK riêng cho lệnh nháp/workflow nên
sau tra vẫn replay đúng yêu cầu cũ để nhận response idempotent, không suy thành công từ trạng thái.

Có thể dán HTTP key của lệnh post để tra ACK; phải dùng chính tài khoản đã gửi lệnh,
chọn đúng kho và còn quyền hiện hành. Execution key được giữ trong yêu cầu post;
backend tra operation theo HTTP key, không có route tra trực tiếp execution key.

Sau ACK, màn hình đọc chi tiết phiếu và đối chiếu **Đã ghi / Còn** theo từng SKU/UOM cơ sở.
Không cộng lượng khác đơn vị. Đây là đối chiếu tiến độ phiếu từ API, không phải báo cáo
đối soát ledger/balance toàn hệ thống; SQL đối soát được chạy trong kiểm thử tích hợp.

## Phạm vi phục hồi và luồng nền

Yêu cầu chờ chỉ giữ trong RAM của process, phân theo user/kho và gắn với một API client/server.
Đổi kho, đăng xuất/đăng nhập lại trong cùng process không làm actor khác gửi được lệnh đó.
Trở lại đúng user/kho phải tra lại; response thuộc sequence/session generation cũ không cập nhật UI.
Đóng/crash ứng dụng chưa có recovery OPENING bền: B19 sở hữu journal/nháp SQLite và migration 003.
Không coi B06 là hoàn tất T02 hoặc T20 tổng; B09 mở ký gửi, B16 nối import.

Tk/widget/biến được cập nhật và hủy trên main thread. HTTP, đọc danh mục, tra/replay chạy
ở một worker; callback chỉ đưa kết quả vào Queue. Shell poll trên main thread và gọi finish
sau khi đóng để thu dọn worker. Form có thanh cuộn để tới phần thao tác/ACK ở cửa sổ nhỏ.

Kiểm thử: `tests/foundation/test_opening_presenter.py`,
`tests/foundation/test_opening_desktop.py` và regression backend `test_openings.py`.
Kết quả thực chạy, commit và giới hạn Windows nằm trong [bàn giao B06](PHAN_CONG/BAN_GIAO/B06.md).
