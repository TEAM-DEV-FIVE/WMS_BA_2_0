# PO/SO và phê duyệt — BE06/BE07/UI05

Đợt triển khai local ngày 03/10/2026 thêm API vòng đời PO/SO và tab desktop **PO/SO và duyệt**.
Đã kiểm thử trên PostgreSQL thật và Tk → HTTP → FastAPI. Tạo/duyệt PO/SO không tăng hoặc giảm tồn.
Receipt/issue, posting và release reservation chưa được triển khai; T10/T14/T17 vẫn là nghiệm thu chưa hoàn tất.

## Nâng cấp và contract

Chạy `python -m apps.server.infrastructure.migrations` theo [IMPLEMENTATION.md](IMPLEMENTATION.md).
Migration 008 bổ sung vai trò duyệt thay trên policy/step, snapshot nội dung bất biến của approval request,
`document_line.closed_base_quantity`, sequence số phiếu và policy PO/SO mặc định. Runtime sau 008 có
**63 bảng/428 cột/125 FK, 56 permissions/121 ánh xạ; 56 paths API** tại revision 008.
Revision 009 bổ sung [nhận hàng](RECEIVING.md): runtime hiện tại 63 bảng/430 cột/125 FK và 61 paths.
Phần schema thêm nằm ở [model](../02_CSDL/order_extension_model.json),
[dictionary](../02_CSDL/order_extension_dictionary.csv) và [DBML](../02_CSDL/order_extension.dbml).

Migration giữ policy PO/SO đã tồn tại, không tự thay policy của database cũ. Request duyệt cũ giữ status/version
và có `content_snapshot=null`; API không coi đó là bằng chứng duyệt hợp lệ. Phiếu SUBMITTED legacy cần đối soát,
hủy theo quyền và lập lại, hoặc một quy trình chuyển đổi được review; không điền snapshot giả để hợp thức hóa.
Nếu DB cũ có nhiều request PENDING cho một phiếu, unique index mới làm migration rollback để xử lý dữ liệu trước.
Chỉ áp dụng trên DB tạm trong đợt kiểm thử này, chưa nâng cấp dữ liệu vận hành.

[openapi_runtime.json](../05_API/openapi_runtime.json) là contract chạy thật; Swagger `/api/v1/docs`.
`openapi_core.json` vẫn giữ thiết kế luồng nhận hàng, chưa đồng nhất DTO/phân trang với runtime PO/SO.
Runtime dùng PUT đầy đủ nội dung và `after` UUID, không có PATCH hay snapshot phân trang `as_of`.

## API và quyền

Prefix `/api/v1`:

| Endpoint | Chức năng/quyền |
| --- | --- |
| `GET /purchase-orders`, `GET /sales-orders` | Danh sách theo `warehouse_id`, `status` tùy chọn; `document.read` đúng kho, lọc assignment với RECEIVER/PICKER |
| `GET /purchase-orders/{id}`, `GET /sales-orders/{id}` | Header/dòng, lượng ròng đã thực hiện/còn lại, phân công, lịch sử duyệt và `allowed_actions`; không trả giá |
| `POST /purchase-orders`, `POST /sales-orders` | Tạo nháp: `document.read` và `po.draft`/`so.draft` đúng kho |
| `PUT /purchase-orders/{id}`, `PUT /sales-orders/{id}` | Sửa DRAFT/REJECTED; quyền draft và là người lập/được giao |
| `POST /documents/{id}/submit` | Gửi PO/SO và snapshot nội dung/policy; cùng quyền sửa |
| `POST /documents/{id}/revise` | APPROVED chưa thực hiện/tham chiếu → DRAFT, vô hiệu approval; cùng quyền sửa |
| `POST /documents/{id}/assignments` | Thay danh sách người được giao trước submit: `document.assign`; mọi người nhận còn quyền đọc đúng kho |
| `POST /documents/{id}/cancel` | Hủy phiếu chưa thực hiện: `document.cancel`; giữ lịch sử, đóng lượng chưa thực hiện |
| `POST /documents/{id}/close` | PARTIAL → COMPLETED với lượng đóng thiếu riêng: `document.cancel` |
| `GET /approval-requests/{id}` | Đọc request/steps qua quyền đọc phiếu; không trả snapshot thô hoặc giá |
| `POST /approval-requests/{id}/decide` | APPROVE/REJECT: `document.approve`, đúng role snapshot của bước và quy tắc phân tách nhiệm vụ |

Các action `/documents/*` và `/approval-requests/*` trong module này **chỉ xử lý PO/SO**, không duyệt receipt,
adjustment, kiểm kê hay tồn đầu kỳ. Các loại đó cần validator/policy riêng trước khi bật.
`GET /documents/{id}` từ IAM vẫn là projection tối thiểu; màn PO/SO dùng endpoint chi tiết của từng loại.

Lệnh ghi bắt buộc `Idempotency-Key: UUID`, `reason`, và `expected_version` ngoại trừ create.
Assign thêm `user_ids` (danh sách đầy đủ); decide thêm `decision` = APPROVE hoặc REJECT.
Create trả 201, action/update trả 200 với ID/số phiếu/kho/loại/status/version/request ID; submit/decide thêm
approval request ID. Response ghi không chứa dòng hàng/giá. Replay vẫn kiểm tra quyền hiện hành, giữ nguyên body/status
đã commit; khác payload/key trả 409. Timeout phải gửi lại đúng key/body, không tạo lệnh thay thế tự động.

## Nội dung đơn hàng và số lượng

Create/PUT gồm `warehouse_id`, `partner_id`, `business_date`, `reason`, `lines` (1–200 dòng).
Một dòng gồm `product_id`, `product_uom_id`, `quantity` dạng chuỗi decimal, `owner_id`, `consignment_id` tùy chọn.
PO yêu cầu nhà cung cấp; SO yêu cầu khách hàng; danh mục phải hoạt động. Kho của phiếu đã tạo không được đổi.
`owner_id` bắt buộc là COMPANY `00000000-0000-4000-8000-000000000001`, `consignment_id` phải null.
PO/SO hiện là mua/bán hàng doanh nghiệp; không tự biến ký gửi thành hàng mua/bán.

Server đọc quy đổi đang hoạt động, lưu `factor_snapshot`, tính `base_quantity` chính xác theo scale 6 và độ chính xác
UOM; từ chối lượng cần làm tròn, vượt giới hạn hoặc serial có lượng lẻ. Không nhận factor/base quantity từ client.
PUT thay toàn bộ dòng, sinh lại ID dòng; caller đọc lại sau lưu. Khi đã có phiếu con/tham chiếu, không thay dòng cũ.
Form sửa cần chọn lại quy cách nếu quy đổi cũ đã ngừng dùng. API chưa hỗ trợ nhập giá hoặc nguồn cho PO/SO;
sửa phiếu legacy đã có giá/nguồn bị chặn để không âm thầm xóa dữ liệu.

Số phiếu có dạng `PO-YYYYMMDD-00000001`/`SO-YYYYMMDD-00000002`, từ sequence chung; rollback có thể để lại khoảng trống.
Không phải số chứng từ kế toán liên tục. Danh sách dùng keyset UUID, `limit` mặc định 50/tối đa 200 và `next_after`;
đây là dữ liệu live, không bảo đảm snapshot bất biến giữa các trang. Desktop lấy 25 phiếu/trang.

Chi tiết trả `posted_base`, `closed_base`, `remaining_base` theo đơn vị cơ sở:

`remaining_base = base_quantity - posted_base - closed_base`.

Posted lấy từ RECEIVE/RECEIPT đối với PO hoặc ISSUE/ISSUE đối với SO, liên kết `source_line_id`, khớp product/owner/
hợp đồng; move đã bị đảo bị loại đúng một lần. Fixture PO 100, receipt 80 trả còn 20; đóng thiếu giữ posted 80,
closed 20, remaining 0. Hủy phiếu chưa thực hiện đóng toàn lượng còn lại và giữ header/dòng/approval/audit.
Nếu sổ vượt lượng yêu cầu, API báo xung đột cần đối soát, không che sai lệch bằng lượng 0.

Hủy/đóng/sửa bị chặn khi còn phiếu con chưa kết thúc hoặc reservation mở ở đơn/dòng con. Module này chưa tự release
reservation. Posting sau này bắt buộc khóa đơn nguồn trước phiếu con, kiểm tra remaining/approval và cập nhật trạng thái
nguồn trong cùng transaction. Test hiện dùng SQL để dựng receipt/issue đã post; không phải bằng chứng có posting API.

## Phê duyệt và tính nguyên tử

Policy mặc định có một bước: WAREHOUSE_MANAGER **hoặc** CONTROLLER tại kho, không hạn mức giá trị theo Q04.
Engine hỗ trợ một hoặc hai bước từ policy; không có policy/step hợp lệ thì từ chối submit.
Người tạo, người submit hoặc người đã quyết định bước trước không được duyệt. Role/grant phải còn hiệu lực đúng kho.
SYSADMIN không tự có quyền nghiệp vụ.

Submit tăng version và lưu snapshot header/dòng/attributes/phân công cùng role chính/role thay của từng bước.
Mỗi quyết định khóa document → request → steps, kiểm tra version và snapshot trước khi ghi. Mỗi bước tăng version;
approve cuối chuyển APPROVED, reject chuyển REJECTED. Hai quyết định cạnh tranh chỉ một thành công với version đã đọc.
Thay policy sau submit không đổi vai trò của request đã snapshot. Lịch sử quyết định/snapshot không UPDATE/DELETE.

SUBMITTED không được sửa. REJECTED có thể sửa hoặc gửi lại. APPROVED cần revise về DRAFT trước khi sửa;
approval cũ trở thành INVALIDATED. Chưa có action rút lại SUBMITTED; quản lý có thể hủy theo policy hiện hành.
Phân công trước submit để nội dung và trách nhiệm được snapshot; muốn đổi sau duyệt cũng cần revise và gửi lại.

CommandBus giữ key theo actor, kiểm tra quyền trước replay, khóa document và kiểm tra version; dữ liệu/approval,
audit/outbox/idempotency commit cùng transaction. Lỗi sau outbox rollback toàn bộ. Outbox worker vẫn chưa triển khai.

## Dùng desktop và giới hạn

1. Đăng nhập, mở **PO/SO và duyệt**, chọn loại/kho rồi **Tải danh sách**.
2. Người lập cần BUYER/SELLER ở kho và quyền `master.read`/`partner.read` GLOBAL để chọn danh mục.
   Có thể cấp thêm cùng role BUYER/SELLER scope GLOBAL cho phần đọc danh mục; không cần cấp MASTER_DATA để ghi danh mục.
   Thiếu quyền GLOBAL vẫn xem/duyệt phiếu được phép, nhưng form lập/sửa bị khóa.
3. **Tạo mới** → chọn đối tác/ngày, sản phẩm/quy cách/lượng → **Thêm dòng** → nhập lý do → **Lưu nháp**.
   Danh mục chọn hiện giới hạn 200 mục; chưa có tìm kiếm dropdown cho tập lớn.
4. Chọn phiếu, nhập lý do và **Gửi duyệt**. Người khác có quyền mở phiếu và **Duyệt** hoặc **Từ chối**.
   Nút khả dụng lấy từ server; tự duyệt luôn bị chặn ở API.
5. Lỗi version giữ nội dung đang nhập; đọc thông báo rồi tải lại phiếu để đối chiếu. Sau timeout, nút gửi lại dùng
   chính payload/key đang giữ. Đổi tài khoản không thấy/gửi được lệnh của tài khoản cũ; dữ liệu phiếu xóa khi logout.

Desktop hiển thị lượng theo đơn vị nhập và lượng đã thực hiện/còn lại theo đơn vị cơ sở, người lập và hai lần duyệt
gần nhất. API trả toàn bộ lịch sử duyệt. Phân công hiện qua API; chưa có GUI phân công/quản trị policy/so sánh bản sửa.
Payload/key chưa rõ kết quả hiện chỉ giữ trong RAM theo user, chưa nối SQLite recovery khi đóng process (UI08).
Chưa UAT Windows hoặc kiểm tra thiết bị quét/in.

## Bằng chứng

[test_orders.py](../tests/foundation/test_orders.py) kiểm tra API, scope/assignment, decimal, snapshot, tự duyệt,
hai bước, cạnh tranh update/decision, retry/revoke, rollback, đóng thiếu/đảo và desktop qua HTTP thật.
[test_order_presenter.py](../tests/foundation/test_order_presenter.py) kiểm tra retry đúng key/body, tách user,
bỏ response phiên cũ và đọc phiếu khi thiếu quyền danh mục. Test upgrade 007 → 008 giữ policy/request cũ nằm ở
[test_postgres.py](../tests/foundation/test_postgres.py).
Kết quả toàn bộ và giới hạn ở [IMPLEMENTATION_REVIEW.md](../07_Kiem_tra/IMPLEMENTATION_REVIEW.md).

BE06/BE07/UI05 đã có phần PO/SO, vẫn chưa nghiệm thu toàn issue. Đã nối receipt/posting và khóa nguồn; còn issue,
release reservation, các policy nghiệp vụ khác, GUI phân công và UAT đủ T10/T14/T17.
