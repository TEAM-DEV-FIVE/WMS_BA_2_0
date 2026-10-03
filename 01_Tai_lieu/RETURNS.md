# Trả hàng có nguồn — B12

Hai luồng CUSTOMER_RETURN từ ISSUE đã ghi sổ và SUPPLIER_RETURN từ RECEIPT đã ghi sổ.
Mỗi phiếu trả tham chiếu một chứng từ nguồn; có thể chọn nhiều lần ghi sổ/lô/serial của nguồn đó.
Trả từng phần bằng nhiều phiếu; mỗi phiếu trả ghi sổ toàn bộ lượng đã được duyệt.
Không mở lại remaining của PO/SO và không dùng reversal cho trả vật lý.

## API và giao dịch

- `GET /api/v1/returns?kind=...&warehouse_id=...`, `GET /returns/{id}`: danh sách/chi tiết,
  lịch sử approval, dòng typed và nguồn. Danh sách dùng `after`/`limit`.
- `GET /returns/sources?kind=...&warehouse_id=...`: từng stock_move nguồn hợp lệ, nguồn phiếu/dòng,
  stock identity/owner/agreement, SKU/đơn vị/lô/serial, posted/returned/remaining; phân trang theo move UUID.
  Nguồn ký gửi hiện có `returnable=false` và `blocked_reason`.
- `GET /returns/locations?warehouse_id=...`: vị trí hoạt động để chọn; POST vẫn kiểm lại cây/kho/freeze.
- `POST /returns`, `PUT /returns/{id}`: `kind`, `source_document_id`, `business_date`, `reason`,
  `lines[{source_move_id,location_id,quantity_base}]`; PUT thêm `expected_version`.
  Lượng là chuỗi decimal dương đúng độ chính xác UOM cơ sở. Không nhận owner/stock_item do client tự gán.
- Lifecycle dùng `/documents/{id}/submit|revise|cancel|assignments` và
  `/approval-requests/{id}/decide`. Sửa chỉ khi nháp/từ chối; không đổi nguồn/loại/kho.
- `POST /returns/{id}/post`: `expected_version`, `execution_key`, `reason`.
  `GET /returns/operations/{Idempotency-Key}` đối chiếu ACK theo actor và quyền hiện tại.
  NOT_FOUND chưa xác nhận lệnh không chạy: chỉ gửi lại nguyên key/execution_key/body.

Mọi command có Idempotency-Key. Draft cần `return.draft` và quyền đọc nguồn; sửa/gửi cần creator/assignment.
Phê duyệt dùng `document.approve`, policy cùng SOD của nền; người ghi sổ cần `return.post` và quyền đọc
nguồn/phiếu trong kho. Approval snapshot giữ header, dòng, source metadata, move/location và policy cách ly.

Lượng còn trả = lượng move nguồn chưa đảo − các return move chưa đảo liên kết đúng source_move.
Nháp không trừ nguồn. Tổng mọi dòng cùng source_move được kiểm lại dưới khóa chứng từ nguồn.
Khóa theo ancestor SO/PO → ISSUE/RECEIPT → return → warehouse SHARE → period UPDATE →
location/tổ tiên theo UUID → product → lot/serial/stock identity → balance → reservation.
Source reversal phải tuân cùng khóa chứng từ nguồn; B14 chưa là dependency runtime của B12.

Return transaction, stock moves, balances, serial_position, trạng thái phiếu, audit, outbox và ACK cùng UoW.
Không cache balance EXTERNAL. Không sửa serial, owner, hợp đồng hay receipt bảo hành gốc.
Namespace sự kiện: `return.create.v1`, `return.update.v1`, `return.submit.v1`, `return.decide.v1`,
`return.revise.v1`, `return.cancel.v1`, `return.assign.v1`, `return.post.v1`; payload ACK có document ID,
kind, warehouse, status, version, request_id và transaction_id khi post. Không thêm consumer/I/O ngoài DB.

## Policy tồn và chất lượng

- Khách trả: EXTERNAL → QUARANTINE, serial dùng lại ID nguồn và lượng 1; phải chưa có vị trí/tồn vật lý.
  QC nhận thêm nguồn CUSTOMER_RETURN/RECEIVE. Quyết định QC và move cất hàng khóa cả chuỗi nguồn của return.
- Trả NCC: RECEIVING/STORAGE → EXTERNAL, hoặc QUARANTINE nếu policy cho phép.
  Kiểm `on_hand - reserved`, đồng thời đối soát reservation còn mở kể cả đã hết hạn chưa release.
  Lô hết hạn vẫn có thể trả NCC; không dùng công thức khả dụng bán để loại lượng vật lý.
  Luồng này không tạo giữ chỗ riêng trước post; lượng chỉ được bảo đảm sau kiểm tra/ghi sổ nguyên tử.
- `WMS_SUPPLIER_RETURN_QUARANTINE_ENABLED=false` là mặc định. Chỉ cấu hình `true` khi chính sách trả NCC
  từ cách ly đã được duyệt. `return.post` vẫn bắt buộc; cờ policy nằm trong approval snapshot nên thay cờ
  làm approval đang giữ không còn khớp, cần revise/duyệt lại. Không phải quyền bỏ qua QC để bán.
- Ký gửi/chưa phân loại bị chặn bằng `OWNER_POLICY_REQUIRED`, theo contract B09 chưa có policy trả/chuyển chủ.
  Không tự lấy COMPANY thay owner nguồn. Không mở return unlinked, RMA, sửa chữa hoặc công nợ.

## Desktop

Hai tab Khách trả hàng / Trả nhà cung cấp có nguồn/vị trí phân trang, lượng ròng, lý do, ngày trả,
sửa/gửi/duyệt/từ chối/hủy/ghi sổ, lịch sử approval và tra chứng cứ bảo hành của serial.
HTTP chạy worker, cập nhật/teardown Tk tại main thread. Đổi người/kho/phiên loại bỏ response cũ.
Yêu cầu chưa rõ kết quả giữ nguyên key/body theo người/kho trong RAM, có retry và tra ACK.
Đóng ứng dụng chưa có recovery bền vững B19; không lưu credential vào journal.

## Schema và kiểm chứng

Revision phát triển `018_b12_returns.sql` thêm `return_document` (nguồn phiếu) và `return_line`
(move nguồn/vị trí), tổng 2 bảng/5 cột/5 FK. Nền 001–014 giữ nguyên. Schema phát triển B12:
74 bảng/496 cột/153 FK. Điều phối chọn số release khi tích hợp; chỉ dùng PostgreSQL test riêng.
Seed approval chỉ thêm khi chưa có policy cho loại phiếu, không ghi đè policy vận hành đã chỉnh.

Test nghiệp vụ: `tests/foundation/test_returns.py`. Test presenter và Tk → HTTP → FastAPI → PG:
`tests/foundation/test_return_desktop.py`. Kiểm upgrade thêm prefix 014 có legacy ledger trong
`test_postgres.py`, giữ checksums/history/owner. Kết quả thực tế và giới hạn nghiệm thu ở
[bàn giao B12](PHAN_CONG/BAN_GIAO/B12.md).
