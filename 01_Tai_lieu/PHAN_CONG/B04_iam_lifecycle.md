# B04 — Hoàn thiện mật khẩu, MFA và quản trị phiên

- Nhánh: `agent/b04-iam-lifecycle`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b04-iam-lifecycle`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#5](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/5), [#6](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/6), [#13](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/13) (đối chiếu snapshot local).
- Yêu cầu: FR01, FR02, FR29, NFR01.
- Bằng chứng liên quan: T07, T11; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B04.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Đổi mật khẩu và quy trình reset được kiểm soát; recovery/reset MFA với re-auth/thu hồi phiên và audit; kiểm tra policy có sẵn trước bổ sung, không bỏ MFA vì có tên role SYSADMIN.
2. UI thực hiện đầy đủ flow, tra kho/user bằng lookup thay vì nhập ID khó dùng, lịch sử cấp/thu hồi quyền và session; giữ hai người trong grant workflow hiện có.
3. Giới hạn/throttle tác vụ nhạy cảm, secret/recovery code chỉ hiển thị khi cần và không log; không lưu password/TOTP/recovery payload trong SQLite hoặc command replay journal.
4. Khi timeout thao tác IAM, tra cứu trạng thái an toàn hoặc yêu cầu đăng nhập lại; không tự replay reset/đổi mật khẩu.

## Phạm vi sửa chính

- `apps/server/application/identity.py`
- `apps/server/api/identity.py`
- `packages/contracts/identity.py`
- `apps/desktop/api/identity.py, admin.py`
- `apps/desktop/views/admin.py, session.py và presenters tương ứng`

Revision phát triển dành riêng: `014_b04_iam_lifecycle.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Mã recovery dùng một lần; replay/đoán mã/rate limit/phiên cũ và quyền vừa thu hồi bị chặn.
- PG + API + presenter/GUI: người không đủ quyền hoặc chéo kho không đọc audit nhạy cảm.
- Kiểm tra response/log/cache SQLite không chứa secret; test logout/login đổi user loại phản hồi phiên cũ.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b04-iam-lifecycle, nhánh agent/b04-iam-lifecycle. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B04_iam_lifecycle.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B04.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
