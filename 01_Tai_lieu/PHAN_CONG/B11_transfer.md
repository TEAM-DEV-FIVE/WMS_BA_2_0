# B11 — Chuyển kho và nhận hàng đang vận chuyển

- Nhánh: `agent/b11-transfer`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b11-transfer`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md)
- Issues liên quan: [#26](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/26), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23) (đối chiếu snapshot local).
- Yêu cầu: FR12, FR13, FR19, FR32, GR01.
- Bằng chứng liên quan: T02, T04, T17, T21, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B11.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Lập/duyệt/dispatch kho nguồn→transit, nhận từng phần transit→kho đích; quantity remaining và source links.
2. Nhận thiếu/hư hỏng có chứng cứ, workflow xử lý phần còn lại không tự cân bằng về 0; phân biệt transit với available kho.
3. Kiểm tra quyền cả kho nguồn/đích tùy thao tác, approval/version/idempotency, serial/lot/owner bất biến.
4. UI chứng từ và history dispatch/receive/missing; dùng kho thứ hai trong fixture, không mô tả thành kho vận hành thật.

## Phạm vi sửa chính

- `apps/server/application/transfers.py (mới)`
- `apps/server/api/transfers.py (mới)`
- `packages/contracts/transfers.py (mới)`
- `apps/desktop/views/transfers.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `017_b11_transfer.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Dispatch 20, nhận 18: transit còn2; không double ledger khi nhận/retry.
- Hai người cùng nhận phần còn, sai owner/kho/serial và dispatch quá tồn bị chặn.
- Atomic rollback + period/freeze guards; R02 internal boundary và R05 có dữ liệu đúng.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b11-transfer, nhánh agent/b11-transfer. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B11_transfer.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B11.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
