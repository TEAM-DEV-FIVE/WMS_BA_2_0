# Nhận hàng từ PO — TL03/TL04/TL05/UI06

Cập nhật 03/10/2026. Đã có luồng local: PO đã duyệt → phiếu nhận → duyệt → ghi sổ từng phần.
Phần này bổ sung migration `009_receiving.sql`. Tồn đầu kỳ/import, xuất/giữ hàng, đảo và nhận ký gửi chưa nằm trong luồng này.

## Quy trình và quyền

1. Lập PO, phân công RECEIVER trước khi gửi duyệt, rồi duyệt bằng người khác creator/requester.
   Người nhận cần `document.read`, `receipt.draft` và `receipt.post` ở kho đó. RECEIVER chỉ thấy PO/phiếu
   do mình lập hoặc được giao; có thể cấp thêm BUYER theo nhu cầu thực tế, không tự mở quyền đọc toàn kho.
2. Tab **Nhận hàng**: tải kho, **Tạo từ PO**, chọn dòng nguồn, vị trí RECEIVING/QUARANTINE và lượng **đơn vị cơ sở**.
   Một dòng là một lô hoặc một serial tại một vị trí. Mỗi serial có lượng 1; mã giữ hoa/thường và số 0 đầu.
   Nhận nhiều lô/serial từ cùng dòng PO bằng nhiều dòng kế hoạch. Nhập ngày `YYYY-MM-DD` khi theo dõi lô.
3. Lưu nháp rồi gửi duyệt. WAREHOUSE_MANAGER hoặc CONTROLLER duyệt theo policy Q04; vẫn cấm tự duyệt.
   Vị trí, lô/serial, metadata và lượng kế hoạch nằm trong snapshot. Muốn đổi phải sửa lại và duyệt lại trước khi có ghi sổ.
4. Người lập/được giao chọn dòng đã duyệt, nhập lượng thực nhận và bấm **Nhận dòng chọn**. Giao diện tải lại
   lượng còn lại từ server sau ACK. API cũng hỗ trợ ghi nhiều dòng trong một transaction.
5. Timeout lúc ghi sổ: mở tab **Phục hồi nhận hàng**, tra kết quả máy chủ rồi chủ động gửi lại đúng lệnh nếu cần.
   HTTP key, execution key và body đã lưu SQLite trước khi gửi nên giữ được sau đóng process; không tạo key mới
   để đoán kết quả. Xem [hướng dẫn phục hồi](RECEIPT_RECOVERY.md). Tạo/sửa/duyệt vẫn giữ yêu cầu trong RAM;
   nút **Gửi lại đúng yêu cầu chưa rõ kết quả** trên tab Nhận hàng dành cho các lệnh RAM này.

Danh sách phiếu có trang 25 dòng; chọn PO tối đa 100 APPROVED + 100 PARTIAL và báo khi bị giới hạn.
Dropdown vị trí tối đa 500. Phân công vẫn qua API, chưa có GUI quản trị/phân công. Màn hình hiện dùng nhập tay,
chưa tích hợp máy quét, đối chiếu barcode hoặc UAT Windows.

## Khởi tạo kỳ kho đầu tiên

Posting yêu cầu ngày ghi sổ thuộc **đúng một kỳ OPEN**. Không tự tạo kỳ theo ngày client gửi.
Trên máy chủ, sau migration và tạo kho, người vận hành có credential DB thiết lập kỳ đầu bằng:

```bash
python -m apps.server.bootstrap_period --warehouse-code WH01 \
  --starts-on 2026-10-01 --ends-on 2026-10-31 --reason 'Thiết lập kỳ đầu cho kho mới'
```

Thay mã kho/ngày bằng dữ liệu triển khai đã chốt. Công cụ dùng quyền tài khoản DB trên máy chủ, giống bootstrap
quản trị; khóa warehouse, chỉ cho kho chưa có kỳ và chưa có lịch sử ghi sổ, lưu audit tài khoản DB/lý do.
Không dùng để mở lại/chỉnh kỳ hoặc tạo các kỳ tiếp theo. Workflow đóng/mở kỳ và kiểm kê đầy đủ thuộc #28, chưa triển khai.

## API runtime

Tất cả path có prefix `/api/v1`; lệnh ghi bắt buộc `Idempotency-Key: UUID`. Contract chính xác ở
[openapi_runtime.json](../05_API/openapi_runtime.json), Swagger `/api/v1/docs`.

| Path | Chức năng |
| --- | --- |
| `GET/POST /receipts` | Danh sách theo kho/quyền; tạo từ đúng một PO APPROVED/PARTIAL |
| `GET/PUT /receipts/{id}` | Chi tiết có `plan`, lượng đã nhận/còn lại; thay toàn bộ nháp với version |
| `GET /receipts/locations?warehouse_id=...` | Vị trí nhận/cách ly đang hoạt động, theo quyền kho |
| `POST /documents/{id}/submit,revise,cancel,assignments` | Dùng workflow duyệt/phân công chung |
| `GET /approval-requests/{id}`; `POST /approval-requests/{id}/decide` | Lịch sử, SOD và quyết định |
| `POST /receipts/{id}/post` | Ghi sổ một hoặc nhiều dòng theo lượng cơ sở |
| `GET /operations/{key}` | Tra ACK bất biến của `receipt.post` đã commit, đúng actor và quyền hiện tại |

Tạo nháp gồm `source_order_id`, `business_date`, `reason` và `lines`:
`source_line_id`, `quantity_base` (chuỗi decimal), `destination_location_id`, cùng `lot_code`/`serial_code`,
`manufactured_on`/`expires_on` nếu áp dụng. Kho/NCC/chủ hàng lấy từ PO. Nhập theo UOM cơ sở với factor 1;
quy đổi của PO giữ nguyên và có thể đối chiếu qua dòng nguồn. Tổng các dòng cùng nguồn không vượt PO remaining.
Nháp không giữ/chặn lượng PO: nhiều phiếu có thể cùng dự kiến nhận, nhưng post phải kiểm tra lại dưới khóa PO.

Post gồm `expected_version`, `execution_key`, `reason`, `lines[{document_line_id,quantity_base}]`.
Không cho đổi vị trí/lô/serial lúc post. ACK có ID transaction, version/status phiếu nhận và PO nguồn.
Các lỗi nghiệp vụ như `SOURCE_EXCEEDED`, `RECEIPT_EXCEEDED`, `LOT_METADATA_CONFLICT`, `PERIOD_CLOSED`,
`LOCATION_FROZEN`, `SERIAL_ALREADY_PRESENT`, `STALE_APPROVAL` trả 409; DTO sai trả 422.
Sau ba lần deadlock/serialization failure trả 503 `DATABASE_BUSY`, `retryable=true`.

`GET /operations` chỉ hỗ trợ receipt.post trong đợt này. GET 404 chưa chứng minh lệnh cũ không commit.
Replay cùng HTTP key trả đúng status/body gốc sau khi kiểm tra quyền lại. Cùng execution key với HTTP key khác
chỉ trả ACK gốc nếu cùng actor và toàn bộ hash payload; khác payload/actor trả `EXECUTION_MISMATCH`.
`request_id` trong ACK là ID lệnh gốc; header `X-Request-ID` là lần HTTP hiện tại.

Runtime dùng PUT thay PATCH, keyset `after` thay snapshot cursor, revise dùng route documents chung.
`openapi_core.json` là thiết kế đích lịch sử: DTO post truyền tracking/location khác runtime này.
Không dùng payload mẫu core cho runtime. Lựa chọn runtime giữ kế hoạch nhận trong
`document.attributes.receipt_plan`, namespace dành riêng cho service; approval snapshot bao gồm toàn bộ namespace.
Số lượng chuẩn vẫn ở `document_line`; số tồn và giá không lưu trong JSON này.

## Bảo vệ giao dịch và kiểm thử

- Khóa PO nguồn trước phiếu nhận ở create/update/submit/decide/revise/cancel/post. Lệnh PO khóa chính PO trước
  kiểm tra phiếu con. Sau đó warehouse/period → vị trí → product theo UUID → danh tính → balance.
  Product lock tuần tự hóa tạo lô/serial/stock item. Vị trí EXTERNAL dùng shared lock và không có balance.
- Kiểm tra bản duyệt thực sự đúng nội dung của cả PO và receipt; không chỉ tin status APPROVED.
  Kiểm tra precision UOM, owner COMPANY, kho/NCC đang hoạt động, kỳ mở và vị trí không khóa kiểm kê.
- Lô yêu cầu hạn dùng phải có ngày; lô đã có phải khớp cả NSX/HSD. Xét hết hạn theo ngày hiện tại ở timezone
  doanh nghiệp, không dùng ngày backdate để vượt kiểm tra; lô hết hạn chỉ nhận QUARANTINE.
- Theo T01, nhận ở RECEIVING và QUARANTINE đều giảm PO remaining. QUARANTINE không phải hàng tốt khả dụng;
  xử lý chất lượng/trả NCC riêng chưa triển khai. Serial đã có position/tồn không được nhận lần nữa.
- Ledger, balance, serial position, tiến độ hai phiếu, audit/outbox, execution ACK và idempotency commit cùng nhau.
  Retry SQLSTATE `40P01`/`40001` tối đa ba attempt với jitter, transaction mới, cùng key/body và kiểm tra quyền lại.
  Không tự retry lỗi mất kết nối/không rõ commit. Outbox worker chưa triển khai.
- Nhận đủ kế hoạch → receipt COMPLETED; nhận thiếu → PARTIAL. PO dựa lượng nhận ròng. PO có phiếu con chưa
  xong không được hủy/đóng thiếu; receipt đã post không sửa/hủy/đóng thiếu trực tiếp trong đợt này.
  Kế hoạch 80/PO 100, nhận đủ 80 thì có thể đóng phần PO còn 20; plan 100 mới nhận 80 phải tiếp tục nhận hoặc chờ workflow xử lý ngoại lệ.

[test_receipts.py](../tests/foundation/test_receipts.py) có bằng chứng API + PostgreSQL và desktop HTTP thật:
nhận từng phần/hoàn tất, replay/operation/revoke, execution trùng, nhận vượt khi cạnh tranh, create đối đầu cancel,
snapshot, revise, kỳ/kiểm kê, lô hết hạn/metadata, serial/nguồn bảo hành, failpoint sau audit/outbox, rollback danh tính,
fault injection SQLSTATE deadlock và đối soát ledger/owner. Chưa phải benchmark deadlock/tải production.
Đã thêm ca process chết sau server commit, trước khi desktop lưu ACK: mở lại desktop và tra cứu xác nhận
chỉ một giao dịch, tồn không cộng lần hai. Kiểm thử SQLite/presenter ở
[test_receipt_recovery.py](../tests/foundation/test_receipt_recovery.py).
[Báo cáo kiểm thử](../07_Kiem_tra/IMPLEMENTATION_REVIEW.md) ghi kết quả thực chạy và phần còn thiếu.
T01–T28 vẫn PLANNED cho nghiệm thu toàn hệ thống; các issue #7/#16/#23/#24 chưa được coi là hoàn tất toàn phạm vi.
