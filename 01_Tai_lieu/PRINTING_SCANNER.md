# In chứng từ, tem và máy quét HID — B18

Bản triển khai mẫu v1 trên nền B01–B17. Theo trao đổi người dùng, model thiết bị,
khổ tem thực tế và mẫu tham chiếu Q06/Q08 được bổ sung sau; vẫn triển khai đầy đủ local.
Các mẫu dưới đây là lựa chọn khởi đầu, chưa thay cho mẫu nghiệp vụ đã được duyệt.

## Mẫu và dữ liệu

| Mẫu | Nguồn thật | Khổ hỗ trợ | Quy tắc |
| --- | --- | --- | --- |
| Phiếu nhập | RECEIPT, dòng, kế hoạch lô/serial/vị trí | A4/A5 | Lượng yêu cầu và đã ghi sổ tách riêng |
| Phiếu xuất | ISSUE, dòng, tiến độ sổ | A4/A5 | Không xác nhận giao hàng bằng trạng thái in |
| Phiếu chuyển | TRANSFER, dòng, stock item/vị trí | A4/A5 | Cần quyền đọc/in cả hai kho |
| Phiếu kiểm kê | COUNT, các dòng trong phạm vi hiện tại | A4/A5 | Luôn đếm mù, không in snapshot/số đã đếm/delta |
| Tem hàng/serial | Product, serial được phép tra trong kho | 100×50 / 80×40 mm | SKU Code128; serial hoặc SKU dài/Unicode dùng QR |
| Tem vị trí | Location đang hoạt động trong kho chọn | 100×50 / 80×40 mm | QR chứa chính xác mã vị trí |

Font DejaVu Sans được đóng gói cùng giấy phép và nhúng trong PDF. ReportLab sinh PDF
với timestamp xác định để cùng snapshot cho cùng hash. Dữ liệu được escape trước khi
render, bảng lặp tiêu đề và phân trang. Tên dài trên tem có dấu rút gọn; mã trong barcode
không bị rút gọn. QR mức sửa lỗi M, vùng trắng; Code128 độ rộng vạch 0,25 mm.
Kiểm thử ZXing đọc lại ảnh PDF ở 300 dpi; kết quả không thay nghiệm thu máy in thực.

Snapshot là projection cho phép rõ ràng, không sao chép raw attributes, custom fields
hoặc lịch sử duyệt. Giá tham chiếu chỉ được lấy khi người dùng chọn và có `price.read`.
Không có quyền thì không lưu giá vào snapshot. Bản có giá bị chặn ở read/download,
worker và gửi in sau thu hồi quyền. File đã được người dùng lưu hoặc spooler nhận
không thể thu hồi từ xa. Đây là giá tham chiếu, không phải giá vốn kế toán.

## API, transaction và trạng thái

- `GET /api/v1/printing/sources`: tìm nguồn theo mẫu/kho/mã, tối đa 50 kết quả.
- `POST /api/v1/printing`: `PrintCreate`, source version, snapshot v1, hết hạn 1 giờ.
- `GET /api/v1/printing/{id}`: metadata/hash/lượt gửi máy in hiện tại của người tạo.
- `GET /api/v1/printing/{id}/download`: PDF riêng; xác thực trước và sau file I/O.
  `attempt_id` tùy chọn yêu cầu đúng lượt và phiên đang gửi máy in.
- `POST /api/v1/printing/{id}/retry|reprint|cancel`: expected_version, lý do, audit.
- `POST /api/v1/printing/{id}/spool`: nhận lượt gửi độc quyền theo job/generation,
  UUID attempt, máy in/driver/số bản (1–20). Trạng thái ban đầu UNKNOWN.
- `POST /api/v1/printing/{id}/result`: kết quả UNKNOWN/FAILED/SUBMITTED + spool id.
- `POST /api/v1/printing/scan`: tra cứu chỉ đọc theo flow/source/version/code/quantity;
  dùng Idempotency-Key theo envelope API chung, không lưu command hay ghi tồn.

Tất cả command DB khác dùng kernel chống trùng, kiểm tra quyền hiện tại trước replay,
version, rollback cùng job/audit/outbox/ACK. Snapshot REPEATABLE READ; tối đa 1.000 dòng,
2 MiB payload, 20 job chưa hết hạn/người, 10 generation/job. Không lệnh nào gọi posting.
Job render: QUEUED → RENDERING → READY hoặc FAILED; cancel dừng quyền truy cập.
`retry` chỉ cho lỗi render. `reprint` chỉ sau một lượt gửi máy in, yêu cầu kiểm tra giấy
và xác nhận rõ ràng. Không có trạng thái PRINTED vì adapter hiện chưa có bằng chứng
thiết bị đã in giấy. Timeout/crash có thể xảy ra sau khi thiết bị đã nhận; giữ UNKNOWN.

Mỗi job/generation chỉ nhận một attempt. Presenter giữ key/body trong RAM; phục hồi
ACK không bao giờ gọi lại adapter máy in. Khi mất ACK của spool claim, operator tra
cùng key, kiểm tra thiết bị rồi chọn In lại nếu cần. B19 sẽ nối journal phục hồi chung;
không thêm SQLite migration và không lưu bearer token/credential.

## Worker và lưu trữ

Migration `023_b18_printing_scanner.sql`: print_job, print_task, print_attempt; trigger
bảo vệ snapshot bất biến. 001–022 và SQLite 001–002 không đổi. Không backfill tồn.

Consumer factory `apps.server.application.print_jobs:consumer_factory`, consumer
`print.enqueue.v1`, event `print.requested.v1`, payload duy nhất `{job_id,generation}`.
Handler outbox chỉ INSERT durable print_task với UNIQUE(job_id,generation), không render
hay gọi máy in trong transaction. B20 ghép factory này vào registry vận hành chung.

```bash
rtk proxy env PYTHONPATH=. .venv/bin/python -m apps.server.worker --once --consumer-factory apps.server.application.print_jobs:consumer_factory
rtk proxy env PYTHONPATH=. .venv/bin/python -m apps.server.print_worker --once
rtk proxy env PYTHONPATH=. .venv/bin/python -m apps.server.print_cleanup
```

Cấu hình worker `WMS_PRINT_STORAGE_ROOT` (mặc định `.wms-print-files`) phải khác import
và export storage. Quyền thư mục riêng như B01/B17. Executor lease + fencing; chỉ publish
file sau kiểm tra lại session/quyền. Reprint cùng snapshot tái dùng object/metadata đã có.
Cleanup dùng advisory lock riêng B18, không mở DB transaction trong I/O; xóa PDF hết hạn,
đánh dấu job hủy và dọn orphan cũ hơn 24 giờ. Giữ snapshot và attempt/audit cho đối soát;
chính sách lưu hồ sơ dài hạn do B22/B25 vận hành, không tự xóa lịch sử nghiệp vụ.
Không tải PDF này qua `/files` của import.

## Desktop và driver

Màn `In chứng từ / tem`: chọn kho/mẫu, tìm số phiếu/SKU/vị trí, chọn khổ, tạo PDF,
đọc trạng thái, xem từng trang, lưu tệp, chọn máy in/copies rồi gửi. Tác vụ HTTP, file,
render preview và spooler chạy worker; Tk/ImageTk và dọn tài nguyên chạy main thread.
Đổi phiên/kho/nguồn loại phản hồi cũ. Trước spool luôn tải lại có kiểm tra quyền, không
in từ preview cache. Trạng thái SUBMITTED chỉ có nghĩa spooler đã nhận.

Windows 10/11: enumerate driver đã cài bằng Winspool, cấu hình DEVMODE khổ giấy,
PDFium raster 300 dpi + GDI StartDoc/StartPage/EndDoc. Kiểm tra kích thước driver trả về;
không âm thầm co tem. Chạy trong subprocess, timeout 60 giây → UNKNOWN. USB/LAN đều
qua driver Windows đã cài. Không dùng shell verb mặc định hoặc gửi raw PDF vào máy in
không hiểu PDF. Linux: CUPS `lpstat -e`, `lp` với argument list, media size rõ ràng,
không shell interpolation; dùng để phát triển, target client chính vẫn Windows.

PDFium không thread-safe; toàn bộ lifetime/render được khóa mutex, theo
[tài liệu PDFium](https://pypdfium2.readthedocs.io/en/stable/python_api.html).
GDI submit theo [StartDocW](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-startdocw),
khổ giấy theo [DocumentProperties](https://learn.microsoft.com/en-us/windows/win32/printdocs/documentproperties).

Dependencies mới được cài vào venv riêng B18, không sửa venv dùng chung: ReportLab,
Pillow, pypdfium2 và ZXing (kiểm thử). Version chốt ở requirements-app-lock.txt;
Windows packaging/license notice và thử target thuộc B23.

## HID 1D/2D

Ô HID được gắn vào receipt, pick, issue, transfer và count. Chỉ bắt phím khi ô này có
focus; Enter/KP_Enter/Tab kết thúc; Escape/focus out/đổi nguồn xóa buffer. Debounce
cùng mã 350 ms, timeout giữa ký tự 1 giây, tối đa 160 ký tự, chặn control/paste lỗi.
Quét nhanh cùng serial không tự cộng lượng hoặc tự post. Barcode đóng gói được đổi
về lượng cơ sở bằng factor đang hoạt động; serial chỉ 1 (kiểm kê 0/1), kiểm tra precision.
Mã phải thuộc dòng/phân công hiện tại, source version phải khớp. Quét chỉ điền/chọn
để người dùng kiểm tra; command nghiệp vụ hiện có vẫn kiểm tra lại và chống trùng.

## Nghiệm thu thiết bị còn chờ

T07/T22 chỉ có bằng chứng thành phần local; không đổi T01–T28 sang PASS. Chưa chạy:
Windows 10/11 thật, model máy in USB/LAN, driver, DPI/lề/khổ giấy thực, scanner1D/2D HID,
mẫu doanh nghiệp Q08. Khi có thiết bị: in cả sáu mẫu (ngắn/dài/nhiều trang), quét lại,
rút cáp/tắt spooler/đổi phiên lúc gửi, đối chiếu audit/ledger, ghi model/driver/OS/kết quả
và ảnh mẫu. Không tuyên bố exactly-once trên thiết bị không có giao thức xác nhận.


## Giao dịch API dùng chung

Rà soát hồi quy B18 phát hiện route quản trị có thể trả thành công trước khi
transaction của dependency hoàn tất. `identity_dependencies` nay dùng dependency
transaction `scope="function"` (FastAPI >=0.121), đảm bảo commit/rollback trước khi
gửi response. Kiểm thử HTTP thật chặn commit để xác nhận chưa có response, rồi kiểm
chứng cả commit thành công và commit lỗi/rollback. Đây là sửa lỗi dùng chung ngoài
hook B18, cần giữ khi tích hợp để tránh ACK không tương ứng dữ liệu đã commit.
Nguồn: [FastAPI dependency scope](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/).
