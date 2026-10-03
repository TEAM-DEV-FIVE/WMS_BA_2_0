# Migration PostgreSQL

Chạy riêng `python -m apps.server.infrastructure.migrations` sau khi đặt `WMS_DATABASE_URL`.
API chỉ kiểm tra readiness, không migrate khi khởi động. Runner lấy advisory transaction lock;
migration SQL, seed và lịch sử revision commit cùng nhau. Hai runner đồng thời được tuần tự hóa.

`001_schema.sql` và `002_seed_permissions.sql` là bản đóng băng của baseline 56 bảng và 53 quyền.
`003_identity.sql` thêm IAM (4 bảng/3 cột); `004_approval_permission.sql` bổ sung CONTROLLER vào quyền duyệt
phiếu thông thường theo Q04. Revision 005 thêm 8 cột version/active cho danh mục, collation ICU Unicode và trigger bất biến quy đổi/giá. Revision 006 thêm owner/hợp đồng và chứng cứ bảo hành, đánh dấu stock item/dòng phiếu cũ UNCLASSIFIED mà không đổi sổ/số dư. Revision 007 thêm ownership.read, serial.read, warranty.write. Revision 008 thêm snapshot approval/vai trò duyệt thay/đóng thiếu và seed policy PO/SO khi chưa có. Revision 009 thêm execution hash/ACK, vị trí đối ứng và policy RECEIPT. Revision 010 thêm opening_document/opening_line, đối ứng và policy OPENING khi chưa có; không thay policy tùy chỉnh. Runtime có 65 bảng/440 cột/129 FK và 56 quyền/121 role-permission.
Mô hình/từ điển/DBML phần bổ sung ở `02_CSDL/iam_extension*`, `02_CSDL/master_extension*`, `02_CSDL/ownership_extension*` , `02_CSDL/order_extension*` và `02_CSDL/receiving_extension*`; giữ model.json cho baseline 001.
Seed trong `02_CSDL` là policy hiện hành; bản migration 002 cũ được giữ nguyên, nâng quyền bằng 004/007.
Không sửa file đã áp dụng: thêm revision mới theo thứ tự tăng dần. Runner lưu SHA-256,
từ chối revision bị sửa hoặc database đang ở release mới hơn. Mỗi SQL không được tự commit;
runner chỉ bỏ wrapper BEGIN/COMMIT ngoài cùng của hai bản baseline.

Database đã nạp DDL thủ công chưa có lịch sử migration sẽ bị từ chối, không tự nhận làm database
do runner quản lý. Với phát triển, tạo database mới. Với dữ liệu thật, cần quy trình đối chiếu,
backup và adoption riêng; không drop/recreate schema để ép chạy.

Nếu migration thất bại, transaction rollback; giữ release trước đó và sửa bằng revision được
review. Không có downgrade phá dữ liệu tự động. [Hướng dẫn truy vết](../01_Tai_lieu/TRACEABILITY.md)
mô tả hợp đồng/owner/chứng cứ và giới hạn: chưa có workflow phân loại lại dữ liệu cũ; receipt posting đã có theo [RECEIVING.md](../01_Tai_lieu/RECEIVING.md).
Bắt buộc đối soát/backup trước nâng cấp dữ liệu thật; kết quả hiện tại chỉ từ DB kiểm thử tạm.

Tài liệu đầy đủ: [hướng dẫn triển khai](../01_Tai_lieu/IMPLEMENTATION.md).

[PO/SO và duyệt](../01_Tai_lieu/ORDERS_APPROVAL.md) giải thích giới hạn nâng cấp 008: giữ policy cũ, snapshot request cũ null, không tự hợp thức hóa duyệt.
[Tồn đầu kỳ](../01_Tai_lieu/OPENING.md) mô tả revision 010 và model `opening_extension*`.
Worker outbox dùng schema hiện có; tích hợp desktop quản trị không thêm migration.

## B09 phát triển

`014_b09_consignment.sql` thêm typed consignment_receipt/consignment_receipt_line và mở MOVE nội bộ
cùng owner/hợp đồng/kho bằng guard forward. Không sửa 001–013, không backfill hay phân loại lại ledger cũ.
Tổng schema B09: 72 bảng/491 cột/148 FK. Revision 014 là số release đã được điều phối chọn khi tích hợp; revision phát triển trước đó là 015.
Xem [contract và thiết kế legacy](../01_Tai_lieu/CONSIGNMENT.md).
