# Bàn giao Agent 3 — Desktop quản trị

Ngày 03/10/2026. Nhánh `agent/admin-ui`, worktree `worktrees/wms-admin-ui`, nền `d5ba723`.
Phạm vi: #13 (UI03), bằng chứng thành phần T07/T11. Không cập nhật issue hoặc trạng thái nghiệm thu tổng.

## Đã triển khai

- Tab quản trị dùng API IAM thật: tải/tạo tài khoản, khóa/mở, thu hồi toàn bộ phiên; xem role/grant,
  lập yêu cầu cấp quyền, xem yêu cầu chờ, quản trị thứ hai duyệt, thu hồi grant.
- Scope/kho/thời hạn/lý do và UUID/người yêu cầu hiện trong bảng/chi tiết có thanh cuộn.
  Form kiểm tra UUID, tương thích scope/kho và thời hạn có múi giờ bằng DTO hiện có.
  Không cần thêm quyền kho; người chỉ có `role.manage` nhập UUID người nhận trực tiếp.
- Phân trang 100 dòng, cursor username cho users và UUID cho grants/grant-requests; còn nút
  Trang sau khi trang đầy, kể cả khi trang tiếp theo rỗng. Không giả định trang đầu là toàn bộ dữ liệu.
- Quyền GLOBAL `iam.manage`/`role.manage` và MFA điều khiển từng nhóm nút. Worker đọc lại `/auth/me`
  trước thao tác; server vẫn quyết định quyền/SOD/scope tại thời điểm thực hiện. Lỗi thật có request ID
  được hiển thị. Tự yêu cầu, tự duyệt, duyệt cho chính mình đều bị backend chặn.
- Adapter IAM gửi write đúng một lần, không header idempotency, không CommandBus, không giữ payload
  để replay. Timeout/network/phản hồi hỏng chuyển sang trạng thái chưa rõ và chặn write mới.
  Tải lại đúng danh sách rồi xác nhận đã đối chiếu mới mở thao tác mới; không tự kết luận lệnh cũ chưa chạy.
- HTTP/refresh trên worker dùng `IdentityClient.in_session`; widget trên main thread. Hủy tác vụ còn chờ,
  chặn gửi sau thay đổi phiên, loại response cũ. Thu hồi phiên xóa dữ liệu và vô hiệu snapshot phiên
  đang chờ để tránh khôi phục lại quyền/UI. Không thay core identity client.
- Mật khẩu xóa ngay khỏi ô nhập; không lưu token/password/MFA vào SQLite/log/nháp. Worker trả kết quả
  đã xử lý lỗi, không đưa exception traceback chứa credential vào hàng đợi UI.
- Điều hướng bằng ô Chức năng thay hàng nhãn tab dài; cả tám tab truy cập được ở 900×690.
  Close/finish và giải phóng biến Tk ở main thread, kể cả khi HTTP còn chạy.

## File thay đổi

| File | Vai trò |
| --- | --- |
| [api/admin.py](../apps/desktop/api/admin.py) | Adapter write một lần; kiểm tra phiên và shape phản hồi |
| [presenters/admin.py](../apps/desktop/presenters/admin.py) | Worker, quyền/MFA, phân trang, chống gửi lặp, reset phiên |
| [views/admin.py](../apps/desktop/views/admin.py) | Form, danh sách, chi tiết, trạng thái và giới hạn đối chiếu |
| [views/shell.py](../apps/desktop/views/shell.py) | Gắn tab, điều hướng, reset phiên và cleanup |
| [test_admin_presenter.py](../tests/foundation/test_admin_presenter.py) | 30 ca presenter/adapter không GUI |
| [test_admin_desktop.py](../tests/foundation/test_admin_desktop.py) | 12 ca GUI, trong đó 6 ca HTTP + PostgreSQL |
| [ADMIN_DESKTOP.md](../01_Tai_lieu/ADMIN_DESKTOP.md) | Hướng dẫn thao tác, phân trang, timeout và giới hạn API |
| Báo cáo này; `SHA256SUMS.txt` | Bàn giao riêng; checksum sinh tự động |

## Kiểm thử

Chạy từ worktree admin-ui. Dùng interpreter của venv điều phối ở chế độ chỉ đọc, đặt `PYTHONPATH="$PWD"`;
đã kiểm tra `apps`, `packages`, `migrations` đều import từ worktree được giao. Không sửa dependency/venv chung,
không dùng `WMS_DATABASE_URL` vận hành. Runner tạo cluster và database PostgreSQL tạm riêng.

```bash
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m pytest tests/foundation/test_admin_presenter.py -q
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy git diff --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
```

Kết quả cuối: presenter **30 passed**; full runner **232 passed, 10 subtests passed**, không skip,
3 cảnh báo dependency hiện có. Ruff, diff check và artifact check đạt; checksum đã sinh lại bằng script.
JUnit của runner nằm tại `.reports/application.xml` (không commit).

Các ca mới chứng minh:

- Tk → HTTP thật → PostgreSQL: tạo user, khóa/mở không hồi sinh token cũ, thu hồi phiên, request/duyệt
  bằng hai quản trị không có quyền kho, kiểm tra SOD, thu hồi grant có hiệu lực ngay ở request kế tiếp.
- Role/kho/requester mất hiệu lực sau khi đã tải yêu cầu thì duyệt trả lỗi thật; thu hồi phiên hoặc quyền
  từ quản trị bên ngoài làm UI xóa dữ liệu/khóa thao tác. Thu hồi chính phiên cũng xóa password/MFA còn ở form.
- Phân trang thực tế 207 users, 205 yêu cầu chờ và 207 grants qua ba trang, không bỏ/trùng dòng trong fixture;
  kiểm thử adapter trang đúng 100 rồi trang rỗng cho cả ba endpoint.
- Thiếu từng quyền/MFA, cấp cả ba scope bằng UUID với chỉ `role.manage`, UUID/scope/múi giờ không hợp lệ;
  timeout không replay, phản hồi hỏng không render, bận không gửi lặp, response cũ/cancel trước write bị loại.
- Mật khẩu không ở log/SQLite; bố cục/tất cả điều hướng ở 900×690, cleanup khi worker đang chạy;
  snapshot phiên đang chờ không khôi phục dữ liệu sau invalidation.

Xvfb trong sandbox không kết nối được display; các kiểm thử GUI/HTTP/PostgreSQL được chạy lại ngoài
sandbox qua escalation. Một lượt subset không integration/GUI trong sandbox không hoàn tất và đã dừng;
full runner bao gồm lại toàn bộ các ca đó. Cảnh báo hiện có của Starlette/httpx và `jsonschema.RefResolver`
không được né bằng skip/xóa test. Bằng chứng là Linux/Xvfb; chưa suy thành Windows UAT.

## Contract, giới hạn và việc điều phối

Không đổi backend, schema, migration 001–009, API contract, core identity client, fixture chung, dependency,
CI hoặc báo cáo tiến độ/nghiệm thu tổng. Không có migration mới, không push/merge.

Các giới hạn API cần cân nhắc đợt sau:

- Không có lookup kho dành riêng cho IAM: form nhập UUID có validation; không mở rộng grant để chạy dropdown.
- `GET /roles` chỉ có code/name; chưa xem được permission chi tiết của từng role.
- `GET /grants` chưa trả lý do cấp/thu hồi; lý do request chỉ có trong danh sách yêu cầu đang chờ.
- Không có danh sách phiên/auth_version/audit phục vụ đối chiếu thu hồi phiên. UI không khẳng định reload users
  chứng minh phiên đã thu hồi. Các thao tác này cần đối chiếu tại phiên đích hoặc qua vận hành.
- Chưa có đổi mật khẩu/reset MFA, yêu cầu bị từ chối/hủy hoặc lịch sử yêu cầu đã duyệt.
- Phân trang IAM hiện tại không phải snapshot; dữ liệu thay đổi đồng thời có thể cần tải lại từ đầu.
- Trạng thái chưa rõ chỉ ở RAM, bị xóa khi đổi/đăng xuất/đóng phiên; không có phục hồi write IAM bền vững.
  Request đã gửi vẫn có thể hoàn tất sau khi đóng UI. Cần đối chiếu trước mọi thao tác mới khi chưa chắc kết quả.

Điều phối review và tích hợp nhánh/commit local, sinh lại checksum sau tích hợp và chạy hồi quy chung.
Cập nhật tài liệu tổng và đoạn “UI quản trị chưa được dựng” trong [IDENTITY.md](../01_Tai_lieu/IDENTITY.md)
khi tích hợp; file này ngoài phạm vi agent nên giữ nguyên. Lập Windows UAT và đối chiếu đủ tiêu chí T07/T11
trước nghiệm thu. T01–T28 giữ PLANNED; báo cáo này không tự đánh dấu PASS nghiệm thu.
