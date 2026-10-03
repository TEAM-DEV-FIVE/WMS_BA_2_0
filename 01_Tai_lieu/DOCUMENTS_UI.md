# PO/SO, phân công và hộp thư duyệt — B15

Màn hình desktop gọi API hiện có để ghi; PostgreSQL vẫn là nguồn chính thức.
PO/SO, gửi duyệt và quyết định duyệt không ghi sổ tồn kho.

## Thao tác

- Trong **PO/SO và duyệt**, chọn loại phiếu, kho và trạng thái. Tìm theo một phần
  số phiếu hoặc tên đối tác, không phân biệt hoa/thường; `%` và `_` là ký tự thường.
  Danh sách dùng cursor máy chủ, 25 phiếu/trang; có Trang trước/Trang sau.
- Chọn phiếu để xem lượng đã nhận (PO)/đã xuất (SO), còn mở và đã đóng theo đơn vị
  cơ sở. `COMPLETED` có lượng đóng được ghi **Đã đóng phần còn lại (chưa thực hiện đủ)**.
  Trong danh sách, trạng thái này là **Kết thúc · xem chi tiết**. Hủy không trở thành
  đã nhận/xuất; không suy `POSTED` từ trạng thái đơn hàng.
- Tab **Phân công**: người có `document.assign` tại kho tìm tên/tài khoản, thêm/bỏ
  người, nhập lý do rồi **Lưu phân công**. Người chọn được giữ qua các trang tìm.
  Danh sách hiện tại có thể hiển thị mã người dùng nếu chưa có tên từ kết quả tìm;
  tài khoản mất quyền vẫn có thể được bỏ khỏi phân công. Máy chủ kiểm tra lại quyền
  và version khi lưu; danh sách gợi ý không phải sự bảo đảm người đó vẫn đủ quyền.
- Tab **Lịch sử duyệt** hiển thị mọi lần gửi và các bước duyệt. Tab **So sánh phiên bản**
  tải snapshot rồi chọn hai bản để xem trường thay đổi. Chọn một dòng để đọc giá trị
  đầy đủ. Chỉ có các bản lưu lúc gửi duyệt và nội dung hiện tại, không có lịch sử mọi
  lần lưu nháp. Giá và thuộc tính tùy biến không thuộc nội dung được hiển thị.
  Lần gửi từ dữ liệu cũ chưa có snapshot được báo không có bản lưu (`content: null`),
  không thay bằng nội dung hiện tại và không đưa vào phép so sánh.
- **Hộp thư duyệt PO/SO/nhận** liệt kê phiếu `SUBMITTED` theo loại và kho. Chọn phiếu
  để xem dòng hàng, nguồn nhận, kế hoạch lô/serial/vị trí, vai trò từng bước và lý do.
  Nút quyết định dựa vào `can_decide` từ máy chủ và grant duyệt tại kho. Thông báo
  phân biệt thiếu grant ở kho, người lập/gửi/đã duyệt bước trước (SOD), và sai vai trò.
- **Mở form nghiệp vụ** từ hộp thư mở PO/SO hoặc phiếu nhận tương ứng; không ghi.
  **Mở nhận hàng** từ PO chuyển tới form nhận đang có, giữ nguyên nháp/yêu cầu phục hồi
  tại form này; người dùng chọn PO nguồn sau khi tải danh sách. Form receipt/opening
  tiếp tục thuộc agent domain. Chưa thêm nút ghi sổ ISSUE.

Các vùng chi tiết có thanh cuộn ở cửa sổ nhỏ; Tab đưa trường được focus vào vùng nhìn.
Enter tìm chứng từ/người, Enter hoặc nhấp đúp thêm người; Delete bỏ người đã chọn.
Các thao tác ghi đều cần lý do. Quyền UI chỉ giúp thao tác, không thay kiểm tra server.

## Version, phiên và kết quả chưa xác định

`STALE_VERSION`, `STALE_APPROVAL`, trạng thái không hợp lệ hoặc quyền đã mất khóa các
thao tác dùng version cũ. Nội dung nhập được giữ khi stale; bấm **Đọc lại phiếu** để
đối chiếu và quyết định lại. Không tự gửi lại ghi hoặc tự dùng version mới.

Timeout/mất mạng/ACK không đọc được giữ chính xác method, endpoint, payload và
idempotency key trong presenter, phân vùng theo user. `UNKNOWN` vẫn tồn tại khi
đổi tab/kho hoặc đăng nhập lại cùng user trong cùng tiến trình; người khác không được
gửi lại lệnh đó. Chỉ nút gửi lại chủ động mới gửi cùng yêu cầu. Đổi tab không hủy presenter.

PO/SO/approval chưa có journal bền sau khi thoát ứng dụng; B19 sở hữu phần đó.
Không ghi token/password vào bộ nhớ phục hồi. Receipt.post vẫn dùng journal riêng
của receipt hiện có. HTTP chạy trên worker; queue được drain trên Tk main thread.
Response bị loại nếu sequence hoặc session generation đã thay đổi.

## Contract bổ sung chỉ đọc

| Route | Quyền và dữ liệu |
| --- | --- |
| `GET /purchase-orders`, `GET /sales-orders` thêm `q` tối đa 100 ký tự | Giữ scope kho, ownership/assignment, status, cursor UUID và limit hiện có; tìm số phiếu/tên đối tác |
| `GET /documents/{id}/assignment-candidates?q=&after=&limit=25` | Đọc được chứng từ và `document.assign` tại kho; tài khoản hoạt động có grant `document.read` hiện hành đúng kho/ALL_WAREHOUSES; tối đa 100/trang; trả id/username/display_name |
| `GET /documents/{id}/approval-snapshots` | Đọc được chứng từ; với receipt kiểm tra cả quyền đọc PO nguồn; trả current_version/current và các snapshot đã lưu, status/version/time |

Projection snapshot dùng allowlist: loại/kho/đối tác/ngày, dòng/sản phẩm/UOM/số lượng/
hệ số/chủ sở hữu/hợp đồng/nguồn/lượng đóng, danh sách phân công và kế hoạch receipt
(vị trí/lô/serial/ngày sản xuất/hạn dùng). Không trả giá, toàn bộ attributes, mật khẩu
hay thông tin IAM khác. UUID là định danh, không tự suy tên lịch sử từ danh mục hiện tại.
Snapshot endpoint chỉ hỗ trợ PO/SO/RECEIPT; không mở rộng nghiệp vụ OPENING.

Lệnh ghi giữ nguyên `POST /documents/{id}/assignments`, lifecycle và
`POST /approval-requests/{id}/decide` với reason/expected_version/Idempotency-Key.
Không thêm migration, event, consumer hay dependency Python.
