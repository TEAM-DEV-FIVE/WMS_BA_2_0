# Giao diện import B16

Chức năng **Import tệp / tồn đầu kỳ** dùng API B01, owner/hợp đồng B09 và mở chứng từ
trong form B06/B15. Desktop không truy cập PostgreSQL hoặc private storage máy chủ.

## Nhập và theo dõi một tệp

1. Đăng nhập, chọn loại import. Chọn kho cho vị trí, tồn đầu kỳ hoặc PO/SO; danh mục
   toàn hệ thống không gửi warehouse_id. **Tải quyền / mẫu** lấy quyền hiện hành và
   cấu trúc mẫu/giới hạn từ máy chủ. Không có quyền thì nút nhập bị khóa; server vẫn
   kiểm tra lại quyền ở mỗi request và khi replay.
2. **Lưu mẫu CSV** xuất header UTF-8 BOM đúng server. CSV hoặc XLSX phải theo mẫu;
   giữ mã/barcode/serial là text. Chọn tệp để kiểm kích thước, đếm dòng và tính SHA-256
   trong worker. Đây là kiểm tra sơ bộ, chưa phải dry-run nghiệp vụ.
3. **Upload tệp**, nhập lý do. Tồn đầu kỳ cần tham chiếu biên bản kiểm đếm đã ký.
   **Tạo job / dry-run** trả mã job. Giữ mã này để tiếp tục tra cứu; màn hình tự đọc
   trạng thái mỗi hai giây trong lúc QUEUED/VALIDATING, không tự gửi lệnh ghi.
4. Xem tab **Dòng dữ liệu / lỗi**: 50 dòng/trang, Trang trước/Trang sau, thanh cuộn;
   chọn dòng để đọc payload, lỗi và gợi ý đầy đủ. Chủ hàng/hợp đồng có cột riêng.
   Lỗi cấp tệp/worker hiển thị trong vùng chi tiết cả khi không có staging row.
   **Tải CSV lỗi** lấy bản đầy đủ có escape công thức từ server.
5. Chỉ khi VALIDATED, còn token và không có lệnh UNKNOWN mới có thể đánh dấu đã
   kiểm tra dữ liệu/hash/thời hạn rồi **Xác nhận commit**. Máy chủ kiểm tra lại
   hash/token/version/mapping/master/owner và commit toàn tệp nguyên tử.
6. COMMITTED của import là đã nhập danh mục hoặc tạo chứng từ **DRAFT**. Với tồn
   đầu kỳ/PO/SO, chọn dòng có target rồi **Mở chứng từ đã tạo**. Form nghiệp vụ đọc
   lại quyền và dữ liệu server, tiếp tục submit/approve/post hiện hành; import không
   tự duyệt hay ghi tồn. Form có dữ liệu sẽ hỏi trước khi thay; form đang pending
   hoặc UNKNOWN không bị ghi đè.

Máy chủ/executor cần hoạt động: consumer
`apps.server.application.import_jobs:consumer_factory` và process
`python -m apps.server.import_worker`. QUEUED lâu nghĩa là chưa được xử lý; desktop
không tự chạy worker hoặc tự xác nhận thành công.

## Giới hạn, owner và cutover

- Hạn mức upload lấy từ server, mặc định 5 MiB; desktop chặn quá giới hạn trước upload.
  Tối đa 500 dòng/tệp, 200 dòng/chứng từ; OPENING tối đa 200 dòng và một batch/kho.
  Không chia tệp để vượt quy tắc một lần opening/kho chưa có lịch sử tồn.
- Opening v2 yêu cầu `owner_code`; chủ ký gửi cần `consignment_code` đúng kho/ngày.
  COMPANY không có hợp đồng. Header opening v1 vẫn được B09 diễn giải COMPANY theo
  contract đã phát hành; desktop không suy chủ hàng từ ghi chú.
- PO/SO vẫn COMPANY; chỉ remaining_quantity được nhập và không làm phát sinh tồn.
  Ghi chú nguồn được xem từ staging vì DTO dòng đơn chưa chứa trường này.
- Chỉ chủ upload/request còn đủ quyền đọc file/job. Biết mã job/file không cấp quyền.
  Thu hồi quyền trước tải/commit sẽ xóa dữ liệu đang hiển thị và chặn thao tác tiếp.
- Sửa tệp local sau khi chọn/dry-run phải chọn lại và kiểm tra lại. Trước upload/commit
  mới, worker so byte với bản đã chọn; không âm thầm dùng tệp vừa thay để gửi lệnh cũ.
  Tệp server là object riêng bất biến và được server rehash khi commit.

## Mất LAN, stale và hủy

Timeout/response sai không được báo thành công. Presenter giữ nguyên key, body và
byte upload theo user/loại/kho trong RAM. Đổi màn/kho hoặc đăng xuất không xóa lệnh
UNKNOWN; đăng nhập lại đúng user/chọn đúng loại/kho để tra. Worker không đưa response
phiên/kho cũ lên màn hình và không lưu download cũ sau khi scope đã đổi.

- **Tra yêu cầu chưa rõ**: khi có job ID, đọc trạng thái server. Commit có result đúng
  ID/version/hash/token thì nhận ACK đã lưu. Khi chưa có ID upload/create, API hiện
  không có lookup theo key; kiểm phiên/file rồi cho **Gửi lại đúng yêu cầu** lấy ACK.
- Retry chỉ do người dùng chọn sau tra cứu; không đổi key/body/byte theo nội dung
  form đã sửa. NOT_FOUND không chứng minh request cũ chưa chạy. Không tạo file/job mới
  để xử lý timeout. Tệp trùng nội dung được server nối về job cũ theo contract B01.
- **Đọc / tiếp tục** nhận job UUID, kiểm loại/kho/user qua API, tải metadata và staging.
  Không có danh sách toàn bộ job; cần giữ mã job. Options/lý do khác cho cùng nội dung
  có thể trả IMPORT_EXISTS: tiếp tục job cũ, không tạo một bản nghiệp vụ mới.
- Stale/token hết hạn cần đọc lại và chạy **Kiểm tra lại** trước xác nhận mới. Không
  tự đổi expected_version và gửi lại. **Hủy job** dùng version hiện hành; nếu commit
  thắng race, phải đọc lại kết quả, không thông báo đã đảo hay hủy dữ liệu đã commit.

**Giới hạn B19:** đóng process làm mất snapshot byte/lệnh UNKNOWN trong RAM. B16 chưa
có journal bền hay tự phục hồi sau restart. Nếu còn mã job, có thể tra trạng thái
server; không tạo request mới khi chưa xác minh. B19 nối persist-before-send và
checkpoint/recovery của mọi form, là chủ sở hữu SQLite revision 003.

## Contract tích hợp

- Thêm `GET /api/v1/import-templates` có xác thực, trả ImportCapabilities gồm
  mapping_version, max_file_bytes và các template (kind, columns, warehouse_required,
  permissions, max_rows). Dữ liệu lấy từ cùng TEMPLATES của parser B01, không có bản
  sao template cố định trong desktop hoặc phụ thuộc thư mục tài liệu khi cài wheel.
- Upload byte thô dùng `X-File-Name-Encoding: percent-utf8` kèm X-File-Name được
  percent-encode UTF-8. Server decode rồi kiểm safe_name trước xử lý. Client cũ không
  gửi header encoding vẫn giữ nguyên cách đọc tên cũ.
- GET file/download, job/rows/errors và POST create/validate/cancel/commit vẫn dùng
  contract B01. IdentityClient thêm đường đi byte sử dụng cùng TLS/session lock;
  không tự refresh/retry upload và không ghi lỗi JSON thành tệp download.
- `ImportCommand` immutable: schema_version=1, operation/path/body_json/key/user_id,
  kind/warehouse/file_id/job_id/source. Mọi command hiện là POST; body_json là bản
  chụp bất biến, SourceFile giữ path/name/hash/row_count/byte (không repr dữ liệu).
  B19 lấy server/device từ IdentityClient, persist trước `ImportApi.execute`, rồi
  nối các điểm command/lookup/retry/reset/drain. Upload cần snapshot byte riêng có
  hash khớp; chỉ đường dẫn tới file có thể bị sửa không đủ để replay an toàn.
- Không ghi access/refresh token, mật khẩu/TOTP vào command, file hoặc log. Chưa thêm
  migration, event, consumer mới hoặc dependency Python cho desktop/server.

Kiểm thử và phạm vi môi trường thực tại [báo cáo B16](PHAN_CONG/BAN_GIAO/B16.md).
