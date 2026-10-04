# Kiểm kê và kỳ kho — runtime B13

Runtime dùng PostgreSQL và CommandBus hiện có. Desktop chỉ gọi HTTP. Migration phát triển
[019_b13_count_period.sql](../migrations/019_b13_count_period.sql) nối sau 001–018; điều phối chốt
số release khi tích hợp. Không sửa revision cũ hoặc chuyển schema từ worktree vào DB vận hành.

## Kiểm kê

1. WAREHOUSE_MANAGER tạo phiên với ngày nghiệp vụ, lý do, danh sách vị trí và ít nhất hai người
   có `count.enter` tại mỗi vị trí. Scope và phân công cố định từ khi tạo; nếu phân công sai,
   hủy phiên rồi tạo lại. Các danh sách có phân trang và tìm theo mã/tên.
2. Freeze khóa kho/kỳ/vị trí theo giao thức hiện có, kiểm reservation còn mở kể cả đã hết hạn,
   chụp balance dương thành `count_line`, rồi tạo active location lock trong cùng transaction.
   STORAGE, RECEIVING, QUARANTINE, SHIPPING được hỗ trợ. Không kiểm kê vị trí GROUP/TRANSIT/đối ứng.
3. Người được phân công nhận DTO **BLIND**: danh tính SKU/owner/hợp đồng/lô/serial/vị trí,
   vòng kế tiếp và quyền thao tác. Không trả snapshot, lượng chốt, delta hoặc số đếm vòng trước.
   Điều này vẫn áp dụng nếu người đếm có thêm quyền quản lý/kiểm soát.
4. Mỗi vòng có số lượng, người đếm, thời gian, scan UUID và lý do. Không sửa/xóa observation.
   Vòng kế tiếp phải do người khác đếm; mỗi dòng cần hai vòng cuối liên tiếp khớp nhau trước submit.
   Lượng 0 hợp lệ; độ chính xác theo base UOM; serial chỉ 0 hoặc 1.
5. Hàng ngoài snapshot được thêm bằng SKU/chủ hàng/hợp đồng và mã lô/serial đã xác minh;
   tạo danh tính dưới product lock, snapshot 0, rồi đếm như dòng thường. Không chuyển chủ/hợp đồng
   của serial đã biết. Vị trí không có dòng hàng cần hai người xác nhận trống riêng.
6. Manager submit tạo ADJUSTMENT riêng và snapshot duyệt bất biến. Policy kiểm kê v1 bắt buộc
   **CONTROLLER → DIRECTOR**, hai actor khác nhau, khác creator/requester và mọi người được
   phân công đếm. Quyền mới `count.approve` không cấp rộng `adjustment.approve` cho DIRECTOR.
   Từ chối đưa phiên về COUNTED, giữ freeze và lịch sử; được đếm tiếp rồi gửi snapshot mới.
7. CONTROLLER dùng `adjustment.post` ghi sổ sau đủ hai quyết định. Recheck snapshot, kỳ, khóa
   của chính phiên, danh tính, UOM, reservation, balance và vị trí serial. Delta âm: physical →
   `WMS-COUNT-ADJUST`; delta dương: ngược lại. Stock move luôn dương, giữ nguyên stock_item.
   Serial đổi vị trí trong cùng scope được trừ ở chỗ cũ trước khi cộng chỗ mới; không sinh hai vị trí.
8. Ledger, balance, serial_position, document COMPLETED, count POSTED, release freeze,
   audit, outbox và hai lớp ACK cùng commit. Delta toàn 0 vẫn có transaction ADJUST để lưu lần
   thực hiện, không tạo stock_move lượng 0. Hủy trước POSTED chỉ giải khóa của phiên đó, có audit;
   không chặn hủy vì vị trí đã ngừng hoạt động hoặc đang được phiên khác khóa sau khi nháp được tạo.

Giới hạn mỗi phiên: 100 vị trí, 20 người/vị trí, 2000 danh tính tồn, 100 vòng/dòng. Freeze tính cả
cache rows lượng 0 khi kiểm giới hạn 2000 để chặn scope quá lớn. Chia phiên trước khi freeze.
Hạn dùng chỉ là danh tính/lịch sử vật lý ở kiểm kê: không coi hàng hết hạn là không tồn tại.
Owner UNCLASSIFIED hoặc hợp đồng không hợp lệ vẫn bị chặn; kiểm kê không thay thế chuyển chủ hàng.

## Kỳ kho

- `period.create` thuộc CONTROLLER, tạo khoảng ngày OPEN, khóa warehouse UPDATE rồi các kỳ
  theo UUID để ngăn overlap (kể cả kỳ CLOSED) qua API. Không có API sửa/rút ngắn khoảng ngày đã tạo.
- `period.close` khóa warehouse UPDATE rồi period; cùng hàng rào mà các writer giữ SHARE/UPDATE.
  Đối soát ledger/balance, reserved/reservation, serial_position; từ chối nếu còn phiên kiểm kê hoặc
  chứng từ kho trong kỳ chưa COMPLETED/CANCELLED. PO/SO không phải pending inventory transaction.
  Transfer được xét ở cả kho nguồn/đích. Chỉ đọc chứng từ pending, không lấy document lock sau period.
- Posting luôn kiểm đúng một kỳ OPEN theo business_date. Ngày nghiệp vụ có thể lùi về kỳ đang mở;
  `posted_at` dùng đồng hồ server. Kỳ đóng chặn ghi lùi ngày; replay ACK đã commit không chạy ledger lại.
- Mở lại gồm hai command: CONTROLLER `confirm-reopen`, rồi DIRECTOR có MFA `reopen` tham chiếu
  confirmation UUID. Xác nhận tăng version kỳ, hợp lệ 24 giờ, cần actor độc lập và quyền kiểm soát còn
  hiệu lực. Reopen đối soát lại và ghi audit; xác nhận cũ mất hiệu lực khi version thay đổi.

## Hợp đồng API

Tất cả endpoint dưới `/api/v1`, có bearer auth. POST cần UUID `Idempotency-Key`; mọi command sau
create cần `expected_version` và lý do. Lượng truyền chuỗi decimal. Schema đầy đủ được sinh trong
[OpenAPI runtime](../05_API/openapi_runtime.json); không thay trạng thái nghiệm thu từ route inventory.

| Nhóm | Routes |
| --- | --- |
| Phiên | GET/POST `/counts`; GET `/counts/{session_id}` |
| Kiểm kê | POST `/counts/{session_id}/{freeze,observe,extra,confirm-empty,submit,decide,post,cancel}` |
| Danh mục | GET `/counts/catalog/{locations,users,products,owners,agreements}` với warehouse_id, q, after, limit |
| Kỳ | GET/POST `/periods`; GET `/periods/{period_id}` |
| Kiểm soát kỳ | POST `/periods/{period_id}/{close,confirm-reopen,reopen}` |
| ACK | GET `/counts/operations/{key}` và `/periods/operations/{key}`, actor hiện tại + quyền hiện tại |

Read count tự chọn contract BLIND hoặc REVIEW theo quyền/assignment, không có cờ client để nâng
quyền xem snapshot. REVIEW gồm observation, quyết định và xác nhận vị trí trống. Mọi số liệu review
vẫn bị loại khỏi BLIND ở schema/API, không chỉ ẩn cột trên giao diện.

Post count thêm `execution_key`; cùng execution và cùng payload trả ACK cũ dù HTTP key mới.
Cùng HTTP key khác payload: IDEMPOTENCY_MISMATCH. Đã post nhưng khác execution/payload:
EXECUTION_MISMATCH. Phiếu ADJUSTMENT kiểm kê không đi qua lifecycle/approval transfer loss;
generic transfer-loss routes từ chối vì không có transfer loss parent.

Các lỗi nghiệp vụ chính: RECOUNT_REQUIRED, INDEPENDENT_COUNTER_REQUIRED, SELF_APPROVAL,
APPROVAL_REQUIRED, STALE_APPROVAL, STALE_VERSION, DUPLICATE_SCAN, LOCATION_FROZEN,
RESERVATION_OPEN, FREEZE_LOST, SNAPSHOT_CHANGED, SERIAL_POSITION_CONFLICT, OWNERSHIP_CONFLICT,
PERIOD_OVERLAP, PERIOD_CLOSED, DOCUMENT_PENDING, COUNT_PENDING, RECONCILIATION_FAILED,
CONTROLLER_CONFIRMATION_REQUIRED, MFA_REQUIRED.

## Giao dịch và migration

Thứ tự khóa count: command key → count_session → adjustment document nếu có → warehouse →
stock_period → location/ancestors theo UUID → product → lot/serial/stock identity → balance → reservation.
Period management không khóa chứng từ sau warehouse. `location_tree` có tham số nội bộ để count
service đi qua freeze của chính phiên; các engine khác vẫn từ chối mọi freeze. Không có DTO bypass.

Revision 019 thêm version kỳ; ngày/lý do phiên; lý do observation; scope; submission/decision bất biến;
xác nhận vị trí trống; execution ACK; xác nhận mở lại kỳ. Backfill legacy scope từ locks/assignments/lines,
ngày từ frozen_at hoặc adjustment document nếu có; draft cũ thiếu cả hai dùng ngày migration và nên
hủy/tạo lại với ngày nghiệp vụ xác minh. Không suy diễn approval mới từ trạng thái legacy SUBMITTED.
Policy ADJUSTMENT đã tùy chỉnh vẫn được giữ nguyên. Guard owner chỉ mở nhánh ADJUST ký gửi khi có
count session SUBMITTED, document APPROVED, đủ hai quyết định, active freeze và đúng delta/stock_item;
các đường issue/transfer/reversal ký gửi khác giữ nguyên hàng rào cũ.

Events dùng `count.{create,freeze,observe,extra,confirm-empty,submit,decide,post,cancel}.v1` và
`period.{create,close,confirm-reopen,reopen}.v1`, payload là ACK tương ứng, không có credential.
Aggregate ID là session/period. B13 không đăng ký consumer tự gọi I/O; B20 ghép registry theo nhu cầu.

## Desktop và phạm vi kiểm chứng

Tab “Kiểm kê / điều chỉnh” hỗ trợ phân công, chọn scope, đếm, hàng ngoài snapshot, xem vòng/lý do,
duyệt, ghi sổ và hủy. Tab “Kỳ kho” hỗ trợ tạo, khóa, xác nhận mở lại và mở lại. HTTP ở worker; Tk ở main
thread; kết quả bị loại nếu khác session generation/user/kho. ACK được validate scope/version/ID/execution
trước khi báo POSTED. Lệnh chưa rõ kết quả giữ nguyên payload/key theo actor/kho trong RAM; có tra ACK
và gửi lại đúng yêu cầu. B19 sở hữu journal bền và phục hồi sau restart, chưa được thay bằng bộ nhớ RAM.

Kiểm thử local dùng PostgreSQL tạm, HTTP thực và Tk/Xvfb. Windows UAT, thiết bị, tải 15 CCU, backup/DR
và nghiệm thu T01–T28 thuộc các đợt tương ứng, không được tuyên bố PASS từ bộ test thành phần B13.
