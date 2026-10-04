# Ký gửi và hợp đồng owner B09

## Nghiệp vụ chạy được

Danh tính tồn là `(product_id, lot_id, serial_id, owner_id, consignment_id)`;
`stock_item_id` là khóa xuyên suốt ledger, balance, reservation và serial. Cùng SKU,
lô và vị trí vẫn có các balance riêng theo owner/hợp đồng. Không suy COMPANY từ
owner thiếu hoặc từ một dòng UNCLASSIFIED.

Nhập tồn đầu kỳ giữ quy tắc cutover hiện có: chỉ ghi đủ một phiếu trước lịch sử
kho, biên bản kiểm kê đã ký, duyệt độc lập CONTROLLER/DIRECTOR. Mỗi dòng nay nhận
`consignment_id` tùy chọn: COMPANY phải để null, CONSIGNOR bắt buộc hợp đồng đúng
owner/kho/ngày nghiệp vụ, đang hoạt động cùng đối tác. Lập, gửi duyệt, quyết định
duyệt và post đều kiểm tra lại. Bản duyệt lưu owner/hợp đồng cùng kế hoạch; thay
nội dung hoặc version danh mục sau duyệt làm bản duyệt cũ không còn hợp lệ.

Phiếu **Nhận ký gửi** là nhận giữ hàng theo hợp đồng, không có PO mua hàng và
không ghi nghĩa vụ thanh toán. Chọn chủ/hợp đồng, SKU, vị trí RECEIVING/QUARANTINE,
tracking, số lượng và chứng từ giao nhận. Phiếu có batch UUID duy nhất/kho, tối đa
200 dòng và ghi đủ một lần. Nhận nhiều đợt dùng các biên bản/batch thực sự riêng.
Không tạo batch mới để xử lý một lần gửi chưa rõ kết quả. Phiếu dùng kind RECEIPT,
operation RECEIVE và policy duyệt RECEIPT đang cấu hình; không thay policy khách
hàng. Quyền `receipt.draft` / `receipt.post`, người post là người lập/được giao;
creator không tự duyệt. Chủ ký gửi nằm trên từng dòng, không giả thành supplier
trên header. PO/SO vẫn COMPANY-only.

QC và cất/chuyển nội bộ giữ nguyên stock item/owner/hợp đồng. Chỉ cùng kho hợp
đồng, đúng nguồn quyết định QC, vị trí vật lý và lượng còn lại; không chuyển sang
EXTERNAL, SHIPPING hoặc kho khác theo đường này. Hợp đồng phải hợp lệ tại ngày
nghiệp vụ. Hàng hết hạn/cách ly và giữ chỗ vẫn tuân thủ B02/B03. Trigger mới chỉ
mở MOVE của INTERNAL_MOVE giữa STORAGE/RECEIVING/QUARANTINE cùng kho; outbound,
chuyển kho, đổi chủ và reversal ký gửi tiếp tục bị chặn ở DB khi chưa có policy.

SO/ISSUE/reservation chỉ cấp tồn COMPANY. Tồn ký gửi không bù thiếu tồn sở hữu;
không đổi owner trên move, balance, reservation hoặc trả hàng. Serial duy nhất
trên mọi owner, mọi vị trí; hai chủ không được cùng ghi nhận một serial vật lý.
Bảo hành giữ `receipt_move_id` của lần RECEIVE và chứng cứ riêng; chuyển nội bộ
không tạo lần nhận mới hay suy thời hạn bảo hành. Với nhận ký gửi không có supplier
PO, các trường supplier cũ có thể null; đây không phải thiếu nguồn receipt.

## API, UI và import

- `GET/POST /api/v1/consignment-receipts`, `GET/PUT /{id}`, `POST /{id}/post`,
  `GET /operations/{key}`. Payload nháp gồm warehouse_id, batch_key, business_date,
  delivery_reference, reason, lines. Dòng gồm product_id, quantity_base, owner_id,
  consignment_id, destination_location_id và tracking giống OPENING. Post gồm
  expected_version, execution_key, reason. HTTP Idempotency-Key và execution_key
  đều bất biến khi retry. Hash nháp COMPANY bỏ đúng trường consignment_id mới khi null để tương thích ACK trước B09; các trường cũ vẫn giữ nguyên. Chuyển trạng thái dùng các route documents/approval hiện có.
- `GET /api/v1/openings/owners` và `/consignment-receipts/owners`: danh sách chủ/hợp
  đồng theo kho, q/after/limit. Kiểm tra document.read và quyền lập phiếu tương ứng;
  không cần mở rộng quyền sửa danh mục. Endpoint không trả toàn bộ chứng cứ hợp đồng.
- RECEIPT theo PO và ký gửi có danh sách/UI riêng. Route PO receipt từ chối đọc/
  post nhầm loại với `CONSIGNMENT_RECEIPT_REQUIRED`. B05 vẫn quản lý owner/hợp đồng;
  B06 thêm selector có tìm kiếm/phân trang và cột chủ/hợp đồng. Màn Nhận ký gửi dùng
  cùng presenter inbound: HTTP chạy worker, callback Tk main thread, loại response
  phiên cũ, giữ nguyên UNKNOWN/ACK theo user/kho. B19 vẫn sở hữu recovery bền;
  yêu cầu chưa rõ kết quả hiện chỉ giữ trong RAM của lần mở ứng dụng.
- CSV mẫu `11_opening` v2 thêm `owner_code` bắt buộc, `consignment_code` bắt buộc
  với CONSIGNOR. Mapping runtime `b09.v2`; dry-run bind hash owner, agreement và
  partner, commit kiểm tra lại rồi gọi OpeningService cùng transaction. Import
  tạo DRAFT, không bỏ qua duyệt/post. Template 8 cột v1 được nhận theo đúng hợp
  đồng cũ COMPANY-only; parser nhận chính xác header v1 rồi bổ sung COMPANY rõ ràng.
  Header v2 thiếu owner bị lỗi. Workbook XLSX v1 hiện có được giữ nguyên và dùng
  đường tương thích này; ký gửi dùng CSV v2 hoặc XLSX có header v2 đúng mẫu.
  Job VALIDATED từ mapping b01.v1 phải validate lại, không dùng token commit cũ.
- Audit/outbox nhận ký gửi dùng namespace mới `consignment_receipt.*.v1`; create/update/submit/decide/revise/cancel/assign mang OrderResult, post mang OpeningPostResult (ID/number/kind/warehouse/status/version/request_id/transaction_id). Không có source_order_id trong ACK ký gửi. `receipt.*.v1` theo PO giữ nguyên contract. OPENING/QC/MOVE giữ events hiện có. Command/ACK ký gửi dùng `consignment_receipt.create/update/post`. Không thêm consumer hay I/O bên trong transaction; B20 chỉ đăng ký consumer mới khi có yêu cầu xử lý sự kiện này, dedup theo event_id + consumer name/version như kernel hiện tại.

## Contract cho các nhánh sau

| Luồng | Contract owner bắt buộc |
|---|---|
| Transfer B11 | Nguồn/đích giữ stock identity đầy đủ, owner/agreement trong snapshot; kiểm chính sách theo cả kho. Hợp đồng hiện chỉ một kho: từ chối ký gửi khi chưa có mô hình/policy chuyển kho. |
| Return B12 | Dẫn chiếu source move/line, lấy đúng owner/lot/serial/agreement nguồn. Không mặc định COMPANY hay tạo nguồn bảo hành khác. Ký gửi trả chủ cần policy cụ thể. |
| Count B13 | Dòng kiểm kê theo stock_item_id + location, hiển thị owner/agreement; tách 10 COMPANY và 5 CONSIGNOR dù physical=15. Chênh lệch chưa phân loại không trở thành COMPANY. |
| Reversal B14 | Dẫn chiếu move gốc và giữ owner; chưa mở reversal ký gửi trong guard hiện tại. Phải review phụ thuộc, agreement và ledger đối ứng trước khi mở. |
| Reports B17 | Physical tổng theo cùng SKU/tracking/UOM; owned chỉ COMPANY, consigned nhóm owner/agreement, UNCLASSIFIED riêng. Reserved/eligible/available phải tính theo đúng owner; không cộng UOM khác nhau. |
| Warranty | Giữ serial_id và receipt_move_id qua MOVE/transfer/return/classification; nếu thiếu chứng cứ trả UNKNOWN, không suy ngày. |

## Thiết kế phân loại legacy UNCLASSIFIED

Phần này là **thiết kế workflow** theo mục 3 brief B09, chưa phải endpoint phân loại
đang chạy. Migration 014 không sửa dữ liệu cũ và không nới chặn UNCLASSIFIED. Đối
soát `02_CSDL/reconcile_ownership.sql` vẫn báo các identity chưa phân loại. Không
dùng OPENING/RECEIVE giả hoặc sửa owner của stock item/ledger để xóa cảnh báo.

Workflow đề xuất có chứng từ `OWNERSHIP_CLASSIFICATION` riêng:

1. CONTROLLER lập hồ sơ theo kho, business_date, reason, danh sách stock_item_id
   UNCLASSIFIED, location_id, quantity, owner/agreement đích; dẫn chiếu kiểm kê đã
   ký, hợp đồng/hóa đơn nguồn, hash/chứng cứ tệp riêng B01 và snapshot số dư/version.
   Khoảng lượng xác minh phải khớp tồn thực còn lại. Dữ liệu chứng cứ thiếu vẫn
   ở UNCLASSIFIED; không đoán theo đối tác giao dịch gần nhất.
2. DIRECTOR hoặc người được cấp quyền phân loại riêng duyệt độc lập; creator ≠
   approver. Quyền draft/approve/post mới phải có trong ma trận đã review, mặc định
   không cấp cho RECEIVER, PICKER hoặc SYSADMIN. Sửa hồ sơ hủy hiệu lực snapshot
   và mọi quyết định cũ. Không dùng quyền sửa danh mục làm quyền đổi chủ.
3. Post khóa chứng từ, warehouse/period, mọi vị trí, product, identity và balance
   theo UUID ổn định; kiểm kỳ mở, count freeze, số dư/version, serial và nguồn chứng
   cứ. Không cho phân loại lượng đang giữ chỗ/pick/transfer hoặc có dependency mở.
   Kiểm lại grant hiện tại, owner/hợp đồng và đủ các bước duyệt trong transaction.
4. Tạo identity đích mới với nguyên SKU/lot/serial. Thêm transaction CLASSIFY,
   hai move mới và typed liên kết cặp source/target, qua vị trí đối ứng CLASSIFICATION
   chuyên dụng. Leg nguồn giảm UNCLASSIFIED tại vị trí vật lý; leg đích tăng đúng
   owner tại cùng vị trí; không tính là mua/bán/nhận mới. Hai dòng chứng từ mang
   đúng owner của mỗi leg, tổng lượng vật lý/lot/serial trước-sau không đổi. Giảm
   balance nguồn trước tăng đích để serial chỉ có một vị trí; cập nhật last_move
   của serial nhưng giữ receipt_move_id trong warranty. Không UPDATE/DELETE bất kỳ
   stock_move, identity hoặc receipt lịch sử nào.
5. Guard DB chỉ cho leg UNCLASSIFIED đã liên kết hồ sơ CLASSIFY được duyệt, đúng
   quantity/identity/location; không mở quyền chung để ghi UNCLASSIFIED. Ledger,
   balance, serial_position, audit, outbox và ACK cùng transaction. Request/execution
   replay kiểm payload/actor như inbound. Reversal phải là hồ sơ ngược được duyệt,
   có source classification, và bị chặn khi tồn đích đã có dependency.
6. Đối soát xuất hồ sơ trước/sau: physical delta=0, reserved delta=0, owner delta
   đúng cặp, mọi balance khớp ledger, serial một vị trí, warranty giữ nguồn; lưu
   actor, approver, chứng cứ, request_id và transaction_id. Báo cáo lịch sử vẫn hiện
   UNCLASSIFIED ở thời điểm trước CLASSIFY; báo cáo hiện tại dùng balance mới.

Điều kiện trước khi triển khai/chạy workflow: chốt quyền và người chịu trách nhiệm
chứng cứ với chủ kho; cấp migration forward riêng; review guard/schema/model/
OpenAPI cùng nhau. Kiểm thử bắt buộc: migrate 001–010 có ledger cũ; phân loại một
phần/nhiều owner; thiếu chứng cứ/SOD/thu hồi quyền; frozen/period/dependency; stale
snapshot; concurrent classify/post/reserve; rollback sau từng leg/audit; replay;
serial và warranty; reconcile trước-sau. Các ca **sau CLASSIFY là NOT_RUN**, vì B09
chỉ thiết kế workflow này. Đây là phân loại dữ liệu chưa rõ quyền sở hữu, không
phải chính sách mua lại/chuyển chủ thương mại của hàng đã xác định owner.

## Triển khai và giới hạn nghiệm thu

Revision release `014_b09_consignment.sql` thêm hai bảng evidence/plan (10 cột,
4 FK) và thay guard MOVE bằng revision forward. 001–013 giữ nguyên. Runtime tổng
72 bảng/491 cột/148 FK. Revision phát triển 015 đã được đổi thành release 014 khi tích hợp; chỉ
dùng DB test tạm cho revision phát triển này. Không dùng downgrade sửa lịch sử.

Cập nhật server và desktop cùng bộ contract B09; client cũ có DTO strict không đọc được dòng OPENING mới có consignment_id. ACK lệnh OPENING trước nâng cấp vẫn giữ hash/result.

Chủ kho chưa cung cấp chính sách tiêu thụ/đổi chủ ký gửi: outbound thương mại,
trả ký gửi/chuyển kho/reversal còn chờ policy/UAT. T01–T28 không được đổi PASS chỉ
từ các kiểm thử local. Windows, thiết bị và tải/DR vẫn cần bằng chứng môi trường
đích; kết quả Linux/API/PG/Tk và commit cụ thể nằm trong báo cáo B09.
