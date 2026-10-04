# Phiếu xuất và giữ hàng — B02

Module thực hiện SO đã duyệt → ISSUE → giữ FEFO → xuất từng phần → hoàn tất hoặc đóng phần còn lại.
Desktop dùng API thật; PostgreSQL lưu số liệu chính thức. Approval và command kernel dùng lại nền hiện có.
Đọc cùng [bất biến](INVARIANTS.md), [orders/approval](ORDERS_APPROVAL.md) và
[báo cáo B02](PHAN_CONG/BAN_GIAO/B02.md). Nội dung issue/reservation trong tài liệu này bổ sung
các giới hạn của tài liệu orders ở mốc trước B02; không tuyên bố nghiệm thu T01–T28.

## Dữ liệu và migration

Revision phát triển `migrations/012_b02_issue_reservation.sql` chỉ chạy bằng runner trên DB tạm riêng.
Điều phối chọn số release tăng tiếp khi tích hợp và chạy lại upgrade từ mốc tổng ngay trước merge.
Không sửa migration `001`–`010` hoặc lịch sử migration DB đã dùng chung.

- Thêm `wms.issue_document(document_id, source_order_id)`: PK/FK đến ISSUE, FK đến SO và index nguồn.
  Header phải cùng kho/khách hàng nguồn; service chỉ nhận SO APPROVED/PARTIAL có approval hợp lệ.
- Dòng ISSUE dùng `document_line.source_line_id`; một dòng cho mỗi dòng SO, lượng theo UOM cơ sở.
  Source link không đổi được qua API. Số lượng không nằm trong JSON.
- Giữ/tiêu thụ/giải phóng dùng bảng `reservation`, `reservation_consumption` và `stock_balance` có sẵn.
- Nếu chưa có bất kỳ policy ISSUE nào, seed một bước WAREHOUSE_MANAGER hoặc CONTROLLER.
  Không ghi đè policy đã chỉnh hoặc tự kích hoạt policy cũ đang inactive; vẫn kiểm tra SOD hiện hành.
- Không backfill ISSUE cũ thiếu nguồn đã xác minh. API nghiệp vụ trả `UNSUPPORTED_ISSUE`; dữ liệu cũ còn nguyên.
  Upgrade tests kiểm chứng header cũ và policy tùy chỉnh không bị thay đổi.
- Runtime gồm 66 bảng, 442 cột, 131 FK. Model/dictionary/DBML bổ sung nằm ở `02_CSDL/issue_extension*`.

## Contract cho API và module phụ thuộc

Tất cả đường dẫn dưới `/api/v1`. Lệnh ghi cần bearer token, `Idempotency-Key` UUID và `reason`.
Sau tạo, mỗi lệnh có `expected_version`; post thêm `execution_key` UUID.
Số lượng là chuỗi decimal dương, đúng độ chính xác UOM. Contract đầy đủ ở
[OpenAPI runtime](../05_API/openapi_runtime.json) và [DTO](../packages/contracts/issues.py).

| Method / route | Nội dung |
| --- | --- |
| `GET /issues?warehouse_id=&status=&after=&limit=` | Danh sách theo kho, phân trang keyset |
| `POST /issues` | `source_order_id`, `business_date`, `reason`, `lines[{source_line_id,quantity_base}]` |
| `GET /issues/{id}` | Header, approval, allowed_actions, dòng/tiến độ, mapping nguồn và reservation history |
| `PUT /issues/{id}` | Body tạo + `expected_version`, chỉ DRAFT/REJECTED |
| `GET /issues/{id}/reservation-plan?document_line_id=&quantity_base=` | Đề xuất FEFO, version phiếu, stock/location/owner/lô/serial/hạn dùng |
| `POST /issues/{id}/reservations/reserve` | Version, reason, `expires_at` tùy chọn, `lines[{document_line_id,stock_item_id,location_id,quantity_base}]` |
| `POST /issues/{id}/reservations/release` | Version, reason, `lines[{reservation_id,quantity_base}]` |
| `POST /issues/{id}/reservations/expire` | Version, reason; giải phóng phần mở đã hết hạn giữ |
| `POST /issues/{id}/post` | Version, reason, execution_key, `lines[{reservation_id,quantity_base}]` |
| `GET /issues/operations/{key}` | ACK đã commit của chính actor; `operation_status`, `command`, `result` |

Lifecycle dùng `POST /documents/{id}/submit|revise|cancel|close|assign` và
`POST /approval-requests/{approval_id}/decide` của orders. Không tạo một approval engine riêng.
ACK thường là `OrderResult`; ACK post thêm `transaction_id`, `source_order_id`,
`source_order_version`, `source_order_status`. Các version trên ACK là tại thời điểm thực hiện lệnh;
đọc lại phiếu để biết trạng thái hiện tại. Lookup hỗ trợ cả lệnh lifecycle ISSUE.

Ví dụ body post một phần từ reservation đã đọc qua API:

```json
{
  "expected_version": 4,
  "reason": "Giao đợt đầu theo SO",
  "execution_key": "10000000-0000-4000-8000-000000000001",
  "lines": [{
    "reservation_id": "20000000-0000-4000-8000-000000000001",
    "quantity_base": "3"
  }]
}
```

Các UUID/version trên chỉ minh họa cấu trúc, phải lấy ID thật từ response. Một lần post có thể chứa
nhiều reservation; chỉ tiêu thụ reservation thuộc chính ISSUE. Tối đa 200 dòng kế hoạch và 500 nguồn/lệnh.

## Quy tắc giữ và xuất

`remaining` của ISSUE/SO tính từ ledger hợp lệ và phần đóng thiếu; nháp không giảm remaining.
Reservation mở bằng `quantity - consumed - released`, kể cả đã quá `expires_at` nhưng chưa giải phóng.
Nhu cầu SO chưa giữ trừ giữ chỗ của mọi ISSUE con và reservation trực tiếp trên SO cũ.
Giữ không được vượt nhu cầu chưa giữ của dòng ISSUE hoặc SO, không chiếm phần phiếu khác.

FEFO sắp `expires_on` tăng dần, NULL sau cùng; UUID stock/location làm thứ tự ổn định khi bằng hạn.
Chỉ lấy STORAGE đúng kho, product/UOM/location active, không khóa kiểm kê, đúng tracking/owner.
QUARANTINE, vị trí blocked/inactive và lô quá hạn không hợp lệ. Hạn lô bằng ngày hiện tại vẫn hợp lệ;
ngày được tính theo `business_timezone` của server. Hàng bắt buộc expiry phải có hạn.
Serial cần đúng vị trí hiện hành và tồn 1; mỗi allocation/move/release serial đúng 1.

GET plan chỉ là đề xuất. Reserve tính lại dưới khóa DB và yêu cầu allocations xác nhận khớp hoàn toàn.
Thay đổi FEFO/khả dụng trả `FEFO_CHANGED` hoặc lỗi thiếu tồn/nhu cầu, không tự đổi nguồn.
Muốn giữ từng phần, người dùng chọn lượng nhỏ hơn rõ ràng; không tự giảm lượng khi thiếu hàng.
Hiện chỉ hỗ trợ COMPANY, không consignment. Stock ký gửi cùng SKU/vị trí không bù cho nhu cầu COMPANY.

Post kiểm tra lại quyền, assignment, approval/SOD snapshot, source, version, kỳ OPEN, freeze, expiry,
owner/tracking/serial và đủ lượng giữ. Tạo ledger STORAGE → EXTERNAL, giảm on_hand/reserved,
tăng consumed, tạo reservation_consumption, cập nhật serial_position và tiến độ nguồn/phiếu.
Không có move âm hoặc cập nhật/xóa ledger cũ.

Release vẫn dùng được khi hàng đã hết hạn hoặc danh mục bị inactive để không mắc kẹt giữ chỗ.
Expiry là lệnh rõ ràng; chưa có worker tự chạy. Hết hạn giữ không tự làm tăng available.
`revise`/`cancel` trước post giải phóng giữ chỗ cùng transaction; revise hủy hiệu lực approval.
Sau post một phần, dùng `close` để giải phóng phần giữ còn lại và ghi lượng đóng thiếu riêng.
Không sửa/hủy phần đã post. Dòng từng có lịch sử reservation giữ ID ổn định khi sửa;
không xóa dòng đó khỏi phiếu, có thể hủy phiếu chưa post và lập lại.

SO còn phiếu con chưa xử lý sẽ bị chặn hủy/đóng. Xử lý ISSUE con trước, tải lại SO rồi hủy SO chưa xuất
hoặc đóng SO PARTIAL. Không tự cascade hủy các ISSUE, không tự đảo phần đã xuất. Khi đóng ISSUE,
phần chưa giao vẫn còn là nhu cầu SO cho đến khi SO được đóng riêng hoặc lập ISSUE tiếp.

## Quyền, transaction và replay

Đọc theo `document.read`/scope kho. Lập/sửa/gửi/revise cần `issue.draft` và creator/assignment;
giữ/release/expire cần `reservation.manage`; post cần `issue.post`, cùng creator/assignment.
Approval dùng `document.approve`, hủy/đóng dùng `document.cancel`, assignment dùng `document.assign`.
Server kiểm tra quyền hiện tại ngay cả khi trả ACK replay/lookup; actor khác không đọc ACK của nhau.

Thứ tự khóa: command key → SO → ISSUE → warehouse → period nếu post → location UUID →
product UUID → stock identity UUID → balance location/stock → reservation UUID.
Allocate khóa mọi STORAGE hiện có trong kho, kể cả bin rỗng; mọi danh tính vẫn giữ chiều owner/hợp đồng.
Post khóa EXTERNAL trong cùng thứ tự location. Đây là khóa khá rộng để an toàn ở nền hiện tại,
chưa phải kết quả tối ưu hoặc benchmark 15 CCU. Freeze/move/picking/transfer sau này phải cùng thứ tự.

Ledger, balance, reservation, serial, trạng thái, audit, outbox và ACK thuộc cùng transaction kernel.
Failpoint tests gây lỗi sau các bước ghi để kiểm chứng rollback và retry lại cùng key.
Cùng key/body trả ACK cũ; key cũ/body khác bị chặn. Key HTTP khác nhưng cùng execution_key/actor/body
trả ACK execution cũ, không tạo move thứ hai. Execution key khác nội dung bị `EXECUTION_MISMATCH`.
`404` lookup không chứng minh request trước chưa chạy; chỉ retry cùng key và nguyên body/execution_key.

Audit/outbox dùng `issue.create/update/submit/decide/assign/revise/cancel/close/reserve/release/expire/post`;
event type thêm `.v1`, aggregate_id là ISSUE, payload là ACK như trên, gồm request_id.
Không thêm consumer factory hoặc I/O ngoài DB trong transaction. Consumer hiện hữu của nền outbox
tiếp tục áp dụng; consumer mới do nhánh sở hữu job và B20 ghép registry.

## Desktop và điểm nối B10/B19

Chọn chức năng **Giữ hàng / xuất kho**: tải kho → tạo từ SO → thêm lượng dòng → lưu/gửi/duyệt bằng
người có quyền khác → chọn dòng/nhập lượng → đề xuất FEFO → xác nhận giữ → chọn reservation/nhập lượng
→ xuất hoặc giải phóng. Danh sách phiếu có trang sau; dropdown nguồn lấy tối đa 100 SO mỗi trạng thái
APPROVED/PARTIAL và báo khi bị giới hạn. API có phân trang đầy đủ; dropdown chưa có tìm kiếm nguồn.

HTTP chạy trên worker, Tk chỉ cập nhật ở main thread. Response gắn sequence, user và session generation;
đổi user/kho/phiên hoặc đóng view thì loại response cũ. UI hiển thị partial và remaining từ máy chủ.
Khi timeout/mất kết nối/phản hồi không xác minh được, giữ lệnh `UNKNOWN`, khóa lệnh mới;
**Tra ACK** hoặc **Gửi lại đúng lệnh** dùng key/body gốc, không tự retry.
Nếu lệnh từng UNKNOWN, lỗi quyền/version ở một lần retry sau không xóa lệnh pending: lỗi đó không chứng minh
lần trước chưa commit. Chỉ ACK hợp lệ mới gỡ UNKNOWN; cần khôi phục quyền để xác minh khi quyền bị thu hồi.

B19 cần nối journal bền vững vào contract hiện có: method/path/body/key/execution_key, actor/kho,
trạng thái UNKNOWN và lookup. B02 giữ các lệnh này trong RAM, phân vùng theo user, không ghi token/secret;
đóng ứng dụng sẽ mất bản ghi pending. UI nhắc giữ cửa sổ để tra ACK. Không thay SQLite revision của B19.

B10 cần dùng reservation ID/remaining/stock/location/owner và khóa nguồn trước phiếu trước inventory.
Hiện B02 chặn release/revise/cancel/close/post nếu reservation liên quan có pick_task chưa CANCELLED;
package/downstream document cũng chặn sửa/hủy/đóng. Đây là hàng rào khi chưa ghép policy picking.
B10 phải review thay guard bằng quy tắc tiêu thụ/hoàn tất picking phù hợp, cùng transaction;
không bật post qua picking hoàn tất bằng cách bỏ kiểm tra giữ chỗ. B11/B12 dùng ledger/source links
và contract trên, không gọi SQL trừ kho tách rời command kernel. B09 bổ sung policy outbound ký gửi.
