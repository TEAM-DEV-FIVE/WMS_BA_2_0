# Import runtime B01

Migration phát triển `011_b01_import_files.sql`, nền ứng dụng `06041b7`, mapping `b01.v1`.
Mẫu và thứ tự cột lấy từ [manifest](../06_Nhap_lieu/imports/template_manifest.json); runtime có bản đóng gói
trong `import_templates.py`, test kiểm tra hai bản trùng nhau. Không cần thư mục tài liệu khi cài wheel.

## Phạm vi nghiệp vụ

CSV UTF-8 (có hoặc không BOM), XLSX chuẩn, mẫu 01–12 và 14. Mẫu 13_grants không có endpoint import;
cấp quyền qua IAM. Danh mục tạo mới, không upsert/ghi đè. Cây cha đứng trước con. Quy đổi active đã có
cùng revision/factor được nhận diện lại; thay đổi cần revision kế tiếp, qua MasterDataService.
Lot/serial chỉ tạo danh tính theo dõi, kiểm tra tracking/ngày theo ReceiptService; không tạo tồn, vị trí
serial hoặc bảo hành. Giá tham chiếu cần `price.write`; không suy giá vốn.

Mỗi tệp/job chứa một mẫu. XLSX nhiều sheet chỉ được có dữ liệu trong sheet của mẫu chọn; sheet khác
chỉ có header/ô trống. Ô mã, barcode, serial, tax_code phải là text để giữ số 0 đầu; ô số đã mất số 0
không được đoán lại. Ngày nhận ISO hoặc Excel date serial, hỗ trợ epoch 1900/1904 và từ chối ngày giả
1900-02-29. Không thực thi công thức, macro, DTD/entity, link ngoài, embedded object hoặc path trong ZIP.
Giới hạn giải nén 20 MiB/tệp, 8 MiB/member, 128 members, ô 4.000 ký tự, tối đa 40 cột.

Toàn tệp commit nguyên tử, tối đa 500 dòng; từng chứng từ tối đa 200 dòng. OPENING chỉ một batch,
một kho, tối đa 200 dòng. Không chia nhiều phiếu để lách một lần ghi sổ/kho. Dry-run báo lỗi vượt giới hạn.
OPENING cần biên bản kiểm đếm đã ký, kỳ OPEN, vị trí đúng kho, tracking hợp lệ. Lô phải có danh mục
ngày trước khi import tồn; lô hết hạn chỉ ở cách ly. Serial có tồn/vị trí bị chặn. Mỗi lần commit đều
kiểm tra lại master, tracking và quy tắc service hiện tại.

PO/SO nhóm theo `(kind, external_number)` trong kho chọn, ngày/đối tác thống nhất, line_no dương và
không trùng. Chỉ nạp remaining_quantity, tạo DRAFT; không tự duyệt, nhận hàng, giữ chỗ hoặc ghi stock.
OPENING cũng tạo DRAFT qua OpeningService, sau đó dùng quy trình submit/approval/post hiện hành.
Import chỉ hỗ trợ COMPANY theo các mẫu hiện có. Không suy owner ký gửi từ ghi chú.

`import_row` giữ payload gốc đã chuẩn hóa, row_no và target_id; `import_document_source` giữ khóa nguồn
và ID chứng từ lâu dài. Số chứng từ thực tế do server cấp. `12_open_orders.note` và số dòng nguồn vẫn
ở staging liên kết chứng từ, chưa thêm vào DTO dòng đơn hàng. Giao diện B16 cần cho xem ghi chú staging.

## API cho B16

Tất cả route dưới `/api/v1`, Bearer token hiện hành, `Cache-Control: no-store`. Tất cả POST cần UUID
`Idempotency-Key`; gửi lại đúng body/key khi mất ACK. Mỗi lệnh khác dùng key khác.

| Route | Payload / kết quả |
|---|---|
| `POST /files?kind=01_uom` | Body byte thô, `Content-Type: application/octet-stream`, `X-File-Name: data.csv`; trả FileView 201 |
| `GET /files/{id}` | Metadata riêng tư, tên gốc/hash/size/kind/kho/ready, không storage_key/path/URL |
| `GET /files/{id}/download` | Attachment octet-stream, nosniff, tên RFC 5987; kiểm quyền trước và sau đọc file |
| `POST /imports` | `{file_id,reason,signed_count_reference?}`; 201 job mới hoặc 200 job cùng nội dung |
| `GET /imports/{id}` | status/version/generation/hash/mapping, total_rows/processed_rows, errors, token/expiry/result |
| `GET /imports/{id}/rows?after=0&limit=50` | Cursor row_no, tối đa 200, payload/errors/target_id/status |
| `GET /imports/{id}/errors` | CSV BOM: row_no,column,code,message,suggested_fix; escape công thức ở mọi trường |
| `POST /imports/{id}/validate` | `{expected_version,reason}`; tăng generation, xóa token/staging cũ, enqueue lại |
| `POST /imports/{id}/cancel` | `{expected_version,reason}`; hủy trước commit, vô hiệu token; job đã commit từ chối |
| `POST /imports/{id}/commit` | `{expected_version,reason,commit_token,file_hash}`; ImportAck và targets row→UUID |

Location/OPENING/open_orders cần query `warehouse_id` khi upload; các loại khác không nhận warehouse_id.
File/job chỉ chủ upload/request đọc được và phải còn quyền tương ứng. Scoped file cần document.read tại
kho; OPENING cần opening.draft; PO/SO kiểm permission từng loại đã staged, kể cả replay. Các template
còn lại dùng master.write, warehouse.configure, partner.write hoặc price.write. Không dùng mã file UUID
làm capability công khai. Thu hồi user/auth_version, role, grant, hoặc kho ngừng dùng đều chặn phù hợp.

Trạng thái: QUEUED → VALIDATING → VALIDATED / INVALID / FAILED; CANCELLED trước commit,
COMMITTED sau commit. Retry I/O chuyển về QUEUED. Progress theo pha: total_rows cập nhật sau parse,
processed_rows bằng total khi xong dry-run; không tuyên bố đã commit một phần. Có thể cancel khi worker
đọc file; khi transaction commit/dry-run đã khóa job, cancel chờ khóa và kiểm lại version. Lệnh nào
khóa/commit trước quyết định kết quả. Không cố hủy transaction đã ghi sổ.

Token sống 1 giờ, gắn file hash, mapping/kind, options, generation/auth_version, staging và snapshot
tham chiếu. Commit rehash file bên ngoài transaction DB, kiểm token/version và gọi lại handler nghiệp vụ
trong transaction. Stale trả 409; cần đọc job và validate lại, không tự đổi expected_version rồi commit.
Các lỗi chính: FILE_LIMIT 413; INVALID_FILENAME/FILE_QUOTA/FILE_HASH_MISMATCH/STALE_IMPORT/STALE_DATA/
IMPORT_INVALID 409; FORBIDDEN 403; tài nguyên không thuộc user/kho 404. Lỗi dữ liệu dry-run nằm trong
errors, không phải exception 500. CSV error không lặp raw giá trị nhạy cảm từ parser/SQL exception.

## Atomicity và khóa

CommandBus ngoài cùng sở hữu auth/retry/idempotency/commit. `TransactionIdentity` và
`TransactionCommands` là adapter transaction cho service con: cùng connection/principal, vẫn gọi
authorize và handler thật, không mở UoW commit độc lập. Dry-run chạy những handler đó trong savepoint
bắt buộc rollback; audit/outbox/source-map/tồn/danh mục thử nghiệm không tồn tại sau dry-run.
Sequence cấp số có thể có khoảng trống do dry-run, UUID preview không phải UUID commit.

Commit ghi business targets, import_row, source-map, audit, outbox, job result và idempotency ACK cùng
transaction. CATALOG_LOCK serialize catalog; handler chứng từ vẫn giữ các khóa/rules nghiệp vụ hiện có.
Toàn bộ tệp rollback khi một dòng/nhóm lỗi. Snapshot tham chiếu đầy đủ được hash và so lại; lần commit
chạy lại business handlers để bắt cả dữ liệu mới xuất hiện như serial hay source document trùng.
Không sửa ledger/balance trực tiếp từ importer.

Dedup upload: actor + upload key + request hash. Reserve quota/metadata trước I/O; PUT bất biến theo
storage_key ngẫu nhiên, fsync file và directory, publish bằng hard link atomic, chmod file 0600/dir mới 0700.
Crash sau reserve/put trước ACK gửi lại cùng key/nội dung để hoàn tất. Reservation chưa hoàn tất vẫn tính
quota, không tự xóa file/metadata. Dedup job: actor + kind + warehouse + SHA-256 (kể cả kho NULL); options
khác trên cùng nội dung bị báo IMPORT_EXISTS. Cancel không tạo lối vòng dedup: dùng validate lại cùng job.
Dedup chứng từ bền: kho + PO/SO/OPENING + source_key; cả actor/tệp/key khác không tạo trùng nguồn.
OPENING batch UUID5 từ kho + batch_code, tiếp tục chịu ràng buộc một lần post/kho của module opening.

## Worker và vận hành cho B20

Consumer factory: `apps.server.application.import_jobs:consumer_factory`.
Subscription `import.enqueue.v1` cho `import.validation.requested.v1`, payload duy nhất
`{"job_id":"<uuid>","generation":1}`, aggregate_id bằng job_id. Payload/version/generation không hợp lệ
thất bại. Handler chỉ INSERT task unique(job_id,generation), cùng transaction receipt+ACK của outbox;
generation cũ/job đã cancel hoặc commit được xác nhận obsolete. Không file I/O trong consumer.
B20 ghép subscription này vào registry thống nhất; không thêm no-op cho các event khác để ACK mù.

Chạy từ gốc checkout hoặc wheel đã cài, cấu hình DB như worker hiện hành:

```bash
rtk proxy python -m apps.server.worker --consumer-factory apps.server.application.import_jobs:consumer_factory --once
rtk proxy python -m apps.server.import_worker --once
```

Bỏ `--once` để chạy dưới supervisor. Executor đọc file ngoài transaction, lease token UUID/fencing và
FOR UPDATE SKIP LOCKED để nhiều process xử lý không trùng. Claim, staging+token+ACK task và retry là
các transaction riêng có checkpoint. Crash sau claim được claim lại khi lease hết; worker cũ mất token
không ghi staging. Crash sau staging trước task ACK rollback staging; crash sau commit nhưng mất stdout
không chạy lại task DONE. Lượt cuối chết được chuyển FAILED/LEASE_EXHAUSTED khi worker kế tiếp quét.
SIGTERM/SIGINT dừng sau đơn vị công việc hiện hành; SIGKILL phục hồi bằng lease.

| Environment | Mặc định |
|---|---|
| WMS_IMPORT_STORAGE_ROOT | `.wms-import-files`, cần cùng private volume cho API/executor |
| WMS_IMPORT_MAX_FILE_BYTES | 5 MiB, cấu hình tối đa 20 MiB |
| WMS_IMPORT_MAX_USER_BYTES | 100 MiB, bao gồm upload pending |
| WMS_IMPORT_MAX_USER_FILES | 100, bao gồm upload pending |
| WMS_IMPORT_LEASE_SECONDS | 60, 5–3600 |
| WMS_IMPORT_MAX_ATTEMPTS | 5, 1–20 |

Retry 5/10/20/40… giây, tối đa 300. Thiếu file/storage tạm lỗi được retry; hash sai/quyền mất không retry
mù. Revalidate tạo generation mới sau khi xử lý nguyên nhân. Không lưu access/refresh token, password
hay TOTP trong job, stage, log. Worker dựng principal từ requested_by/auth_version và kiểm grants hiện tại.
Log chỉ mã trạng thái, không exception SQL/đường dẫn/content. `--once` exit 1 cho RETRY/FAILED/LOST_LEASE.

Backup/restore cần DB **và** private volume tương ứng; không phục vụ volume như thư mục static. Không
có garbage collector/retention tự động trong B01; B20 lập runbook xử lý quota/reservation bỏ dở, không
xóa file còn FK tham chiếu. Tên client không được dùng làm đường dẫn. Volume thuộc tài khoản dịch vụ;
không cấp quyền ghi cho client. Hash kiểm chứng corruption, không thay ACL của hệ điều hành.

## Migration và kiểm chứng

Migration cộng thêm import_file, import_task, import_document_source và 13 cột import_job. Tổng runtime
68 bảng / 474 cột / 137 FK. Legacy import_job có auth_version NULL, không được tự xác nhận bằng runtime
mới; dữ liệu staging cũ giữ nguyên, cần nạp lại nguồn thành job được kiểm tra. Unique content index có
predicate auth_version IS NOT NULL, không làm hỏng legacy duplicates. Migration 001–010 giữ nguyên.

[Báo cáo B01](PHAN_CONG/BAN_GIAO/B01.md) ghi lệnh/kết quả thực chạy. Test dùng PostgreSQL tạm, có API
thật, lỗi giữa batch, cùng key/hash, stale file/master/staging, serial đã nhận bằng ReceiptService,
scope/revoke, approval/post OPENING, crash enqueue/ACK/lease, CLI process và upgrade từ 010 có dữ liệu.
Windows, thiết bị kho, tải mục tiêu, backup/restore và nghiệm thu nghiệp vụ vẫn cần bằng chứng riêng.
