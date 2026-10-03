# B19 — Nháp và phục hồi mất LAN cho mọi luồng ghi

- Nhánh: `agent/b19-recovery-all`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b19-recovery-all`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B01](./B01_import_files.md), [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B04](./B04_iam_lifecycle.md), [B05](./B05_master_traceability_ui.md), [B06](./B06_opening_ui.md), [B07](./B07_custom_fields.md), [B09](./B09_consignment.md), [B10](./B10_fulfillment.md), [B11](./B11_transfer.md), [B12](./B12_returns.md), [B13](./B13_count_period.md), [B14](./B14_reversal.md), [B15](./B15_documents_ui.md), [B16](./B16_import_ui.md), [B18](./B18_printing_scanner.md)
- Issues liên quan: [#18](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/18), [#12](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/12), [#7](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/7) (đối chiếu snapshot local).
- Yêu cầu: FR25, FR28, NFR02, NFR03, NFR06.
- Bằng chứng liên quan: T02, T08, T11, T23; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B19.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Lập ma trận mọi write endpoint: durable draft, command an toàn replay cùng key, hoặc phải online/re-auth. Tất cả domain đã có phải được phân loại và có UI tương ứng; không gom IAM secrets vào queue.
2. Versioned draft/payload schema, persist-before-send, SENDING→UNKNOWN khi crash, lookup ACK trước explicit same-key retry, chặn hash mismatch.
3. Draft/recovery cho receipt/opening/issue/move/transfer/return/count/reversal/import và workflow phù hợp; không post offline, không tự sinh key mới để tránh conflict.
4. Partition theo server/device/user/kho, xử lý logout/user change/revoked grants, cleanup giữ pending; migration SQLite v2→v3 không mất nháp và có backup/validation.
5. Bảo toàn UNKNOWN qua đóng app, đổi màn và nâng cấp; hướng dẫn giải quyết xung đột version bằng refresh/manual review.

## Phạm vi sửa chính

- `apps/desktop/local_store/ (chủ sở hữu SQLite revision 003 trong đợt này)`
- `apps/desktop/api/client.py (recovery integration)`
- `apps/desktop/views/receipt_recovery.py và màn phục hồi dùng chung`
- `adapter recovery trong presenter các domain sau khi đã tích hợp`

B19 sở hữu SQLite revision 003. PostgreSQL không được cấp revision mới trong nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Kill process ở trước/sau gửi/commit/ACK, restart bằng process khác → tối đa một tác động business và trạng thái đúng.
- Test migration cache có dữ liệu/pending, single-process lock, network flapping và đổi user/server.
- Credential/TOTP/reset payload không xuất hiện trên disk/log; Windows upgrade bảo toàn journal được B23 kiểm chứng thực.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b19-recovery-all, nhánh agent/b19-recovery-all. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B19_recovery_all.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B19.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
