# Tồn đầu kỳ doanh nghiệp — backend OPENING

Ngày 03/10/2026, migration `010_opening.sql`. Đợt này cung cấp API tạo/sửa/đọc/danh sách,
gửi/duyệt và ghi toàn bộ phiếu tồn đầu kỳ; chưa có màn hình hay pipeline import file.

## Quyền, policy và cách hiểu cutover

- `opening.draft`: CONTROLLER được lập và sửa/gửi phiếu của mình hoặc được giao.
- `opening.approve`: CONTROLLER hoặc DIRECTOR đúng kho; không yêu cầu thêm `document.approve`.
  Người lập, người gửi và người đã duyệt bước trước luôn bị chặn tự duyệt.
- `opening.post`: CONTROLLER đúng kho. UC23 không giới hạn người ghi sổ phải là người lập/được giao;
  quyền ghi sổ và quyền đọc phiếu được kiểm tra lại cả khi replay/tra ACK.
- Policy mặc định một bước CONTROLLER **hoặc** DIRECTOR. Engine giữ hỗ trợ hai bước có thứ tự từ
  policy tùy chỉnh, mỗi bước khác người. Không tự bỏ bước khi thiếu người. Snapshot giữ role chính/thay;
  đổi policy sau submit không đổi yêu cầu đang duyệt.

Nguồn: [UC23](USE_CASES.md), [ma trận quyền](../04_Phan_quyen/policy.json),
[SOD](../04_Phan_quyen/RBAC.md), [BR02](BA/07_RULES.md). Q04 về phiếu thông thường không được dùng
để cấp quyền duyệt OPENING cho WAREHOUSE_MANAGER. Hồ sơ yêu cầu hỗ trợ policy tối đa hai bước;
chưa quy định OPENING luôn bắt buộc hai bước. Migration chỉ seed khi **chưa từng có policy OPENING**,
giữ cả policy tùy chỉnh đang tắt và các bước đã có. Không thêm permission hoặc ánh xạ role mới.

UC23 ghi “không cộng thêm vào kho đang hoạt động”, “trùng batch hoặc execution không nạp lại”,
và tồn nguồn đã kiểm kê/ký. Cách hiện thực đợt này:

1. Một lần ghi toàn bộ OPENING cho một kho chưa có lịch sử giao dịch tồn. Kho đã có transaction,
   move qua bất kỳ vị trí nào, hoặc số dư/giữ chỗ khác 0 đều bị chặn. Lịch sử đã đảo hoặc tồn ròng bằng 0
   vẫn đóng cửa sổ cutover. Không suy từ ngày backdate rằng kho còn được khởi tạo.
2. `batch_key` UUID duy nhất trong mỗi kho, không đổi sau tạo; phiếu đã hủy vẫn giữ mã này.
   Cùng mã ở kho khác được phép vì bộ import tương lai có thể sinh một phiếu cho mỗi kho.
3. `signed_count_reference` bắt buộc, là mã/tham chiếu biên bản nguồn đã kiểm kê/ký, được snapshot cùng
   nội dung khi gửi duyệt. API không xác minh chữ ký điện tử hoặc tính xác thực của biên bản ngoài hệ thống.
   Người duyệt phải đối chiếu nguồn trước quyết định.
4. Không có API mở cửa sổ cutover bằng ngày cấu hình, nạp bổ sung, upsert số dư hoặc chia phiếu thành
   nhiều lần post. Mỗi phiếu tối đa 200 dòng; kho lớn hơn cần thiết kế batch/chunk trong đợt import sau,
   không gửi nhiều phiếu để vượt giới hạn.

Đây là quyết định phạm vi backend được ghi rõ để điều phối review. T20 còn pipeline dry-run/import,
hash file, staging, chống nhập lại batch nguồn và nghiệm thu cutover thực tế; API này chưa hoàn tất T20.

## API runtime

Prefix `/api/v1`, Bearer session IAM thật. Lệnh ghi cần header `Idempotency-Key: UUID`.
Contract chạy thật: [openapi_runtime.json](../05_API/openapi_runtime.json).

| Route | Nội dung |
| --- | --- |
| `GET /openings?warehouse_id=...` | Danh sách theo kho/quyền, `status`, keyset `after`, `limit` 1–200 |
| `POST /openings` | Lập nháp, trả 201 |
| `GET /openings/{id}` | Header, dòng, kế hoạch, approval, lượng đã ghi/còn lại và allowed actions |
| `PUT /openings/{id}` | Thay toàn bộ nháp/từ chối với `expected_version`; sinh lại ID dòng |
| `POST /documents/{id}/submit,revise,assignments,cancel` | Workflow chung; không hỗ trợ close thiếu cho OPENING |
| `GET /approval-requests/{id}` | Xem bước duyệt và lịch sử |
| `POST /approval-requests/{id}/decide` | APPROVE/REJECT theo `opening.approve`, role snapshot, version và SOD |
| `POST /openings/{id}/post` | Ghi toàn bộ nội dung đã duyệt, APPROVED → COMPLETED |
| `GET /openings/operations/{key}` | ACK của opening.post đã commit, đúng actor và quyền hiện hành |

Create/PUT gồm `warehouse_id`, `batch_key`, `business_date`, `signed_count_reference`, `reason` và `lines`.
Mỗi dòng: `product_id`, `quantity_base` dạng **chuỗi decimal**, `owner_id`, `destination_location_id`,
`lot_code`/`serial_code`, `manufactured_on`/`expires_on` nếu áp dụng. Chủ hàng bắt buộc là COMPANY
`00000000-0000-4000-8000-000000000001`. Không nhận NCC, giá, nguồn PO, hợp đồng ký gửi hoặc factor từ client.
Nhập lượng cơ sở, factor snapshot 1; UOM đọc từ sản phẩm, kiểm tra precision và không âm thầm làm tròn.

Post chỉ gồm `expected_version`, `execution_key` và `reason`: không nhận lại dòng/lượng/vị trí để thay
nội dung đã duyệt. ACK trả ID transaction, ID/number/kho/status/version phiếu và `request_id` gốc.
Sửa phiếu đã duyệt cần revise trước, vô hiệu approval cũ và gửi duyệt lại. Phiếu đã post không sửa/hủy trực tiếp.

Timeout: giữ nguyên HTTP key, execution key và toàn bộ body. Tra `/openings/operations/{key}`;
404 không chứng minh request cũ chắc chắn chưa commit. Chỉ gửi lại cùng yêu cầu. Replay cùng key
trả status/body gốc sau kiểm tra quyền; cùng execution key với HTTP key khác chỉ trả ACK gốc nếu cùng
actor và hash payload. Khác actor/body trả `EXECUTION_MISMATCH`; đổi nội dung cùng HTTP key trả
`IDEMPOTENCY_MISMATCH`. Không có cơ chế phục hồi desktop cho OPENING trong đợt này.

## Ghi sổ và dữ liệu

- Vị trí đích đang hoạt động, đúng kho, loại STORAGE/RECEIVING/QUARANTINE/SHIPPING; không nạp vào
  GROUP, TRANSIT hoặc đối ứng. Lô hết hạn theo ngày hiện tại ở timezone doanh nghiệp chỉ vào QUARANTINE.
- NONE không có lô/serial; LOT cần lô, ngày khớp dữ liệu đã có; SERIAL mỗi dòng đúng 1, không trùng
  trong phiếu và không có vị trí/tồn khác trên toàn hệ thống. Không làm mất số 0 đầu hoặc đổi hoa/thường.
- Khóa theo thứ tự document → warehouse → period → location → product → identity → balance.
  Post giữ khóa độc quyền warehouse, xung đột với shared lock của receipt; dù hai phiếu khác kỳ/vị trí,
  receipt đã commit trước sẽ khiến OPENING bị chặn. OPENING commit trước thì receipt được tiếp tục bình thường.
- Kỳ của ngày nghiệp vụ phải tồn tại đúng một kỳ OPEN; vị trí không khóa kiểm kê. Kiểm tra lại kho,
  owner, product, UOM, tracking, snapshot/version và nội dung typed plan trong transaction.
- Nguồn cố định `WMS-OPENING` (`00000000-0000-4000-8000-000000000202`), loại OPENING ngoài kho.
  Operation `OPEN`; không tạo/cache balance tại đối ứng. Balance tăng từ các ledger move, không ghi trực tiếp từ client.
- Ledger, balance, serial position, trạng thái/version, audit `opening.*`, outbox `opening.*.v1`,
  execution ACK và HTTP idempotency record commit/rollback cùng transaction. Retry deadlock/serialization
  dùng CommandBus hiện có, tối đa ba lần với cùng key/body; mất kết nối không tự tạo lệnh mới.
- OPENING không tạo receipt/NCC hoặc `serial_warranty_record`. Tra serial mới nhận qua OPENING trả
  nguồn receipt/NCC null và bảo hành UNKNOWN cho đến khi có chứng cứ hợp lệ từ nghiệp vụ riêng.

Migration thêm `opening_document` (batch/biên bản theo kho) và `opening_line` (tracking/vị trí), không nhét
plan mới vào JSON attributes. Lượng và ownership vẫn ở `document_line`; snapshot duyệt bao gồm cả hai bảng mới.
Tổng runtime: 65 bảng, 440 cột, 129 FK; API 65 paths. Model/dictionary/DBML bổ sung nằm tại
[`opening_extension_model.json`](../02_CSDL/opening_extension_model.json).
Migration 001–009 và baseline giữ nguyên. Phiếu legacy không được điền dữ liệu hoặc approval giả để hợp thức hóa.

## Kiểm thử và phần còn lại

[`test_openings.py`](../tests/foundation/test_openings.py) kiểm thử IAM/scope/SOD/replay, policy một/hai bước,
snapshot, vòng đời, period/count lock, precision, NONE/LOT/SERIAL, cạnh tranh transaction và rollback ở ledger,
balance, audit, outbox, đối soát và nâng cấp từ 009. Kết quả chạy thực tế, lệnh và giới hạn nằm trong
[`AGENT_OPENING_REPORT.md`](../07_Kiem_tra/AGENT_OPENING_REPORT.md).

Chưa triển khai import file, UI, ký gửi, điều chỉnh/đảo, lịch cutover cấu hình hoặc xác minh biên bản ký.
T01–T28 vẫn giữ trạng thái nghiệm thu hiện có; không thay thành PASS từ kiểm thử module.
