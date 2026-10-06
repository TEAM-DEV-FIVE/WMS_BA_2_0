# B20 — Vận hành outbox và I/O worker

B20 dùng consumer thật từ B01/B17/B18. Outbox chỉ enqueue DB; executor riêng đọc/ghi file,
render CSV/XLSX/PDF và kiểm tra lease/quyền. In vật lý vẫn ở desktop B18, không tự gửi lại
spooler từ server. Xem [hợp đồng transaction](OUTBOX_WORKER.md) và
[bàn giao B20](PHAN_CONG/BAN_GIAO/B20.md). Đây là khả năng phần mềm local, chưa là nghiệm thu
service trên máy vận hành, tải đại diện hay Q08.

## Khởi động

Chạy migration bằng runner riêng của đúng release. Revision phát triển B20 là
`027_b20_outbox_operations.sql`, không đưa trực tiếp lên DB vận hành. Điều phối chốt số
release kế tiếp và kiểm thử upgrade. Worker/API không tự migrate. Dùng cùng phiên bản wheel,
registry và `WMS_OUTBOX_*` trên API và mọi worker; không trộn retry budget.

Service nhận `WMS_DATABASE_URL` và cấu hình khóa mã hóa IAM qua tệp môi trường quyền hạn chế,
không qua command line. `WMS_IMPORT_STORAGE_ROOT`, `WMS_EXPORT_STORAGE_ROOT`,
`WMS_PRINT_STORAGE_ROOT` phải là ba thư mục riêng, không lồng nhau; cùng path với API trên
server. Worker dùng cấu hình/quota/lease riêng `WMS_IMPORT_*`, `WMS_EXPORT_*`, `WMS_PRINT_*`
đã bàn giao ở các module. Không trỏ storage lên thư mục dùng chung desktop.

Kiểm tra kết nối/schema/config trước khi start:

```bash
rtk proxy python -m apps.server.worker --check
rtk proxy python -m apps.server.operations_worker --kind import --check
rtk proxy python -m apps.server.operations_worker --kind export --check
rtk proxy python -m apps.server.operations_worker --kind print --check
```

Chạy mỗi dòng bằng một service/process riêng:

```bash
rtk proxy python -m apps.server.worker
rtk proxy python -m apps.server.import_worker
rtk proxy python -m apps.server.export_worker
rtk proxy python -m apps.server.print_worker
rtk proxy python -m apps.server.operations_worker --kind export-cleanup
rtk proxy python -m apps.server.operations_worker --kind print-cleanup
```

Các CLI executor cũ nay chuyển vào cùng supervisor B20; không khởi động thêm một bản cũ
không có heartbeat. `--once` chạy một batch outbox hoặc tối đa một task I/O; cleanup chạy
một batch. `--once` không khẳng định queue rỗng. Exit 0 là lượt không lỗi, exit 1 là lỗi/retry/
lost lease/hạ tầng; outbox cấu hình sai exit 2. Cleanup liên tục chạy mỗi 900 giây,
heartbeat mỗi tối đa 30 giây khi nghỉ. Executor nghỉ 1 giây khi hết việc; outbox theo
`WMS_OUTBOX_POLL_SECONDS` (mặc định 1).

Supervisor của B21 cần `Restart=on-failure`, backoff restart, user service riêng, WorkingDirectory
và đường dẫn interpreter/wheel rõ ràng. SIGTERM/SIGINT ngắt chờ ngay, không claim task mới,
hoàn tất hoặc rollback công việc đang giữ rồi dispose pool. Đặt grace period theo thời gian
I/O đo được; handler CPU treo không tự bị Python signal hủy. Sau hạn có thể SIGKILL và điều tra;
DB rollback, I/O task được reclaim khi lease hết. Không giảm lease chỉ để làm drain nhanh.

## Registry và phiên bản

Factory mặc định: `apps.server.consumers.registry:consumer_factory`.

| Event | Consumer | Hiệu ứng nguyên tử với receipt |
| --- | --- | --- |
| `import.validation.requested.v1` | `import.enqueue.v1` | Enqueue `import_task` |
| `export.requested.v1` | `export.enqueue.v1` | Enqueue `export_task` |
| `print.requested.v1` | `print.enqueue.v1` | Enqueue `print_task` |

Cả ba payload đúng `{job_id: UUID, generation: integer >= 1}`; aggregate_id phải trùng job.
Job/generation cũ được đối chiếu thật để bỏ qua, payload sai/future generation không được ACK.
Task dedup `(job_id,generation)`, receipt dedup `(event_id,consumer)`.
Event khác/phiên bản chưa có consumer giữ pending, không tăng attempts hoặc ACK giả.
Nhiều sự kiện audit nghiệp vụ hiện chưa cần consumer; số `unhandled` không tự có nghĩa lỗi.

`registry_hash` SHA256 của danh sách event/consumer đã sort giúp phát hiện cấu hình khác nhau;
không thay thế kiểm tra wheel/commit hoặc chứng minh handler semantics giống nhau. Đổi factory
bằng CLI chỉ dùng cho mã triển khai tin cậy; API phải nhận cùng cấu hình qua environment.
Không lấy đường dẫn Python từ DB hoặc API request.

Rollout: dừng producer liên quan, drain, dừng toàn bộ worker cũ, triển khai wheel/schema/config
đồng nhất, kiểm tra hash và khởi động worker rồi mở producer. Không rolling deploy hai registry
khác nhau: receipt/ACK không lưu tập subscription bắt buộc của từng release. Đổi tên consumer
có thể chạy lại hiệu ứng. Consumer mới cho event đã processed cần backfill được review riêng;
API replay B20 cố ý không mở lại event thành công. Không xóa receipt để ép chạy lại.

## Quan sát và replay

Các API dưới đều yêu cầu grant GLOBAL `config.manage` hiện hành và phiên MFA; không cấp
thêm quyền mới cho các vai trò. Quyền này hiện dành quản trị cấu hình, được tái sử dụng cho
vận hành queue. Bearer token không đưa vào URL hoặc ghi log.

| Route | Nội dung |
| --- | --- |
| `GET /api/v1/operations/workers` | Lag, processed/pending/retry/dead-letter/unhandled, attempts/replay, tổng trạng thái jobs/tasks, lease hết hạn, worker heartbeat/hash |
| `GET /api/v1/operations/outbox?limit=50&after=UUID` | ID/aggregate/type/version/attempts/replay/error code; không trả payload hoặc exception |
| `GET /api/v1/operations/jobs?kind=import|export|print&limit=50&after=UUID` | Job ID/state/version/generation, task state/attempt/lease/error code; không trả nội dung tệp/snapshot |
| `POST /api/v1/operations/outbox/{id}/replay` | Replay một dead-letter có kiểm quyền, version, idempotency, audit |

Trang có giới hạn 1–200, cursor UUID tăng dần; heartbeat hiển thị tối đa 200 process gần nhất,
có `workers_truncated`. Danh sách không phải snapshot nhất quán trong lúc queue đang đổi.
`ready=true` khi có process IDLE/BUSY mới hơn 120 giây, đúng registry_hash cho đủ sáu kind.
STOPPED/FAILED/stale không được tính. Hãy kiểm tra cả hash của các process khác còn hoạt động;
readiness không phải khóa ngăn deployment khác registry. BUSY quá 120 giây báo stale để điều tra,
không tự cướp lease hay kill process. Một kind có nhiều replica, chỉ cần một replica hợp lệ để sẵn sàng.
`/api/v1/health` và `/ready` vẫn là health API/migration, không thay thế `/operations/workers`.
`--check` không tạo heartbeat và không chứng minh khả năng ghi file/quyền OS hoặc worker khác đang chạy.

Log gồm JSON event `outbox_batch`, `worker_status`, `cleanup_batch`; chỉ có UUID process,
kind, state, mã kết quả và counts. BUSY ở DEBUG để giữ log INFO một batch trước trạng thái.
Lỗi startup/DB dùng thông báo cố định, không log exception/SQL/DSN/payload/token. Failure được
ghi nhận trong outbox/task/job và heartbeat; cần giữ log ngoài máy theo chính sách doanh nghiệp.

Replay sau khi đã sửa nguyên nhân:

1. Đọc event/job, phân biệt outbox dead-letter với executor FAILED. Executor FAILED dùng lệnh
   retry/dry-run/reprint domain hiện có; replay outbox không reset task đã EXHAUSTED.
2. Với outbox chưa processed, `attempts >= WMS_OUTBOX_MAX_ATTEMPTS`, phiên bản có trong registry:
   gửi `Idempotency-Key` UUID và body `{"expected_version":N,"reason":"Lý do xử lý cụ thể"}`.
3. Cùng key/body trả cùng ACK sau khi kiểm quyền lại. Cùng key khác body trả mismatch; version
   cũ trả conflict. Không tạo key mới khi ACK chưa rõ. Tối đa 3 replay/event, cách nhau ít nhất 60 giây.
4. Replay reset attempts/available_at/last_error, tăng version/replay_count, ghi replayed_at;
   không sửa payload/processed_at/receipt. Audit lưu actor, request, reason, attempts/version trước đó.
   Event + audit + idempotency ACK cùng transaction; không có tác động file/network.

`attempts_current_cycles` là tổng attempts trong chu kỳ hiện tại, không phải lifetime sau replay;
attempts chu kỳ trước tra audit. Attempt không tăng khi process chết trước commit. Giữ budget giống
nhau trên mọi process; đổi budget có thể làm dead-letter đủ điều kiện lại mà không qua replay,
do đó là thay đổi cấu hình cần review trong rollout, không dùng để bỏ giới hạn replay.

Drain: tạm dừng producer ghi mới theo cửa sổ vận hành; tiếp tục DB/I/O worker đến khi các event
đã đăng ký không còn pending/retry và tasks không còn READY/RUNNING. Điều tra dead-letter/
EXHAUSTED riêng, không đánh dấu processed bằng tay. UNHANDLED không được xóa để ép số liệu về 0.
SIGTERM từng service và kiểm tra STOPPED/process exit. Nếu kill bắt buộc, chờ lease hết rồi
khởi động executor trước khi tuyên bố drain; kiểm tra lại job/file/receipt.

## Retention bảo thủ

Chưa có Q08 chốt hạn lưu nên ứng dụng **không purge** outbox (cả processed/pending/dead-letter),
consumer_receipt, audit, idempotency, import file/rows, job/task tombstone, print snapshot/attempt
hoặc worker_status. Hồ sơ nghiệp vụ giữ vô hạn ở mức ứng dụng, tối thiểu yêu cầu 5 năm; backup,
dung lượng, lịch xoay log và khôi phục phải do B21/B22/B24 đo và nghiệm thu. Không đồng nhất
TTL tệp báo cáo với hạn lưu hồ sơ nghiệp vụ.

Chỉ snapshot báo cáo và file export/PDF dẫn xuất hết TTL được dọn theo chính sách sẵn có B17/B18.
Mỗi lượt tối đa 100 snapshot/job và 100 orphan object; tham số nội bộ batch_size trong 1–1000.
Không chọn job QUEUED/RUNNING/RENDERING hoặc bất kỳ task READY/RUNNING của job, kể cả generation
cũ. Job pending hết TTL được worker xử lý thành lỗi kết thúc trước khi dọn. Giữ job/task và tăng
generation tombstone chống sự kiện muộn tạo lại file. Print giữ snapshot/attempt để đối soát;
export xóa snapshot tạm nhưng audit/ACK/ledger và báo cáo nguồn còn nguyên.

Session advisory fence chặn cleanup cùng lúc publish file; I/O không giữ transaction DB.
Orphan chỉ là tên hash64 hoặc UUIDhex32.part, không symlink, không còn stored_file tham chiếu,
cũ hơn 24 giờ, trong private root tương ứng. Metadata còn tham chiếu làm file không được dọn.
Unlink thất bại giữ tham chiếu/quota để retry. Crash sau unlink trước commit có thể làm tệp đã hết
TTL không còn nhưng metadata còn; retry cleanup hoàn tất. Không xóa file hợp lệ để lấy quota.
Batch giới hạn số lần xóa, chưa giới hạn thời gian scan directory/query metadata; cần benchmark
kho file lớn. Nếu job bị bỏ pending vô hạn, dung lượng được giữ để điều tra, không purge ép buộc.

DB effects/receipt nguyên tử chống duplicate commit. File publication dùng khóa ổn định và lease
fencing, nhưng không hứa exactly-once cho I/O bên ngoài hoặc giấy in thật. OS spool ACK chỉ là đã
nhận lệnh; trạng thái UNKNOWN phải đối soát, không replay tự động. Chính sách lưu log/backup lâu dài,
hardware, tải và restart service trên target server còn NEEDS_ENVIRONMENT.
