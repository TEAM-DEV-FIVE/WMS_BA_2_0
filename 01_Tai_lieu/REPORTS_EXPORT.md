# B17 — Báo cáo và xuất dữ liệu

Runtime trên nền B01–B14 đã tích hợp, migration release `021_b17_reports_export.sql`, đã ghép cùng B07 release 022. Không sửa DDL 001–020, không thêm quyền/role và không thay policy tồn.

## Ý nghĩa dữ liệu

| Báo cáo | Cách tính và phạm vi |
|---|---|
| R01 | Mỗi stock item/location, giữ SKU, base UOM, owner và hợp đồng ký gửi. Physical gồm STORAGE/RECEIVING/QUARANTINE/SHIPPING; TRANSIT ở cột riêng, không cộng vào physical. Eligible dùng chính sách giữ hàng hiện tại: COMPANY, STORAGE hoạt động, SKU/UOM hoạt động, đủ hạn dùng, không bị khóa kiểm kê và serial đúng vị trí. Reserved là tổng quantity−consumed−released, kể cả reservation hết hạn nhưng chưa release; có cột đối soát balance_reserved. Available = eligible−reserved, không che số âm do hàng bị khóa/hết hạn sau giữ chỗ. |
| R02 | Ranh giới là toàn bộ vị trí lá của một kho hoặc danh sách vị trí lá được chọn. Chỉ move qua ranh giới tính inbound/outbound; move có cả hai đầu bên trong không cộng đôi. Có opening, inbound, outbound, net, closing. Closing cộng toàn bộ ledger đến các cận trên; opening là phần không thuộc cửa sổ cận dưới trong tập đó. Với cả business_date và posted_at, cửa sổ là giao của hai điều kiện. Không gọi đây là số dư lịch sử theo riêng ngày ghi sổ khi có thêm bộ lọc ngày nghiệp vụ. |
| R03 | Giữ từng move, bao gồm move đảo; thứ tự tăng posted_at, transaction.id, move.id. business_date là filter độc lập. Đầu move ngoài ranh giới chỉ có cờ outside, không chiếu ID vị trí ngoài phạm vi. Không hỗ trợ đổi sort của thẻ kho. |
| R04 | Một dòng PO/SO đã duyệt; nhu cầu mở = base_quantity−closed_base_quantity−net posted của chứng từ con. Reservation trên các issue con, giữ chi tiết consumed/released/remaining. `demand_scope=WAREHOUSE_ORDER_LINE`: nhu cầu thuộc dòng đơn hàng toàn kho; filter vị trí chỉ giới hạn reservation, không phân bổ giả nhu cầu vào từng kệ. |
| R05 | Theo từng dispatch move, dispatch/GOOD/DAMAGED/LOSS chỉ tính move chưa bị đảo. Transit = dispatch−arrivals−loss. Biên bản MISSING/DAMAGED và evidence_ref giữ riêng; reported_missing không tự trừ transit. Chỉ hiện phiếu mà người dùng có quyền báo cáo/owner/serial ở cả hai kho. Filter thời gian áp dụng dispatch; nhận/loss là trạng thái đối soát tại lúc snapshot. |
| R06 | Tồn hiện tại >0, hạn dùng và lần dịch chuyển gần nhất chạm stock item/location (kể cả move ra và đảo). Tuổi là số ngày lịch theo múi giờ nghiệp vụ từ lần dịch chuyển đó, **không phải tuổi lớp nhập/FIFO**. Thiếu lịch sử trả UNKNOWN/null. Giữ serial/lot/owner; không suy ngày bảo hành từ tuổi tồn, tra nguồn bảo hành bằng API B05 hiện có. |
| R07 | Snapshot kiểm kê, từng vòng đếm, approved, delta, submission/decision/người duyệt. Vị trí kiểm kê trống vẫn có dòng không có SKU và evidence xác nhận trống. Cần count.snapshot.read; người được phân công đếm luôn bị loại khỏi báo cáo phiên đó, kể cả có thêm role quản lý. Tải snapshot/file cũ kiểm tra lại assignment. |
| R08 | Hoạt động theo SKU/base UOM/owner/hợp đồng. Giá là reference_price mới nhất có effective_on ≤ ngày chọn (mặc định ngày tạo snapshot theo WMS_BUSINESS_TIMEZONE). Chỉ khi include_price=true và có price.read mới có các cột giá/ngày hiệu lực/tiền tệ và giá trị inbound/outbound. Nhãn “Giá tham chiếu quản trị”; không phải giá vốn hay báo cáo kế toán. Thiếu giá trả null. |

R01/R06 không nhận filter lịch sử. R04/R07 chỉ nhận business_date. R05 dùng toàn tuyến hai kho, không nhận filter vị trí.
Các filter không áp dụng bị từ chối, không âm thầm bỏ qua. Vị trí GROUP không tự mở rộng thành descendants.
Tồn ký gửi và UNCLASSIFIED không được hòa vào COMPANY hoặc tự coi đủ điều kiện xuất.

## API và snapshot

- `POST /api/v1/reports/{R01..R08}/snapshots`: `ReportCriteria`, header UUID `Idempotency-Key`.
- `GET /api/v1/reports/snapshots/{id}?after=0&limit=50`: snapshot metadata, items, next_after; limit 1–200.
- `GET /api/v1/reports/lookups/{product|owner|location}?warehouse_id=...&code=...`: tra chính xác mã cho form.
- `POST /api/v1/exports`: `{snapshot_id,format:csv|xlsx}`, cùng quy tắc idempotency.
- `GET /api/v1/exports/{id}`: trạng thái, version, generation, hash/kích thước sau READY.
- `POST /api/v1/exports/{id}/{cancel|retry}`: `{expected_version}`, Idempotency-Key. Retry chỉ FAILED, tối đa 5 generation; hủy READY chặn tải ngay.
- `GET /api/v1/exports/{id}/download`: attachment riêng tư, no-store/nosniff; không có URL storage công khai.

Snapshot tạo trong REPEATABLE READ, lưu bộ lọc, thời điểm tạo/hết hạn, cột, row count, SHA-256 và từng dòng với ordinal.
Paging/export đọc cùng snapshot, không đổi thứ tự khi nghiệp vụ phát sinh tiếp. Tối đa 20.000 dòng/16 MiB JSON,
10 snapshot chưa hết hạn/người, TTL một giờ. Vượt giới hạn trả lỗi, không xuất tập con bị cắt mà báo thành công.
Quota dùng row version guard để transaction cạnh tranh phải retry snapshot mới, không chỉ advisory lock trên snapshot cũ.

Mọi lần đọc đều kiểm tra danh tính hiện tại, đúng người tạo và các quyền report.read/ownership.read;
serial.read với báo cáo có chiều serial; count.snapshot.read với R07; price.read với snapshot có giá.
Export cần thêm report.export trên toàn bộ kho thực sự góp dữ liệu. Không dùng role ở kho A để đọc kho B.
Worker kiểm tra cả phiên gốc còn hiệu lực; retry chủ động có thể dùng phiên đăng nhập mới. Download xác thực lại
sau file I/O trong transaction mới, vì grant/session/cancel có thể thay đổi trong lúc đọc file.
Router `/files` của import không trả file export.

CSV UTF-8 BOM và XLSX OOXML không cần thư viện mới. Mọi ô XLSX là inline string, giữ nguyên Decimal lớn,
không có formula/hyperlink/macro/external relationship. Các giá trị bắt đầu bằng công thức (kể cả sau whitespace/BOM)
được thêm dấu nháy đơn. Ô tối đa 32.767 ký tự, XML worksheet tối đa 64 MiB, file tối đa theo cấu hình.
File có snapshot ID, thời điểm, criteria, hash để đối chiếu. Khi report rỗng, file chỉ có header; metadata vẫn ở snapshot/job.
Baseline không có mẫu PDF riêng cho R01–R08; bốn mẫu chứng từ và tem thuộc B18, B17 không thêm bộ render PDF.

## Worker và vận hành

Outbox event `export.requested.v1` có đúng `{job_id: UUID string, generation: integer >=1}`.
Factory: `apps.server.application.export_jobs:consumer_factory`.
Consumer `export.enqueue.v1` chỉ enqueue `export_task` trong connection của outbox, dedup `(job_id,generation)`;
không đọc/ghi file hay tự commit. B20 ghép registry chung với các consumer khác.

Chạy trên server với cùng WMS_DATABASE_URL và thư mục private riêng cho B17:

```bash
python -m apps.server.worker --consumer-factory apps.server.application.export_jobs:consumer_factory
python -m apps.server.export_worker
python -m apps.server.export_worker --once
python -m apps.server.export_cleanup
```

Executor claim SKIP LOCKED, lease mặc định 60s, tối đa 5 attempts và backoff 5..300s. Lease token + generation
được kiểm tra trước publication; worker cũ không ghi đè kết quả mới/hủy. Crash ở attempt cuối chuyển FAILED/LEASE_EXHAUSTED.
File render/put nằm ngoài DB transaction. Một session advisory fence đã commit phối hợp với cleanup;
không giữ transaction trong lúc file I/O. Mỗi tiến trình CLI có một executor; không chạy nhiều thread executor
chia pool nhỏ. File key và bytes ổn định qua retry, ghi nguyên tử/fsync, không tạo biến động ledger/balance.
Nếu DB commit sau put thất bại, file private chưa được tham chiếu; lần retry dùng lại đúng object.

`WMS_EXPORT_STORAGE_ROOT` mặc định `.wms-export-files`, độc lập thư mục import, không công khai qua web server.
Các cấu hình kế thừa giới hạn storage: `WMS_EXPORT_MAX_FILE_BYTES` mặc định 5 MiB, tối đa 20 MiB;
`WMS_EXPORT_MAX_USER_BYTES` mặc định 100 MiB; `WMS_EXPORT_MAX_USER_FILES` mặc định 100;
`WMS_EXPORT_LEASE_SECONDS`, `WMS_EXPORT_MAX_ATTEMPTS`. Quota tính cả job chưa tạo xong theo mức file tối đa;
mỗi snapshot chỉ có một job mỗi định dạng. Muốn xuất lại job đã hủy phải tạo snapshot mới.

Chạy cleanup định kỳ, ví dụ mỗi 15 phút bằng scheduler vận hành B20/B21. Cleanup lấy fence độc quyền,
trả lỗi retryable nếu executor đang giữ fence; xóa snapshot/file hết hạn, giữ job tombstone/generation cho event cũ,
giữ audit/idempotency theo retention chung. Object/temp `.part` mồ côi quá 24 giờ được dọn trong storage private.
Nếu lỗi quyền unlink, giữ metadata/quota để thử lại. Không xóa chứng từ, ledger, audit hoặc dữ liệu import.
Không cấu hình import và export trùng storage root.

Mục tiêu Q05 (15 CCU, 1 kho/3 khu, 20 GB/3 năm) cần benchmark B24/B26. Row/file/TTL/quota là giới hạn bảo vệ,
không phải bằng chứng đạt tải. Dữ liệu nguồn giữ ít nhất 5 năm theo chính sách chung; snapshot/file báo cáo chỉ là
bản dẫn xuất tạm, không thay hồ sơ nghiệp vụ. Cần đo dung lượng JSONB/WAL và throughput cleanup trên dataset đại diện.

## Desktop và bàn giao tiếp

Màn “Báo cáo / xuất dữ liệu” có kho, R01–R08, mã SKU/chủ hàng/vị trí, ngày nghiệp vụ/ghi sổ/ngày giá,
sort, paging, tạo CSV/XLSX, trạng thái, cancel/retry/download. HTTP/render file local ở worker;
Tk và vòng đời widget ở main thread. Thay user/kho/session loại response cũ và ngăn ghi đè file local.
ACK mất được giữ trong RAM theo user/kho; nút tra/gửi lại dùng nguyên route/body/key. B19 nối journal chung sau tích hợp,
không thêm SQLite revision hoặc lưu token ở B17.

Xem [bàn giao B17](PHAN_CONG/BAN_GIAO/B17.md) để biết commit và kết quả kiểm thử thực tế.
