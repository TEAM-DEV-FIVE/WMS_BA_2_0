# B24 — Kiểm thử cạnh tranh, phân quyền và tải 15 CCU

- Nhánh: `agent/b24-concurrency-security`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b24-concurrency-security`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B04](./B04_iam_lifecycle.md), [B07](./B07_custom_fields.md), [B08](./B08_ci_contracts.md), [B13](./B13_count_period.md), [B14](./B14_reversal.md), [B17](./B17_reports_export.md), [B19](./B19_recovery_all.md), [B20](./B20_outbox_operations.md), [B21](./B21_lan_deployment.md)
- Issues liên quan: [#35](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/35), [#6](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/6), [#7](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/7), [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23), [#20](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/20) (đối chiếu snapshot local).
- Yêu cầu: GR01, GR02, GR03, NFR01, NFR02, NFR05, FR32, FR33.
- Bằng chứng liên quan: T02, T03, T04, T05, T06, T07, T10, T11, T14, T15, T16, T17, T18, T19, T21, T24, T25, T26, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B24.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Race harness multi-process/session PostgreSQL cho mọi posting, approvals, reservation/cancel, freeze/period và reversal; assert DB invariants bằng đối soát độc lập.
2. Security matrix role/kho/owner/price/download, revoke giữa tạo job và tải, direct SQL constraint negative tests và secret leakage checks.
3. Tải đại diện 15 CCU / 1 kho / 3 phân khu, dataset/thời gian warmup/duration/mix/seed công khai; stress50.000 SKU / 1 triệu moves được ghi riêng không giả là số thực tế.
4. Đo throughput/latency/lock/deadlock/retry/reconcile; số đo15 phút là thời gian quy trình phiếu, không phải API SLA; <0.5% sai lệch kho có phương pháp đo riêng.
5. Ghi lỗi về owner nhánh, sửa phạm vi harness hoặc fix nhỏ được review; không nới invariant/skip test để xanh.

## Phạm vi sửa chính

- `tests/concurrency/, tests/security/, tests/performance/ (mới)`
- `reconcile scripts/queries và harness tải`
- `báo cáo riêng đo tải/an toàn`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Lặp race có barrier đủ tái lập, proof ít nhất 2DB connections và commit/rollback outcomes.
- Đối soát ledger/balance/serial/reservation/transit/owner sau full load; lỗi tồn kho do phần mềm không được chấp nhận bằng ngưỡng0.5%.
- Kết quả gồm commit, OS/PG, cấu hình tài nguyên, dataset, log; baseline so sánh sau fix và danh sách hạn chế.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần máy và workload đại diện Q05/Q07; kết quả trên laptop/fixture nhỏ được ghi giới hạn, không tự nâng thành nghiệm thu tải.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b24-concurrency-security, nhánh agent/b24-concurrency-security. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B24_concurrency_security.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B24.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
