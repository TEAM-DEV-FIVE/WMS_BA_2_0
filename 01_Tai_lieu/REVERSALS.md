# Đảo một lần ghi sổ — B14

Phiếu REVERSAL đảo **toàn bộ một inventory_transaction**, bằng các stock_move mới có cùng danh tính
tồn, đơn vị, số lượng và hoán đổi nguồn/đích. Liên kết gốc→đảo nằm trên transaction, từng move,
reversal_document/reversal_line và document_link. Không sửa/xóa transaction, move, reservation consumption,
quyết định QC, snapshot kiểm kê hoặc chứng cứ bảo hành cũ.

## Thao tác và quyền

Trong Desktop chọn **Đảo giao dịch**, kho của chứng từ gốc, tải lần ghi sổ gốc, chọn ngày đảo rồi
**Xem trước ảnh hưởng**. Màn hình hiển thị danh tính, từng leg, tồn hiện tại, giữ chỗ, lượng thay đổi,
tồn sau đảo và lý do chặn. Nhập lý do, lưu nháp, gửi duyệt; một người độc lập duyệt trước khi ghi sổ.
Phiếu đã có nguồn không được đổi sang transaction khác. Muốn đổi nguồn: hủy nháp và tạo phiếu mới.

- Đọc: document.read; tạo/sửa/gửi/sửa lại: adjustment.draft; duyệt: adjustment.approve;
  post: adjustment.post; phân công/hủy dùng document.assign/document.cancel hiện có.
- TRANSFER và loss adjustment yêu cầu quyền tại **cả hai kho**, kể cả đọc và replay/tra ACK.
  Danh sách nguồn được phân trang theo kho chính của chứng từ.
- ADJUST từ kiểm kê còn yêu cầu count.snapshot.read. Người được phân công đếm không được dùng
  màn đảo để xem số liệu của phiên đếm mù, kể cả khi được cấp thêm vai trò kiểm soát viên.
- Migration 020 thêm policy REVERSAL một bước CONTROLLER khi chưa có policy loại này.
  Policy tùy biến, kể cả policy vô hiệu, được giữ nguyên. Creator/submitter không tự duyệt.

Preview chỉ phản ánh thời điểm đọc. Máy chủ kiểm tra lại version, snapshot duyệt, nguồn, kỳ, vị trí,
serial, reservation và số dư dưới khóa khi ghi sổ. Lưu nháp không cho client gửi lượng/owner/vị trí tự chọn.

## Ma trận điều kiện

Mọi trường hợp chỉ hỗ trợ COMPANY, đúng tracking và lượng của từng stock_item. Chặn kỳ gốc hoặc kỳ đảo
đã khóa/không tồn tại, ngày đảo trước ngày gốc, kho/vị trí không hoạt động, vị trí khóa kiểm kê,
không đủ đúng danh tính tồn hoặc đang giữ chỗ ở vị trí phải lấy hàng. Reservation đã hết thời hạn nhưng
chưa được giải phóng vẫn có hiệu lực. Lô hết hạn theo ngày vận hành hiện tại không được đảo vào STORAGE.

| Nguồn | Nghịch đảo | Giới hạn riêng |
| --- | --- | --- |
| RECEIVE của phiếu nhận | Vị trí nhận → EXTERNAL gốc | Có kế hoạch PO đã xác minh; chặn QC đã quyết định, trả nhà cung cấp còn hiệu lực và hàng đã đi tiếp |
| OPEN | Vị trí tồn đầu → OPENING gốc | Giữ metadata/biên bản; net về 0 vẫn không mở lại cửa sổ nạp tồn đầu |
| ISSUE | EXTERNAL → vị trí xuất gốc | Chặn phiếu khách trả đang xử lý/đã post chưa đảo; không hồi sinh reservation hoặc giảm consumed |
| MOVE / putaway | Đích → nguồn gốc | Chặn hàng ở đích đã đi tiếp/giữ chỗ; decision_moved tính ròng nhưng giữ quyết định QC và followup cũ |
| DISPATCH | TRANSIT → kho nguồn | Chặn ARRIVE/LOSS còn hiệu lực và loss draft chưa hủy; phải đủ đúng transit riêng của transfer |
| ARRIVE | Kho đích → TRANSIT | Chặn hàng đã đi tiếp; received/remaining transit tính ròng; có thể nhận lại bằng lệnh ARRIVE mới |
| SUPPLIER_RETURN | EXTERNAL → vị trí trả gốc | Giữ nguồn receipt và PO; lượng đã trả tính ròng, không coi là một lần nhận mua mới |
| CUSTOMER_RETURN | Vị trí nhận trả → EXTERNAL | Giữ nguồn issue/SO; chặn QC/hàng đã đi tiếp; không coi là xuất bán mới |
| ADJUST kiểm kê | Hoán đổi từng leg | Phiên POSTED có liên kết adjustment; giữ số đếm/snapshot/quyết định và khóa đã giải phóng |
| ADJUST mất hàng transit | LOSS → TRANSIT | Có liên kết transfer/discrepancy; lost và lượng discrepancy đã xử lý tính ròng |
| REVERSE, nguồn đã đảo, giao dịch rỗng | Chặn | Không đảo phiếu đảo, không đảo trùng, không tạo bút toán rỗng |
| Nguồn legacy thiếu kế hoạch/liên kết | Chặn | Không suy lịch sử chỉ từ loại chứng từ hoặc tồn hiện tại |
| CONSIGNOR / UNCLASSIFIED | Chặn | B09 chưa mở policy đảo; không sửa guard hoặc mượn tồn COMPANY để bù |

Với NONE/LOT gộp lượng, không có provenance từng đơn vị hàng. Engine bảo thủ: nếu đúng stock_item tại
đích gốc từng có phát sinh lấy đi **chưa đảo**, chặn đảo nguồn đó; việc nhập bù cho đủ số dư không chứng minh
hàng gốc còn nguyên. Không suy nguồn từ posted_at. Các cặp gốc–nghịch đã đảo đầy đủ được loại khỏi guard.
Quy tắc này có thể chặn cả phát sinh cũ không phân bổ được; cần chứng từ bù được duyệt thay vì tự ép đảo.

## Lịch sử và lượng ròng

Header gốc giữ trạng thái, closed_base và nội dung; version tăng để chặn màn hình/bản duyệt đảo đã cũ.
Phiếu đảo COMPLETED và có transaction mới. PO/SO, receipt/issue/return, QC và transit tính net bằng cách
loại original move đã có inverse; không đồng thời trừ inverse lần nữa. Không tự mở lại PO/SO hay batch OPENING.
Một transfer COMPLETED có lượng transit được phục hồi có thể nhận lại qua lệnh mới, đúng snapshot duyệt
ban đầu, quyền hiện tại, version mới, ngày/kỳ, nguồn và số dư. DISPATCH không tự thực hiện lại.

## API và khôi phục

- `GET /api/v1/reversals?warehouse_id=…`, `/reversals/sources?warehouse_id=…`: phân trang UUID.
- `GET /api/v1/transactions/{id}/reversal-preview?business_date=YYYY-MM-DD`.
- `POST /api/v1/reversals`: source_transaction_id, source_version, business_date, reason.
- `PUT /api/v1/reversals/{id}`: như tạo, thêm expected_version.
- `GET /api/v1/reversals/{id}`: nguồn, plan, preview, lịch sử duyệt và ID giao dịch đảo nếu đã post.
- Lifecycle dùng `/documents/{id}/submit|revise|cancel|assignments` và `/approval-requests/{id}/decide`.
- `POST /api/v1/reversals/{id}/post`: expected_version, execution_key, reason.
- `GET /api/v1/reversals/operations/{Idempotency-Key}`: command và ACK đã commit của chính actor;
  bao gồm lifecycle generic. Kiểm quyền hiện tại; 404 không chứng minh yêu cầu cũ chưa commit.

Mọi mutation cần UUID Idempotency-Key. Cùng actor/key/nội dung trả ACK cũ; đổi nội dung bị chặn.
Execution key bảo vệ riêng lần post, kể cả HTTP key thay đổi. Desktop giữ bản sao payload/key trong RAM,
khóa lệnh mới khi chưa rõ kết quả, xác minh kind/scope/target/version/source/command của ACK, cô lập
kết quả theo phiên/người/kho. Tra ACK hoặc gửi lại đúng yêu cầu; journal bền sau restart thuộc B19.

## Transaction, khóa và schema

Command lock → tổ tiên chứng từ theo cấp và UUID (count session trước adjustment) → chứng từ đảo →
kho theo UUID (SHARE) → kỳ theo UUID → vị trí và tổ tiên theo UUID → product/stock_item → balance
theo location/stock → serial. Dùng cùng hàng kho/kỳ/vị trí với B13 close/freeze để tuần tự hóa.
Đọc lại downstream sau khi khóa. Mọi ledger, balance, serial_position, version nguồn/đảo, audit,
outbox và ACK commit hoặc rollback trong cùng UoW. Không gọi I/O ngoài DB trong handler.

Migration [020](../migrations/020_b14_reversal.sql) bổ sung hai bảng, bốn FK và deferred constraint
triggers chứng minh đủ dòng và nghịch đảo chính xác của duy nhất một original transaction. Giữ nguyên
001–019, guard owner và unique reverse/execution của baseline. Schema tổng: 89 bảng, 584 cột, 188 FK;
58 permission và 125 role-permission. Các thử nghiệm nâng cấp dùng DB tạm, không nâng DB vận hành.

Bằng chứng chạy và giới hạn môi trường nằm trong [bàn giao B14](PHAN_CONG/BAN_GIAO/B14.md).
Kiểm thử tự động không đổi T01–T28 sang ACCEPTED; Windows/DPI, thiết bị, LAN, tải và DR theo các nhánh riêng.
