# Chủ sở hữu, ký gửi và bảo hành serial — UC32/UC33

Đợt triển khai local ngày 02/10/2026 bổ sung nền dữ liệu, API và màn tra serial cho BE02/BE05/TL04/UI04.
Contract chạy thật: [OpenAPI runtime](../05_API/openapi_runtime.json), Swagger `/api/v1/docs`.
Chưa có luồng PO → duyệt → nhận hàng/ghi sổ hoàn chỉnh; các fixture receipt đã post trong test được dựng bằng SQL.

## Nâng cấp dữ liệu

Sau khi cài dependencies theo [IMPLEMENTATION.md](IMPLEMENTATION.md), chạy
`python -m apps.server.infrastructure.migrations` trước khi mở server. Không nạp lại DDL nền.

- Revision 006 thêm `stock_owner`, `consignment_agreement`, `serial_warranty_record`, chiều owner/hợp đồng trên
  `stock_item` và `document_line`, cùng version bảo hành trên serial. Revision 007 thêm ba quyền tra cứu/ghi chứng cứ.
- Runtime sau 007: **63 bảng, 424 cột, 123 FK; 10 vai trò, 56 quyền, 121 ánh xạ**.
  [Model](../02_CSDL/ownership_extension_model.json), [dictionary](../02_CSDL/ownership_extension_dictionary.csv)
  và [DBML](../02_CSDL/ownership_extension.dbml) mô tả phần mở rộng, cộng với baseline/IAM/master.
- Hai owner hệ thống bất biến: COMPANY `00000000-0000-4000-8000-000000000001`,
  UNCLASSIFIED `00000000-0000-4000-8000-000000000002`. API không tạo thêm hoặc sửa hai owner này.
- **Mọi stock item và dòng phiếu có trước 006 được đánh dấu UNCLASSIFIED**, giữ nguyên ID/sổ/số dư.
  Không tự nhận hàng cũ là tài sản doanh nghiệp. Cột owner của dữ liệu mới bắt buộc và không có default.
  Dữ liệu chưa phân loại được hiển thị riêng và bị chặn ghi sổ/giữ chỗ mới.
- Chưa có workflow chuyển quyền sở hữu hoặc phân loại lại tồn cũ. Không UPDATE danh tính để vượt trigger.
  DB có dữ liệu thật cần backup, đối soát nguồn và migration/workflow chuyển đổi được review trước khi vận hành;
  hiện mới kiểm thử nâng cấp trên DB tạm. Không có downgrade phá dữ liệu.

## Owner và hợp đồng ký gửi

`/api/v1/master/stock-owners` và `/api/v1/master/consignment-agreements` hỗ trợ GET list/detail, POST, PUT detail.
Cả đọc lẫn ghi các danh mục quản trị này cần `partner.write` GLOBAL (mặc định MASTER_DATA).
Quyền đó không cấp quyền xem tồn theo kho. Chưa có form desktop cho hai collection này.

Owner mới loại CONSIGNOR gắn duy nhất một đối tác nhà cung cấp đang hoạt động. Hợp đồng gồm `code`, `owner_id`,
`warehouse_id`, `valid_from`, `valid_until`, `source_ref`, `is_active`; bắt buộc nguồn hợp đồng và ngày có thứ tự.
Các lệnh dùng `reason`, Idempotency-Key; PUT thêm `expected_version` như API danh mục.
Owner không đổi loại/đối tác; hợp đồng đã tham chiếu không đổi chủ hàng/kho/thời hạn/nguồn, có thể ngừng dùng.

Danh tính hàng là `(product, lot, serial, owner, consignment)`. Balance, ledger, reservation và kiểm kê mang chiều
này qua `stock_item_id`. Cùng SKU/lô/vị trí nhưng khác chủ hàng không hòa chung danh tính. Resolver nội bộ kiểm tra
tracking/owner/hợp đồng theo kho/ngày, INSERT ON CONFLICT rồi khóa; caller tương lai vẫn phải authorize và khóa
chứng từ/vị trí. Một serial chỉ được có tối đa một balance dương (lượng 1), kể cả khác owner/vị trí.

Move/reservation phải khớp owner của dòng phiếu. Hiện chỉ cho dữ liệu ký gửi theo operation RECEIVE/OPEN với hợp đồng
đúng kho/ngày còn hiệu lực; giữ chỗ, xuất, chuyển, đảo và đổi owner ký gửi bị từ chối cho tới khi có policy/workflow.
Trigger là lớp bảo vệ dữ liệu, chưa thay thế posting service và các bất biến kỳ/duyệt/nguồn/số dư.

## Tra tồn theo chủ sở hữu

`GET /api/v1/stock-ownership?warehouse_id=UUID&location_id=UUID&stock_item_id=UUID`
cần đồng thời `stock.read` và `ownership.read` tại kho. Stock item mốc phải có balance ở vị trí vật lý trong kho đó.
Kết quả cộng các danh tính cùng product/lot/serial, trả decimal chuỗi:

`physical_base = owned_base + SUM(consigned_by_owner.quantity_base) + unclassified_base`.

Fixture 10 doanh nghiệp + 5 ký gửi trả vật lý `15.000000`, sở hữu `10.000000`, ký gửi `5.000000`.
Không trả giá; TRANSIT không tính vào endpoint vật lý này. Đây là quyền theo kho, chưa phải phân vùng dữ liệu 3PL
theo từng đối tác. Chạy thêm [reconcile_ownership.sql](../02_CSDL/reconcile_ownership.sql) để kiểm tra sổ/số dư,
owner của dòng/move/reservation và tồn legacy chưa phân loại; nhóm legacy có thể trả dòng cần xử lý sau nâng cấp.

## Chứng cứ và trạng thái bảo hành

| API | Mục đích |
| --- | --- |
| `GET /api/v1/serials/lookup?warehouse_id=UUID&code=000123&sku=...` | Tìm mã serial chính xác, giữ hoa/thường và số 0 đầu; SKU tùy chọn để phân biệt |
| `GET /api/v1/serials/{id}/warranty?warehouse_id=UUID` | Đọc serial, phiếu nhận/NCC/ngày nhập, chứng cứ và trạng thái |
| `POST /api/v1/serials/{id}/warranty-records` | Thêm revision chứng cứ; không sửa/xóa lịch sử |

Đọc cần `stock.read` + `serial.read` tại kho yêu cầu; serial phải có tồn hoặc nguồn nhận hợp lệ ở kho đó.
Khi trả receipt/NCC/chứng cứ, server kiểm tra thêm quyền serial ở kho nguồn và `document.read` của phiếu nguồn;
RECEIVER/PICKER chỉ đọc phiếu do mình tạo/được giao. Ngoài phạm vi trả 404 hoặc bị loại khỏi kết quả tìm.
Tra mã dùng tối đa 201 ứng viên; mã dùng trên hơn 200 SKU yêu cầu nhập thêm SKU. Chưa có tìm gần đúng/phân trang serial.

POST cần Idempotency-Key và body: `expected_version` (khởi đầu 0), `receipt_move_id`, `starts_on`, `ends_on`,
`evidence_ref`, `reason`. Ba trường chứng cứ/ngày có thể null để ghi nhận chưa đủ thông tin. Nguồn phải là move
RECEIVE của RECEIPT đã ghi sổ, cùng serial và chưa đảo. Cần quyền đọc nguồn cùng `warranty.write` tại kho nguồn.
Không dùng riêng ID phiếu nháp làm bằng chứng. Source reference do người có quyền nhập; hệ thống chưa tải/xác minh tệp.

Lệnh khóa document trước serial, kiểm tra version rồi append record, tăng version, audit/outbox/idempotency trong
cùng transaction. Gửi lại cùng key/body giữ kết quả; đổi body hoặc stale version trả 409; thu hồi quyền chặn replay.
Response ghi chỉ chứa ID/version/trạng thái RECORDED. Xem chứng cứ phải qua GET với quyền hiện hành.

Ngày nghiệp vụ do server tính theo `WMS_BUSINESS_TIMEZONE` (mặc định `Asia/Ho_Chi_Minh`), không dùng đồng hồ desktop.
Gói server có `tzdata` để chạy trên OS thiếu cơ sở dữ liệu múi giờ.

- VALID / Còn bảo hành: đủ ngày bắt đầu/kết thúc/nguồn và ngày nghiệp vụ nằm trong khoảng, gồm cả ngày kết thúc.
- EXPIRED / Hết bảo hành: đủ chứng cứ và đã qua ngày kết thúc.
- UNKNOWN / Chưa xác định: thiếu chứng cứ/ngày, chưa tới ngày bắt đầu, hoặc nguồn đã đảo/không còn xác minh được.

Không tự suy ngày bắt đầu từ ngày nhận hoặc cộng số tháng mặc định. Khi chưa có revision, dùng nguồn nhận chưa đảo
sớm nhất để truy receipt; khi có revision, dùng đúng nguồn ghi trong revision mới nhất. Không gồm sửa chữa/RMA.

## Desktop và kiểm thử

Đăng nhập, mở tab **Tra serial / bảo hành**, chọn kho, nhập mã (thêm SKU nếu cần), bấm **Tra serial** rồi chọn dòng.
Màn hình hiển thị ba trạng thái, số phiếu, tên NCC, ngày nhập và chứng cứ. HTTP chạy worker; dữ liệu xóa khi đổi
kho/phiên hoặc đăng xuất. Desktop hiện chỉ đọc; nhập revision chứng cứ qua API. Chưa có màn tồn theo owner.

`tests/foundation/test_traceability.py` kiểm tra API/quyền, 10+5, chứng cứ/ngày/múi giờ, rollback/replay,
hai kết nối cạnh tranh serial/version/danh tính và Tk → HTTP → PostgreSQL. `test_postgres.py` kiểm tra nâng cấp
005 → 007 giữ nguyên sổ/số dư và không tự suy owner/bảo hành. Test fallback múi giờ nằm ở `test_api_contracts.py`.
Ảnh bố cục desktop được kiểm tra bằng Xvfb với dữ liệu giả; chưa UAT Windows hoặc thiết bị quét.

T27/T28 có bằng chứng thành phần, vẫn **PLANNED** cho nghiệm thu đủ luồng. [PO/SO và duyệt](ORDERS_APPROVAL.md) đã có cho hàng doanh nghiệp. Còn receipt/posting, policy hàng ký gửi,
import/báo cáo/kiểm kê theo owner, các form quản trị mới và nâng cấp dữ liệu vận hành.

## Tích hợp nhận hàng revision 009

[RECEIVING.md](RECEIVING.md) bổ sung nguồn RECEIVE thật từ PO/receipt đã duyệt và serial position nguyên tử.
Luồng PO chỉ nhận COMPANY; policy nhận ký gửi và chuyển owner chưa có. Kiểm thử mới xác nhận serial sau receipt.post tra đúng phiếu/NCC và vẫn UNKNOWN nếu thiếu chứng cứ bảo hành.
