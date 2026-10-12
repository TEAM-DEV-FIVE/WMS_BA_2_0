# Cách đọc sơ đồ hiện hành

Đối chiếu mã nguồn ngày 13/10/2026. Bắt đầu từ [kiến trúc](Hien_hanh/svg/ARCHITECTURE.svg), sau đó đọc [mục lục 130 sơ đồ](Hien_hanh/index.md). [PDF](Hien_hanh/WMS_Hien_hanh.pdf) có 5 trang mục lục và 130 trang nội dung.

| Nhóm | Căn cứ thực tế |
|---|---|
| Kiến trúc | Desktop Tkinter, FastAPI, PostgreSQL, journal SQLite, vault, cấu hình Nginx, kho tệp và 7 loại worker |
| Lớp | Tên/thành viên đọc AST các lớp đang có, lát cắt desktop, server và DTO |
| Luồng | Đường xử lý chính của service và vòng đời desktop; nhánh quyền/lỗi đọc mã nguồn ghi kèm |
| Vai trò | 10 vai trò và 58 quyền seed sau migration; không phải quyền đang cấp của một tài khoản cụ thể |
| ERD | Catalog schema `wms`: 108 bảng, 736 cột, 219 FK, migration 001–026 |

[Schema JSON](../02_CSDL/current/schema.json), [DBML hiện hành](../02_CSDL/current/wms.dbml), [OpenAPI runtime](../05_API/openapi_runtime.json) là các nguồn đối chiếu. `model.json`, core OpenAPI và bộ 91 trang cũ là thiết kế cơ sở.

Chạy `scripts/export_report_schema.py --check`, `scripts/export_runtime_contract.py --check` và `scripts/check_report_current.py` để phát hiện nguồn thay đổi. Không dùng số bảng ở PDF cũ để kết luận DB mới thiếu/thừa. Xem [kiến trúc](../01_Tai_lieu/ARCHITECTURE.md) và [giới hạn bằng chứng](../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
