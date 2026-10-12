<p align="center"><img src="apps/desktop/assets/wms-logo-navy.png" alt="Logo WMS" width="150"></p>

# WMS Quản lý kho

Ứng dụng quản lý kho desktop bằng Python/Tkinter, kết nối FastAPI và PostgreSQL. WMS quản lý danh mục, chứng từ, hàng doanh nghiệp/hàng ký gửi, vận hành kho, kiểm kê, báo cáo và phục hồi lệnh.

**Cập nhật theo mã nguồn ngày 13/10/2026.** Ảnh bên dưới được chụp trực tiếp từ ứng dụng trên máy người dùng ngày 13/10/2026, không phải mockup. Số liệu hiển thị thuộc bộ dữ liệu đang nạp trên máy; việc xuất hiện trong ảnh không xác nhận đó là giao dịch phát sinh tại doanh nghiệp.

[Thuyết minh để viết báo cáo](01_Tai_lieu/HIEN_TRANG_BAO_CAO.md) · [Sơ đồ hiện hành PDF](03_So_do/Hien_hanh/WMS_Hien_hanh.pdf) · [Sơ đồ draw.io](03_So_do/Hien_hanh/WMS_Hien_hanh.drawio) · [Mục lục SVG](03_So_do/Hien_hanh/index.md)

## Quy mô mã nguồn hiện tại

| Thành phần | Số liệu đối chiếu |
|---|---|
| Cơ sở dữ liệu PostgreSQL | 108 bảng, 736 cột, 219 khóa ngoại trong schema `wms` |
| Migration | PostgreSQL 001–026; SQLite 001–003 |
| API | 199 đường dẫn, 249 thao tác HTTP trong OpenAPI runtime |
| Quyền được seed | 10 vai trò, 58 quyền |
| Giao diện | 26 mục trên menu chức năng; thêm màn đăng nhập và các hộp thoại/tabs bên trong |
| Bản mã | `0.1.0`; mã nguồn làm việc có các thay đổi sau gói bàn giao 06/10/2026 |

Số liệu schema được đọc từ PostgreSQL tạm sau khi chạy toàn bộ migration. [Catalog hiện hành](02_CSDL/current/schema.json) lưu cột, ràng buộc và index; [DBML hợp nhất](02_CSDL/current/wms.dbml) và [từ điển dữ liệu](02_CSDL/current/dictionary.csv) dùng cho báo cáo. Đây không phải số lượng bản ghi hay phép đo tải của máy chủ đang vận hành.

## Đăng nhập và giao diện chung

Đăng nhập tài khoản, MFA, nhớ phiên qua kho bí mật hệ điều hành, đổi mật khẩu và khôi phục tài khoản. Mã nguồn có luồng email/SMS và Google; khả năng sử dụng phụ thuộc cấu hình máy chủ và dịch vụ ngoài. Hồ sơ cho phép đổi tên hiển thị và ảnh đại diện. Thanh trên có tìm chức năng, hỗ trợ, menu tài khoản, chế độ sáng/tối và **Tải lại**. Khi đóng hoặc tải lại, ứng dụng hỏi xác nhận và chờ tác vụ nền kết thúc.

![Màn đăng nhập thực tế](assets/readme/login.png)

Nguồn: [giao diện tài khoản](apps/desktop/views/session.py), [xác thực mở rộng](apps/server/api/modern_identity.py), [vòng đời desktop](apps/desktop/lifecycle.py).

## Không gian làm việc

### Kho làm việc

Chọn kho làm việc, xem quyền, quản lý phiên, đổi mật khẩu, thiết lập MFA và đăng xuất. Menu tài khoản hiển thị tên/ảnh đại diện, mở chỉnh sửa hồ sơ và đổi ảnh.

![Kho làm việc](assets/readme/session_view.png)

[Mã nguồn chức năng](apps/desktop/views/session.py)

## Dữ liệu

### Danh mục sản phẩm

Quản lý sản phẩm, đơn vị tính, nhóm hàng, kho, vị trí và đối tác; tìm kiếm và phân trang. Các tab riêng quản lý quy đổi đơn vị, barcode, giá tham chiếu, chủ hàng, hợp đồng ký gửi và tồn theo chủ sở hữu. Có hồ sơ ảnh và mô tả sản phẩm.

![Danh mục sản phẩm](assets/readme/master_container.png)

[Mã nguồn chức năng](apps/desktop/views/master_data.py)

### Serial & bảo hành

Duyệt hoặc tra chính xác serial, xem lịch sử truy vết và chứng cứ bảo hành theo quyền hiện tại. Thông tin nguồn, ngày nhập và mốc bảo hành được lấy từ dữ liệu đã lưu.

![Serial & bảo hành](assets/readme/serial_view.png)

[Mã nguồn chức năng](apps/desktop/views/serial_lookup.py)

### Trường mở rộng

Định nghĩa bộ trường có kiểu, xuất bản phiên bản và nhập giá trị bổ sung cho đối tượng. Xem lịch sử giá trị; chuyển phiên bản khi lưu theo kiểm tra của máy chủ.

![Trường mở rộng](assets/readme/custom_fields_view.png)

[Mã nguồn chức năng](apps/desktop/views/custom_fields.py)

## Nhập hàng

### Đơn mua / đơn bán

Lập và sửa đơn mua PO/đơn bán SO; thêm dòng hàng, giao người xử lý, gửi duyệt, sửa lại hoặc hủy theo trạng thái. Danh sách, chi tiết và lịch sử được tách để theo dõi từng chứng từ.

![Đơn mua / đơn bán](assets/readme/order_view.png)

[Mã nguồn chức năng](apps/desktop/views/orders.py)

### Hộp thư phê duyệt

Xem phiếu chờ phê duyệt theo loại và kho, đọc nội dung/snapshot, duyệt hoặc từ chối kèm lý do. Máy chủ kiểm tra quyền, phiên bản và phân tách nhiệm vụ; không cho tự duyệt trái quy định.

![Hộp thư phê duyệt](assets/readme/approval_view.png)

[Mã nguồn chức năng](apps/desktop/views/approvals.py)

### Nhận hàng

Lập phiếu nhận từ PO, chọn vị trí nhận và định danh hàng; duyệt rồi ghi sổ theo lượng thực nhận. Hỗ trợ nhận từng phần, tra kết quả ghi sổ và nhập mã bằng máy quét HID.

![Nhận hàng](assets/readme/receipt_view.png)

[Mã nguồn chức năng](apps/desktop/views/receipts.py)

### Tồn đầu kỳ

Lập tồn đầu kỳ theo kho, sản phẩm, vị trí, lô/serial và chủ sở hữu. Có biên bản nguồn, gửi duyệt và ghi sổ; điều kiện khởi tạo được kiểm tra ở máy chủ.

![Tồn đầu kỳ](assets/readme/opening_view.png)

[Mã nguồn chức năng](apps/desktop/views/openings.py)

### Nhận ký gửi

Tiếp nhận hàng ký gửi gắn với chủ hàng và hợp đồng; lập dòng, gửi duyệt và ghi sổ nhận. Hàng ký gửi giữ định danh sở hữu riêng trong tồn kho.

![Nhận ký gửi](assets/readme/consignment_view.png)

[Mã nguồn chức năng](apps/server/application/consignments.py)

## Vận hành kho

### Giữ hàng & xuất kho

Lập phiếu xuất từ SO, đề xuất nguồn giữ hàng theo khả dụng/FEFO, giữ hoặc giải phóng lượng giữ. Xuất một phần hoặc toàn bộ theo chứng từ được duyệt, có kiểm tra phiên bản và truy vết kết quả.

![Giữ hàng & xuất kho](assets/readme/issue_view.png)

[Mã nguồn chức năng](apps/desktop/views/issues.py)

### Soạn & đóng kiện

Phân công và xử lý tác vụ soạn hàng, quét mã, ghi lượng thực soạn, đóng kiện và quản lý nội dung kiện. Kiểm tra nguồn giữ hàng, quyền người thao tác và trạng thái phiếu xuất.

![Soạn & đóng kiện](assets/readme/fulfillment_view.png)

[Mã nguồn chức năng](apps/desktop/views/fulfillment.py)

### Kiểm định chất lượng

Xem hàng cần kiểm định, ghi quyết định chất lượng và lượng được chấp nhận hoặc cách ly. Quyết định chất lượng làm căn cứ cho thao tác cất và di chuyển tiếp theo.

![Kiểm định chất lượng](assets/readme/quality_view.png)

[Mã nguồn chức năng](apps/desktop/views/quality.py)

### Cất & di chuyển hàng

Chọn nguồn tồn và vị trí đích để cất hoặc di chuyển hàng trong kho. Liên kết quyết định kiểm định khi cần; có lập nháp, phê duyệt và ghi sổ.

![Cất & di chuyển hàng](assets/readme/move_view.png)

[Mã nguồn chức năng](apps/desktop/views/moves.py)

### Chuyển kho

Lập chuyển kho, theo dõi lượng đã gửi, đã nhận và còn đang vận chuyển. Có lịch sử giao nhận, xử lý thiếu/hỏng và chứng cứ chênh lệch; kiểm tra phạm vi quyền tại các kho liên quan.

![Chuyển kho](assets/readme/transfer_view.png)

[Mã nguồn chức năng](apps/desktop/views/transfers.py)

### Khách trả hàng

Lập phiếu khách trả hàng tham chiếu chứng từ xuất; kiểm tra hàng và lượng có thể trả, phê duyệt rồi ghi nhận về vị trí được phép.

![Khách trả hàng](assets/readme/customer_return_view.png)

[Mã nguồn chức năng](apps/desktop/views/returns.py)

### Trả nhà cung cấp

Lập phiếu trả nhà cung cấp có tham chiếu nguồn nhận; chọn nguồn tồn, kiểm tra số lượng, gửi duyệt và ghi sổ trả.

![Trả nhà cung cấp](assets/readme/supplier_return_view.png)

[Mã nguồn chức năng](apps/server/application/returns.py)

## Kiểm soát

### Tồn kho & báo cáo

Tra cứu R01 tồn theo vị trí; R02 nhập/xuất qua ranh giới; R03 thẻ kho; R04 giữ hàng/nhu cầu mở; R05 chuyển kho/transit; R06 hạn dùng/tồn lâu; R07 kiểm kê; R08 hoạt động/giá tham chiếu. Lọc, phân trang, xuất CSV/XLSX, theo dõi job và lịch sử export. Giá tham chiếu cần quyền giá, không phải giá vốn kế toán.

![Tồn kho & báo cáo](assets/readme/report_view.png)

[Mã nguồn chức năng](apps/desktop/views/reports.py)

### Kiểm kê & điều chỉnh

Tạo phiên kiểm kê, chọn và đóng băng phạm vi, chụp snapshot tồn, ghi các lần đếm hoặc xác nhận vị trí trống. Nộp, xét duyệt chênh lệch và ghi điều chỉnh theo quy trình.

![Kiểm kê & điều chỉnh](assets/readme/count_view.png)

[Mã nguồn chức năng](apps/desktop/views/counting.py)

### Kỳ kho

Xem và mở kỳ kho, khóa kỳ/đối soát, xác nhận và thực hiện mở lại kỳ theo vai trò và MFA. Thông tin kỳ và quy định hiển thị khi cần; có tra ACK cho thao tác ghi.

![Kỳ kho](assets/readme/period_view.png)

[Mã nguồn chức năng](apps/desktop/views/periods.py)

### Đảo giao dịch

Lập phiếu đảo có tham chiếu giao dịch gốc, lý do, phê duyệt và ghi bút toán bù. Không sửa trực tiếp giao dịch tồn đã ghi sổ.

![Đảo giao dịch](assets/readme/reversal_view.png)

[Mã nguồn chức năng](apps/desktop/views/reversals.py)

## Công cụ & hệ thống

### Nhập dữ liệu từ tệp

Tải mẫu CSV/XLSX, chọn và upload tệp, tạo job/dry run, xem lỗi từng dòng, xác nhận commit và xem lịch sử nhập. Tồn đầu kỳ/đơn hàng nhập từ tệp tạo chứng từ để tiếp tục nghiệp vụ. Kiểm tra lại, hủy và khôi phục yêu cầu nằm trong menu Thao tác khác.

![Nhập dữ liệu từ tệp](assets/readme/import_view.png)

[Mã nguồn chức năng](apps/desktop/views/imports.py)

### In chứng từ & tem

Chọn chứng từ hoặc hàng, mẫu và khổ giấy; tạo PDF tiếng Việt, xem trước khi mở thao tác in, lưu PDF hoặc gửi máy in. Có phiếu nhận, xuất, chuyển, kiểm kê và tem sản phẩm/vị trí; theo dõi trạng thái, in lại và kiểm tra yêu cầu.

![In chứng từ & tem](assets/readme/print_view.png)

[Mã nguồn chức năng](apps/desktop/printing/view.py)

### Tài khoản & phân quyền

Quản lý tài khoản, trạng thái hoạt động, vai trò và quyền theo kho/thời hạn; xử lý yêu cầu cấp quyền, thu hồi phiên và các thao tác bảo mật theo quyền hiện tại.

![Tài khoản & phân quyền](assets/readme/admin_view.png)

[Mã nguồn chức năng](apps/desktop/views/admin.py)

### Nháp & phục hồi lệnh

Xem nhật ký nháp và lệnh theo thiết bị/tài khoản/máy chủ; tra ACK, xem nội dung, sửa hoặc bỏ nháp chưa gửi. Gửi lại dùng đúng key và nội dung. Danh sách và chi tiết nằm ở hai tab riêng.

![Nháp & phục hồi lệnh](assets/readme/recovery_view.png)

[Mã nguồn chức năng](apps/desktop/views/recovery.py)

### Phục hồi nhận hàng

Tra các lần ghi sổ nhận hàng bị gián đoạn, kiểm tra kết quả máy chủ và tiếp tục với đúng yêu cầu cũ. Không tự ghi nhận thành công khi chưa có xác nhận.

![Phục hồi nhận hàng](assets/readme/receipt_recovery_view.png)

[Mã nguồn chức năng](apps/desktop/views/receipt_recovery.py)

### Kết nối máy chủ

Kiểm tra kết nối API và trạng thái sẵn sàng của máy chủ/cơ sở dữ liệu. Hiển thị địa chỉ API được cấu hình và kết quả kiểm tra.

![Kết nối máy chủ](assets/readme/connection_view.png)

[Mã nguồn chức năng](apps/desktop/views/shell.py)

## Các thành phần vận hành phía máy chủ

API kiểm quyền hiện tại, phạm vi kho, phân tách nhiệm vụ và phiên bản chứng từ. CommandBus quản lý idempotency trong transaction. Worker xử lý outbox, import, export, in, dọn tệp export/PDF và gửi thông báo xác thực. Kho tệp riêng chỉ được tải qua API kiểm quyền.

![Kiến trúc triển khai theo mã nguồn](03_So_do/Hien_hanh/svg/ARCHITECTURE.svg)

Công cụ vận hành có triển khai LAN/HTTPS, health/readiness, backup/PITR, nâng cấp và rollback. Các tính năng này được mô tả trong [runbook vận hành](01_Tai_lieu/OPERATIONS_RUNBOOK.md) và [runbook triển khai](01_Tai_lieu/LAN_DEPLOYMENT.md); sơ đồ thể hiện thành phần có trong mã và cấu hình, không khẳng định mọi dịch vụ đều đang bật trên máy hiện tại.

## Chạy từ mã nguồn

Yêu cầu phát triển: Python 3.12, Tkinter và PostgreSQL 15/16. Cài dependency theo `requirements-app-lock.txt`, cấu hình API/cơ sở dữ liệu theo [hướng dẫn triển khai](01_Tai_lieu/LAN_DEPLOYMENT.md), rồi chạy:

```bash
python -m apps.server.infrastructure.migrations
python -m apps.server
# Terminal khác
python -m apps.desktop
```

Migration chỉ chạy khi người quản trị yêu cầu; API không tự nâng schema khi khởi động. Không có mật khẩu đăng nhập mặc định trong README. Client kết nối LAN sử dụng HTTPS với CA tin cậy.

## Kiểm chứng và phạm vi kết luận

Schema hiện hành đã được dựng và đọc từ PostgreSQL 16 trong database tạm, không sử dụng database vận hành. OpenAPI được xuất/đối chiếu trực tiếp từ `create_app()`. Ảnh được chụp từ UI thực sau đăng nhập, có [thời điểm và SHA-256](assets/readme/screenshots.json).

Bằng chứng **1.320 test + 10 subtest** của đợt bàn giao thuộc mã `97d4c51`, không dùng làm kết quả hồi quy toàn bộ cho mã đang sửa ngày 13/10. [Biên bản bàn giao](07_Kiem_tra/release/FINAL_HANDOVER.md) giữ nguyên phạm vi thử nghiệm và các điều kiện chưa nghiệm thu. Xem [thuyết minh hiện trạng](01_Tai_lieu/HIEN_TRANG_BAO_CAO.md) để dùng đúng bằng chứng trong báo cáo.

[Kết quả kiểm tra đợt cập nhật](07_Kiem_tra/current_report/README.md): 17 kiểm thử desktop không cần GUI đạt; schema, API, ảnh và liên kết đã được đối chiếu.

## Bộ cài bàn giao và tài liệu lịch sử

[Windows x64](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/download/v0.1.0-handover.1/WMS-Setup-0.1.0-97d4c510dab8-x64.exe) · [macOS ARM64](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/download/v0.1.0-handover.1/WMS-macos-arm64-TEST-ONLY.zip) · [Linux Server](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/download/v0.1.0-handover.1/WMS-Server-0.1.0-97d4c510dab8-linux-x64.tar.gz)

Các liên kết trên là bộ bàn giao `97d4c51`, chưa bao gồm mọi chỉnh sửa giao diện mới trong workspace. Windows đã thử trên Server 2022 x64, macOS trên 15 ARM64; chữ ký lab/test không phải phát hành công khai. [README bàn giao cũ](README_BAN_GIAO_20261006.md) và bộ sơ đồ gốc được giữ để truy vết lịch sử.

## Cập nhật tài liệu và ảnh

```bash
PYTHONPATH=. python scripts/export_runtime_contract.py
python scripts/export_report_schema.py
python scripts/build_current_diagrams.py
PYTHONPATH=. python scripts/capture_readme_screenshots.py
python scripts/build_readme_features.py
python scripts/check_report_current.py
python scripts/update_artifacts.py
python scripts/check_artifacts.py
```

Công cụ chụp ảnh cần desktop thật và đăng nhập tương tác. Công cụ không tạo dữ liệu minh họa, không cấp quyền và không lập/duyệt/ghi sổ chứng từ. Cần đóng WMS trước khi chạy để giữ khóa ứng dụng.
