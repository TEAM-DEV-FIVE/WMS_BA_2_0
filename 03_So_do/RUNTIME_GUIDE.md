# Cách đọc sơ đồ hiện hành

Bắt đầu từ [kiến trúc](Hien_hanh/svg/ARCHITECTURE.svg), sau đó đọc [mục lục 136 sơ đồ](Hien_hanh/index.md). [PDF](Hien_hanh/WMS_Hien_hanh.pdf) gồm 5 trang mục lục và 136 trang nội dung.

| Nhóm | Căn cứ và mức mô hình |
|---|---|
| Kiến trúc | Thành phần đang triển khai và kết nối trong cấu hình LAN |
| Use case | Mục tiêu sử dụng tương ứng 26 chức năng; actor tham gia theo quyền được cấp, không biểu thị mọi tài khoản có toàn bộ quyền |
| Lớp | Implementation view; tên/thành viên từ AST Python, chọn các lớp desktop, server và DTO |
| BPMN | Quy trình trong phần mềm với làn trách nhiệm; các nhánh phê duyệt, kiểm tra và kết thúc nằm trong phạm vi ghi trong mục lục |
| Vai trò | 10 vai trò và 58 quyền seed; quyền tài khoản cụ thể còn phụ thuộc scope và thời hạn |
| ERD | Physical model của schema `wms`: 108 bảng, 736 cột, 219 FK, migration 001–026 |

[Ký pháp và trang giáo trình](NOTATION_GUIDE.md) quy định cách đọc màu/hình, ngăn lớp và lực lượng quan hệ. Sơ đồ vai trò là RBAC, không phải ma trận quyền lực/mức quan tâm stakeholder. Kiến trúc là sơ đồ thành phần, không được gắn nhãn BPMN.

[Schema JSON](../02_CSDL/current/schema.json), [DBML](../02_CSDL/current/wms.dbml), [OpenAPI runtime](../05_API/openapi_runtime.json) và [manifest nguồn](Hien_hanh/diagram_sources.json) dùng để kiểm tra nội dung. Mã Python sinh bản vẽ nằm trong `scripts/build_current_diagrams.py` và `scripts/diagram_scenes.py`.

BPMN/use case dùng chung tọa độ khi xuất SVG, PDF và draw.io. Các sơ đồ Graphviz dùng cùng vị trí nút; diagrams.net định tuyến lại đường nối khi chỉnh sửa. Lớp có dấu `…` lược tham số phương thức; thuộc tính thiếu annotation được giữ nguyên tên, không tự suy kiểu.

[Tái tạo và kiểm định](../01_Tai_lieu/DOCUMENTATION.md) · [Hiện trạng hệ thống](../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
