# Bất biến và hợp đồng giao dịch

## Phạm vi và lớp bảo vệ

DDL cung cấp PK/FK, uniqueness, CHECK theo dòng, một số partial indexes và trigger append-only. DDL không phải engine nghiệp vụ hoàn chỉnh. Các ràng buộc liên bảng dưới đây phải được hiện thực trong service trong cùng transaction rồi kiểm thử PostgreSQL thật; không thể suy ra đã an toàn production chỉ vì tạo bảng thành công.

## Nhận dạng và số lượng

Sau migration 006, stock_item = product + lot hoặc serial + owner + consignment (nếu ký gửi). Owner bắt buộc, danh tính bất biến; sổ/số dư/reservation/kiểm kê giữ chiều này qua stock_item_id. Dữ liệu cũ UNCLASSIFIED không tự coi là hàng doanh nghiệp; chưa có workflow chuyển owner. Hàng ký gửi chỉ nhận/tồn đầu kỳ theo hợp đồng đúng kho/ngày; giữ chỗ/xuất/chuyển/đảo chưa được bật. Xem [TRACEABILITY.md](TRACEABILITY.md). NONE không có cả hai; LOT có lot đúng product; SERIAL có serial đúng product và không lot. Product SERIAL chỉ dùng số nguyên và stock_move.quantity_base = 1 cho mỗi serial. Một serial có tối đa một serial_position; balance hiện hữu của serial chỉ có một dòng lượng 1. UNIQUE NULLS NOT DISTINCT trên stock_item chặn hai danh tính NONE hoặc cùng lô do NULL. Serial được trả về sau khi xuất dùng lại cùng serial ID.

Base UOM và tracking không thay sau phát sinh. Product_uom cũ giữ nguyên factor, tạo revision mới và ngừng revision cũ; dòng phiếu giữ factor_snapshot. base_quantity phải bằng quantity * factor_snapshot một cách chính xác ở scale 6 và bội số độ chính xác UOM; từ chối nếu cần làm tròn ngoài quy tắc đã duyệt, không âm thầm round. Decimal truyền dưới dạng chuỗi API. So sánh lượng không dùng float.

## Sổ và số dư

stock_move luôn dương, có nguồn và đích khác nhau. Cho mỗi stock_item/location: on_hand = SUM(incoming) - SUM(outgoing). Chỉ cache balance cho STORAGE, RECEIVING, QUARANTINE, SHIPPING, TRANSIT. EXTERNAL, LOSS, OPENING là đối ứng, không có balance và không ràng buộc không âm. GROUP không được dùng trong move.

Tồn vật lý kho = STORAGE + RECEIVING + QUARANTINE + SHIPPING. Transit trình bày riêng. Lượng đủ điều kiện bán là STORAGE còn hạn, không bị khóa kiểm kê. Khả dụng = lượng đủ điều kiện - reservation còn mở của chính các chiều đó; không cộng các đơn vị khác loại. Expiry xét theo ngày nghiệp vụ hiện tại ở timezone doanh nghiệp, không theo ngày backdate do client chọn. Reserve hết hạn vẫn chiếm reserved cho đến khi release transaction hoàn tất. Posting phải kiểm tra lại hạn dùng, không tin cache available.

reserved = SUM(reservation.quantity - consumed - released). Tiêu thụ có reservation_consumption để truy vết. Release/consume phải khóa reservation và balance. Mọi luồng xuất từ vị trí đều bảo vệ reservation của phiếu khác. Hàng trả NCC có thể lấy từ QUARANTINE theo policy riêng, vẫn không dùng lượng đã giữ. Không reserve hàng TRANSIT, EXTERNAL, LOSS, OPENING hoặc GROUP.

## Thứ tự khóa chung

1. BEGIN; advisory transaction lock theo actor + idempotency key (hash ổn định); nếu đã có kết quả thì so hash rồi trả kết quả, không chạy lại.
2. Khóa chứng từ nguồn trước chứng từ thực hiện; trong mỗi cấp khóa theo UUID tăng dần, kiểm tra version/state. Runtime PO → RECEIPT cùng dùng thứ tự này ở create/sửa/duyệt/post và kiểm tra phụ thuộc khi hủy/đóng PO. Các workflow nhiều nguồn/chuyển/đảo chưa triển khai phải giữ thứ tự cấp nguồn này, không khóa phiếu con rồi quay lại nguồn.
3. Khóa stock_period của các kho theo UUID; kiểm tra ngày thuộc đúng một kỳ OPEN. Tạo/chỉnh kỳ cần khóa warehouse và chặn overlap. Close dùng cùng period lock.
4. Khóa location nguồn/đích theo UUID và kiểm tra count_location_lock. Freeze kiểm kê cũng phải khóa location trước snapshot. Mọi reserve/release/post/reconcile tác động vị trí cùng tuân thủ.
5. Runtime nhận hàng khóa product theo UUID trước khi tạo/khóa lot/serial và stock_item; mọi receipt có cùng product được tuần tự hóa ở đây. Workflow khác phải dùng cùng product lock hoặc một thứ tự khóa danh tính tương thích. Tạo stock_item bằng INSERT ON CONFLICT theo unique dimensions, sau đó SELECT FOR UPDATE; giữ owner/hợp đồng trong khóa danh tính.
6. INSERT balance 0 bằng ON CONFLICT DO NOTHING rồi khóa balance theo location_id/stock_item_id; khóa reservation theo UUID. Worker expiry và các lệnh hủy tuân cùng thứ tự.
7. Kiểm tra toàn bộ dòng trước ghi: kho/product/lot/serial phù hợp, quyền, tồn, lượng nguồn/đã trả/đã chuyển, UOM, khóa kỳ, approval revision. Không gọi HTTP/in máy in trong DB transaction.
8. Ghi inventory_transaction, stock_move, balance, reservation, serial_position, tiến độ document, audit, outbox và idempotency response trong một transaction. COMMIT xong mới trả thành công.

execution_key unique theo document là hàng rào thứ hai chống post lại. Giữ idempotency key/hash/status bền vững cho mọi command; expires_at chỉ giới hạn giữ chi tiết response, không cho tái sử dụng key. Bản cơ sở chưa có job purge. Cùng key khác hash => 409. Transaction thất bại rollback toàn bộ. Retry deadlock có giới hạn và jitter với cùng key/payload; nếu hết budget trả lỗi retryable. GET operation trả NOT_FOUND không có nghĩa một request cũ chắc chắn chưa chạy; gửi lại chỉ cùng key và execution_key, không tạo mới.

## Liên kết chứng từ và từng phần

Mỗi move.line phải thuộc transaction.document và cùng product/base UOM với stock_item. Receipt source_line phải là PO, issue là SO; customer return tham chiếu ISSUE đã post, supplier return tham chiếu RECEIPT đã post. Khóa dòng nguồn để tổng posted quantity của các child không vượt lượng nguồn. DRAFT không làm giảm remaining; tiến độ từ các lần posted hợp lệ có xét reversal. Nguồn có thể bỏ trống với luồng độc lập được policy cho phép; hàng trả không nguồn cần quyền ngoại lệ.

TRANSFER có source warehouse, destination warehouse và một TRANSIT location duy nhất không dùng lại. DISPATCH chỉ source -> transit, ARRIVE chỉ cùng transit -> destination. Nhận từng phần không tự xóa thiếu. Mất/hỏng transit dùng ADJUSTMENT tham chiếu TRANSFER, quyền phê duyệt của hai kho và kiểm soát. Tổng nguồn + đích + transit bảo toàn trừ nghiệp vụ mất/hỏng có duyệt.

Duyệt gắn document version và snapshot policy. Thay dòng/hàng/lượng/đích sau duyệt vô hiệu approval và giải phóng reservation liên quan trong transaction trước khi submit lại. Audit không thay thế version. Hai quyết định cạnh tranh cùng bước phải khóa request/step và chỉ một thành công.

## Kiểm kê, đảo và bất biến lịch sử

Freeze vị trí chỉ khi không còn reservation mở. Khóa vị trí áp dụng nhận, xuất, move, reserve, transfer và import opening; chỉ count adjustment của chính phiên được phép bypass sau phê duyệt. Đếm mù không trả snapshot_quantity. Hàng ngoài snapshot phải thêm count_line snapshot 0, kể cả SKU/lô mới đã xác minh. Người duyệt khác creator/requester và tất cả counters. Post adjustment + count POSTED + release locks nguyên tử.

Đảo v1 áp dụng toàn bộ một inventory_transaction, đổi nguồn/đích cùng stock_item/lượng, unique reverses_transaction_id và reverses_move_id. Nếu hàng đã đi tiếp hoặc bị giữ thì chặn đảo, dùng chứng từ bù sau phê duyệt; không xóa sửa ledger. Không cho đảo một reversal; xử lý tiếp bằng phiếu bù có trace. Không tự khôi phục reservation cũ sau đảo xuất; nếu muốn giữ lại phải tạo reservation mới có kiểm tra. PO/SO remaining được tính từ net posted quantities; hàng trả là nghiệp vụ riêng và không tự mở nhu cầu mua/bán đã hoàn tất.

## Mở rộng

Modules sở hữu bảng: master, iam, documents, inventory, fulfillment, approval, counting, operations, extension. Service khác gọi application interfaces, không tự ghi balance/ledger. Type mới phải có validator, state machine, quyền, API, tests, migration và báo cáo tương ứng. attributes JSONB chỉ lưu thuộc tính mô tả theo custom_field_definition, không đưa tồn/giá lõi/quyền vào blob. Không có plugin chạy mã tùy ý từ DB. Outbox events có version; consumer idempotent. Multi-company/3PL/ghi sổ offline chưa nằm trong schema, cần ADR và migration, không chỉ thêm một cột company_id.

Ngoại lệ có chủ đích từ revision 009: `document.attributes.receipt_plan` là namespace nội bộ của receipt service
cho kế hoạch tracking/vị trí trước duyệt; approval snapshot giữ toàn bộ namespace. Số lượng chuẩn vẫn lưu
ở document_line; tồn/giá/quyền không chuyển vào JSON. Custom-field API tương lai phải cấm ghi namespace này.
Quyết định và giới hạn runtime ở [RECEIVING.md](RECEIVING.md).
