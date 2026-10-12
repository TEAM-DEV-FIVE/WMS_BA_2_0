# Căn cứ thiết kế và hiện thực

Hiện trạng ngày 13/10/2026 được đối chiếu trực tiếp từ [mã và schema thực thi](HIEN_TRANG_BAO_CAO.md), [API runtime](../05_API/openapi_runtime.json) và [ảnh ứng dụng](../assets/readme/screenshots.json). Hai liên kết DBML/PostgreSQL bên dưới đã được sửa và kiểm tra lại.

## Nguồn thiết kế cơ sở

1. Ke_hoach_WMS_ERP_Lite_200tr.pdf, WMS-PMP-001 v1.0, 33 trang: phạm vi trang 6-16; dữ liệu/API trang 18; test trang 25; chuyển dữ liệu trang 26.
2. Roadmap_cong_nghe_WMS_Tkinter_200tr.pdf, WMS-TRM-002 v1.0, 28 trang: kiến trúc/desktop/offline trang 3-10; kiểm thử/phát hành/vận hành trang 21-23.
3. Yêu cầu cập nhật 26/09/2026: dự phòng khoảng 50 triệu, server Linux/Windows/macOS, LAN, bộ ERD/class/DBML/usecase/phân quyền và file nhập liệu.
4. DBML syntax (đã đối chiếu 26/09/2026): https://dbml.dbdiagram.io/docs/ — tham chiếu cú pháp table/ref/check/index; PostgreSQL-specific index nằm trong DDL bổ sung.
5. PostgreSQL constraints: https://www.postgresql.org/docs/16/ddl-constraints.html — căn cứ NULLS NOT DISTINCT và giới hạn CHECK; bộ schema chọn cú pháp PostgreSQL 15+.
6. Python Tkinter: https://docs.python.org/3/library/tkinter.html — căn cứ thiết kế tương tác event loop và threading.
7. PyInstaller operating mode: https://pyinstaller.org/en/stable/operating-mode.html — căn cứ build theo môi trường đích.

Các nguồn 1–3 giải thích thiết kế cơ sở và các giả thiết ban đầu; không phải bằng chứng triển khai production. Với bảng/lớp/quyền/luồng hiện tại, dùng tài liệu và sơ đồ hiện hành ở liên kết trên. Phiên bản phụ thuộc của mã nằm trong pyproject.toml và các lockfile của repository.
