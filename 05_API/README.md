# API WMS hiện hành

Cập nhật 13/10/2026: **199 paths, 249 HTTP operations**, version 0.1.0. [OpenAPI runtime](openapi_runtime.json) được sinh từ `apps/server/api/app.py`; [inventory](contract_inventory.json) liệt kê từng thao tác. Tái lập bằng `python scripts/export_runtime_contract.py --check`.

API đã có xác thực/MFA/phiên, danh mục, owner/hợp đồng, serial/bảo hành, PO/SO/duyệt, nhận/tồn đầu/ký gửi, giữ hàng/xuất, fulfillment, chất lượng/di chuyển/chuyển kho, trả hàng, kiểm kê/kỳ/đảo, báo cáo/export/import/print, trường mở rộng và quản trị. DTO thực tế nằm ở `packages/contracts`; tra schema từng operation thay vì dùng payload của bản thiết kế.

Các lệnh ghi kiểm quyền hiện tại, scope, trạng thái, version và chống trùng theo key/nội dung. Phục hồi chung dùng yêu cầu gốc cùng header `X-WMS-Recovery: lookup-v1` để tra ACK mà không thực thi khi chưa có kết quả; gửi lại thật dùng cùng key và nội dung. Một số module vẫn có endpoint tra operation riêng. Nguồn: [middleware recovery](../apps/server/api/recovery.py), [command kernel](../apps/server/application/commands.py).

`openapi_core.json` và [README cơ sở](README_BASELINE.md) là thiết kế lịch sử. Các số 65 paths, khẳng định chưa có xuất/chuyển/đảo hoặc cursor snapshot trong bản đó không mô tả runtime hiện tại. Dùng schema runtime để xác định route, giới hạn phân trang, field và mã lỗi của từng module.

[Chức năng và ảnh](../README.md) · [Kiến trúc](../01_Tai_lieu/ARCHITECTURE.md) · [Căn cứ báo cáo](../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
