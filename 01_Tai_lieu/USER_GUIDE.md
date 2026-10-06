# Hướng dẫn sử dụng theo vai trò

Áp dụng bản tích hợp B01–B24. Mỗi người dùng một tài khoản; quyền được cấp theo kho và theo nghiệp vụ.
SYSADMIN quản trị tài khoản/cấu hình, không tự có quyền ghi sổ kho. Người lập/gửi/đếm không tự duyệt.

## Bắt đầu ca

1. Mở WMS bằng profile IT đã cấp, kiểm tra đúng URL HTTPS, kho, tài khoản và ngày nghiệp vụ.
   Lỗi chứng thư hoặc thông báo server không tương thích: dừng thao tác, báo IT; không bỏ kiểm tra TLS.
2. Đăng nhập/MFA. Khi hết phiên hoặc đổi tài khoản, tải lại dữ liệu bằng phiên mới. Không dùng màn còn
   hiển thị từ người trước để quyết định duyệt; server luôn kiểm tra lại quyền hiện hành.
3. Xem **Nháp / phục hồi lệnh** trước khi làm lại nghiệp vụ đang dang dở. DRAFT là nháp trên máy,
   SUBMITTED là gửi duyệt, APPROVED là được duyệt, POSTED/COMPLETED phải đọc đúng ý nghĩa từng loại.
   PO/SO COMPLETED có thể là đóng phần chưa thực hiện, không đồng nghĩa đã nhận/xuất đủ.

## Nhân viên nhận hàng

1. Mở PO nguồn đã duyệt còn lượng nhận; kiểm đối tác, kho, SKU/UOM, owner và ngày.
2. Tạo phiếu nhận từng phần, ghi số thực nhận, vị trí nhận, lô/serial/hạn dùng theo sản phẩm.
   Trường tùy biến lấy schema hiện hành; lỗi bắt buộc/kiểu dữ liệu phải sửa trước gửi.
3. Lưu, gửi duyệt và người đủ quyền duyệt theo policy. Đọc lại version trước ghi sổ.
4. Ghi sổ một lần, kiểm ACK và lượng còn mở của PO. Timeout chuyển sang phục hồi; không lập phiếu khác.
5. Kiểm chất lượng rồi đưa lượng đạt vào STORAGE, lượng không đạt vào QUARANTINE bằng luồng chất lượng/
   di chuyển. Hàng cách ly vẫn tồn vật lý nhưng không tự đủ điều kiện xuất.
   Ví dụ nhận 80 từ PO100, cất75/cách ly5: vật lý80, PO còn20.

Chi tiết nguồn/vị trí/idempotency: [Nhận hàng](RECEIVING.md), [Chất lượng/di chuyển](MOVE_QUALITY.md).

## Nhân viên soạn và xuất

1. Chọn SO đã duyệt và tạo ISSUE từ dòng còn mở. Kiểm đúng kho, owner, UOM và vị trí.
2. Giữ hàng trên stock item đủ điều kiện; không lấy hàng cách ly, hàng khóa kiểm kê hoặc trộn ký gửi.
   Lượng available có thể đổi do người khác thao tác; đọc lại khi server báo thiếu tồn/stale.
3. Người được phân công xác nhận soạn, đóng kiện theo luồng [Fulfillment](FULFILLMENT.md).
   Quét HID chỉ chọn/điền dữ liệu, không thay xác nhận soạn hoặc tự ghi sổ.
4. Kiểm chứng từ/kiện/số lượng, ghi sổ xuất từng phần. Reservation đã tiêu thụ và ledger phải cùng giao dịch.
5. Hủy/đóng lượng chưa thực hiện phải nhập lý do; không xóa chứng từ đã ghi sổ và không tự sửa số dư.

Tham khảo [Giữ hàng/xuất](ISSUES_RESERVATIONS.md), [PO/SO và duyệt](DOCUMENTS_UI.md).

## Chuyển kho, trả hàng và đảo sai sót

- Chuyển: kho nguồn dispatch vào TRANSIT, kho đích receive số thực nhận. Giao20/nhận18 giữ2 ở TRANSIT
  và lập xử lý chênh lệch; không tự ghi2 là mất chỉ từ ghi chú. Đọc quyền cả hai kho. [Quy trình](TRANSFERS.md).
- Khách trả: chọn giao dịch/dòng xuất gốc, số có thể trả và chất lượng nhận. Trả NCC: chọn receipt nguồn,
  tồn thực còn và luồng duyệt; không vượt số nguồn hoặc tồn. [Quy trình](RETURNS.md).
- Đảo: người có quyền chọn đúng lần ghi sổ, đọc tác động tồn/source/serial, nhập lý do, gửi và duyệt theo
  policy; server kiểm lại đủ hàng và kỳ. Đảo tạo giao dịch bù, giữ nguyên ledger gốc. Nếu hàng đã đi tiếp,
  không ép đảo bằng SQL hoặc sửa quantity. [Quy trình](REVERSALS.md).

## Quản lý kho và người đếm

1. Manager tạo phiên đúng vị trí, ít nhất hai người đếm; kiểm không còn reservation vướng rồi freeze.
   Vị trí khóa không nhận giao dịch cạnh tranh. Chia phiên trước freeze nếu vượt giới hạn.
2. Người được phân công vào form đếm mù; không được nhìn lượng sổ, delta hoặc vòng trước.
   Đếm0 là hợp lệ, serial chỉ0/1. Hàng ngoài snapshot phải xác minh danh tính/owner rồi thêm theo form.
3. Hai vòng cuối phải khớp và do người khác thực hiện; vị trí trống cũng cần xác nhận độc lập.
4. Manager submit; CONTROLLER và DIRECTOR duyệt hai bước, khác người lập/đếm và khác nhau.
5. CONTROLLER ghi sổ điều chỉnh; đọc trạng thái POSTED và kiểm giải khóa. Không phát tán báo cáo R07
   cho người đang đếm để né đếm mù. [Chi tiết kỳ kho/kiểm kê](COUNTING_PERIODS.md).

Đóng kỳ chỉ sau xử lý chứng từ dở dang, kiểm kê và đối soát. Mở lại kỳ cần quyền/lý do/audit, không đổi
ngày nghiệp vụ để né kỳ đóng.

## Tồn đầu kỳ và import

Cutover có biên bản kiểm đếm thực và người phê duyệt. Kho opening chưa có lịch sử tồn; không dùng opening
để điều chỉnh kho đang hoạt động. Tải mẫu hiện hành từ **Import tệp / tồn đầu kỳ**, giữ barcode/serial là text.
Upload → tạo job/dry-run → đọc tất cả lỗi → xác nhận hash/token → commit. Commit import chứng từ chỉ
tạo DRAFT; tiếp tục gửi/duyệt/ghi sổ trên form nghiệp vụ. Không chia tệp để vượt quy tắc opening một lần.

Mở tab **Lịch sử import**, chọn loại/kho, ngày UTC và trạng thái rồi **Tải lịch sử**; chọn job để **Mở job đã chọn**. Có thể nhập mã job trực tiếp để **Đọc / tiếp tục**. Tệp đổi sau dry-run phải chọn/kiểm lại; hết hạn token phải validate lại.
Trường hợp UNKNOWN tra trạng thái bằng mã cũ trước khi gửi lại. [Import](IMPORT_DESKTOP.md),
[Opening](OPENING_DESKTOP.md), [giới hạn dữ liệu](IMPORTS.md).

## Báo cáo, owner và bảo hành

Chọn kho, R01–R08 và bộ lọc phù hợp; tạo snapshot, xem trang rồi xuất CSV/XLSX, đợi READY mới tải.
Snapshot giữ thời điểm và filter, hết hạn sau1giờ. Tạo mới để có số liệu mới, không sửa file thành báo cáo
nguồn chính thức. Quyền export/giá/owner bị thu hồi sẽ chặn tải cả file đã READY.

R01 phân biệt physical/transit/eligible/reserved/available. R08 là giá tham chiếu quản trị.
Không cộng COMPANY với CONSIGNED để suy hàng doanh nghiệp có thể xuất. Khi tra serial, bảo hành chỉ
còn/hết theo dữ liệu thời hạn và nguồn hợp lệ; thiếu nguồn là **Chưa xác định**.
Xem [ý nghĩa R01–R08](REPORTS_EXPORT.md), [chủ sở hữu](CONSIGNMENT.md), [truy vết](TRACEABILITY.md).

## In và máy quét

Mở **In chứng từ / tem**, chọn kho/mẫu/nguồn/version/khổ, tạo PDF, xem từng trang rồi chọn máy in/số bản.
Phiếu A4/A5, tem100×50 hoặc80×40mm. Kiểm mẫu InternTechLead, MST/điện thoại/tên người ký; ô ký vẫn cần
người thật ký. Phiếu kiểm kê luôn mù. In không ghi sổ tồn.

SUBMITTED chỉ chứng minh spooler đã nhận, chưa chứng minh đã ra giấy. Timeout/crash giữ UNKNOWN;
kiểm máy/giấy/hàng đợi trước **In lại**, không bấm liên tục. Ô HID cần focus, quét rồi Enter/Tab;
đối chiếu SKU/serial/UOM/số lượng trước xác nhận. [Chi tiết in/HID](PRINTING_SCANNER.md).

## Mất mạng, stale và kết ca

- Để giữ nội dung nháp: bật **Chỉ lưu nháp nghiệp vụ (trừ IAM/tệp)** rồi bấm thao tác lưu của form.
  Chữ đang gõ chưa bấm lưu không được tự lưu. Không đăng nhập hoặc ghi sổ offline.
- UNKNOWN: mở **Nháp / phục hồi lệnh**, **Tra ACK** trước, chỉ chủ động gửi lại nguyên key/body khi
  server xác nhận chưa có kết quả. Không tạo key khác, đổi version hay xóa cache để né lệnh chưa rõ.
- CONFLICT/stale: đọc lại và đối chiếu hiện trạng. Không tự coi mọi lỗiHTTP là transaction đã rollback;
  chỉ ACK/proof hợp lệ mới xác định kết quả. Lệnh print phục hồi không gọi lại máy in.
- Kết ca: kiểm nháp/UNKNOWN, phiếu chưa xử lý, công việc được giao; đăng xuất. Không sao chép SQLite
  đang mở hoặc để trên SMB. Giữ thư mục device/receipts/commands khi nâng cấp.

Gửi hỗ trợ: commit/version, thời điểm, kho, loại thao tác, mã phiếu/job/operation và mã lỗi, các bước tái lập.
Không gửi password, OTP, token hoặc nội dung dump. [Quy tắc phục hồi đầy đủ](RECOVERY_ALL.md).

## Lịch sử export

Trong Báo cáo, chọn kho và R01–R08, mở tab **Lịch sử export** rồi **Tải lịch sử**.
Ngày nhập theo YYYY-MM-DD (UTC), ngày kết thúc bao gồm cả ngày đó. Trang trước/sau dùng con trỏ
ổn định; đổi bộ lọc bắt đầu lại trang đầu. Mở job còn hiệu lực để đọc trạng thái, tải file READY,
hủy hoặc retry job FAILED. Mỗi thao tác kiểm tra lại quyền hiện tại.
Chỉ thấy job của chính mình còn đủ quyền (bao gồm quyền giá/hai kho/kiểm kê nếu có).
Job hết hạn chỉ còn metadata; tạo snapshot mới để xuất dữ liệu hiện tại.
Các tombstone đã dọn bằng phiên bản cũ và mất thông tin quyền không được khôi phục vào lịch sử.
