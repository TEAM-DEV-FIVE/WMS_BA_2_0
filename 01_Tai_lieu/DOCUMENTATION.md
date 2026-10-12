# Bảo trì tài liệu hệ thống

## Nguồn và công cụ

Catalog PostgreSQL được trích bằng migration trên cluster tạm; OpenAPI được xuất từ `create_app()`. Danh mục tính năng đối chiếu `SECTIONS`. Ảnh trong README là ảnh chụp ứng dụng, có thời điểm và SHA-256 trong [manifest](../assets/readme/screenshots.json).

Python cần dependency của dự án. Dựng sơ đồ cần Graphviz, ReportLab và Poppler (`pdfunite`); xuất schema cần PostgreSQL 16. Chạy các lệnh ở thư mục gốc repository:

```bash
PYTHONPATH=. python scripts/export_runtime_contract.py
python scripts/export_report_schema.py
python scripts/build_current_diagrams.py
python scripts/build_readme_features.py
python scripts/check_report_current.py
python scripts/check_diagram_notation.py
python scripts/update_artifacts.py
python scripts/check_artifacts.py
```

Dữ liệu và ký pháp của bộ sơ đồ nằm trong `scripts/build_current_diagrams.py` và `scripts/diagram_scenes.py`. File `diagram_sources.json` lưu các nút, quan hệ, lực lượng và nguồn đối chiếu. SVG, PDF và draw.io được sinh lại cùng lượt; không sửa riêng tệp xuất.

## Ảnh giao diện

Khi giao diện thay đổi, đóng WMS rồi chạy trên máy có màn hình:

```bash
PYTHONPATH=. python scripts/capture_readme_screenshots.py
python scripts/build_readme_features.py
```

Công cụ yêu cầu đăng nhập và đồng ý chụp, chỉ mở màn hình theo quyền tài khoản. Không tạo dữ liệu, cấp quyền hoặc lập/duyệt/ghi sổ chứng từ. Ảnh chưa có dữ liệu được giữ nguyên. Sau khi cập nhật ảnh, chạy lại các kiểm tra tài liệu và checksum.

## Hồ sơ lịch sử

Catalog, sơ đồ và API hiện hành tách khỏi thiết kế cơ sở. Bằng chứng release được giữ theo commit gốc; số test của một commit không tự áp dụng cho phiên bản khác. [Ký pháp](../03_So_do/NOTATION_GUIDE.md) · [Kiểm chứng](../07_Kiem_tra/current_report/README.md).
