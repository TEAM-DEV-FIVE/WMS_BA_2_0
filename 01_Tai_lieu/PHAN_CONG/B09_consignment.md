# B09 — Hoàn thiện nghiệp vụ hàng ký gửi và phân loại dữ liệu cũ

- Nhánh: `agent/b09-consignment`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b09-consignment`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B01](./B01_import_files.md), [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B05](./B05_master_traceability_ui.md), [B06](./B06_opening_ui.md)
- Issues liên quan: [#4](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/4), [#8](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/8), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23), [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24), [#25](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/25), [#31](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/31) (đối chiếu snapshot local).
- Yêu cầu: FR32, FR33, GR01, GR03.
- Bằng chứng liên quan: T01, T06, T20, T24, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B09.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Nhận ký gửi và tồn đầu kỳ theo owner/hợp đồng; nối import B01 và UI B05/B06; snapshot quyền sở hữu bền, không gộp item đồng SKU nhưng khác owner.
2. Rà reservation/move/issue đã tích hợp để luôn dùng owner; chỉ cho outbound/đổi chủ khi có contract và policy rõ. Thiếu policy thì từ chối có lý do, ghi phần UAT còn chờ thay vì tự coi là COMPANY.
3. Thiết kế workflow phân loại legacy UNCLASSIFIED có quyền, chứng cứ, audit và đối soát; không UPDATE/DELETE ledger lịch sử để gán lại owner.
4. Nếu cần chuyển quyền sở hữu, lập thao tác nghiệp vụ có truy vết và được duyệt; không đổi owner âm thầm trong move/return.
5. Chốt contract owner cho transfer/return/count/report; bảo hành giữ liên kết nguồn sau các giao dịch.

## Phạm vi sửa chính

- `apps/server/application/stock_identity.py, traceability.py`
- `apps/server/application/receipts.py, openings.py (mở rộng owner có kiểm soát)`
- `packages/contracts/receipts.py, openings.py, traceability.py`
- `UI ownership/opening và fixtures owner, sau khi B05/B06 tích hợp`

Revision phát triển dành riêng: `015_b09_consignment.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Company 10 + consigned 5 cùng SKU/location = physical 15; eligible/reserved/owned riêng đúng từng owner.
- Race/rollback theo owner, chống mượn reservation khác owner; receipt/opening/import/replay không làm trộn tồn.
- Legacy chưa phân loại mặc định bị chặn nghiệp vụ cần owner; chứng cứ và audit đầy đủ sau phân loại.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Chủ kho cần cung cấp hợp đồng/quy tắc tiêu thụ hoặc đổi chủ ký gửi; không tự dựng chính sách thương mại.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b09-consignment, nhánh agent/b09-consignment. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B09_consignment.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B09.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
