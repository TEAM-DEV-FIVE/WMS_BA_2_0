# B02 — Giữ hàng, xuất kho và đóng phần còn lại

- Nhánh: `agent/b02-issue-reservation`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b02-issue-reservation`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#25](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/25), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23), [#9](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/9), [#10](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/10), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16), [#7](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/7) (đối chiếu snapshot local).
- Yêu cầu: FR08, FR09, FR11, FR19, FR30, GR01, GR03, NFR02.
- Bằng chứng liên quan: T02, T03, T14, T17, T25, T27; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B02.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Luồng từ SO đã duyệt: tạo/sửa/gửi/duyệt phiếu xuất, giữ chỗ theo SKU/lô/vị trí/owner, partial post, giải phóng/tiêu thụ reservation, đóng thiếu/hủy phần còn lại; UI gọi API thật.
2. FEFO cho hàng có expiry; không lấy quarantine/blocked/expired, không xuất âm, không chiếm giữ của phiếu khác; serial quantity=1. Tính remaining theo source/consumed/released chính xác.
3. Chốt contract reservation/issue cho picking, transfer, return và recovery; trả execution ACK và operation lookup tương ứng.
4. Giữ chiều owner trong khóa và truy vấn ngay từ đầu; tạm từ chối outbound ký gửi chưa có policy, B09 hoàn thiện. Tích hợp tối thiểu service orders hiện có, không viết lại approval/kernel.

## Phạm vi sửa chính

- `apps/server/application/issues.py, reservations.py (mới)`
- `apps/server/api/issues.py (mới)`
- `packages/contracts/issues.py (mới)`
- `apps/desktop/views/issues.py và presenters/issues.py (mới)`

Revision phát triển dành riêng: `012_b02_issue_reservation.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Hai session PG đồng thời xuất 7 từ tồn 10: chỉ lượng hợp lệ thành công; không lock bằng mutex Python để né race.
- Race cancel/post, approve/edit, expiry/release; rollback giữa ledger/balance/reservation/audit/outbox/ACK.
- Retry cùng key/payload không trùng; key khác/hash khác/stale version và quyền bị thu hồi xử lý đúng; UI hiển thị partial và UNKNOWN.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b02-issue-reservation, nhánh agent/b02-issue-reservation. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B02_issue_reservation.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B02.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
