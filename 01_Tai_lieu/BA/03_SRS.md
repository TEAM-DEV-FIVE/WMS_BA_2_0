# SRS và đối chiếu hiện thực WMS

Cập nhật 13/10/2026 theo mã nguồn. [SRS cơ sở](03_SRS_BASELINE.md) giữ nội dung thiết kế ban đầu. Tài liệu này sửa các mô tả đã lỗi thời; không tự nâng trạng thái yêu cầu hoặc nghiệm thu lên Verified.

## Phạm vi phần mềm hiện có

WMS gồm desktop Tkinter, API FastAPI, dịch vụ nền và PostgreSQL. Hệ thống có các nhóm danh mục, PO/SO/phê duyệt, nhập kho, vận hành kho, kiểm soát, import/export/in, tài khoản và phục hồi. [README](../../README.md) liệt kê đủ 26 mục menu kèm ảnh chạy thật; [current_features.json](../current_features.json) gắn từng mục với mã nguồn.

FR32/UC32 về ký gửi và FR33/UC33 về serial/bảo hành đã có schema, API và giao diện trong mã hiện tại. Module nhận ký gửi, chủ hàng/hợp đồng và tra bảo hành không còn là đề xuất chưa triển khai. Phạm vi thao tác trên hàng ký gửi vẫn do guard nghiệp vụ quyết định; có màn hình không có nghĩa mọi nghiệp vụ xuất/chuyển đều mở cho mọi chủ hàng. Nguồn: [consignments.py](../../apps/server/application/consignments.py), [traceability](../TRACEABILITY.md).

## Dữ liệu và giao diện

Migration 001–026 dựng schema `wms` gồm 108 bảng, 736 cột, 219 FK. [Catalog hiện hành](../../02_CSDL/current/schema.json) lưu cột, nullability, PK/FK/CHECK/UNIQUE và index; [ERD mới](../../03_So_do/Hien_hanh/index.md) phản ánh cùng snapshot. 56 bảng / 105 FK là mốc thiết kế cơ sở.

[OpenAPI runtime](../../05_API/openapi_runtime.json) có 199 paths, 249 HTTP operations sinh từ ứng dụng FastAPI. `openapi_core.json` là thiết kế lịch sử; DTO/cursor/route của nó không thay thế runtime contract. Server và các module xuất/chuyển/đảo giao dịch đã có mã, vì vậy các ghi chú cũ “chưa có server” hoặc “chưa có runtime” không mô tả hiện trạng.

Giao diện gồm phân quyền theo tài khoản/kho, bảng có phân trang, danh sách/chi tiết, nhóm thao tác phụ, ảnh đại diện, chế độ sáng/tối và tải lại có xác nhận. Ảnh trong README là ảnh ứng dụng; dữ liệu thực hành trong ảnh không phải bằng chứng giao dịch doanh nghiệp.

## Yêu cầu và truy vết

Các mã GR/TR/FR/NFR và UC trong `requirements.json`, `use_cases.json`, `USE_CASES.md` giữ vai trò định danh và truy vết. Không tự tái sử dụng mã cũ, không coi có route hoặc ảnh là đủ để chuyển yêu cầu sang Verified. Mục tiêu hiệu năng, chi phí và vận hành trong hồ sơ cơ sở cần bằng chứng đo/biên bản riêng trước khi đưa vào phần kết quả thực nghiệm.

RBAC seed hiện có 10 vai trò, 58 quyền. Vai trò nghiệp vụ không đồng nghĩa có toàn bộ quyền tại mọi kho; quyền hiện tại, SOD, version, trạng thái và dữ liệu nguồn được server kiểm tra. [Quyền sau migration](../../04_Phan_quyen/current_permissions.json), [CommandBus](../../apps/server/application/commands.py).

## Kiểm chứng và giới hạn

Sơ đồ mới mô tả hiện thực phần mềm; As-Is/To-Be cũ là hồ sơ khảo sát/đề xuất, không chứng minh khảo sát thực địa. T01–T28 và các cổng nghiệm thu giữ nguyên trạng thái đã ghi nhận. Kết quả 1320 tests + 10 subtests thuộc bản `97d4c51`, không tự đại diện cho mã hiện tại.

Căn cứ, cách tái lập và giới hạn dùng trong báo cáo ở [hiện trạng báo cáo](../HIEN_TRANG_BAO_CAO.md). [Mốc bàn giao](../../07_Kiem_tra/release/FINAL_HANDOVER.md) được giữ nguyên để không làm sai lịch sử kiểm thử.
