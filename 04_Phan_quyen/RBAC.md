# Phân quyền thực thi

Mặc định từ chối. Role chỉ gom permissions. Một user có thể có nhiều grant, mỗi grant gắn role + scope + thời hạn; không lấy hợp quyền của các role rồi nhân với hợp các kho.

## Thuật toán

1. Xác thực session, user active, auth_version, MFA khi cần.
2. Tra action trong permission. Nếu GLOBAL: cần grant GLOBAL có role chứa action. ALL_WAREHOUSES chỉ áp dụng action WAREHOUSE.
3. Nếu WAREHOUSE: với từng kho cần thiết, tìm một grant còn hiệu lực chứa action và đúng kho hoặc ALL_WAREHOUSES. Scope không suy ra từ warehouse_id client gửi mà tra từ tài nguyên server.
4. Kiểm tra trạng thái/version, assignment/ownership, policy step, không tự duyệt, hạn mức và kỳ khóa.
5. Với trả/chuyển/đảo cần xem các tài nguyên liên quan, chỉ trả trường tối thiểu được phép. List/query/export/download áp dụng cùng bộ lọc. Không dùng việc ẩn nút làm kiểm soát.

Quyền đọc chứng từ theo role vận hành RECEIVER/PICKER chỉ áp dụng phiếu do mình tạo hoặc được giao. Các role đọc rộng như CONTROLLER có thể đọc toàn kho theo grant của chính role đó. Khi user có nhiều grant, một grant đủ điều kiện có thể cho phép; ràng buộc không tự duyệt luôn thắng.

## Chuyển kho và hàng đang chuyển

Tạo/sửa/duyệt lệnh chuyển cần quyền tương ứng ở cả kho nguồn và đích. Dispatch chỉ cần nguồn; receive chỉ cần đích. Nhân viên chỉ được xem thông tin nguồn/đích tối thiểu của chính phiếu được giao. Không được dùng quyền nhận để liệt kê toàn bộ tồn kho nguồn. Transit gắn độc quyền với document, không phải một kho public.

## Phân tách nhiệm vụ

SYSADMIN không có quyền stock/price/approve theo mặc định. Migration 003 bổ sung `grant_request`: người yêu cầu và người duyệt phải là hai tài khoản khác nhau, có `role.manage` GLOBAL và phiên đã xác thực MFA; cả hai khác người nhận quyền. Grant chỉ có hiệu lực sau bước duyệt trong transaction cùng audit. Biên bản vận hành vẫn là bằng chứng tổ chức; API không xác minh danh tính con người đứng sau hai tài khoản. Bootstrap tối đa hai SYSADMIN ban đầu chỉ chạy qua CLI cục bộ. DB superuser vẫn là quyền hạ tầng mạnh, không thể bị giới hạn bằng RBAC ứng dụng.

Theo TL01 Q04, `document.approve` cho phiếu thông thường thuộc WAREHOUSE_MANAGER **hoặc** CONTROLLER, không có hạn mức giá trị. Migration 004, seed và ma trận quyền đã đồng bộ. Điều chỉnh/kiểm kê/tồn đầu kỳ vẫn tuân bước policy và SOD riêng; đã có API duyệt PO/SO theo migration 008; receipt đã có policy/snapshot/posting ở revision 009; kiểm kê/điều chỉnh/tồn đầu kỳ chưa có workflow hoàn chỉnh. Xem [RECEIVING.md](../01_Tai_lieu/RECEIVING.md). Xem [ORDERS_APPROVAL.md](../01_Tai_lieu/ORDERS_APPROVAL.md).

Người tạo hoặc gửi duyệt không được duyệt phiếu của mình. Với kiểm kê, cả người lập và mọi người đã đếm trong phiên không được duyệt điều chỉnh. Hai bước duyệt phải khác người. Không tự động bỏ qua bước khi thiếu người. Quyền giá luôn cần đồng thời quyền đọc đối tượng. return.unlinked là quyền ngoại lệ bổ sung, không tự cấp return.post. import.commit không tự cấp master.write/opening.post.

## Ví dụ bắt buộc kiểm thử

- User A = WAREHOUSE_MANAGER tại WH-A và RECEIVER tại WH-B: được duyệt A, không được duyệt B.
- User B = CONTROLLER tại WH-A: không đọc giá WH-B qua API, file export hay đường dẫn tệp.
- Thu hồi grant giữa lúc tạo export và tải: từ chối tải.
- User tạo điều chỉnh và có CONTROLLER ở kho đó vẫn không được tự duyệt.
- Worker xuất báo cáo dùng scope snapshot để xử lý và quyền hiện hành khi trả file; không mở rộng thành quyền toàn hệ thống.
- Tài khoản dịch vụ tương lai phải có permissions riêng và scope; không dùng tài khoản migration cho API.

Ma trận CSV là cấu hình mặc định đề xuất. ALLOW vẫn phải thỏa toàn bộ conditions. DENY biểu thị không có grant, không phải explicit deny override. File seed chỉ tạo role/permission, không tạo user hoặc mật khẩu mặc định.

## Owner và bảo hành serial (migration 007)

Policy hiện hành: 10 role, 56 permissions, 121 ánh xạ. `ownership.read` tại kho cho WAREHOUSE_MANAGER,
CONTROLLER, DIRECTOR, AUDITOR; `serial.read` thêm RECEIVER/PICKER; `warranty.write` cho WAREHOUSE_MANAGER
và CONTROLLER. Các API này luôn cần thêm `stock.read` đúng kho. Đọc nguồn nhận/chứng cứ cần `serial.read`
ở kho nguồn và `document.read` với ownership/assignment; không nhân quyền giữa các kho.

Quản trị owner/hợp đồng dùng `partner.write` GLOBAL cho cả GET và ghi; không tự cho phép xem tồn.
Quyền đọc owner không cấp quyền xuất/chuyển ký gửi. Các luồng này còn mặc định bị chặn. Đây là scope theo kho,
chưa phải phân quyền từng đối tác 3PL. [Hướng dẫn và giới hạn](../01_Tai_lieu/TRACEABILITY.md).
