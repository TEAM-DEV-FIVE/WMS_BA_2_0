# Chuyển kho, transit và xử lý thiếu B11

## Luồng đang chạy

TRANSFER có hai kho khác nhau và một vị trí TRANSIT riêng, do server tạo; không nhận
transit ID từ client và không tái sử dụng transit của phiếu khác. Lập kế hoạch theo
stock_item_id/vị trí STORAGE/SL cơ sở (tối đa 200 dòng), phân công trước duyệt, gửi
và duyệt độc lập theo policy thật. Draft/edit và duyệt cần quyền cả hai kho. Bản
snapshot giữ hai kho, transit, toàn bộ dòng và kế hoạch danh tính nguồn. Sửa phiếu
đã duyệt phải revise, vô hiệu duyệt cũ; phiếu đã ghi sổ không sửa/hủy/đóng thiếu.

Xuất chuyển **toàn kế hoạch một lần**, có biên bản soạn/giao bắt buộc. Người lập/
được giao có transfer.dispatch ở kho nguồn thực hiện; server kiểm lại duyệt, hàng
STORAGE còn hạn theo ngày hiện tại của doanh nghiệp và tồn chưa giữ chỗ. B02 giữ
chỗ hết hạn vẫn chiếm reserved đến khi release; B11 không tiêu thụ hoặc di chuyển
reservation của ISSUE/SO. Phiếu có task/kiện cần workflow picking tương ứng bị
chặn. B11 không tự tạo task B10 hoặc tuyên bố picking tự động đã tích hợp: B10 và
B11 là hai nhánh ngang hàng trong DAG. Biên bản ở đây xác nhận chuẩn bị/giao thực tế.

DISPATCH giảm nguồn, tăng transit; trạng thái PARTIAL. ARRIVE nhận từng phần từ
**dispatch_move_id** của chính phiếu, giữ stock_item/owner/agreement/lot/serial.
Ngày nhận không trước ngày gửi. Hàng tốt vào RECEIVING; hàng hỏng vào QUARANTINE,
luôn có chứng cứ giao nhận. Nhận 18/20 giữ 2 tại transit; hàng transit không có
available để bán. Hàng đã nhận tiếp tục qua quality.decide và INTERNAL_MOVE B03
ở kho đích. ARRIVE là nguồn kiểm định; không giả thành receipt mua hàng hoặc tạo
nguồn bảo hành mới. Serial giữ receipt_move_id và chứng cứ bảo hành gốc.

## Quyền và nguyên tử

Dispatch cần scope kho nguồn, receive/ghi thiếu cần scope kho đích và người lập/
được giao. API transfer có projection riêng: người chỉ có kho đích đọc phiếu được
giao nhưng không nhận vị trí nguồn, giá hoặc tồn kho nguồn. Không nới quyền đọc
chứng từ chung. Quản lý có document.read ở một kho có thể xem dữ liệu chuyển liên
quan; thao tác quản lý/duyệt vẫn cần cả hai kho. Phân công chỉ chọn user đang hoạt
động có document.read trong ít nhất một kho của phiếu; không tự cấp thêm quyền.

Mọi command kiểm quyền hiện tại trước trả idempotency replay. Posting có thêm
execution_key, hash và ACK bất biến theo người/document/nội dung. Retry đổi HTTP
key nhưng giữ execution_key không thêm ledger. Hết quyền vẫn không đọc được ACK.

Khóa parent TRANSFER trước ADJUSTMENT, rồi warehouse theo UUID, kỳ thực tác động,
vị trí/tổ tiên + transit theo UUID, product/identity, balance theo location/item và
reservation. Dispatch kiểm kỳ nguồn; receive kiểm kỳ đích theo ngày nhận; loss
kiểm cả hai kỳ. Tất cả giữ warehouse SHARE ở cả hai kho để phối hợp cutover.
Freeze kiểm lại dưới location lock. Chỉ số dư thật được kiểm tra tại thời điểm post.
Ledger, source links, balance, serial_position, trạng thái/version, audit, outbox và
ACK chung một transaction; lỗi bất kỳ không để lại lượng/hồ sơ ghi sổ một phần.

## Thiếu và điều chỉnh mất

Ghi biên bản MISSING/DAMAGED lưu dispatch_move_id, lượng, người/thời điểm và
`evidence_ref` bắt buộc. Chứng cứ là tham chiếu biên bản thực tế; API này không tải
file hay tự xác nhận chữ ký. Biên bản append-only, không có stock_move và không
cộng các biên bản bổ sung thành lượng mất. Lượng còn lại luôn suy từ ledger.

Sau xác minh mất, WAREHOUSE_MANAGER có adjustment.draft ở cả hai kho lập phiếu
ADJUSTMENT riêng từ một biên bản, chọn lượng và ngày điều chỉnh. Dòng tham chiếu
đúng dòng TRANSFER. Phiếu được gửi duyệt; CONTROLLER có adjustment.approve ở cả
hai kho duyệt độc lập, không là creator/requester. Policy seed một bước kiểm soát
chỉ được thêm nếu chưa có policy ADJUSTMENT; không ghi đè cấu hình. Post cần
adjustment.post ở cả hai kho và bản duyệt đúng snapshot. Lượng không vượt chứng
cứ chưa xử lý hoặc phần transit còn thực tế; receive cạnh tranh với loss dùng
cùng parent lock. ADJUST chuyển transit → đối ứng LOSS, không tạo balance LOSS.
Chỉ khi nhận + mất được duyệt bằng lượng gửi thì TRANSFER COMPLETED.

Phiếu loss không có sửa lượng tại chỗ: hủy nháp/từ chối và lập phiếu đúng, giữ lịch
sử. Đây chỉ là điều chỉnh mất từ transit; không phải engine kiểm kê/điều chỉnh
chung của B13. B13 có thể dùng contract nguồn này, không cần dependency vòng.

## API và sự kiện

- GET/POST `/api/v1/transfers`; GET/PUT `/{id}`; GET `/stock`, `/locations`.
- GET `/{id}/assignees`, `/{id}/history`, `/{id}/discrepancies`, `/{id}/adjustments`:
  phân trang UUID `after`/`limit`. Lịch sử có thời điểm, transaction_id,
  dispatch_move_id, disposition, quantity và chứng cứ. Màn chi tiết có tối đa 200
  biên bản/phiếu con gần nhất; các endpoint phân trang truy cập đầy đủ lịch sử.
- POST `/{id}/dispatch`: expected_version, execution_key, reason, evidence_ref.
- POST `/{id}/receive`: thêm business_date và lines gồm dispatch_move_id,
  destination_location_id, quantity_base, disposition GOOD/DAMAGED.
- POST `/{id}/discrepancies`: expected_version, reason, dispatch_move_id,
  kind MISSING/DAMAGED, quantity_base, evidence_ref. Không có execution ledger.
- POST `/{id}/adjustments`: expected_version của TRANSFER, reason,
  discrepancy_id, quantity_base, business_date; trả ADJUSTMENT DRAFT.
- GET `/transfers/{adjustment_id}` đọc phiếu loss; POST `/{adjustment_id}/loss-post`
  dùng payload cùng dispatch. Các thao tác submit/decide/revise/cancel/assign dùng
  API documents/approval-requests hiện có; không nhận generic update PO/SO cho B11.
- GET `/transfers/operations/{key}` trả TransferPostResult của actor hiện tại,
  gồm operation DISPATCH/ARRIVE/ADJUST, source_transfer_id khi là loss,
  warehouse_id, destination_warehouse_id, transaction_id, status/version/request_id.
  Các lượng trong DTO là Decimal string, không dùng float.

Audit/outbox: `transfer.create/update/submit/decide/revise/cancel/assign/dispatch/
receive/discrepancy` và `transfer.loss.create/submit/decide/revise/cancel/assign/post`,
suffix `.v1` cho outbox. Lifecycle chung giữ OrderResult; create/update/evidence
trả TransferResult; posting trả TransferPostResult. Source links và quantities lấy
qua GET chi tiết/history. Không thêm consumer, không I/O trong DB transaction;
B20 đăng ký consumer khi có nghiệp vụ cụ thể, dedup theo event_id + tên/version.

## Desktop và đối soát

Tab **Chuyển kho / transit** có kế hoạch, nhận/thiếu, điều chỉnh mất, lịch sử và
phân công. HTTP chạy worker; callback/huỷ Tk ở main thread, bỏ response phiên/kho
cũ. Yêu cầu UNKNOWN giữ nguyên body/key theo user/kho, chỉ retry/tra ACK theo thao
tác cũ. ACK dispatch PARTIAL và receive PARTIAL là kết quả hợp lệ; UI tải lại
trạng thái hiện tại sau ACK. Bộ nhớ phục hồi hiện là RAM; journal restart thuộc B19.

R05 lấy từng nguồn dispatch: dispatched − received − lost = remaining. R02 tính
ledger theo ranh giới kho: +quantity khi đích ở kho, −quantity khi nguồn ở kho;
MOVE trong cùng kho tự triệt tiêu. Không cộng transit vào available/physical kho,
không cộng số lượng khác UOM. B17 sở hữu màn báo cáo đầy đủ; B11 cung cấp nguồn và
kiểm thử đối soát, không nhận là đã triển khai toàn bộ report UI.

Chạy `02_CSDL/reconcile.sql` và `02_CSDL/reconcile_transfers.sql`: mọi result set
phải rỗng. Kiểm thử có nhận 18/20, nhận nốt/điều chỉnh mất cạnh tranh, owner,
reservation thật, LOT/SERIAL, bảo hành nguồn, kỳ/freeze, rollback, API/Tk/HTTP và
nâng cấp legacy. Kho thứ hai chỉ là fixture; chưa xác nhận có hai kho vận hành.

## Migration và giới hạn bàn giao

`015_b11_transfer.sql` là revision phát triển, chỉ cho DB tạm. Thêm 4 bảng typed,
18 cột, 11 FK; tổng 76 bảng/509 cột/159 FK. Model/dictionary/DBML đi cùng migration.
Không sửa 001–014 đã tích hợp; điều phối chọn số release tiếp theo và chạy fresh/
upgrade từ release 014 khi tích hợp B11. Không tái dùng DB tạm có lịch sử số cũ.

Chỉ COMPANY được chuyển. CONSIGNOR/UNCLASSIFIED bị từ chối; không đổi chủ hay nới
agreement một kho của B09. Reversal transfer chưa được mở, cần B14 review source
links và dependencies. Windows, thiết bị, 15 CCU, DR và UAT cần bằng chứng riêng.
Kết quả local/commit và phạm vi T02/T04/T17/T21/T27 nằm trong báo cáo B11.
