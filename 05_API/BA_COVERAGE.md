# Coverage theo use case

Có path không đồng nghĩa đủ luồng, authorization hoặc đã triển khai. Bảng dưới giữ coverage của contract nghiệp vụ lõi; IAM đã có [contract runtime](openapi_runtime.json) và [hướng dẫn](../01_Tai_lieu/IDENTITY.md).

| UC | Path hiện có | Coverage |
|---|---|---|
|UC01|Runtime: /api/v1/auth/login, /auth/mfa, /auth/refresh, /auth/logout, /auth/me|IMPLEMENTED_LOCAL - đăng nhập/rotation/revoke/MFA được kiểm thử API và desktop; chưa UAT Windows|
|UC02|Runtime: /api/v1/users, /roles, /grants, /grant-requests và approve/revoke|PARTIAL - API và desktop quản trị/two-person grant chạy thật; reset MFA, lookup/lịch sử nâng cao và Windows UAT còn thiếu|
|UC03|Runtime: /api/v1/master/products,uoms,categories,product-uoms,barcodes,scan|PARTIAL - API có validation/version/idempotency, form sản phẩm/UOM/category; còn import và GUI quy đổi/barcode|
|UC04|Runtime: /api/v1/master/warehouses,locations|PARTIAL - API/form cây kho, chặn chu kỳ/sai kho/phát sinh; UAT Windows chưa chạy|
|UC05|Runtime /api/v1/purchase-orders, /purchase-orders/{id}, /documents/{id} actions|PARTIAL - CRUD/list PO, assignment, submit/duyệt/revise/cancel/close đã chạy API và desktop; posting còn thiếu|
|UC06|/purchase-orders, /purchase-orders/{id}, /receipts, /receipts/{id}, /receipts/{id}/revise, /receipts/{id}/post, /documents/{id}/submit, /approval-requests/{id}/decide|PARTIAL - runtime PO/receipt/duyệt/post và phục hồi receipt.post sau crash đã có; PUT/revise/DTO khác core, scanner/UAT còn thiếu|
|UC07|/moves/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC08|Runtime /api/v1/sales-orders, /sales-orders/{id}, /documents/{id} actions|PARTIAL - CRUD/list SO, assignment và duyệt đã chạy; giữ hàng/xuất/posting chưa có|
|UC09|/issues/{id}/reserve|PARTIAL - chưa đủ toàn luồng UC|
|UC10|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC11|/issues/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC12|/transfers/{id}/dispatch|PARTIAL - chưa đủ toàn luồng UC|
|UC13|/transfers/{id}/receive|PARTIAL - chưa đủ toàn luồng UC|
|UC14|/returns/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC15|/returns/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC16|/counts/{id}/freeze|PARTIAL - chưa đủ toàn luồng UC|
|UC17|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC18|/counts/{id}/submit, /adjustments/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC19|Runtime /api/v1/documents/{id}/cancel, /close|PARTIAL - hủy/đóng thiếu PO/SO giữ lịch sử; chặn reservation/phiếu con mở; đã có source lock với receipt; release và posting khác chưa tích hợp|
|UC20|/adjustments/{id}/post|PARTIAL - chưa đủ toàn luồng UC|
|UC21|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC22|/imports/{id}/commit|PARTIAL - chưa đủ toàn luồng UC|
|UC23|Runtime /api/v1/openings, /openings/{id}, /openings/{id}/post, /openings/operations/{key}|PARTIAL - backend draft/duyệt/post toàn phiếu, chống batch/execution trùng và cutover đã có; import/UI và nghiệm thu còn thiếu|
|UC24|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC25|Runtime /api/v1/operations/{key}|PARTIAL - receipt.post có SQLite checkpoint, lookup và explicit retry cùng key/body qua desktop sau restart; nháp/lệnh khác và Windows UAT còn thiếu|
|UC26|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC27|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC28|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC29|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC30|Runtime /api/v1/approval-requests/{id}, /decide và /documents/{id}/submit|PARTIAL - snapshot/SOD/duyệt theo policy cho PO/SO/receipt/opening; policy kiểm kê/điều chỉnh chưa có|
|UC31|Chưa có|MISSING - chưa đặc tả trong OpenAPI lõi|
|UC32|Runtime: /api/v1/master/stock-owners, /master/consignment-agreements, /stock-ownership|PARTIAL - owner/hợp đồng/schema/API đọc và quyền đã chạy local; posting/import/báo cáo/kiểm kê/policy xuất chuyển còn thiếu|
|UC33|Runtime: /api/v1/serials/lookup, /serials/{id}/warranty, /serials/{id}/warranty-records|PARTIAL - API chứng cứ/nguồn/quyền, desktop tra cứu và nguồn receipt.post đã chạy; GUI ghi chứng cứ/UAT Windows còn thiếu|

## Chi tiết coverage UC06

| Bước | Contract | Phần chưa có / cần kiểm thử |
|---|---|---|
| Chọn PO và xem lượng còn lại | `GET /purchase-orders`, `GET /purchase-orders/{id}` | Runtime đã có net posted/scope/assignment. WAREHOUSE_MANAGER phân công trước submit; RECEIVER chỉ đọc phiếu được giao/đã lập. Đã nối màn nhận hàng và receipt.post theo runtime 009. |
| Tạo/sửa nháp receipt | Core dùng PATCH/revise riêng; runtime dùng PUT và `/documents/{id}/revise` | Runtime đã có kiểm tra nguồn, lượng cơ sở, snapshot và stale version; core không phải DTO của server. |
| Gửi và duyệt | `POST /documents/{id}/submit`, `POST /approval-requests/{id}/decide` | PO/SO/RECEIPT có workflow/snapshot/role/version/SOD và kiểm thử API/desktop. |
| Quét lô/serial và chọn vị trí | Core truyền tracking lúc post; runtime lưu kế hoạch trước duyệt | Runtime có vị trí theo quyền và receipt_plan trong snapshot duyệt; desktop nhập tay lô/serial/vị trí. Scanner chưa tích hợp. |
| Ghi sổ và tra kết quả | `POST /receipts/{id}/post`, `GET /operations/{key}` | Runtime có transaction/source lock/chống trùng/đối soát; desktop lưu SQLite trước HTTP và tra cứu/retry sau crash. Test PostgreSQL thật đạt; chưa nghiệm thu toàn T01/T02. |
| Cách ly và cất hàng | `/moves/{id}/post` chỉ có lệnh post | Chưa có API lập/sửa move nháp, quyết định chất lượng hoặc kiểm thử đủ luồng cách ly 5/80 của T01. |

Mức `PARTIAL` không phải kết quả acceptance test; những dòng có ghi runtime phản ánh bằng chứng triển khai local.

Phân trang còn cần backend tạo snapshot `as_of` thật cho tập kết quả; cursor theo `(created_at,id)` không tự bảo đảm danh sách PO còn lượng nhận không đổi giữa các trang. Phiếu SUBMITTED cần quay về DRAFT để sửa theo mô tả kiến trúc, nhưng bảng trạng thái chưa định nghĩa chuyển tiếp này; chờ thống nhất trước khi thêm endpoint.

Quy tắc nghiệp vụ chưa chốt với tech lead: hàng hỏng/cách ly đã kiểm nhận có trừ PO remaining hay không. T01 hiện tính là đã nhận; tài liệu nghiệp vụ chỉ xác nhận hàng hỏng không tăng tồn hàng tốt.

## Coverage liên luồng BE01

| Chặng | Contract hiện có | Phần còn thiếu / owner tiếp theo |
|---|---|---|
| Đăng nhập | Runtime IAM/MFA/refresh/logout đã chạy | Còn recovery/reset MFA và UAT Windows. |
| Danh mục | Runtime /master/* có DTO, keyset, UOM revision và barcode/scan | Owner/bảo hành đã có API; còn GUI owner/hợp đồng/ghi chứng cứ/quy đổi/barcode/giá và tra vị trí theo quyền vận hành. |
| PO | `GET /purchase-orders`, `GET /purchase-orders/{id}` cho lượng còn nhận | BE06 đã có create/PUT/list/read, assignment, đóng thiếu; RECEIVER chỉ đọc phiếu được giao. Đã tích hợp receipt và kiểm thử concurrency tại source PO. |
| Receipt | `POST /receipts`, `GET/PATCH /receipts/{id}`, `POST /receipts/{id}/revise` | Runtime lưu kế hoạch ở attributes.receipt_plan trong snapshot; PUT và revise qua documents. Core vẫn là thiết kế lịch sử. |
| Duyệt | `/documents/{id}/submit`, `/approval-requests/{id}/decide` có DTO lõi | BE07 đã có runtime PO/SO/RECEIPT với lookup/snapshot/SOD/vô hiệu duyệt; các loại phiếu khác còn thiếu. |
| Post và retry | `/receipts/{id}/post`, `/operations/{key}`; có mẫu thành công/lỗi và projection | Runtime receipt.post và SQLite desktop phục hồi sau crash đã có test thành phần; chưa nghiệm thu toàn T01/T02. |
| Tra tồn | Runtime `/api/v1/stock-ownership` cộng vật lý/sở hữu/ký gửi/chưa phân loại | Đã có scope kho + ownership.read; còn UI tồn/báo cáo và luồng posting. |

## Runtime và giới hạn UC32/UC33

- UC32 đã có owner/consignment trên stock item và dòng phiếu; balance/ledger/reservation/count giữ owner qua stock_item_id.
  Migration 006 giữ dữ liệu cũ ở UNCLASSIFIED; không tự chuyển thành hàng doanh nghiệp. Truy vấn 10+5, đối soát,
  rollback và race serial đã kiểm thử. Chưa có workflow phân loại lại legacy, chuyển owner hoặc posting.
- UC33 đã lưu revision chứng cứ append-only từ RECEIVE đã ghi sổ đúng serial/chưa đảo. Ngày nghiệp vụ theo timezone
  server; thiếu chứng cứ trả UNKNOWN. Kiểm tra quyền tại kho yêu cầu/nguồn và ownership/assignment của phiếu.
  Desktop đọc qua API thật; ghi chứng cứ hiện qua API, sửa chữa/RMA ngoài phạm vi.
- Hai path proposal của core giữ cờ `PROVISIONAL_BLOCKED...` như tài liệu lịch sử. Dùng OpenAPI runtime cho client mới.
  Xem [TRACEABILITY.md](../01_Tai_lieu/TRACEABILITY.md) cho schema/quyền/DTO hiện hành.
- T27/T28 có bằng chứng thành phần, vẫn PLANNED cho nghiệm thu đủ luồng. Xuất/chuyển/giữ chỗ/đảo ký gửi bị chặn
  cho tới khi có policy và workflow; không suy ra từ việc đã có GET hoặc trigger.

Chi tiết runtime PO/SO, phân trang live và phần T10/T14/T17 chưa nghiệm thu: [ORDERS_APPROVAL.md](../01_Tai_lieu/ORDERS_APPROVAL.md).

## Runtime nhận hàng revision 009

[RECEIVING.md](../01_Tai_lieu/RECEIVING.md) là mô tả hiện hành cho receipt. Các câu hỏi/core payload trong bảng lịch sử ở trên không thay thế runtime contract.
Đã chọn kế hoạch tracking/vị trí trước duyệt, nhập UOM cơ sở và tính QUARANTINE vào lượng PO đã nhận theo T01.
Backend tồn đầu kỳ đã có ở revision 010; import/UI tồn đầu kỳ, policy ký gửi, chất lượng/trả NCC, barcode/scanner, snapshot pagination và Windows UAT còn thiếu.

## Tích hợp tồn đầu kỳ, outbox và desktop quản trị

Backend [OPENING](../01_Tai_lieu/OPENING.md) dùng bảng kế hoạch typed và khóa warehouse độc quyền khi cutover.
[Desktop quản trị](../01_Tai_lieu/ADMIN_DESKTOP.md) nối API IAM có sẵn, không tự retry write khi timeout.
[Worker outbox](../01_Tai_lieu/OUTBOX_WORKER.md) có engine/adapter DB; consumer nghiệp vụ chưa được cấu hình.
Các phần này chưa thay trạng thái nghiệm thu T01–T28.
