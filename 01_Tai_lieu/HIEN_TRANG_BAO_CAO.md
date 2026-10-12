# Hiện trạng hệ thống WMS

Đối chiếu mã nguồn tại nhánh `main` ngày **13/10/2026**. Bản mã có thay đổi sau bản bàn giao `97d4c51`; không đồng nhất với các gói cài đặt đã phát hành trước đó.

## Căn cứ có thể kiểm tra lại

| Nội dung | Kết quả quan sát | Nguồn |
|---|---|---|
| Giao diện | 26 mục chức năng đang đăng ký, không còn mục Tổng quan | [SECTIONS](../apps/desktop/views/admin_workspace.py), [danh mục chức năng](current_features.json) |
| Ảnh minh họa | 27 ảnh: đăng nhập và 26 mục chức năng, chụp trực tiếp ngày 13/10/2026 giờ Việt Nam | [Ảnh, thời điểm và SHA-256](../assets/readme/screenshots.json) |
| Cơ sở dữ liệu | Schema `wms`: 108 bảng, 736 cột, 219 khóa ngoại | [Catalog PostgreSQL](../02_CSDL/current/schema.json) |
| Migration | 001–026 được thực thi trên cluster PostgreSQL tạm để lấy catalog | [Công cụ xuất schema](../scripts/export_report_schema.py), [SQL](../migrations/README.md) |
| API | 199 đường dẫn, 249 thao tác HTTP, version 0.1.0 | [OpenAPI sinh từ ứng dụng](../05_API/openapi_runtime.json) |
| Quyền mặc định | 10 vai trò, 58 quyền trong seed sau migration | [Quyền hiện hành](../04_Phan_quyen/current_permissions.json) |
| Sơ đồ | 136 sơ đồ: 12 kiến trúc/lớp/luồng, 6 use case, 10 vai trò và 108 ERD | [Mục lục sơ đồ](../03_So_do/Hien_hanh/index.md) |

Số bảng trên không tính bảng lịch sử migration ngoài schema `wms`. Quyền seed không phải danh sách quyền thực tế đang cấp cho từng tài khoản. Việc dựng catalog xác minh DDL trên cơ sở dữ liệu tạm; không xác nhận trạng thái migration của mọi máy triển khai.

## Mô tả hệ thống

WMS là ứng dụng quản lý kho gồm desktop Python/Tkinter, máy chủ FastAPI và PostgreSQL. Desktop cung cấp các màn hình theo quyền; máy chủ xử lý xác thực, kiểm tra phạm vi kho, trạng thái chứng từ, phiên bản và lệnh nghiệp vụ. PostgreSQL lưu dữ liệu nghiệp vụ chính thức. SQLite phía desktop lưu nháp và nhật ký phục hồi lệnh, không thay thế cơ sở dữ liệu tồn kho.

Các chức năng đã có mã gồm danh mục sản phẩm và đơn vị quy đổi, barcode/giá tham chiếu, chủ hàng và hợp đồng ký gửi, serial/bảo hành, trường mở rộng, PO/SO và phê duyệt, nhận hàng, tồn đầu kỳ, nhận ký gửi, giữ hàng/xuất kho, soạn/đóng kiện, kiểm định, di chuyển/chuyển kho, trả hàng, kiểm kê, kỳ kho, đảo giao dịch, tám báo cáo R01–R08, nhập tệp, xuất CSV/XLSX, in/PDF, quản trị tài khoản/quyền và phục hồi lệnh. [README](../README.md) mô tả từng mục và gắn ảnh thật tương ứng.

Giao diện hiện dùng danh sách/chi tiết tách tab ở các màn hình nghiệp vụ, màu xanh cho mục được chọn và đầu bảng, phân trang phía dưới và nhóm thao tác phụ trong menu ở màn hình nhập tệp. Nút **Tải lại** khởi động lại ứng dụng từ nguồn đang cài sau quy trình đóng có xác nhận và chờ công việc nền; đây không phải cơ chế tự tải bản cập nhật từ Internet. [Vòng đời desktop](../apps/desktop/lifecycle.py), [shell](../apps/desktop/views/shell.py).

## Kiến trúc và xử lý nghiệp vụ

[Kiến trúc hiện hành](ARCHITECTURE.md) mô tả các thành phần thực tế. Ba sơ đồ lớp lấy tên lớp, thuộc tính khai báo và phương thức trực tiếp từ AST Python; chúng là các lát cắt đại diện, không phải toàn bộ lớp của hệ thống. Không dùng các lớp khái niệm trong bản thiết kế cũ để khẳng định phần mềm có lớp tương ứng.

Lệnh ghi đi qua dịch vụ nghiệp vụ và `CommandBus`. Máy chủ kiểm quyền trong đơn vị công việc, tuần tự hóa cùng key, so khớp nội dung rồi thực hiện hoặc trả kết quả cũ. Kết quả chống trùng được lưu cùng transaction; handler nghiệp vụ chịu trách nhiệm cập nhật dữ liệu, sổ, số dư, audit và outbox tương ứng. [CommandBus](../apps/server/application/commands.py), [bất biến](INVARIANTS.md).

Khi mất phản hồi, client giữ trạng thái chưa rõ kết quả. Cơ chế phục hồi chung gửi lại yêu cầu gốc với header `X-WMS-Recovery: lookup-v1` để tra ACK; không thực thi một lệnh mới khi chưa tìm thấy kết quả. Việc gửi lại thật dùng cùng key và nội dung, theo thao tác người dùng. Một số module còn có endpoint tra kết quả riêng. [API recovery](../apps/server/api/recovery.py), [nhật ký desktop](../apps/desktop/local_store/recovery.py).

Các luồng nhận/xuất/kiểm kê/chuyển/nhập tệp trong bộ sơ đồ mới mô tả đường xử lý chính của phần mềm. Nhánh lỗi, quyền, version, loại hàng và điều kiện giao dịch phải đọc kèm service. Chúng không phải biên bản khảo sát quy trình thực tế của một doanh nghiệp.

## Sơ đồ hiện hành và thiết kế cơ sở

Dùng [PDF hiện hành](../03_So_do/Hien_hanh/WMS_Hien_hanh.pdf) để đọc/in và [draw.io hiện hành](../03_So_do/Hien_hanh/WMS_Hien_hanh.drawio) để chỉnh sửa. PDF có 5 trang mục lục và 136 trang sơ đồ. [Ký pháp](../03_So_do/NOTATION_GUIDE.md) đối chiếu tám chương giáo trình BA; use case, BPMN, lớp và ERD dùng đúng ký hiệu của từng loại. ERD được sinh từ catalog PostgreSQL sau migration; mỗi bảng có trang đầy đủ cột, PK, nullable và các FK đi ra. CHECK, UNIQUE và index đầy đủ nằm trong catalog JSON; sơ đồ không biểu diễn mọi invariant nghiệp vụ.

| Tài liệu trước đây | Cách dùng khi viết báo cáo hiện tại |
|---|---|
| 56 bảng / 105 FK, 91 trang thiết kế ban đầu | Chỉ trích như thiết kế cơ sở; dùng bộ 108 bảng / 219 FK khi mô tả hiện trạng |
| 101 bảng tại revision 024 | Mốc lịch sử trước identity 025 và avatar 026 |
| Các lớp domain giả định, cấu trúc thư mục đề xuất | Thay bằng lớp và cấu trúc thực tế trong sơ đồ mới |
| BPMN As-Is và đề xuất To-Be ban đầu | Không dùng làm bằng chứng đã khảo sát hoặc vận hành tại doanh nghiệp |
| Ngân sách, số người đồng thời, dung lượng, RPO/RTO mục tiêu | Là giả thiết/mục tiêu trong hồ sơ ban đầu; không phải chi phí hay kết quả đo thực tế |
| 1320 tests + 10 subtests tại `97d4c51` | Chỉ là bằng chứng của bản bàn giao cũ, không tự áp dụng cho mọi sửa đổi hiện tại |

Bản cũ được giữ ở [README bàn giao](../README_BAN_GIAO_20261006.md), [kiến trúc cơ sở](ARCHITECTURE_BASELINE.md), [SRS cơ sở](BA/03_SRS_BASELINE.md) và các thư mục sơ đồ cũ để truy vết.

## Ảnh thật và nguồn dữ liệu

Ảnh trong README được công cụ chụp từ cửa sổ Tk đang chạy sau khi người dùng đăng nhập và đồng ý. Công cụ chỉ điều hướng các màn hình theo quyền hiện có; không tạo, duyệt hoặc ghi sổ chứng từ để dựng ảnh. Màn hình không có bản ghi được giữ nguyên. [Công cụ chụp](../scripts/capture_readme_screenshots.py).

Kho dữ liệu dùng để chạy ứng dụng có dữ liệu mẫu và dữ liệu phục vụ thực hành. Việc một phiếu hiện trạng thái hoàn tất trong ảnh chỉ phản ánh bản ghi tại môi trường này; không chứng minh doanh nghiệp đã thực hiện giao dịch đó. Khi viết báo cáo, gọi đây là **ảnh chạy ứng dụng trên bộ dữ liệu thực hành**, không gọi là khảo sát giao dịch thực tế. [Dữ liệu mẫu](DU_LIEU_MAU.md), [công cụ nhập nguồn](../scripts/import_warehouse_source.py), [chuẩn bị nghiệp vụ thực hành](../scripts/prepare_training_workflows.py).

Email/SMS/Google, TLS, vault hệ điều hành và máy in phụ thuộc cấu hình môi trường. Có mã hỗ trợ không đồng nghĩa dịch vụ ngoài đã cấu hình hoặc thiết bị đã được nghiệm thu. Không suy ra hiệu năng, bảo mật hay khả năng phục hồi production chỉ từ ảnh giao diện.

## Kiểm chứng và tái lập

[Kết quả kiểm tra đợt cập nhật](../07_Kiem_tra/current_report/README.md) kèm JUnit nguyên bản: 17 kiểm thử desktop không cần GUI đạt; hai test GUI không thuộc lần chạy này. Kiểm tra schema, contract, ảnh và liên kết có phạm vi riêng, không thay thế hồi quy toàn bộ.

Các lệnh dưới chạy ở gốc repository. Python cần dependencies của dự án; xuất schema cần PostgreSQL 16; dựng sơ đồ cần Graphviz, ReportLab và Poppler. Xuất schema dùng cluster tạm, không kết nối cơ sở dữ liệu vận hành.

```bash
python scripts/export_runtime_contract.py --check
python scripts/export_report_schema.py --check
python scripts/check_report_current.py
python scripts/check_artifacts.py
```

Khi nguồn thay đổi, chạy lần lượt `export_runtime_contract.py`, `export_report_schema.py`, `build_current_diagrams.py` và `build_readme_features.py`; chụp lại giao diện nếu nội dung màn hình đổi. Sau đó cập nhật artifact bằng `scripts/update_artifacts.py` và chạy các kiểm tra trên.

T01–T28 và các cổng nghiệm thu môi trường giữ nguyên trạng thái trong hồ sơ bàn giao. Đợt cập nhật tài liệu này không tạo biên bản UAT hoặc xác nhận chủ nghiệp vụ mới.
