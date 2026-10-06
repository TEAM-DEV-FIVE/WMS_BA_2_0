# Nháp và phục hồi lệnh — B19

Desktop lưu yêu cầu nghiệp vụ trước khi gửi HTTP. PostgreSQL vẫn là dữ liệu chính thức;
nháp cục bộ không phải phiếu đã lưu/duyệt/ghi sổ. Không tự gửi khi khởi động, đăng nhập,
đổi kho hoặc nối lại LAN. Phục hồi chỉ chạy khi người dùng chọn tra ACK/gửi lại.

## Thao tác trên desktop

1. Để giữ nội dung trên máy, bật **Chỉ lưu nháp nghiệp vụ (trừ IAM/tệp)** ở thanh chức năng,
   nhập form rồi bấm nút lưu/thực hiện của nghiệp vụ. Form vẫn kiểm tra dữ liệu đầu vào.
   Thông báo **Đã lưu nháp cục bộ, chưa gửi máy chủ** xác nhận checkpoint. Ô đang gõ mà
   chưa bấm lưu không được tự lưu. IAM và upload tệp luôn cần online, không nhận chế độ nháp này.
   Presenter lưu nháp trước phần preflight HTTP: đang có phiên/form mà mất LAN vẫn lưu
   được dữ liệu đã nhập. Sau restart cần đăng nhập online để mở đúng tài khoản; không có
   đăng nhập offline hoặc ghi sổ offline. Chế độ nháp không gửi lại một lệnh UNKNOWN cũ.
2. Mở **Nháp / phục hồi lệnh**, chọn kho hoặc tất cả kho, tải nhật ký. Danh sách chỉ có
   metadata thao tác, key, thời gian và trạng thái; không tự hiển thị giá/nội dung đã lưu.
   `GLOBAL` là danh mục hoặc thao tác chưa suy được kho từ payload/tài nguyên đã tải,
   không phải quyền toàn hệ thống. Server luôn kiểm tra phạm vi thật, kể cả hai kho chuyển hàng.
3. **Xem nội dung** tra quyền hiện tại qua route gốc trước khi đưa payload lên màn hình.
   Thiếu LAN hoặc bị thu hồi quyền thì không hiện nội dung lưu. Nháp chưa gửi có thể sửa
   từng giá trị và **Lưu sửa nháp**; số lượng Decimal vẫn là chuỗi, không qua float.
   Reference ID, version, execution key giữ nguyên. Đổi các trường đó cần tải lại form
   nghiệp vụ, bỏ nháp chưa gửi và lập nháp đã được người vận hành kiểm tra lại.
   Nhập lại cùng thao tác rồi lưu nháp cập nhật nháp chưa gửi, không nhân bản nháp/key.
4. **Tra ACK** chỉ đọc kết quả của key/payload cũ. **Gửi nháp / gửi lại cùng key** có xác nhận
   rõ ràng, tra ACK trước rồi mới gửi khi server trả `OPERATION_UNCONFIRMED`. Không thay
   version, execution key, payload hay sinh key mới cho lệnh đang phục hồi.
5. `COMMITTED`: đã có ACK khớp; tải lại màn nghiệp vụ để xem trạng thái hiện tại. ACK cũ
   có thể mô tả phiên bản cũ hơn phiếu hiện tại. `CONFLICT`: server đã từ chối trong handler,
   transaction rollback; tải lại và đối chiếu thủ công. Không tự đổi version để gửi lại.
   `UNKNOWN`: chưa biết kết quả, kể cả timeout, lỗi mạng, mất quyền hoặc không tìm thấy nguồn.
   Không xóa file, không tạo lệnh mới để né lệnh UNKNOWN cùng thao tác.
6. **Bỏ nháp chưa gửi** chỉ xóa DRAFT. READY/SENDING/UNKNOWN không được xóa bằng thao tác này.
   Đăng xuất/đổi người dùng xóa nội dung UI và tách partition, không xóa lệnh đang chờ.

Màn **Phục hồi nhận hàng** tiếp tục đọc nháp/lệnh receipt.post cũ ở `receipts/` để tương
thích nâng cấp. Lệnh nhận hàng mới trong shell B19 đi qua journal chung `commands/`.
Nếu có lệnh nhận hàng cũ chưa rõ kết quả, hoàn tất ở màn cũ trước. Không chuyển lệnh bằng
cách tạo key mới; thư mục cũ giữ nguyên dữ liệu và hash.

## Ma trận mọi write endpoint

[Ma trận đầy đủ](RECOVERY_ENDPOINTS.md) liệt kê 120 method/path của B01–B20;
nguồn máy đọc được là `packages/contracts/recovery_routes.py`. Test đối chiếu chính xác
với OpenAPI runtime, route mới chưa phân loại bị chặn. OpenAPI có `x-wms-recovery` cho từng write.

- **COMMAND — 99**: draft và command bền, gồm danh mục/owner/hợp đồng/UOM/barcode/giá,
  bảo hành, PO/SO/assignment/approval, receipt/opening/ký gửi, issue/reservation,
  pick/package, QC/move, returns, transfer/transit, count/period, reversal, custom fields,
  import job/validate/commit/cancel, report snapshot/export và print DB commands.
- **ONLINE — 19**: 18 IAM/auth/grant/lifecycle routes và upload tệp. Dùng UI hiện hành,
  online/re-auth, không ghi password, reset/challenge/access/refresh token, TOTP hay
  recovery code xuống SQLite. Upload giữ cơ chế exact key/file hash của B16 trong RAM;
  sau restart chọn lại tệp và đối chiếu job/file trên server, không replay file I/O từ journal.
- **READ_ONLY — 2**: scan HID và preview custom fields dùng POST nhưng không ghi nghiệp vụ;
  gọi online theo lựa chọn hiện tại, không đưa vào hàng lệnh.

Import `commit_token` của dry-run là chứng cứ nghiệp vụ gắn job/file/version, không phải credential
đăng nhập. Được giữ nguyên trong command import commit; hết hạn thì server từ chối và
người dùng phải chạy lại dry-run/đối chiếu thủ công. Không lưu byte tệp, đường dẫn download,
PDF, preview cache hoặc thông tin phiên đăng nhập trong journal.

## Giao thức tra cứu và ACK v1

Không thêm route PostgreSQL hoặc schema DB. Dùng route/method/body/key gốc và header tùy chọn:

- `X-WMS-Recovery: lookup-v1`: schema validation và live authorization của domain chạy
  như lệnh gốc. Kernel khóa actor/key, so hash, trả ACK nếu có; nếu chưa có thì trả
  `OPERATION_UNCONFIRMED` (409) trước khi gọi handler. Không dùng GET NOT_FOUND làm bằng
  chứng lệnh chưa chạy. Thu hồi quyền/MFA/nguồn không còn hợp lệ có thể chặn cả lookup.
- `X-WMS-Recovery: send-v1`: handler gốc và các khóa/bất biến không đổi; checkpoint SQLite
  SENDING đã commit trước request. Ledger/balance/audit/outbox/idempotency ACK vẫn nguyên tử.
- `X-WMS-ACK = SHA256(canonical([1, request_hash, result_body]))`, trong đó request hash
  là SHA256 canonical `[1, method, path kể cả query, body, UUID key]`. Canonical JSON sort
  keys, UTF-8, separators `,`/`:`, không NaN. Header chỉ được phát khi kernel xác nhận đúng
  key và đã commit hoặc trả record idempotency cũ. Client so cả body nhận được, không chỉ
  HTTP 2xx. Đây là ràng buộc định dạng/phát hiện sai phản hồi, không thay chữ ký hay TLS.
- Khi kernel chưa có record và handler trả DomainError/rollback, server trả
  `X-WMS-Rejected` bằng request hash. Client có bằng chứng này mới đánh dấu CONFLICT;
  các lỗi không có bằng chứng giữ UNKNOWN. Không lưu lỗi/input server tự do vào journal.

ContextVar chứa object riêng cho từng request, đi qua sync worker của FastAPI. Chế độ
lookup không được dùng với IAM/upload/scan/preview hoặc route lạ. Giao thức giữ nguyên
khóa, quyền và DTO của từng domain, không dựng lại một bảng quyền phục hồi song song.
Client cũ không có header vẫn hoạt động; client B19 gặp server cũ thiếu proof sẽ giữ UNKNOWN.
Phải triển khai server hỗ trợ B19 trước hoặc cùng lúc nâng cấp client.

## SQLite003, partition và trạng thái

`003_commands.sql` thêm `recovery_command`; giữ nguyên byte SQLite001–002 và PostgreSQL001–023.
Không sửa/xóa legacy local_draft, scan_event, pending_operation hoặc cache_metadata.
Envelope schema v1 chứa server URL, user UUID, device UUID, warehouse/scope, method/path,
key và body nguyên bản. SHA256 bao phủ toàn envelope; response có hash riêng. Unknown
schema/hash sai/partition sai bị chặn, giữ file để điều tra, không tự sửa hoặc gửi dữ liệu đó.

SQLite riêng theo server/device/user trong `WMS_LOCAL_DATA_DIR/commands/`; kho nằm trong
envelope và chỉ mục để lọc, hash kiểm tra không cho đổi partition của record. Một storage
worker sở hữu connection; OS lock chặn hai process cùng partition. HTTP chạy worker của
presenter/recovery, widgets và hủy Tcl ở main thread. Identity lock + session_generation
chặn một lệnh của phiên cũ chạy bằng credential của phiên mới; queue/idle UI bỏ kết quả cũ.

Luồng: DRAFT → READY → SENDING → COMMITTED hoặc UNKNOWN/CONFLICT. Khi mở lại store,
SENDING → UNKNOWN trong transaction cục bộ. UNKNOWN chỉ được tra/gửi đúng lệnh; DRAFT có
thể sửa trước gửi nhưng không đổi tham chiếu/version/key. Nhấn gửi trên form khi còn lệnh
chưa rõ cùng endpoint bị chặn; cần giải quyết lệnh đó trước. Mở store không gọi API ghi.

Trước upgrade v1/v2: quick_check, foreign_key_check, tạo SQLite backup nhất quán trong
cùng thư mục với tên `*.vN.<uuid>.backup.sqlite3`, integrity_check và fsync. Upgrade SQL
trong transaction; lỗi giữ nguyên revision và dữ liệu cũ. File riêng quyền 0600 trên Linux,
thư mục 0700; Windows dùng thư mục người dùng và cần B23 kiểm chứng ACL/installer thực tế.
Phiên bản SQLite tương lai bị từ chối thay vì tạo file rỗng. Không tự restore backup lên
dữ liệu đang dùng: giữ file và dừng client trước quy trình hỗ trợ/đối chiếu.

Không tự purge hoặc TTL lệnh. `CommandStore.cleanup(before)` chỉ dọn COMMITTED/CONFLICT
cũ khi được chủ động gọi; luôn giữ DRAFT/READY/SENDING/UNKNOWN và mọi nháp/receipt legacy.
Backup nâng cấp không tự xóa. Giữ cả device.sqlite3, receipts/ và commands/ khi nâng cấp.
Không đặt SQLite trên SMB/network share. Máy khác/device khác không tự replay partition cũ.

## In và các tác động ngoài DB

Create/retry/reprint/cancel/spool claim/result được lưu như command DB. Phục hồi generic
chỉ gọi HTTP, không import/call spool adapter, renderer, download hay file uploader.
Crash sau khi claim lượt in vẫn giữ UNKNOWN ở server; tra ACK không chứng minh máy đã
in giấy và không gọi lại OS I/O. Muốn in lại, người vận hành kiểm tra thiết bị rồi chọn
workflow In lại của B18. Không gọi renderer/executor B20 trong transaction recovery.

## Kiểm chứng và giới hạn

Test mới ở `tests/foundation/test_recovery_all.py`: matrix coverage, secret rejection,
v2→v3 backup/legacy data, OS lock, hash/partition/cleanup, immutable sent requests, đọc/sửa
nháp, live revocation, session/user change, mất proof/ACK, các điểm process death và restart
process khác. Có PostgreSQL/API thật cho danh mục, receipt ledger/execution key và print
claim UNKNOWN, cùng Tk/Xvfb cho nhập nháp → sửa → gửi → logout. Fake lỗi mạng/crash chỉ
được tiêm quanh API thật, không thay dependency production bằng stub.

Kết quả/lệnh tái lập tại [bàn giao B19](PHAN_CONG/BAN_GIAO/B19.md). Windows installer/ACL,
mất điện vật lý, LAN triển khai, máy in/scanner thật, 15 CCU, DR và UAT chưa được chứng minh
bởi test local. T02/T08/T11/T23 có bằng chứng thành phần; T01–T28 vẫn PLANNED.
