# Trường mở rộng có kiểu — B07

## Phạm vi và quyền

Bộ trường mô tả áp dụng theo `PRODUCT` hoặc loại chứng từ: PO, SO, RECEIPT, OPENING,
ISSUE, INTERNAL_MOVE, TRANSFER, ADJUSTMENT mất transit, CUSTOMER_RETURN, SUPPLIER_RETURN,
REVERSAL. Phiếu điều chỉnh tự sinh từ kiểm kê thuộc workflow B13, không mở sửa qua API này.
Không mở rộng bảng số dư, dòng sổ, count session, reservation hoặc thêm loại chứng từ tùy ý.
Mỗi loại có một bộ trường toàn hệ thống; quyền giá trị vẫn theo đối tượng và kho thực tế.

`config.manage` GLOBAL và MFA hiện hành cho đọc/phát hành định nghĩa. Quyền này không cấp
quyền đọc giá trị chứng từ. Đọc chứng từ áp dụng `document.read`, assignment và cả hai kho
của TRANSFER; ghi cần quyền draft tương ứng và người lập/người được giao. REVERSAL và
điều chỉnh transit dùng lại kiểm tra nguồn/quyền của B14/B11. Sản phẩm dùng `master.read`
và `master.write` GLOBAL. Không thêm permission/role hoặc sửa seed đã phát hành.

Trường `PRICE` còn cần `price.read` ở kho thực tế; ghi cần thêm `price.write` GLOBAL.
Với sản phẩm, truyền `warehouse_id` để xác định scope giá. Chứng từ lấy kho từ DB,
không tin tham số kho của client. TRANSFER và điều chỉnh mất transit yêu cầu quyền giá
ở cả hai đầu; REVERSAL kế thừa tất cả kho từ giao dịch nguồn.
Đọc, lịch sử và preview cùng dùng bộ lọc. Trường không được xem bị bỏ cả definition lẫn
giá trị. Code từng phân loại PRICE không được hạ thành BUSINESS; lịch sử BUSINESS của
code được nâng lên PRICE cũng áp dụng quyền giá hiện tại. Trường ẩn không bị xóa khi
người dùng chỉ sửa trường thông thường. Chuyển phiên bản có giá trị ẩn cần quyền giá.

## Phiên bản và giao dịch

`custom_field_schema` nhận dạng bộ trường theo entity_type. Mỗi lần phát hành tạo
`custom_field_revision` và các dòng `custom_field_definition` mới. Không UPDATE/DELETE
định nghĩa đã phát hành. Bỏ một code khỏi phiên bản mới là ngừng dùng ở phiên bản đó;
không xóa định nghĩa/giá trị cũ. Bộ trường rỗng là cách ngừng dùng toàn bộ cho đối tượng mới.

`custom_field_binding` gắn đối tượng với revision bất biến và giá trị JSON phẳng.
`custom_field_change` giữ lịch sử append-only. Không ghi `product.attributes` hoặc
`document.attributes`; `receipt_plan` và các kế hoạch typed thuộc module nghiệp vụ giữ nguyên.
Không cho tên trường lõi như quantity, base_uom_id, owner_id, warehouse_id, price_read,
ledger, stock_balance, receipt_plan; không thực thi SQL, biểu thức hoặc mã từ cấu hình.

Lần lưu đầu gắn revision mới nhất. Các lần sau tiếp tục revision đang gắn dù quản trị
đã phát hành revision mới. Chuyển revision phải chủ động gửi revision mới nhất và
`expected_revision_id` cũ. Máy chủ giữ code còn tồn tại, áp dụng patch, bỏ code đã ngừng
ở bản mới, kiểm tra lại toàn bộ kiểu/ràng buộc; thất bại không đổi dữ liệu. Lịch sử vẫn giữ
giá trị đã bỏ. Không tự ép TEXT thành INTEGER hoặc làm tròn DECIMAL khi migrate.

Ghi tăng version của sản phẩm/chứng từ. Chứng từ chỉ sửa ở DRAFT/REJECTED; kiểm tra
dependency và vô hiệu approval theo engine hiện có. Muốn sửa bản APPROVED phải dùng
`revise` của nghiệp vụ trước để giải phóng reservation và vô hiệu duyệt đúng transaction.
SUBMITTED/PARTIAL/COMPLETED/CANCELLED không ghi metadata. Khi submit, máy chủ kiểm tra
trường bắt buộc và pin bộ trường nếu chưa gắn. Approval snapshot chứa đầy đủ schema và
giá trị đã pin; API đọc thông thường vẫn che giá. Thay định nghĩa sau submit không làm
stale approval cũ; sửa giá trị trên bản nháp làm stale version của client cũ.

Chứng từ đã submit trước khi có bộ trường tiếp tục snapshot cũ, không bổ sung khóa JSON
trống làm sai so sánh approval. Sản phẩm được tạo trước rồi bổ sung metadata; required
được kiểm tra khi lưu binding, không chặn tạo bản danh mục chưa bổ sung metadata.
Đảo giao dịch giữ nguyên metadata chứng từ nguồn; REVERSAL có binding/snapshot riêng.

Thứ tự khóa: idempotency actor/key → nguồn/chứng từ theo engine hiện có hoặc catalog
advisory lock/product → schema advisory SHARE. Phát hành schema dùng advisory UPDATE,
không khóa đối tượng. Hai lệnh cùng version chỉ một thành công; cùng key/payload trả ACK
cũ sau kiểm tra quyền hiện hành. Schema/value/history, version, audit, outbox và ACK cùng
transaction. Không ghi ledger/balance/reservation từ custom-field service.

Events: `custom_field.schema.published.v1`, `custom_field.values.updated.v1`.
Payload chỉ có id, version, revision_id, request_id; không đưa giá trị vào audit/outbox/ACK.
Chi tiết giá trị ở bảng lịch sử có quyền đọc riêng. Event là thông báo hậu kỳ; B07 không
đăng ký consumer tự động hoặc gọi I/O trong transaction. B20 quyết định registry vận hành.

## Contract API và import/export

Prefix `/api/v1/custom-fields`; contract thực ở `packages/contracts/custom_fields.py`
và OpenAPI runtime được sinh từ code.

| Route | Chức năng |
| --- | --- |
| GET /schemas/{entity_type} | Bộ trường mới nhất, version 0 khi chưa có |
| PUT /schemas/{entity_type} | Phát hành đầy đủ bộ trường, expected_version, fields, reason |
| GET /{products hoặc documents}/{id} | Đối tượng/version, binding revision, schema đã lọc quyền, values |
| GET /{products hoặc documents}/{id}?latest=true | Xem metadata bản mới để chuẩn bị chuyển phiên bản; không ghi |
| GET /{products hoặc documents}/{id}/history | Lịch sử đã lọc quyền; limit 1–200, before theo target_version |
| POST /{products hoặc documents}/{id}/preview | Kiểm tra lệnh import/patch; không ghi DB |
| PUT /{products hoặc documents}/{id} | Commit chính lệnh đã kiểm tra; kiểm tra lại quyền, version, revision |

PUT bắt buộc `Idempotency-Key`. Preview cũng nhận header này theo convention runtime
cho POST nhưng không lưu ACK hoặc cấp vé bỏ qua validation. Commit dùng key riêng;
retry commit giữ đúng key và nguyên payload. `warehouse_id` tùy chọn chỉ phục vụ giá
sản phẩm, thuộc nhận dạng lệnh để không replay sang scope giá khác.

Ví dụ lệnh giá trị/import JSON (UUID lấy từ GET, không dùng mẫu này như dữ liệu thật):

```json
{
  "expected_version": 3,
  "expected_revision_id": "00000000-0000-4000-8000-000000000701",
  "revision_id": "00000000-0000-4000-8000-000000000702",
  "reason": "Chuyển bộ trường đã rà soát",
  "values": {"batch_note": "Lô hàng mẫu", "checked": true, "rating": 4}
}
```

`values` là patch. Không gửi code nghĩa là giữ giá trị cũ còn thuộc revision; gửi null
nghĩa là xóa trường tùy chọn. Unknown code bị từ chối. GET là contract export JSON có
revision/schema/value đủ để diễn giải, không phải file job đã có quyền tải vĩnh viễn.
B01/B17 phải gọi projection hiện hành khi preview/commit/export/download; không đọc
JSON thô hoặc tái dùng kết quả preview sau thu hồi quyền. Import hàng loạt, CSV/XLSX
và export job thuộc B01/B17, không tự mở thêm cột tùy ý vào template lõi. Khi B17 tạo
CSV cần escape công thức theo encoder của export; B07 chỉ trả JSON dữ liệu.

Kiểu: TEXT tối đa 2.000 ký tự, INTEGER thật (không nhận boolean), DECIMAL chuỗi tối đa
14 chữ số nguyên/6 thập phân, BOOLEAN thật, DATE ISO hợp lệ, ENUM theo danh sách code.
Số có minimum/maximum; TEXT có max_length; enum tối đa 100 lựa chọn duy nhất.
Tối đa 50 field/schema và 50 key/patch. Không nhận object/array/float trong values.
Body tối đa 64 KiB khi stream, depth tối đa 8 trước parse JSON; từ chối duplicate keys,
NaN/Infinity, NUL và Unicode surrogate. Lỗi không phản chiếu giá trị/giá ẩn.

## Desktop

Mục **Trường mở rộng** có hai trang: giá trị theo metadata và định nghĩa bộ trường.
Quản trị có thể cấu hình dù không được cấp kho; không cần nhập JSON. Form định nghĩa
có code, nhãn, kiểu, bắt buộc, phân loại quyền, độ dài, khoảng số và lựa chọn enum.
Người dùng chọn loại, kho, tải trang đối tượng (50 dòng), chọn đối tượng rồi sửa các ô
được tạo theo metadata. BOOLEAN/ENUM dùng combobox; ngày/số được server kiểm tra.
Điều chỉnh transit có thể mở bằng ID chứng từ từ workflow chuyển kho.

Xem bộ trường mới nhất chỉ là preview metadata; nút lưu thực hiện chuyển revision.
Lịch sử hiện 50 thay đổi gần nhất; API hỗ trợ phân trang lịch sử đầy đủ.
Form có cuộn dọc/ngang và nằm trong navigation của shell ở 800×620/900×690.
HTTP ở worker; Tk và hủy tài nguyên ở main thread. Đổi user/kho/loại bỏ response cũ,
xóa dữ liệu đang hiển thị. UNKNOWN giữ đúng payload/key trong RAM theo user/kho, chỉ
retry yêu cầu cũ; ACK phải khớp id/revision/version. Journal bền/crash recovery chung
thuộc B19, chưa được tuyên bố có trong B07. Không lưu credential hoặc dữ liệu này vào SQLite.

## Migration và vận hành

Revision phát triển `025_b07_custom_fields.sql`, chỉ dùng DB kiểm thử bỏ được. Giữ nguyên
001–020. Điều phối gán số release tăng tiếp khi ghép. Bốn bảng mới và ba cột bổ sung
definition; baseline model001 không đổi. Dictionary/DBML/model bổ sung đi kèm.

Migration không backfill, không đổi attributes hoặc policy cũ. Definition legacy có
revision_id NULL giữ nguyên và có partial unique index riêng. Nếu entity còn legacy
definition, publish bị chặn `LEGACY_CUSTOM_FIELDS`. Kế hoạch chuyển dữ liệu có kiểm soát:

1. Kiểm kê/export legacy definition và attributes bằng quyền hiện hành, giữ bản sao/hash.
2. Chốt mapping code, kiểu, quyền giá và ràng buộc; liệt kê dữ liệu không hợp lệ, không tự ép kiểu.
3. Chuẩn bị migration forward được review để lưu provenance/retire definition legacy;
   không xóa attributes/approval cũ. Không sửa migration đã phát hành hoặc tự adopt dữ liệu.
4. Phát hành revision mới. Chuyển từng sản phẩm/bản nháp qua ValuesWrite với reason,
   version và preview; đối chiếu lịch sử. Chứng từ đã phát sinh giữ nguyên snapshot.
5. Chạy backup/restore và rehearsal trên bản sao trước triển khai vận hành.

Rollback giao dịch được kiểm thử. Rollback release có dữ liệu cần restore/forward fix
được điều phối; không DROP bảng lịch sử. Windows, 15 CCU, LAN và UAT nghiệp vụ phải
nghiệm thu riêng; bằng chứng local không đổi trạng thái T01–T28.
