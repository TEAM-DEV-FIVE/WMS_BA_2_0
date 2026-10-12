# Kiểm tra cập nhật báo cáo ngày 13/10/2026

Phạm vi: tài liệu hiện trạng, catalog cơ sở dữ liệu, OpenAPI, sơ đồ và ảnh README. Không thay thế nghiệm thu nghiệp vụ T01–T28 hoặc bộ kiểm thử toàn ứng dụng.

| Kiểm tra đã chạy | Kết quả |
|---|---|
| `export_report_schema.py --check` | Dựng migration 001–026 trong PostgreSQL 16 tạm; snapshot khớp: 108 bảng, 736 cột, 219 FK, 10 vai trò, 58 quyền |
| `export_runtime_contract.py --check` | Khớp 199 paths; 249 HTTP operations trong OpenAPI |
| `check_report_current.py` | Đủ 26 mục chức năng, 27 hash ảnh; 130 sơ đồ, đủ FK và quyền seed; PDF và liên kết tài liệu hợp lệ |
| Ruff trên 5 script báo cáo/chụp ảnh | Đạt |
| `git diff --check` | Không phát hiện lỗi khoảng trắng |
| `check_artifacts.py` | Đạt kiểm định định dạng, mô hình bổ sung, ZIP và checksum; 23 API paths trong dòng kiểm định này thuộc core thiết kế, không phải runtime |

Kiểm thử desktop đã chạy:

```bash
python -m pytest tests/foundation/test_desktop_lifecycle.py tests/foundation/test_desktop.py -m "not gui" -q --junitxml=.reports/report-current-unit.xml --disable-warnings
```

Kết quả: **17 passed, 2 deselected**, một cảnh báo. Hai test GUI nằm ngoài lần chạy này; môi trường công cụ không truy cập được màn hình Tk. [JUnit nguyên bản](desktop_unit.xml) lưu test case và thời gian chạy. Không gọi đây là kiểm thử GUI hay hồi quy toàn bộ.

Ảnh được người dùng chụp trên máy có màn hình bằng công cụ trong repository, sau đăng nhập. Đã rà 27 ảnh bằng ảnh tổng hợp; manifest chứa SHA-256 và thời điểm. Không dùng ảnh dựng/synthetic trong thư mục preview.

PDF được render để rà toàn bộ 135 trang ở dạng tổng hợp, mở lớn các sơ đồ kiến trúc, lớp server/desktop, phục hồi, quyền và ERD document. Các trang được chỉnh bố cục có render lại. XML draw.io đã kiểm tra, chưa kiểm thử trực tiếp bằng ứng dụng diagrams.net.

Lặp lại kiểm tra sau khi sửa nguồn bằng các script nêu trên; kết quả ghi tại đây thuộc đợt cập nhật này. Bằng chứng 1320 tests + 10 subtests của bản `97d4c51` vẫn ở hồ sơ bàn giao cũ.
