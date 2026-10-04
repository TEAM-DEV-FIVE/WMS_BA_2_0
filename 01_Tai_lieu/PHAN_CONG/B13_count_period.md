# B13 — Kiểm kê, điều chỉnh và khóa kỳ

- Nhánh: `agent/b13-count-period`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b13-count-period`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Trạng thái hiện tại 04/10/2026: **READY**. Đã đồng bộ nền `d4676b67e1302e0ea545d22da5ec16c4f9453840`,
  giữ commit nghiên cứu `07a6f55f580c8b180021b740bdd858e294d8c0b0`; đủ dependency để triển khai.
  Xem commit đồng bộ và dependency thực trong [sổ tích hợp](integration_log.json).
- Phụ thuộc: [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md), [B11](./B11_transfer.md), [B12](./B12_returns.md)
- Issues liên quan: [#28](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/28), [#17](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/17), [#10](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/10), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23) (đối chiếu snapshot local).
- Yêu cầu: FR16, FR17, FR18, FR21, FR30, FR32.
- Bằng chứng liên quan: T05, T07, T16, T19, T24, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B13.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Mở phiên/snapshot theo scope, freeze vị trí, đếm mù/đếm lại, tính delta, duyệt hai bước theo policy kiểm kê và posting adjustment.
2. UI không lộ snapshot cho người đếm mù, phân vai người đếm/người duyệt, theo dõi rounds và lý do chênh lệch.
3. Mở/khóa kỳ, backdate rules và audit; thống nhất locking period/location với mọi engine đã tích hợp.
4. Điều chỉnh kiểm kê giữ owner/lot/serial, không sửa ledger cũ; quy trình giải freeze khi hoàn tất/hủy có kiểm tra.

## Phạm vi sửa chính

- `apps/server/application/counting.py, periods.py (mới)`
- `apps/server/api/counting.py, periods.py (mới)`
- `packages/contracts/counting.py, periods.py (mới)`
- `apps/desktop/views/counting.py, periods.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `019_b13_count_period.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Snapshot 100, đếm 98 → đúng -2 sau đủ bước duyệt; không tự duyệt hoặc tự post khi nhập số đếm.
- Freeze vs receipt/issue/move/transfer/return/opening race bằng PG sessions; close-period vs post/backdate cũng phải được tuần tự hóa.
- Serial mất/thừa, count trùng, quyền chéo kho và retry adjustment không tạo lần ghi sổ thứ hai.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b13-count-period, nhánh agent/b13-count-period. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B13_count_period.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B13.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
