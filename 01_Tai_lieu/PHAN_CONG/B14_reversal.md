# B14 — Đảo giao dịch và bảo toàn lịch sử

- Nhánh: `agent/b14-reversal`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b14-reversal`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md), [B11](./B11_transfer.md), [B12](./B12_returns.md), [B13](./B13_count_period.md)
- Issues liên quan: [#27](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/27), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) (đối chiếu snapshot local).
- Yêu cầu: FR20, GR03, FR32.
- Bằng chứng liên quan: T02, T10, T18, T19, T24, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B14.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Đảo transaction đủ điều kiện bằng bút toán nghịch có lý do/duyệt/source linkage; giữ ledger gốc bất biến.
2. Ma trận đủ điều kiện cho receipt/opening/issue/move/transfer/return/adjustment: downstream vật lý/return/reservation, kỳ và trạng thái serial/owner; nêu rõ các trường hợp bị chặn.
3. Không đảo một reversal hoặc đảo trùng transaction; không tự hủy downstream để ép reversal thành công.
4. UI xem ảnh hưởng trước gửi/duyệt/post và trace gốc→đảo, ACK/operation lookup.

## Phạm vi sửa chính

- `apps/server/application/reversals.py (mới)`
- `apps/server/api/reversals.py (mới)`
- `packages/contracts/reversals.py (mới)`
- `apps/desktop/views/reversals.py và presenters tương ứng (mới)`

Revision phát triển dành riêng: `020_b14_reversal.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Hai session đảo cùng transaction: chỉ một reversal, balance/serial/reservation/source net nhất quán.
- Chặn đã chuyển/tiêu thụ, còn reservation, kỳ khóa hoặc thiếu quyền; test transaction lỗi giữa các cập nhật rollback toàn bộ.
- Đối soát toàn chuỗi nhận/xuất/trả/chuyển/kiểm kê rồi reversal, không UPDATE/DELETE sổ gốc.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b14-reversal, nhánh agent/b14-reversal. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B14_reversal.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B14.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
