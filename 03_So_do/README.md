# Sơ đồ WMS

**Bộ hiện hành ngày 13/10/2026:** [PDF](Hien_hanh/WMS_Hien_hanh.pdf) · [draw.io chỉnh sửa được](Hien_hanh/WMS_Hien_hanh.drawio) · [mục lục SVG](Hien_hanh/index.md) · [nguồn từng sơ đồ](Hien_hanh/diagram_sources.json).

Bộ mới gồm 130 sơ đồ: 1 kiến trúc, 3 lớp thực tế, 1 trạng thái chứng từ, 1 phục hồi lệnh, 6 luồng phần mềm, 10 vai trò/quyền seed và 108 trang ERD. PDF có thêm 5 trang mục lục. Các lớp lấy từ AST Python; ERD lấy catalog PostgreSQL sau khi chạy đủ migration 001–026 trên cluster tạm, gồm 736 cột và 219 FK.

Mỗi trang ERD có đầy đủ cột bảng chính và FK đi ra. Bảng đích chỉ hiện các cột được tham chiếu; mỗi tên bảng xuất hiện một lần trên trang. Dấu `?` là nullable; mũi tên từ cột FK sang cột được tham chiếu. CHECK/UNIQUE/index đầy đủ nằm trong [schema JSON](../02_CSDL/current/schema.json); sơ đồ không thay thế invariant nghiệp vụ.

PDF và SVG do Graphviz dựng; draw.io dùng tọa độ nút từ cùng layout nhưng đường nối do diagrams.net định tuyến lại. File draw.io được kiểm tra cấu trúc XML; không khẳng định đã mở trên mọi phiên bản diagrams.net. Có thể tái sinh bằng `scripts/build_current_diagrams.py`.

**Các thư mục ngoài `Hien_hanh` là bộ thiết kế lịch sử 91 trang** với 56 bảng / 105 FK. Các class khái niệm, As-Is giả thuyết và To-Be đề xuất trong bộ này không phải mô tả đầy đủ ứng dụng hiện tại. Giữ để truy vết, dùng bộ mới khi viết báo cáo hiện trạng.

[Hướng dẫn runtime](RUNTIME_GUIDE.md) · [Căn cứ báo cáo](../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
