# B25 — Tài liệu sử dụng, vận hành và hồ sơ bàn giao

- Nhánh: `agent/b25-docs-runbooks`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b25-docs-runbooks`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B07](./B07_custom_fields.md), [B15](./B15_documents_ui.md), [B16](./B16_import_ui.md), [B17](./B17_reports_export.md), [B18](./B18_printing_scanner.md), [B19](./B19_recovery_all.md), [B20](./B20_outbox_operations.md), [B21](./B21_lan_deployment.md), [B22](./B22_backup_restore.md), [B23](./B23_windows_packaging.md), [B24](./B24_concurrency_security.md)
- Issues liên quan: [#2](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/2), [#11](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/11), [#20](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/20), [#38](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/38) (đối chiếu snapshot local).
- Yêu cầu: GR01, GR02, GR03, GR04, TR01, TR02, TR03, TR04, NFR08.
- Bằng chứng liên quan: T01, T09, T22, T23, T26, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B25.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Hướng dẫn vai trò kho/admin theo ứng dụng thật: nhận/tồn đầu/xuất/chuyển/trả/kiểm kê/đảo/import/report/in/offline recovery.
2. Runbook LAN/upgrade/consumer/retry/backup/restore, sơ đồ và contract hiện hành, ma trận49requirements→implementation→tests→evidence.
3. Đào tạo: dữ liệu demo có owner/bảo hành, bài tập và checklist nghiệp vụ; nhận diện mẫu chứng từ/hardware/retention chưa được xác nhận.
4. Chuẩn bị gói bàn giao source/version/config mẫu/migration/template/installer/checksum; ghi giới hạn và known issues, không giả chữ ký/sponsor approval hoặc tự đóng issue.
5. Đối chiếu hồ sơ thiết kế lịch sử với runtime, giữ tài liệu gốc và gắn nhãn thay thế; không sửa số liệu thiết kế cho giống kết quả chưa đo.

## Phạm vi sửa chính

- `01_Tai_lieu hướng dẫn người dùng/admin và runbook (sau khi code ổn định)`
- `03_So_do/ tài liệu hiện hành cần cập nhật`
- `05_API/ chú thích contract`
- `07_Kiem_tra hồ sơ mẫu bàn giao riêng, không tự đổi acceptance tổng`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Chạy hướng dẫn chính từ môi trường sạch bằng artifact, kiểm tra link/command/config và ảnh minh họa khớp UI thật.
- Cross-check mọi yêu cầu/test có owner/evidence hoặc NOT_RUN rõ; không coi checklist là bằng chứng vận hành.
- Người dùng/IT xác nhận tài liệu và đào tạo ở bước UAT thực, không do agent tự ký.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Thông tin bàn giao/đào tạo, mẫu và quyết định còn mở cần người phụ trách thực tế; user sẽ điều phối thu thập.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b25-docs-runbooks, nhánh agent/b25-docs-runbooks. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B25_docs_runbooks.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B25.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
