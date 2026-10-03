# B10 — Soạn hàng và đóng kiện

- Nhánh: `agent/b10-fulfillment`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b10-fulfillment`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md)
- Issues liên quan: [#29](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/29), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) (đối chiếu snapshot local).
- Yêu cầu: FR10, FR11, FR32.
- Bằng chứng liên quan: T03, T15, T17, T25, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B10.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Pick task từ reservation hợp lệ, phân công, xác nhận/reject thiếu hàng; package/package_line theo số lượng đã pick và source.
2. Picking/packing không tạo stock_move và không giảm physical stock; chỉ issue.post tiêu thụ reservation và tạo sổ.
3. UI danh sách pick/scan input, đóng kiện, trạng thái/khóa version; công bố scanner hooks cho B18.
4. Cancel/release/update phiếu không bỏ lại pick/package mồ côi; bảo toàn lô/serial/owner.

## Phạm vi sửa chính

- `apps/server/application/picking.py, packing.py (mới)`
- `apps/server/api/fulfillment.py (mới)`
- `packages/contracts/fulfillment.py (mới)`
- `apps/desktop/views/fulfillment.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `016_b10_fulfillment.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- T15 soạn/đóng kiện xong balance không đổi; xuất mới trừ đúng một lần.
- Race pick/release/cancel/post, vượt số lượng/serial trùng/package khác kho bị chặn.
- Desktop không tạo thay đổi stock bằng thao tác đổi trạng thái local.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b10-fulfillment, nhánh agent/b10-fulfillment. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B10_fulfillment.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B10.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
