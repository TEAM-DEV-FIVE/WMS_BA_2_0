# Soạn hàng và đóng kiện — B10

Runtime triển khai tại `agent/b10-fulfillment`, trên nền release 016. Migration mới
[017_b10_fulfillment.sql](../migrations/017_b10_fulfillment.sql) được người dùng cho phép
sau khi đồng bộ commit tổng `1a17cc5`. PostgreSQL là nguồn dữ liệu chính thức.

## Luồng và lượng

1. Duyệt SO, tạo/duyệt ISSUE và giữ hàng theo B02. Nếu người soạn chỉ có vai trò PICKER,
   giao quyền xem **cả SO và ISSUE trước khi duyệt** bằng document assignment hiện có.
2. Giao nhiệm vụ từ một reservation: `target_quantity` là lượng cơ sở giao soạn.
   `OPEN → PICKING → DONE`; có thể xác nhận trực tiếp từ OPEN. Xác nhận một lần với lượng
   thực soạn dương không vượt lượng giao; thiếu một phần ghi lượng thực và lý do.
   Không có hàng dùng `reject` để chuyển CANCELLED. Nhiệm vụ khác có thể nhận phần thiếu.
3. Tạo kiện DRAFT từ một hoặc nhiều nhiệm vụ DONE, chốt sang PACKED. Nguồn
   document line/stock item/owner/lô/serial/vị trí lấy từ reservation, không nhận tùy ý từ client.
   Tổng lượng trong kiện đang hoạt động không vượt lượng đã soạn chưa xuất.
4. Xuất hàng bằng API/UI B02. Nếu reservation có nhiệm vụ đang hoạt động, chỉ xuất lượng
   đã chốt kiện. Server phân bổ theo UUID dòng kiện tăng dần; xuất từng phần được hỗ trợ.
   `fulfillment_consumption` liên kết từng dòng kiện với `reservation_consumption → stock_move`.
5. Muốn giải phóng, sửa lại/hủy/đóng phần còn lại của ISSUE: hủy phần kiện chưa xuất rồi
   hủy nhiệm vụ còn hoạt động trước. Giữ nguyên dòng kiện, lượng đã pick/đã tiêu thụ và trace.
   Không sửa hay xóa sổ để hủy phần còn lại. Đổi nội dung kiện bằng hủy kiện và tạo mã mới.

Picking/packing **không ghi stock_move, không đổi on_hand hoặc reserved**. B02 `issue.post`
mới tiêu thụ reservation, giảm cả on_hand/reserved và ghi sổ một lần. Ví dụ tồn 10, giữ 5,
soạn/đóng 5: vẫn 10/5; xuất 3: còn 7/2. Các reservation chưa dùng fulfillment tiếp tục hỗ trợ
luồng xuất trực tiếp B02; hủy toàn bộ nhiệm vụ cũng trả về luồng đó.

Chỉ COMPANY được xuất theo chính sách B02/B09 hiện hành. Không hỗ trợ xuất thương mại ký gửi,
chuyển chủ hoặc tự phân loại UNCLASSIFIED. Kiểm tra lại approval snapshot, expiry giữ chỗ/lô,
UOM, vị trí STORAGE và cây Zone/Rack/Bin đang hoạt động, khóa kiểm kê, serial và số dư hiện tại.
Hủy logic vẫn thực hiện được khi hàng đã hết hạn hoặc bị khóa kiểm kê.

## Contract HTTP

Prefix `/api/v1/fulfillment`. Xem [OpenAPI runtime](../05_API/openapi_runtime.json).

| Route | Nội dung |
|---|---|
| GET `/` | ISSUE theo warehouse/status, cursor UUID `after`, `limit` 1–200 |
| GET `/{document_id}` | version ISSUE, nguồn SO, reservations, tasks, packages, actions hiện tại |
| GET `/{document_id}/assignees` | Người còn hoạt động, có pick.confirm và quyền xem ISSUE/SO; cursor UUID |
| POST `/{document_id}/picks` | `reservation_id`, `assigned_to`, `quantity_base` |
| POST `/{document_id}/picks/{entity_id}/assign` | Giao lại `assigned_to` khi OPEN/PICKING |
| POST `/{document_id}/picks/{entity_id}/start` | Bắt đầu soạn |
| POST `/{document_id}/picks/{entity_id}/confirm` | `quantity_base`, `location_code`, `item_code`, `trace_code` |
| POST `/{document_id}/picks/{entity_id}/reject` | Không có hàng; giữ reservation cho xử lý tiếp |
| POST `/{document_id}/picks/{entity_id}/cancel` | Hủy nhiệm vụ sau khi hủy kiện còn lượng |
| POST `/{document_id}/packages` | `code`, `lines[{pick_task_id,quantity_base}]` |
| POST `/{document_id}/packages/{entity_id}/seal` | Chốt kiện DRAFT |
| POST `/{document_id}/packages/{entity_id}/cancel` | Hủy phần chưa xuất; giữ trace đã xuất |
| GET `/operations/{key}` | ACK của chính actor, kiểm tra lại quyền và nguồn hiện tại |

Mọi POST cần `Idempotency-Key: UUID`, `expected_version` của **ISSUE** và `reason`.
Thao tác trên task/package đã tồn tại còn cần `entity_version`. Lượng là chuỗi Decimal,
tối đa 6 số thập phân và phải đúng độ chính xác UOM cơ sở. Scan SKU hoặc barcode đang hoạt động;
barcode chỉ kiểm tra danh tính sản phẩm, **không tự nhân hệ số UOM**. `trace_code` phải khớp
lô/serial reservation; hàng không theo dõi truyền null.

ACK `FulfillmentResult` chứa OrderResult ISSUE và `entity_id/entity_kind/entity_status/entity_version`,
`assigned_to` tại thời điểm ghi lệnh, `quantity_base` thực pick (null đối với package). Lịch sử phân công
không mất khi giao lại task; tra ACK tạo task cho người khác vẫn cần quyền document.assign ban đầu.
Mọi mutation tăng ISSUE version nhưng không
đổi nội dung approval snapshot. POST create trả 201, action trả 200. Cùng key/nội dung trả ACK cũ
sau kiểm tra quyền hiện tại; key khác dùng version cũ bị STALE_VERSION.

Quyền `pick.confirm` theo kho áp dụng cho soạn/đóng kiện. Chỉ người được giao được start/confirm/reject.
Giao cho người khác, giao lại hoặc hủy nhiệm vụ của người khác cần `document.assign`;
không tự mở rộng quyền xem chứng từ cho người được giao. Trang assignees có thể rỗng nhưng
vẫn có next_after do lọc theo quyền hiện tại trên trang user được quét.

## Transaction, audit và nâng cấp

CommandBus kiểm tra quyền trước cả replay. Thứ tự khóa: SO → ISSUE → warehouse SHARE →
(period UPDATE khi post) → location/ancestor và EXTERNAL theo UUID → product/identity/balance →
reservation. Khóa ISSUE tuần tự hóa mọi task/package, release/cancel/revise/post cùng phiếu.
Khóa product/balance là hàng rào chung với B02/B03; không dùng mutex Python.

Audit action và outbox event `fulfillment.pick.{create,assign,start,confirm,reject,cancel}.v1`
hoặc `fulfillment.package.{create,seal,cancel}.v1` dùng ACK làm payload, aggregate_id là ISSUE.
Audit lưu actor/warehouse/reason/request_id. ACK, progress versions, audit và outbox cùng transaction;
khi post còn gồm ledger/balance/reservation/serial/package consumption. Không cần consumer mới;
B18/B20 phải dùng key event ID hoặc `(event_type, aggregate_id, entity_id, entity_version)` nếu
thêm consumer. Không gọi máy in, network hoặc file I/O trong transaction.

017 chỉ thêm cột và bảng, không sửa 001–016/seed/policy. Tổng runtime: **79 bảng, 530 cột, 169 FK**.
NULL `pick_task.target_quantity`, `package.status` và `package_line.pick_task_id` nhận diện legacy;
không backfill lượng/nguồn giả. Legacy chưa đủ nguồn bị chặn để đối soát riêng; chưa có công cụ adoption.
`fulfillment_consumption` append-only bằng trigger. Model/dictionary/DBML `fulfillment_extension*`
và [SQL đối soát](../02_CSDL/reconcile_fulfillment.sql) đi cùng migration.

## Desktop và hook B18/B19

Tab **Soạn hàng / đóng kiện** có danh sách ISSUE theo trang, chọn reservation/người soạn,
bảng nhiệm vụ/version, ô quét và bảng kiện. Tất cả lệnh chạy HTTP worker; Tk chỉ ở main thread.
ACK phải khớp warehouse/document/entity/kind/version/trạng thái mới gỡ lệnh đang chờ.
Response cũ của user/kho/session bị bỏ. Timeout, phản hồi sai và quyền bị thu hồi sau timeout
giữ nguyên key/body để gửi lại hoặc tra ACK; không tự tạo key thay thế.

B18 gọi trên Tk thread:

```python
view.scan("location_code", code)  # hoặc item_code, trace_code
view.confirm_pick()              # chỉ gửi command, chờ server xác nhận
```

Enter tại ô vị trí chuyển sang SKU, Enter tại SKU chuyển sang lô/serial; Enter tại ô cuối
gửi xác nhận. Adapter không tự tăng lượng hay chuyển trạng thái local. Từ worker thiết bị,
B18 phải chuyển callback vào hàng đợi/main loop; không gọi Tk trực tiếp.

Lệnh chưa rõ kết quả hiện giữ trong **RAM theo user/kho**, không tồn tại qua đóng app.
B19 sẽ nối journal SQLite003; B10 không sửa SQLite001/002, không lưu credential.
Không có in tem/vận đơn hay tích hợp thiết bị thật trong B10.
