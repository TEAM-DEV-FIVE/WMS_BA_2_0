# Worker outbox PostgreSQL

Worker chạy tách khỏi API. B20 ghép consumer thực tế import/export/print và thêm vận hành,
heartbeat, replay được kiểm quyền và cleanup theo batch. Xem [runbook B20](OUTBOX_OPERATIONS.md)
cho lệnh triển khai hiện hành. Migration release `024_b20_outbox_operations.sql` đã tích hợp và kiểm thử upgrade;
revision phát triển027 chỉ tồn tại ở hồ sơ bàn giao/DB tạm cũ. Không coi #22/QA03 hoặc T02/T24/T26 đã nghiệm thu.

## Khởi động và cấu hình

Cài dependencies server hiện có, chạy migration bằng runner riêng trước khi khởi động. Worker không tự
migrate. Cấp `WMS_DATABASE_URL` qua cấu hình bí mật của service, định dạng
`postgresql+psycopg://…/database`; không đặt credential trong tham số CLI, SQLite hay log.
Worker dùng `Settings`/`make_engine` hiện hành, gồm pool và timeout DB. Các cấu hình dưới dành riêng worker:

| Biến môi trường | Mặc định | Giới hạn/ý nghĩa |
| --- | --- | --- |
| `WMS_OUTBOX_CONSUMER_FACTORY` | `apps.server.consumers.registry:consumer_factory` | `module:function` trả `ConsumerRegistry` không rỗng |
| `WMS_OUTBOX_BATCH_SIZE` | 100 | 1–1000 event tối đa mỗi lượt |
| `WMS_OUTBOX_POLL_SECONDS` | 1 | 0,05–60 giây nghỉ khi lượt chưa đầy |
| `WMS_OUTBOX_MAX_ATTEMPTS` | 5 | 1–100 lần xử lý đã ghi nhận |
| `WMS_OUTBOX_BACKOFF_BASE_SECONDS` | 5 | 1–86400 giây; không vượt mức trần |
| `WMS_OUTBOX_BACKOFF_MAX_SECONDS` | 300 | 1–86400 giây |

Registry mặc định dùng các factories đã tích hợp của B01/B17/B18. Khởi động:

```bash
rtk proxy python -m apps.server.worker --check
rtk proxy python -m apps.server.worker --once
rtk proxy python -m apps.server.worker
```

Cờ `--consumer-factory module:function` ưu tiên hơn biến môi trường và chỉ dùng cho mã
triển khai tin cậy đã được review. Registry rỗng/đường dẫn sai bị từ chối; không dùng consumer
no-op. API, DB worker và I/O worker phải có cùng cấu hình registry/retry. `--check` kiểm tra
kết nối, migration và cấu hình; không chứng minh process worker khác đang sống.

`--once` chỉ chạy tối đa một batch, không drain toàn bộ queue. Exit 0 nghĩa lượt đó không có lần xử lý thất bại,
không khẳng định queue rỗng: event tương lai, đang bị khóa, hết retry hoặc chưa có handler đều có thể còn lại.
Exit 1 khi lượt có retry/exhausted hoặc lỗi DB/worker; exit 2 khi cấu hình/đối số sai. Chế độ liên tục giữ chạy
khi một event thất bại, nhưng thoát 1 nếu không thể claim/commit/ghi retry do lỗi hạ tầng để supervisor xử lý.

`SIGINT`/`SIGTERM` dừng nhận event mới, để event hiện tại commit hoặc rollback rồi đóng engine; chờ poll
bị ngắt ngay. Handler phải có thời gian chạy hữu hạn. Timeout DB hiện hành giới hạn từng câu SQL và lần
chờ khóa, không giới hạn toàn bộ hàm Python hay tổng thời gian transaction. Handler CPU treo không được
Python signal handler tự hủy; supervisor cần grace period phù hợp và có thể cưỡng bức dừng sau hạn.

## Hợp đồng consumer và ACK

Các interface nằm ở [application/outbox.py](../apps/server/application/outbox.py).
Một `Consumer(name, event_type, handle)` đăng ký chính xác một event versioned, ví dụ `receipt.post.v1`
do producer nhận hàng hiện tại phát ra. Không wildcard. `name` là danh tính dedup ổn định, tối đa 100 ký tự;
cùng tên có thể đăng ký nhiều loại event, nhưng trùng cặp tên/type bị từ chối. Registry được chụp cố định,
consumer cùng type chạy theo tên tăng dần. Mỗi handler nhận bản sao payload độc lập.

Handler nhận `sqlalchemy.Connection` thuộc transaction của worker và `OutboxEvent` gồm id, event_type,
aggregate_id, payload, occurred_at. Handler phải:

- Kiểm tra version/nội dung payload; chỉ ghi hiệu ứng DB thuộc chức năng của consumer qua connection được cấp.
- Trả `HandlerResult.APPLIED` sau hiệu ứng thật hoặc sau khi đã xác minh dedup nghiệp vụ tương đương.
  `None` hay kết quả khác đều thất bại và rollback. API không thể chứng minh handler trả APPLIED là trung thực;
  review và test consumer thực tế vẫn bắt buộc, không dùng handler trả APPLIED mà không làm gì.
- Không commit/rollback, không mở transaction/connection khác để ghi; không sửa outbox/receipt của engine.
  Đây là hợp đồng cho mã tin cậy, không phải sandbox ngăn SQL tùy ý.
- Không gọi HTTP/email/in máy in/file I/O và không ghi lại ledger/balance của giao dịch nguồn đã commit.
  Không ghi payload, token, URL DB hay exception chứa credential ra log.

Adapter [infrastructure/outbox.py](../apps/server/infrastructure/outbox.py) xử lý từng event như sau:

1. Bắt đầu transaction; chọn event đã đến `available_at`, chưa processed, còn retry và có handler bằng
   `FOR UPDATE SKIP LOCKED`. Giữ khóa tới commit/rollback, mỗi transaction chỉ nhận một event.
2. Mở savepoint bên trong khóa. Bỏ qua consumer đã có receipt; chạy các consumer còn thiếu và insert receipt
   có UNIQUE `(event_id, consumer)`. Không dùng `ON CONFLICT DO NOTHING` để che xung đột sau hiệu ứng.
3. Chỉ đặt `processed_at` khi mọi consumer bắt buộc của type trong registry đã có receipt. Mọi hiệu ứng mới,
   receipt mới và ACK cùng commit. Nếu consumer sau thất bại, hiệu ứng/receipt mới của consumer trước cũng rollback.
4. Khi thất bại thông thường, rollback savepoint, vẫn giữ khóa event, ghi attempts/backoff/error rồi commit.
   Event khác trong batch dùng transaction riêng nên không bị rollback theo. Trong cùng batch, mỗi event
   được thử tối đa một lần dù thời gian backoff đã qua.

Event không có handler không bị claim, tăng attempts, sửa `last_error` hoặc đánh dấu processed. Chúng không
chiếm batch nên không chặn các loại event đã có consumer; khi triển khai đúng handler, chúng mới đủ điều kiện.
Event chưa tới hạn hoặc đã processed cũng được giữ nguyên. Không bảo đảm thứ tự giữa các event cùng aggregate:
`SKIP LOCKED` cho phép worker khác đi tiếp. Consumer cần chịu được thứ tự khác hoặc thiết kế khóa/version riêng.

Mọi worker dùng cùng registry, consumer names, retry budget và handler semantics. Schema chưa lưu phiên bản
registry/danh sách consumer bắt buộc trong từng event, nên không bảo đảm đầy đủ khi hai deployment có tập
consumer khác nhau chạy đồng thời. Khi đổi tập consumer: dừng toàn bộ worker cũ, triển khai đồng nhất, xác
định event cần replay rồi mới khởi động. Event đã processed không tự được mở lại cho consumer mới; đổi tên
consumer có thể tạo hiệu ứng lặp, phải có kế hoạch dedup/backfill riêng.

## Retry và quan sát

`attempts` tăng 1 cho mỗi lần xử lý đã commit kết quả thành công hoặc metadata lỗi, không tăng theo số
consumer. Backoff lần `n` là `min(base * 2^(n-1), max)` giây tính bằng đồng hồ PostgreSQL lúc ghi lỗi.
Thành công xóa `last_error`. Đến budget, `processed_at` vẫn NULL, giữ error và không tự retry nữa.
Đây là trạng thái exhausted suy ra từ `attempts >= WMS_OUTBOX_MAX_ATTEMPTS`, chưa có bảng dead-letter riêng.
Tăng budget sau deploy có thể làm event exhausted đủ điều kiện lại; cần thay đổi có chủ đích.

Crash/kill/connection mất trước commit rollback cả hiệu ứng/receipt/attempts. Khi DB giải phóng khóa, worker
khởi động lại có thể thử lại. Vì vậy retry budget giới hạn các lần thất bại được ghi nhận, không phải số lần
process chết trước commit. Với kết quả commit không rõ, không đoán thành công; lần chạy sau đọc lại trạng thái
và receipt. Engine không xóa event, receipt, audit hay command idempotency record.

`last_error` chỉ chứa mã cố định: `HANDLER_NOT_APPLIED` (handler không xác nhận hiệu ứng) hoặc `DELIVERY_FAILED`
(handler/receipt/ACK thất bại). Không chứa exception thô, SQL hay secret. Log `outbox_batch` xuất JSON counters
`attempted`, `processed`, `retry`, `exhausted`; lỗi cấu hình/hạ tầng chỉ log mã và hướng xử lý tổng quát.
Chi tiết lỗi cần tái hiện bằng payload đã xử lý thông tin nhạy cảm trong môi trường kiểm thử.

Ví dụ truy vấn vận hành read-only; thay `5` bằng retry budget đang triển khai:

```sql
SELECT event_type,
       count(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
       count(*) FILTER (WHERE processed_at IS NULL AND attempts >= 5) AS exhausted,
       count(*) FILTER (WHERE processed_at IS NULL AND attempts < 5
                        AND available_at <= statement_timestamp()) AS due,
       min(occurred_at) FILTER (WHERE processed_at IS NULL) AS oldest_pending
FROM wms.outbox_event GROUP BY event_type ORDER BY event_type;

SELECT id, event_type, attempts, available_at, last_error
FROM wms.outbox_event
WHERE processed_at IS NULL AND last_error IS NOT NULL
ORDER BY available_at, id LIMIT 100;
```

Đối chiếu nhóm `event_type` pending với registry đang triển khai để nhận diện event không có handler.
Số due bao gồm cả các event này; không đọc số due như số worker chắc chắn xử lý được.

Sau khi sửa nguyên nhân, dùng `POST /api/v1/operations/outbox/{id}/replay` với quyền
`config.manage` + MFA, `Idempotency-Key`, `expected_version` và reason. Replay chỉ áp dụng
sự kiện chưa processed, đã hết retry và đúng phiên bản registry; tối đa 3 lần, cách nhau ít nhất
60 giây. Event, audit và ACK commit nguyên tử. Giữ receipts và payload gốc; không reset queue
bằng SQL vận hành. Lịch sử attempts trước replay nằm trong audit, attempts hiện tại là của chu kỳ mới.
Event đã processed/đổi consumer name cần backfill riêng, không được mở lại bằng API replay.

## Giới hạn bảo đảm và kiểm thử

Với consumer DB tuân hợp đồng, cùng event/consumer không có hai hiệu ứng đã commit do tranh chấp hoặc retry;
receipt và hiệu ứng cùng transaction. Đây không phải lời hứa exactly-once cho tác động ngoài DB. Khi cần
gửi HTTP/email/in ấn, phải xây adapter riêng với delivery at-least-once, dedup phía nhận bằng event/consumer ID
và chính sách retry tương ứng. Không gọi dịch vụ đó trong handler DB hiện tại.

B20 có API vận hành, heartbeat và worker I/O thật; chưa có UI quản trị queue và không tự
cài service lên máy vận hành. Event/receipt/audit/ACK và hồ sơ job giữ vô hạn trong ứng dụng,
không tự purge. Tệp export/print dẫn xuất hết hạn được dọn có fencing/batch; xem chính sách
trong runbook. Index pending hiện có vẫn cần benchmark queue lớn ở B24.

Test riêng ở [test_outbox.py](../tests/foundation/test_outbox.py) dùng bảng hiệu ứng không có UNIQUE riêng
để phát hiện xử lý lặp thật. Có PostgreSQL thật, nhiều kết nối, failpoint trước/sau receipt/ACK, SQL error,
rollback nhiều consumer, retry budget, subprocess `--once`, SIGTERM lúc bận/rảnh và SIGKILL/restart.
Chạy qua `scripts/check_application.py --gui` trên cluster/database tạm; tuyệt đối không dùng DB vận hành.
