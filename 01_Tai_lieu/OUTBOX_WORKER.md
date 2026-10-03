# Worker outbox PostgreSQL

Worker chạy tách khỏi API qua `python -m apps.server.worker`, dùng schema migration 001–009 hiện có.
Đợt này bàn giao engine/adapter và consumer kiểm thử tạo hiệu ứng DB thật; **chưa có consumer nghiệp vụ
được định nghĩa/triển khai để bật trên DB vận hành**. Không coi #22/QA03 hoặc T02/T24 đã nghiệm thu đầy đủ.
Xem [bất biến](INVARIANTS.md) và [báo cáo bàn giao](../07_Kiem_tra/AGENT_OUTBOX_REPORT.md).

## Khởi động và cấu hình

Cài dependencies server hiện có, chạy migration bằng runner riêng trước khi khởi động. Worker không tự
migrate. Cấp `WMS_DATABASE_URL` qua cấu hình bí mật của service, định dạng
`postgresql+psycopg://…/database`; không đặt credential trong tham số CLI, SQLite hay log.
Worker dùng `Settings`/`make_engine` hiện hành, gồm pool và timeout DB. Các cấu hình dưới dành riêng worker:

| Biến môi trường | Mặc định | Giới hạn/ý nghĩa |
| --- | --- | --- |
| `WMS_OUTBOX_CONSUMER_FACTORY` | Không có | `module:function` trả `ConsumerRegistry` không rỗng |
| `WMS_OUTBOX_BATCH_SIZE` | 100 | 1–1000 event tối đa mỗi lượt |
| `WMS_OUTBOX_POLL_SECONDS` | 1 | 0,05–60 giây nghỉ khi lượt chưa đầy |
| `WMS_OUTBOX_MAX_ATTEMPTS` | 5 | 1–100 lần xử lý đã ghi nhận |
| `WMS_OUTBOX_BACKOFF_BASE_SECONDS` | 5 | 1–86400 giây; không vượt mức trần |
| `WMS_OUTBOX_BACKOFF_MAX_SECONDS` | 300 | 1–86400 giây |

Sau khi có package consumer đã được review, ví dụ package tên `warehouse_consumers` có factory `create_registry`:

```bash
python -m apps.server.worker --consumer-factory warehouse_consumers:create_registry --once
python -m apps.server.worker --consumer-factory warehouse_consumers:create_registry
```

`warehouse_consumers` trong ví dụ là package triển khai tương lai, không phải module đã có trong repo.
Có thể bỏ `--consumer-factory` khi đã đặt biến môi trường tương ứng; cờ CLI ưu tiên hơn biến môi trường.
Factory là mã Python tin cậy được operator chọn, không đọc mã/cấu hình plugin từ DB. Factory chỉ khai báo
consumer, không thực hiện nghiệp vụ hay tự mở transaction. Chưa cấu hình factory hoặc registry rỗng thì
worker thoát mã 2 trước khi kết nối DB; không có handler mặc định đánh dấu thành công giả.

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

Sau khi đã sửa nguyên nhân và ghi nhận việc vận hành, operator có thể dừng worker rồi reset một event lỗi
cụ thể. Ví dụ dưới dùng bind parameter `:event_id`, cần truyền UUID event đã review, không chạy update toàn queue:

```sql
BEGIN;
SELECT id, attempts, last_error FROM wms.outbox_event WHERE id=:event_id FOR UPDATE;
UPDATE wms.outbox_event
SET attempts=0, available_at=clock_timestamp(), last_error=NULL
WHERE id=:event_id AND processed_at IS NULL AND last_error IS NOT NULL;
COMMIT;
```

Giữ nguyên receipts để không lặp hiệu ứng đã commit; không sửa audit hay payload gốc. Schema chỉ giữ lỗi cuối
và bộ đếm hiện tại, không có lịch sử retry/admin replay; cần lưu biên bản vận hành riêng. Mở lại event đã
processed hoặc đổi consumer name là backfill được thiết kế riêng, không thuộc thao tác retry trên.

## Giới hạn bảo đảm và kiểm thử

Với consumer DB tuân hợp đồng, cùng event/consumer không có hai hiệu ứng đã commit do tranh chấp hoặc retry;
receipt và hiệu ứng cùng transaction. Đây không phải lời hứa exactly-once cho tác động ngoài DB. Khi cần
gửi HTTP/email/in ấn, phải xây adapter riêng với delivery at-least-once, dedup phía nhận bằng event/consumer ID
và chính sách retry tương ứng. Không gọi dịch vụ đó trong handler DB hiện tại.

Không thay migration/API/producers/command kernel/dependency/CI. Chưa có consumer nghiệp vụ, service unit,
metrics endpoint, UI retry, retention/purge hay lịch sử delivery; không tự coi queue đã được tiêu thụ trong
nghiệp vụ chỉ vì test engine đạt. Index `ix_outbox_pending(available_at,id)` hiện có được tận dụng; queue lớn
với nhiều event unknown/exhausted cần theo dõi/đo hiệu năng trước đề xuất index bổ sung.

Test riêng ở [test_outbox.py](../tests/foundation/test_outbox.py) dùng bảng hiệu ứng không có UNIQUE riêng
để phát hiện xử lý lặp thật. Có PostgreSQL thật, nhiều kết nối, failpoint trước/sau receipt/ACK, SQL error,
rollback nhiều consumer, retry budget, subprocess `--once`, SIGTERM lúc bận/rảnh và SIGKILL/restart.
Chạy qua `scripts/check_application.py --gui` trên cluster/database tạm; tuyệt đối không dùng DB vận hành.
