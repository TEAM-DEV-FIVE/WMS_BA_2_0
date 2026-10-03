# Kiểm định, cất hàng và di chuyển nội bộ — B03

Module mở rộng nền `06041b7`; PostgreSQL là nguồn dữ liệu chính thức. Desktop chỉ gọi API.
Luồng đã triển khai: nhận thực tế → quyết định đạt/lỗi → phiếu INTERNAL_MOVE → duyệt → ghi sổ.
Di chuyển giữ nguyên stock_item (product/lô/serial/owner/consignment), giảm nguồn và tăng đích
cùng một lượng, trong cùng kho. Không có transfer liên kho, picking hoặc chuyển quyền sở hữu.

## Nguồn và quy tắc chất lượng

- Nguồn là `stock_move` thuộc transaction RECEIVE của RECEIPT, chưa bị đảo; không dùng lượng PO
  hoặc nháp receipt làm lượng đã nhận. Mỗi lần post receipt tạo nguồn kiểm định riêng.
- Quyết định ACCEPT/REJECT chỉ ghi bằng chứng; không ghi ledger hay tự tăng lượng khả dụng.
  Tổng đã quyết định không vượt lượng thực nhận của nguồn. Lượng cơ sở dùng Decimal/chuỗi,
  đúng precision UOM; serial nguyên lượng 1.
- Quyết định dùng version của receipt. Ghi thành công tăng version receipt; mọi form receipt
  đang giữ version cũ phải tải lại. Snapshot duyệt không bao gồm version tiến độ nên phần nhận
  còn lại vẫn dùng được approval hợp lệ sau khi tải lại.
- Nguồn RECEIVING/QUARANTINE cần quyết định khớp stock_item và đúng vị trí lần nhận.
  ACCEPT chỉ đi STORAGE, REJECT chỉ đi QUARANTINE. Tổng MOVE đã post của một quyết định
  không vượt lượng quyết định, kể cả khi nhiều phiếu đã được duyệt đồng thời.
- STORAGE có thể chuyển sang STORAGE hoặc QUARANTINE, không cần quyết định từ receipt.
  Nguồn/đích phải khác nhau. Hàng đã cách ly do một lần chuyển từ STORAGE chưa có policy
  tái kiểm để xuất lại STORAGE trong B03; không cho mượn quyết định của lần nhận khác.
- Hàng nhận trực tiếp tại QUARANTINE có thể được ACCEPT rồi cất sang STORAGE. Nếu REJECT
  ngay tại QUARANTINE thì hàng đã ở đúng nơi; không tạo MOVE cùng nguồn/đích để tiêu hao
  quyết định. `remaining_base` của quyết định là lượng chưa MOVE, không phải lệnh bắt buộc chuyển.
- Chỉ hỗ trợ owner COMPANY; hàng ký gửi hoặc UNCLASSIFIED trả `OWNERSHIP_UNSUPPORTED`
  đến khi B09 có policy. Không suy owner từ ghi chú hoặc trộn các chủ hàng.

## API và lệnh

Prefix `/api/v1`. Mọi lệnh ghi yêu cầu Bearer token, `Idempotency-Key` UUID, lý do;
server kiểm tra quyền hiện tại trước cả replay. Trang dùng `after` UUID, `limit` 1–200
(mặc định 50); không có tải ngầm toàn bộ dữ liệu.

| Route | Hợp đồng và quyền |
| --- | --- |
| `GET /quality/sources?warehouse_id=…` | Các lần nhận thực tế và lượng còn kiểm; `document.read`, scope/assignment của receipt |
| `GET /quality/sources/{receipt_move_id}` | Nguồn/version, lịch sử quyết định phân trang, lượng đã/còn MOVE, actor/time/reason, allowed_actions |
| `POST /quality/sources/{receipt_move_id}/decide` | `{expected_version, accepted_base, rejected_base, reason}`; `quality.decide`; tổng lượng >0 |
| `GET /moves?warehouse_id=…` | Danh sách INTERNAL_MOVE; lọc status, cursor; scope document.read |
| `POST /moves` | Tạo nháp `MoveInput`, quyền move.draft; trả 201 |
| `GET /moves/{id}` | OrderView cùng typed plan nguồn/đích/stock/decision và approval history |
| `PUT /moves/{id}` | `MoveUpdate = MoveInput + expected_version`; chỉ nháp/từ chối và may_edit |
| `GET /moves/stock?warehouse_id=…` | stock.read; stock_item, lô/serial/owner, nguồn, lượng theo bảng dưới |
| `GET /moves/locations?warehouse_id=…` | Các vị trí hoạt động trong kho; cây/khóa kiểm lại tại submit/approve/post |
| `POST /moves/{id}/post` | `{expected_version, execution_key, reason}`; move.post; toàn bộ phiếu đã duyệt |
| `GET /moves/operations/{key}` | ACK move.post của chính actor; kiểm tra lại quyền move.post và quyền xem phiếu |

`MoveInput` gồm `warehouse_id`, `business_date`, `reason`, `lines` (1–200).
Mỗi dòng gồm `stock_item_id`, `source_location_id`, `destination_location_id`,
`quantity_base` (chuỗi dương), `quality_decision_id` (có thể null nếu nguồn STORAGE).
Không nhận owner/product/UOM mới trong payload để đổi danh tính.

Submit/revise/cancel dùng `POST /documents/{id}/{action}`; approve/reject dùng
`POST /approval-requests/{id}/decide` của kernel hiện có. Phiếu mới theo
`DRAFT → SUBMITTED → APPROVED → COMPLETED`; từ chối/sửa lại/hủy theo state machine chung.
Không hỗ trợ đóng thiếu hoặc post một phần INTERNAL_MOVE. Nháp không chiếm lượng quyết định
hay reservation. Đích và quality decision nằm trong approval snapshot; đổi sau duyệt bị chặn.

ACK quyết định gồm receipt id, receipt_move_id, warehouse_id, version, decision_ids, request_id,
status DECIDED. ACK move.post gồm id/number/kind/warehouse/status/version, transaction_id,
request_id. Cùng key/cùng payload trả ACK ban đầu; khác payload trả IDEMPOTENCY_MISMATCH.
Execution key theo document chống post lại với key mới; khác actor/nội dung trả EXECUTION_MISMATCH.
NOT_FOUND khi tra ACK chưa khẳng định request cũ chưa commit: chỉ retry cùng key/body/execution key.

Các lỗi chính: STALE_VERSION, STALE_APPROVAL, SELF_APPROVAL, SOURCE_EXCEEDED,
SOURCE_MISMATCH, QUALITY_REQUIRED, INSUFFICIENT_STOCK, RESERVATION_CONFLICT,
PERIOD_CLOSED, LOCATION_FROZEN, INVALID_LOCATION/INVALID_TREE, LOT_EXPIRED,
TRACKING_MISMATCH, SERIAL_POSITION_CONFLICT, OWNERSHIP_UNSUPPORTED.

## Lượng và helper công khai

`apps/server/application/move_safety.py` nhận connection đang trong transaction của caller;
không commit, không tự cấp quyền, không đổi owner.

| Helper | Trách nhiệm |
| --- | --- |
| `movable_quantity(on_hand, reserved, frozen=False)` | max(0, on_hand-reserved), bằng 0 khi freeze; lượng vật lý chưa giữ, không phải lượng bán |
| `stock_availability(on_hand, reserved, location_kind, expires_on, business_today, frozen=False)` | Trả `(eligible, available)`: chỉ STORAGE còn hạn, không freeze; available trừ reservation |
| `lock_open_period(connection, warehouse_id, business_date)` | Warehouse SHARE, khóa period UPDATE; ngày phải thuộc đúng một kỳ OPEN |
| `location_tree(connection, warehouse_id, location_ids, lock=False)` | Collection UUID; thu thập/khóa tổ tiên theo UUID, kiểm lại cây, kho, active, kind/depth và freeze |
| `check_reservations(connection, stock_item_id, location_id, reserved)` | Khóa reservation theo UUID, xác nhận tổng quantity-consumed-released khớp balance.reserved |

`business_today` lấy từ clock server theo business_timezone, không lấy business_date có thể
backdate của phiếu. Hết hạn reservation không tự giải phóng lượng. Không cộng lượng khác UOM
hoặc chủ hàng với nhau. Policy tiêu thụ theo owner do caller/B09 chịu trách nhiệm.

Stock lookup có `on_hand`, `reserved`, `movable_base` (chưa giữ về vật lý), `eligible_base`
(đủ điều kiện trước reservation), `available_base` (sau reservation), `frozen`.
Lookup chỉ là snapshot; posting kiểm tra lại danh mục, cây và toàn bộ điều kiện dưới khóa.
Một dòng ký gửi có thể có lượng vật lý/đủ điều kiện về vị trí nhưng B03 vẫn chặn lệnh theo owner.

Thứ tự khóa: actor/key → PO nguồn (UUID) → RECEIPT nguồn (UUID) → INTERNAL_MOVE →
warehouse SHARE → period UPDATE → toàn bộ location/tổ tiên (UUID) → product (UUID) →
lot/serial/stock_item → balances (location/stock_item) → reservation (UUID) → serial_position.
Quyết định chất lượng khóa cùng PO/receipt trước khi tính lượng đã quyết định.
Đơn vị đang di chuyển vào một nguồn khác trong cùng phiếu không được dùng để bù thiếu nguồn:
tổng lượng rời mỗi nguồn phải <= lượng chưa giữ trước phiếu.

Period close phải dùng cùng period lock; freeze phải khóa location trước khi snapshot/insert
count_location_lock. B03 đã thử tranh chấp bằng transaction PG thật theo giao thức này;
điều phối phải chạy lại qua API B13 khi module đó được tích hợp. B02 reserve/release/expiry,
B10/B11/B14 cần giữ thứ tự khóa chung, không tự ghi balance ngoài application transaction.

## Nguyên tử, migration và sự kiện

`013_b03_move_quality.sql` là revision phát triển riêng, chỉ chạy trên DB tạm. Điều phối đổi
sang số tăng tiếp khi tích hợp nếu cần; không đổi revision đã phát hành. 001–010 giữ nguyên.

- Bảng typed `wms.move_line`: document_line_id PK/FK, stock_item_id, source_location_id,
  destination_location_id, quality_decision_id nullable; indexes quality/stock.
- Seed policy INTERNAL_MOVE manager hoặc controller chỉ khi chưa có policy loại này;
  không ghi đè policy người dùng, kể cả policy inactive.
- Trigger giữ bất biến quality_decision. Followup pointer legacy chỉ được gán lần đầu;
  mọi followup thực tế được truy qua move_line + ledger, không chỉ pointer đầu tiên.
- Không backfill owner, ledger hoặc lượng. Fresh schema: 66 bảng, 445 cột, 134 FK.
  Model/dictionary/DBML bổ sung đi cùng revision; baseline model001 không sửa.

Posting ghi transaction MOVE, stock_move, +/- balance, serial_position, followup pointer,
document status/version, audit, outbox và idempotency ACK trong cùng transaction. Lỗi rollback
toàn bộ. Ledger không sửa/xóa. `decision_moved(connection, decision_id)` tính net lượng MOVE
chưa bị đảo; B14 vẫn phải kiểm tra phụ thuộc hàng đi tiếp khi xây reversal.

Event version 1: `quality.decide.v1`, `move.create.v1`, `move.update.v1`,
`move.submit.v1`, `move.decide.v1`, `move.revise.v1`, `move.cancel.v1`, `move.post.v1`.
Payload outbox chính là ACK; aggregate_id là receipt hoặc move. Actor/reason/request_id
được giữ ở audit_event (request_id cũng có trong ACK); không suy actor từ outbox payload.
Không có consumer mới, I/O hoặc external side effect; worker hiện giữ event chưa có handler
ở pending. B20 đăng ký consumer có version/dedup khi cần.

## Desktop và giới hạn vận hành

Hai tab mới: Kiểm định chất lượng và Cất hàng / di chuyển. Chọn kho, phân trang lần nhận,
quyết định, phiếu, tồn nguồn và đích; xem lô/serial/owner, lịch sử, lý do và action theo quyền.
Hiện tham chiếu quyết định được sao chép bằng UUID từ lịch sử sang dòng cất/chuyển; server
kiểm tra khớp nguồn. Mọi nút lưu/duyệt/post gọi command thật, không cập nhật tồn giả tại client.

HTTP chạy worker; Tk và hủy widget/variable ở main thread. Bỏ phản hồi phiên/người/kho cũ,
chống bấm lặp khi busy, không refresh/retry command tự động. Lệnh timeout giữ nguyên body/key
theo người+kho trong RAM; chỉ retry đúng lệnh hoặc tra ACK ghi sổ. Đăng xuất xóa dữ liệu form,
không đưa lệnh của người trước cho người sau. Không lưu password/TOTP/token xuống đĩa.
Client xác thực ACK command theo DTO/kho/nguồn hoặc phiếu; ACK sai cấu trúc hay quyền hiện tại
bị thu hồi khi replay không được coi là bằng chứng lệnh trước chưa commit, nên vẫn giữ lệnh cũ.
Recovery sau đóng ứng dụng chưa bền vững: B19 sở hữu SQLite003/journal chung; phải nối vào
module đó khi tích hợp. Kiểm chứng hiện tại là Linux/Xvfb; Windows/DPI thật chưa chạy.

## Nguồn nhận chuyển B11

ARRIVE của TRANSFER nay là nguồn quality.decide ở kho đích. INTERNAL_MOVE dẫn chiếu quyết định này khóa TRANSFER trước phiếu move, giữ nguyên owner/stock_item và nguồn bảo hành. Người nhận chỉ có quyền kho đích vẫn đọc được nguồn đã giao; không mở quyền kho nguồn. Hàng tốt nhận vào RECEIVING, hàng hỏng vào QUARANTINE, sau đó dùng đúng kiểm định/cất hàng B03. Xem [Chuyển kho](TRANSFERS.md).
