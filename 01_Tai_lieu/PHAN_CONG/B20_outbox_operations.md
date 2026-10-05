# B20 — Consumer thực tế và vận hành worker

- Nhánh: `agent/b20-outbox-operations`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b20-outbox-operations`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B01](./B01_import_files.md), [B08](./B08_ci_contracts.md), [B17](./B17_reports_export.md), [B18](./B18_printing_scanner.md)
- Issues liên quan: [#22](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/22) (đối chiếu snapshot local).
- Yêu cầu: TR04, NFR02, NFR08.
- Bằng chứng liên quan: T02, T24, T26; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B20.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Ghép factories consumer import/export/print đã có vào registry mặc định có version; worker dùng được bằng CLI với cấu hình thật, không no-op consumer giả hoàn thành.
2. Giữ hiệu ứng DB + consumer_receipt nguyên tử; handler không file/network/spool/commit. Đối với I/O worker job riêng dùng lease/retry/dedup và ghi nhận kết quả.
3. Quan sát lag/attempt/failure/dead-letter/job state, structured logs không secret, health/readiness/shutdown; tác vụ replay lỗi có quyền/audit và giới hạn.
4. Chính sách retention/dọn batch tham chiếu record còn dùng và hồ sơ tối thiểu 5 năm; không purge pending hoặc consumer_receipt gây replay duplicate. Runbook retry/drain/version rollout.

## Phạm vi sửa chính

- `apps/server/worker.py`
- `apps/server/application/outbox.py`
- `apps/server/infrastructure/outbox.py`
- `apps/server/consumers/registry.py và worker job composition (mới)`

Revision phát triển dành riêng: `027_b20_outbox_operations.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Hai worker, worker bị kill, handler rollback/crash sau effects, poison message, version mismatch và shutdown; không mất hoặc nhân đôi hiệu ứng DB.
- End-to-end một import/export/print job thật từ domain event đến job/result, I/O failure/retry quan sát được.
- Retention test bảo toàn dedup/history và job đang chạy; nêu rõ giới hạn exactly-once của I/O.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Thời hạn lưu từng loại log/outbox/job cần chính sách Q08; dùng cấu hình bảo thủ, không tự xóa hồ sơ nghiệp vụ.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b20-outbox-operations, nhánh agent/b20-outbox-operations. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B20_outbox_operations.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B20.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```

Điều phối 05/10/2026: dev023 đổi thành027 vì release023 đã thuộc B18; chỉ phát triển trên DB tạm sau đồng bộ.
