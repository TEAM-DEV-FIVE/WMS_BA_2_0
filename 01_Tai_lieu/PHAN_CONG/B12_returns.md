# B12 — Khách trả hàng và trả nhà cung cấp

- Nhánh: `agent/b12-returns`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b12-returns`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md)
- Issues liên quan: [#27](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/27), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23) (đối chiếu snapshot local).
- Yêu cầu: FR14, FR15, FR19, FR32, FR33.
- Bằng chứng liên quan: T02, T06, T10, T17, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B12.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Customer return từ issue và supplier return từ receipt, trả từng phần có lý do/nguồn/approval.
2. Khóa nguồn và tính lượng ròng đã trả, chặn trả vượt hoặc serial không thuộc nguồn; return vào quarantine/eligible đúng policy, không tự bỏ bước chất lượng.
3. Supplier return phải kiểm tra số dư, reservation, owner và kỳ/freeze; không dùng reversal để đại diện trả hàng vật lý.
4. UI hai flow, source lookup, lịch sử và warranty provenance; không mở sửa chữa/RMA/công nợ.

## Phạm vi sửa chính

- `apps/server/application/returns.py (mới)`
- `apps/server/api/returns.py (mới)`
- `packages/contracts/returns.py (mới)`
- `apps/desktop/views/returns.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `018_b12_returns.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- T10 trả NCC hợp lệ/thiếu tồn/sai serial; customer return không vượt issued net.
- Concurrent returns cùng nguồn không trả hai lần; replay cùng key đúng ACK.
- Owner/serial/source và ledger/balance nhất quán; receipt provenance bảo hành không bị mất.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b12-returns, nhánh agent/b12-returns. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B12_returns.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B12.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
