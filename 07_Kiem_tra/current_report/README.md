# Kiểm chứng tài liệu và sơ đồ WMS

## Bộ sơ đồ theo giáo trình BA — 13/10/2026

Phạm vi: tài liệu và bản vẽ hiện hành; không sửa mã ứng dụng, migration hoặc trạng thái nghiệm thu T01–T28.

| Kiểm tra | Kết quả |
|---|---|
| `check_report_current.py` | 26 chức năng, 27 hash ảnh, 136 sơ đồ, 108 bảng và 219 FK; PDF 141 trang và liên kết hợp lệ |
| `check_diagram_notation.py` | Lực lượng/đầu nối FK, PK định danh, FK ghép; ngăn lớp và kế thừa; actor/boundary cho 26 use case; 6 luồng BPMN có start/end, gateway và lane hợp lệ |
| Ruff | Đạt trên 6 script dựng/kiểm tra sơ đồ và README |
| `git diff --check` | Không phát hiện lỗi khoảng trắng |

Sáu trường hợp lực lượng quan hệ được kiểm tra riêng với kỳ vọng cố định: `user_avatar.user_id`, ba FK kho/transit của `document`, hai FK của `role_permission`. Các trường hợp bao gồm 1–1, 1–n, nullable, UNIQUE có điều kiện `IS NOT NULL` và UNIQUE ghép không bảo đảm từng cột riêng lẻ là duy nhất.

Tám PDF giáo trình có tổng 358 trang, SHA-256 trùng bộ tài liệu BA đã lưu trước đây. [Manifest](../../03_So_do/reference_sources.json) ghi tên tệp được cung cấp; [bảng ký pháp](../../03_So_do/NOTATION_GUIDE.md) ghi trang PDF áp dụng.

PDF/SVG được render để rà bố cục; kiểm tra cấu trúc XML và các đầu nối của draw.io. Việc mở/chỉnh sửa tương tác bằng diagrams.net không nằm trong phạm vi kiểm tra này.

## Bằng chứng ứng dụng và dữ liệu

[Kết quả kiểm tra ban đầu ngày 13/10](VERIFICATION_INITIAL_20261013.md) ghi lần dựng schema PostgreSQL 16 tạm, xuất OpenAPI và 17 kiểm thử desktop không cần GUI. [JUnit](desktop_unit.xml) giữ nguyên bằng chứng. Bộ sơ đồ mới kiểm tra lại hash migration và ảnh, đối chiếu cột/FK/quyền seed với catalog, không coi đây là lần chạy lại toàn bộ test ứng dụng.

Ảnh là màn hình ứng dụng trên dữ liệu thực hành. [Manifest ảnh](../../assets/readme/screenshots.json) lưu thời điểm và hash. Bằng chứng 1.320 tests + 10 subtests của runtime `97d4c51` vẫn thuộc [hồ sơ bàn giao](../release/FINAL_HANDOVER.md).

[Tái tạo tài liệu](../../01_Tai_lieu/DOCUMENTATION.md) · [Hiện trạng hệ thống](../../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
