# B08 — Review runtime và thiết kế API

Phạm vi: base `45e51a5` (code nền `06041b7`), nhánh `agent/b08-ci-contracts`.
Đây là review mã/contract, không phải nghiệm thu T01–T28. Không thay đổi `openapi_core.json`.

## Nguồn và cách tái lập

- [Runtime](openapi_runtime.json) sinh trực tiếp từ `create_app().openapi()`, không kết nối DB.
- [Thiết kế lõi](openapi_core.json) giữ các API planned và ví dụ lịch sử.
- [Inventory](contract_inventory.json) sinh cùng runtime bằng `scripts/export_runtime_contract.py`;
  `--check` yêu cầu nội dung tái lập. Test xác nhận schema runtime hợp lệ và inventory không stale.
- Inventory so method + path sau bỏ `/api/v1` và chuẩn hóa tên tham số đường dẫn. Cùng route
  chỉ có nghĩa `IMPLEMENTED_ROUTE_REVIEW_DTO`, không có nghĩa DTO/policy giống thiết kế hoặc đã nghiệm thu.
  Quyền nghiệp vụ không suy được từ Bearer/OpenAPI; phải đọc service và test thực tế bên dưới.

Mốc review có **65 paths / 95 operations**, trong đó 90 operations cần Bearer; 5 public là health,
ready, login, mfa challenge, refresh. Trong 25 operations thiết kế lõi, 13 có route runtime tương ứng,
12 còn `PLANNED` theo method/path. Một số planned có phương án runtime khác ở bảng dưới.

## Khác biệt cần client tuân thủ

| Thiết kế lõi | Runtime hiện tại | Ảnh hưởng / nhánh tiếp nối |
| --- | --- | --- |
| PATCH `/receipts/{id}` | PUT `/api/v1/receipts/{document_id}` | Dùng ReceiptUpdate, expected_version, thay kế hoạch theo DTO runtime; không gọi PATCH |
| POST `/receipts/{id}/revise` | POST `/api/v1/documents/{document_id}/revise` | Action chung có reason/version/key; thay đổi nội dung phải duyệt lại |
| `cursor`, `as_of`, mặc định 100 | `after`, `next_after`, mặc định 50, tối đa 200 cho orders/receipts | Keyset không bảo đảm snapshot qua nhiều trang; không gửi as_of để giả snapshot |
| Nhập kế hoạch tracking lúc post | ReceiptInput/Update lưu kế hoạch trước duyệt; ReceiptPost chọn dòng/lượng theo kế hoạch | Không lấy ví dụ post trong core làm DTO runtime |
| `/operations/{key}` cho nhiều command | `/api/v1/operations/{key}` chỉ receipt.post; `/api/v1/openings/operations/{key}` chỉ opening.post | 404 kể cả key của command đã commit khác loại; không sinh key mới khi UNKNOWN; B19 mở rộng recovery |
| Owner/warranty DTO provisional | Runtime owner/consignment typed, quyền theo kho, warranty có chứng cứ/version | Dùng contracts.traceability; UNKNOWN khi thiếu chứng cứ; không suy hạn từ ngày nhập |
| `/openings/{id}/post` generic | OpeningPost có version/execution_key; COMPANY, kho chưa hoạt động, một batch tối đa 200 dòng | Có backend và operation lookup riêng; UI/import còn B06/B01/B16 |
| issue reserve/post, transfer dispatch/receive, return/move/adjustment post, count freeze/submit, import commit | Chưa có các routes này tại mốc B08 | Giữ planned; B01/B02/B03/B11/B12/B13/B14 bổ sung và regenerate sau tích hợp |

## Quyền, version và chống trùng đã review

| Họ API / nguồn code | Quyền server và scope | Version / idempotency |
| --- | --- | --- |
| `api/identity.py`, `application/identity.py`, `authorization.py` | Phiên live; IAM `iam.manage` / `role.manage` với MFA; grant theo kho/thời hạn; người duyệt grant khác requester/recipient | IAM chưa dùng CommandBus/Idempotency-Key/expected_version; không tự replay khi timeout. Refresh xoay token và phát hiện replay theo cơ chế riêng; B04/B19 tiếp nối |
| `application/master_data.py` | ENTITIES: master.read/write; partner.read/write; warehouse.configure; owner/agreement dùng partner.write; giá đọc cần price.read đúng kho | Mọi command danh mục yêu cầu UUID Idempotency-Key; PUT cần expected_version; authorization kiểm tra lại trước trả replay |
| `application/orders.py` | document.read và ownership/assignment; po.draft/so.draft; document.assign/cancel/approve; OPENING dùng opening.approve | CRUD/action dùng key; cập nhật/submit/decide/revise/cancel/close/assign dùng expected_version; approval gắn snapshot, cấm tự duyệt |
| `application/receipts.py`, `openings.py` | receipt.draft/post hoặc opening.draft/post; kiểm tra kho, nguồn, phiên và approval hiện hành | Key cho create/update/post; update/post có expected_version; post có execution_key; ACK cùng ledger/balance/audit/outbox transaction |
| `application/traceability.py` | stock.read và ownership.read/serial.read đúng kho; warranty.write cho append chứng cứ và quyền đọc nguồn | Warranty append dùng key/expected_version; ownership và tra cứu chỉ đọc, che tài nguyên ngoài scope |

Inventory ghi riêng required headers/body fields, Bearer, mã lỗi được khai báo và success chưa có schema.
Các trường này phản ánh OpenAPI, không thay thế kiểm thử quyền hoặc nguyên tử.

## Response lỗi và bằng chứng thành phần

- Error runtime gồm code/message/request_id, retryable và field_errors. Header X-Request-ID là UUID mới
  của request; header này khớp body Error. ACK replay thành công có request_id gốc trong body, không
  yêu cầu request_id gốc phải trùng header của lần HTTP mới. Cache-Control luôn no-store.
- 401 UNAUTHENTICATED có WWW-Authenticate: Bearer. Test mới gọi đủ **90 operations được bảo vệ**
  không có token, xác nhận từ chối trước khi chạm DB.
- 403 FORBIDDEN khi thiếu action; tài nguyên ngoài scope có thể 404 NOT_FOUND. Existing IAM/receipt/traceability
  tests kiểm tra kho, assignment, che giá và thu hồi quyền. B08 thêm HTTP thật qua TestClient + PostgreSQL:
  thiếu quyền → cấp grant → 201 → replay đúng body → 409 IDEMPOTENCY_MISMATCH → PUT → 409 STALE_VERSION →
  lookup unknown/command khác loại 404 → thu hồi grant → replay bị 403.
- Thiếu key/body/type: 422 VALIDATION_ERROR. DomainError chưa có mapping riêng mặc định trả **409**;
  không mặc định lỗi nghiệp vụ tracking nào cũng 422 theo ví dụ core. 503 DATABASE_NOT_READY là retryable;
  lỗi checksum/history migration làm ready 503 dù health 200.
- `test_errors_conform_to_design_and_never_echo_input` kiểm tra 422/404/500 và không lộ input/secret;
  suite domain hiện có kiểm tra stale, race, rollback và post/replay trên PG thật.

## Khoảng trống được giữ rõ

1. **13 success operations chưa có response_model đầy đủ** (xem `untyped_success` trong inventory):
   document generic, grants/roles, scan, receipt locations, một số IAM actions và append giá.
   B04/B05/B15/B19 nên thêm DTO khi sửa API của mình; chưa cam kết client codegen đủ các endpoint này.
2. Error 500 đã có handler chung, nhưng OpenAPI chưa khai báo 500 trên từng operation. B08 kiểm tra
   hành vi thực; đề xuất điều phối thêm metadata lỗi chung tại app/router khi chốt contract tổng.
3. IAM version/idempotency và operation lookup không đồng nhất các domain. Không đánh dấu hết TR03
   hoặc T02 là đạt từ test receipt; cần B04/B19 và B24/B26 xác nhận end-to-end.
4. API signatures có trong schema không chứng minh UI tồn tại, không chứng minh PG15/Windows/hosted CI đã chạy.
   Kết quả và NOT_RUN ghi riêng tại [bàn giao B08](../01_Tai_lieu/PHAN_CONG/BAN_GIAO/B08.md).

## B14 sau B13/B16 — 04/10/2026

Runtime hiện có 166 paths. [Reversal contract](../01_Tai_lieu/REVERSALS.md) dùng một transaction gốc,
source_version, plan do server dẫn xuất; post cần expected_version/execution_key/Idempotency-Key.
Lifecycle dùng routes documents/approval-requests chung; operation lookup riêng có envelope command/result.
Quyền adjustment theo cả hai kho với transfer/loss; count snapshot không lộ cho người đếm.
Core OpenAPI giữ mốc thiết kế; runtime/inventory đã tái sinh. Không suy nghiệm thu từ route tồn tại.
