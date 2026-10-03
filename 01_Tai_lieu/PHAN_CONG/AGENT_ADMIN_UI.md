# Agent 3 — Giao diện quản trị tài khoản và quyền

- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-admin-ui`
- Nhánh: `agent/admin-ui`
- Issue liên quan: #13 (UI03), dùng backend #5/#6; bằng chứng thành phần T07/T11.
- Đọc [quy tắc chung](README.md), [IAM](../IDENTITY.md), `apps/server/api/identity.py`, DTO identity,
  session presenter/view, master presenter/view, shell và test IAM/desktop hiện có.

## Kết quả cần bàn giao

Tab quản trị nối API thật: danh sách/tạo user, khóa/mở user, thu hồi phiên; xem role/grant,
lập yêu cầu cấp quyền, xem yêu cầu chờ, quản trị viên thứ hai duyệt và thu hồi grant.
Hiển thị scope/kho/thời hạn/lý do rõ ràng. Phân trang khi API giới hạn danh sách; không coi 100/200 dòng
đầu tiên là toàn bộ dữ liệu. Chỉ hiện/bật chức năng theo `iam.manage`/`role.manage` và MFA hiện tại.

Server tiếp tục quyết định quyền. SYSADMIN không mặc nhiên có quyền đọc tồn/chứng từ kho.
Không thêm grant rộng hơn để làm dropdown chạy; dùng lookup đã có khi đủ quyền, hoặc nhập UUID với
validation và mô tả giới hạn nếu chưa có endpoint quản trị phù hợp. Người yêu cầu, người duyệt, người nhận
quyền phải tuân thủ SOD hiện tại; role/kho/quyền thay đổi giữa chừng phải hiển thị lỗi thật từ server.

Các lệnh quản trị IAM hiện không đi qua CommandBus như receipt.post. Không coi việc gửi header key là
đã có idempotency server; không tự retry lệnh tạo user/cấp quyền khi timeout. Báo chưa rõ kết quả và cho
tải lại danh sách đối chiếu. Không lưu password/token/MFA trong nháp, log hoặc báo cáo.

## Phạm vi được sửa

- Module mới `apps/desktop/views/admin.py`, `apps/desktop/presenters/admin.py`; adapter API riêng nếu cần.
- `apps/desktop/views/shell.py`: gắn tab, session reset và cleanup đúng main thread.
- Test mới `tests/foundation/test_admin_desktop.py`, `tests/foundation/test_admin_presenter.py`;
  fixture nội bộ test, dùng API hiện có.
- Hướng dẫn `01_Tai_lieu/ADMIN_DESKTOP.md`, báo cáo `07_Kiem_tra/AGENT_ADMIN_UI_REPORT.md`.

Không sửa backend/schema/API contract, core identity client, view/presenter nghiệp vụ khác, dependency/CI
hoặc fixture chung. Chưa làm đổi mật khẩu/reset MFA vì backend chưa có. Nếu endpoint/DTO thiếu thật sự,
ghi đề xuất trong báo cáo; tiếp tục hoàn thiện các thao tác đã có API.

## Kiểm thử bắt buộc

- Presenter: worker không sửa widget; response phiên cũ bị bỏ; logout/thu hồi phiên xóa dữ liệu UI.
- Quyền và MFA: thiếu từng quyền không mở thao tác tương ứng; không có quyền kho vẫn quản trị đúng scope.
- Qua Tk → HTTP thật → PostgreSQL: tạo user, khóa/mở, revoke phiên, yêu cầu cấp quyền và duyệt bằng
  quản trị thứ hai; tự duyệt hoặc duyệt cho chính mình bị chặn; thu hồi grant có hiệu lực.
- Timeout không tự phát lại write; hiển thị lỗi và đối chiếu danh sách; nút không gửi trùng khi đang bận.
- Password/MFA xóa khỏi ô nhập khi gửi, không xuất hiện trong log/SQLite; cleanup không lỗi finalizer Tk.
- Kiểm tra bố cục ở 900×690: thêm tab có thể tràn ngang, cần navigation vẫn dùng được cả tab cũ.
- Full suite hồi quy, Ruff và artifact check. Ghi rõ Linux/Xvfb; không suy thành Windows UAT.

Commit local, trả hash và báo cáo; không tự thay trạng thái issue hoặc báo cáo nghiệm thu tổng.
