# Danh mục — BE05 / UI04

Đã triển khai API danh mục và sáu form desktop trên nhánh `feat/application-foundation`.
Đây là nền cho PO/nhận hàng; tạo/sửa danh mục không tạo số dư hoặc ghi sổ kho.
Đặc tả chạy thật: [openapi_runtime.json](../05_API/openapi_runtime.json), Swagger `/api/v1/docs`.

## Nâng cấp và dùng desktop

1. Cài dependencies theo [IMPLEMENTATION.md](IMPLEMENTATION.md), đặt `WMS_DATABASE_URL`.
2. Chạy `python -m apps.server.infrastructure.migrations` trước khi khởi động server.
   Revision 005 thêm version cho sáu bảng, trạng thái hoạt động cho UOM/category và bảo vệ lịch sử quy đổi/giá.
   Dữ liệu trước đó giữ nguyên, version mới = 1. Không nạp lại `001_schema.sql` vào database đang dùng.
3. PostgreSQL 15+ cần được build với ICU; migration tạo collation `wms.catalog_unicode` để tìm kiếm tiếng Việt
   đúng chữ hoa/thường kể cả database locale `C`. Các gói PostgreSQL Linux thông dụng có ICU; nếu môi trường đích
   thiếu provider này, migration rollback và cần bổ sung PostgreSQL có ICU trước khi chạy tiếp.
4. Khởi động `python -m apps.server`, rồi `python -m apps.desktop`. Đăng nhập tài khoản đã được cấp quyền
   qua quy trình [IAM](IDENTITY.md); chọn tab **Danh mục**.

Desktop hiện có Đơn vị tính, Nhóm hàng, Sản phẩm, Đối tác, Kho, Vị trí. Quyền hiện hành quyết định danh mục
được chọn và khả năng lưu. Bấm **Tìm / tải lại**, chọn một dòng để sửa hoặc **Tạo mới**, nhập lý do rồi **Lưu**.
Ngừng dùng bằng trường **Đang dùng = Không**; không xóa cứng. Khi server báo mã trùng/lỗi field, form giữ nội dung.
Để tạo Bin: tạo kho, Zone loại GROUP không có cha, Rack loại GROUP dưới Zone, rồi Bin STORAGE dưới Rack.
NONE/LOT/SERIAL áp dụng theo SKU; LOT không bắt buộc hạn dùng trừ khi bật thuộc tính tương ứng.

Danh sách phân trang 50 dòng; **Trang sau** và **Tìm / tải lại** để về trang đầu. Dropdown tham chiếu có giới hạn
200 mục và thông báo khi bị cắt; cần mở rộng tìm kiếm dropdown trước khi dùng danh mục lớn. Barcode, revision
UOM và giá tham chiếu hiện thao tác qua API, chưa có form riêng. Thông tin nhạy cảm của đối tác không có trong DTO này.

Nếu mất phản hồi lệnh lưu, UI giữ nguyên payload/key và bật **Gửi lại cùng yêu cầu**; không tự gửi lại lệnh.
Tải lại/đăng nhập lại cùng tài khoản trong cùng process vẫn giữ yêu cầu chưa rõ kết quả; tài khoản khác không thấy
hoặc gửi nó. Widget chỉ cập nhật ở main thread, HTTP chạy worker. Form/yêu cầu này hiện chỉ nằm trong RAM:
đóng process chưa khôi phục được qua SQLite. Sau restart cần tra mã và version hiện tại trước khi nhập tiếp;
không coi phần này là hoàn tất UI08/T08. Lệnh ghi không tự refresh khi 401; tải lại phiên rồi gửi lại nội dung.

## API và quyền

Prefix của bảng sau: `/api/v1/master`.

| Collection | GET | POST / PUT |
| --- | --- | --- |
| `/uoms`, `/categories`, `/products`, `/barcodes` | `master.read` GLOBAL | `master.write` GLOBAL |
| `/stock-owners`, `/consignment-agreements` | `partner.write` GLOBAL | `partner.write` GLOBAL |
| `/partners` | `partner.read` GLOBAL | `partner.write` GLOBAL |
| `/warehouses`, `/locations` | `warehouse.configure` GLOBAL | `warehouse.configure` GLOBAL |
| `/product-uoms?product_id=UUID` | `master.read` GLOBAL | POST revision mới: `master.write` GLOBAL |
| `/products/{id}/prices?warehouse_id=UUID` | `master.read` GLOBAL + `price.read` tại kho đang hoạt động | POST giá mới: `price.write` GLOBAL |
| `/scan?code=0000123` | `master.read` GLOBAL | Chỉ tra barcode đang dùng, trả SKU/quy cách; không phải tra bảo hành serial |

Kho/vị trí ở đây là danh mục cấu hình. `/api/v1/warehouses` vẫn trả riêng các kho được cấp quyền xem nghiệp vụ;
quyền cấu hình không cấp quyền xem tồn. UI nhận/xuất còn cần endpoint lựa chọn vị trí theo scope nghiệp vụ.
DTO sản phẩm và scan không chứa giá. POST giá chỉ trả id/trạng thái, kể cả replay; muốn đọc giá phải gọi GET
với quyền kho phù hợp. Giá là bản ghi append có ngày hiệu lực và nguồn, không phải giá vốn kế toán.

Collections chuẩn có `GET /{collection}/{id}`, `POST /{collection}`, `PUT /{collection}/{id}`.
PUT gửi đầy đủ trường cho phép, `expected_version` và `reason`; không có PATCH tùy ý hoặc DELETE.
Tất cả lệnh ghi bắt buộc header **Idempotency-Key: UUID**. Tạo trả 201, sửa 200; gửi lại cùng actor/key/route/body
trả body/status gốc. Key khác payload trả 409; quyền bị thu hồi không được đọc replay.

Ví dụ body tạo UOM:

```json
{"code":"EA","name":"Chiếc","decimal_places":0,"is_active":true,"reason":"Thiết lập đơn vị cơ sở"}
```

POST product cần `sku`, `name`, `base_uom_id`, `tracking`, `reason`; category có thể bỏ trống.
Server tự tạo quy đổi đơn vị cơ sở với factor 1. POST product-uoms cần `product_id`, `uom_id`, `factor` dạng chuỗi,
`expected_product_version` và `reason`; thành công tăng version sản phẩm. Đọc lại sản phẩm trước revision tiếp theo.

GET collection dùng `limit` mặc định 50, tối đa 200, `after=UUID` lấy từ `next_after`, `q` tìm mã/tên, `active=true/false`.
Locations thêm `warehouse_id`. Keyset sắp theo UUID, không lặp bản ghi chỉ vì đổi tên; đây không phải snapshot `as_of`
của contract PO/receipt. Dữ liệu có thể đổi giữa các trang. Ký tự `%`/`_` trong tìm kiếm là ký tự thường.

## Quy tắc được kiểm soát

- Mã mới chuẩn hóa trim/chữ hoa; barcode giữ nguyên hoa/thường và số 0 đầu. Mã ngừng dùng vẫn được giữ, không tái gán.
  Mã legacy giữ nguyên giá trị DB khi cập nhật tên. Mọi SQL identifier đến từ allowlist trong code.
- Tracking/base UOM/quy tắc hạn dùng bị khóa khi có dòng chứng từ, stock item, lot hoặc serial. Đổi tên vẫn được.
  UOM đã được tham chiếu không đổi độ chính xác hoặc ngừng dùng. SERIAL cần base UOM nguyên và factor nguyên.
- Quy đổi dùng decimal chuỗi chính xác tối đa 8 số lẻ. Factor/revision cũ không UPDATE/DELETE; revision mới ngừng
  quy đổi trước và barcode đang gắn vào quy đổi đó. Barcode không gán sang SKU/quy cách khác. Dòng phiếu tương lai
  phải lưu snapshot và kiểm tra scale 6 khi quy đổi lượng; danh mục chưa thay thế validator của posting.
- Category không có chu kỳ. Cây lưu trữ: Kho → Zone GROUP → Rack GROUP → Bin STORAGE. Khu RECEIVING/QUARANTINE/
  SHIPPING đặt ở kho hoặc Zone. Vị trí ảo do nghiệp vụ tương lai quản lý, không được tạo/sửa qua form này.
- Không chuyển vị trí sang kho khác; không đổi cấu trúc đã có lịch sử hoặc vị trí còn con. Chặn ngừng dùng khi còn
  tồn/giữ chỗ/khóa kiểm kê; ngừng cây rỗng từ con lên cha. Kho còn vị trí hoạt động không được ngừng dùng.
- Mọi lệnh khóa actor/key, kiểm tra lại auth, khóa danh mục, kiểm tra version rồi ghi bản ghi/audit/outbox/idempotency
  cùng UoW. Lỗi giữa transaction rollback cả bốn phần. Khóa danh mục toàn cục dành cho lưu lượng cấu hình thấp;
  handler posting tương lai vẫn phải khóa product/location tương ứng khi kiểm tra bất biến. Worker outbox chưa có.
- Lỗi kiểu dữ liệu trả 422; mã trùng, stale version, cây sai hoặc dữ liệu đang dùng trả 409 kèm `field_errors` khi
  xác định được trường. Không trả SQL hay nội dung credential.

## Bằng chứng và phần còn thiếu

`tests/foundation/test_master_data.py` kiểm thử API/RBAC, tìm kiếm Unicode, keyset, concurrency, rollback,
immutable history, UOM/barcode, cây vị trí, khóa tracking và che giá trên PostgreSQL thật.
`test_master_desktop.py` kiểm tra presenter/timeout và Tk → HTTP → PostgreSQL; `test_postgres.py` kiểm tra nâng cấp
001/002 và 001–004 giữ dữ liệu. Chạy `xvfb-run -a .venv/bin/python scripts/check_application.py --gui`.

Schema sau 005: 60 bảng/393 cột/113 FK; phần thêm ở [master model](../02_CSDL/master_extension_model.json),
[dictionary](../02_CSDL/master_extension_dictionary.csv), [DBML](../02_CSDL/master_extension.dbml).

Owner/hợp đồng và truy vết receipt/NCC/bảo hành đã có API; desktop đã có tab tra serial. Xem
[TRACEABILITY.md](TRACEABILITY.md) cho runtime 006/007 và bằng chứng thành phần T27/T28.
BE05/UI04 còn: form owner/hợp đồng/ghi chứng cứ/barcode/UOM revision/giá, policy xuất/chuyển ký gửi,
dropdown có tìm kiếm quy mô lớn và UAT Windows. PO/SO và approval đã có tại [ORDERS_APPROVAL.md](ORDERS_APPROVAL.md). Chưa có nhập file vào server hoặc
posting. T12/T13 có bằng chứng thành phần; toàn bộ T01–T28 vẫn PLANNED cho tới nghiệm thu đủ luồng.
