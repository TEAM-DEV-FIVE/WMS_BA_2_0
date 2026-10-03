# B03 — Kiểm định, cất hàng và di chuyển nội bộ

- Nhánh: `agent/b03-move-quality`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b03-move-quality`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#29](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/29), [#26](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/26), [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23) (đối chiếu snapshot local).
- Yêu cầu: FR06, FR07, GR01, FR32.
- Bằng chứng liên quan: T01, T06, T13, T24, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B03.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Tạo quyết định chất lượng có nguồn receipt; chuyển inbound→storage/quarantine, putaway và di chuyển vị trí trong cùng kho.
2. Kiểm tra cây vị trí, kho, trạng thái location, lô/serial/owner, lượng còn của nguồn và hàng đang giữ; move không làm tăng tổng tồn kho.
3. UI chọn nguồn/đích, số lượng đạt/lỗi, lịch sử decision, lý do và quyền; dùng command/version/ACK thật.
4. Công bố helper/contract khả dụng và kiểm tra freeze/period để các luồng tiếp nối dùng; không tự xây transfer liên kho hoặc picking thuộc B10/B11.

## Phạm vi sửa chính

- `apps/server/application/quality.py, moves.py (mới)`
- `apps/server/api/quality.py, moves.py (mới)`
- `packages/contracts/quality.py, moves.py (mới)`
- `apps/desktop/views/quality.py, moves.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `013_b03_move_quality.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- T01 nhận 80/100, chuyển 75 storage và 5 quarantine: tổng 80, available≤75, PO remaining 20, đúng ledger.
- Race cùng serial, move với reservation, sai kho/vị trí inactive/cycle; không đổi owner trong move.
- Rollback và idempotency post, race period/freeze khi đã có B13 sẽ được chạy lại tại tích hợp.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b03-move-quality, nhánh agent/b03-move-quality. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B03_move_quality.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B03.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
