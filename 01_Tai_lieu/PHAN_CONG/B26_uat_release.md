# B26 — Nghiệm thu T01–T28 và chốt bản bàn giao

- Nhánh: `agent/b26-uat-release`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b26-uat-release`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B01](./B01_import_files.md), [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B04](./B04_iam_lifecycle.md), [B05](./B05_master_traceability_ui.md), [B06](./B06_opening_ui.md), [B07](./B07_custom_fields.md), [B08](./B08_ci_contracts.md), [B09](./B09_consignment.md), [B10](./B10_fulfillment.md), [B11](./B11_transfer.md), [B12](./B12_returns.md), [B13](./B13_count_period.md), [B14](./B14_reversal.md), [B15](./B15_documents_ui.md), [B16](./B16_import_ui.md), [B17](./B17_reports_export.md), [B18](./B18_printing_scanner.md), [B19](./B19_recovery_all.md), [B20](./B20_outbox_operations.md), [B21](./B21_lan_deployment.md), [B22](./B22_backup_restore.md), [B23](./B23_windows_packaging.md), [B24](./B24_concurrency_security.md), [B25](./B25_docs_runbooks.md)
- Issues liên quan: [#38](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/38) (đối chiếu snapshot local).
- Yêu cầu: GR04, TR02, NFR01, NFR02, NFR03, NFR04, NFR05, NFR06, NFR07, NFR08.
- Bằng chứng liên quan: T01, T02, T03, T04, T05, T06, T07, T08, T09, T10, T11, T12, T13, T14, T15, T16, T17, T18, T19, T20, T21, T22, T23, T24, T25, T26, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B26.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Thực thi T01–T28 đúng scenario/fixture/role/env; mỗi test ghi commit/artifact/version, steps, actual/expected, log/ảnh và reviewer thật.
2. Nghiệm thu end-to-end ứng dụng đã tích hợp trên client Windows/server Linux/LAN/hardware, gồm restore/load/recovery và owner/warranty.
3. Tổng hợp lỗi chặn, regression sau fix và checklist rollback/delivery; không chỉ dùng301tests nền làm bằng chứng đủ MVP.
4. Chuẩn bị release manifest, source và bộ cài đã kiểm chứng để người dùng bàn giao; không push/tag remote/deploy thật/đóng issue thay người dùng.
5. Test chưa chạy giữ NOT_RUN/PLANNED với lý do; chỉ đề xuất PASS khi đủ bằng chứng. Mọi defer/CR phải do người có thẩm quyền chấp nhận, không tự bỏ B07.

## Phạm vi sửa chính

- `07_Kiem_tra/release/ và báo cáo UAT riêng (mới)`
- `release manifest/checklist, liên kết evidence của các nhánh`
- `đề xuất cập nhật acceptance/implementation cho điều phối duyệt`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Toàn bộ suite regression, wheel/install, contract/schema/artifact/checksum và T01–T28 với target evidence.
- Tất cả dependent branches có commit tích hợp và handoff được review; không còn lỗi chặn hoặc scope bị bỏ im lặng.
- Xác nhận nghiệp vụ/người ký là bằng chứng người thật, agent không tự tạo biên bản đã ký.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần người nghiệm thu, Windows/Linux/LAN/thiết bị và số đo DR/load; thiếu đầu vào thì báo chặn phát hành cụ thể.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b26-uat-release, nhánh agent/b26-uat-release. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B26_uat_release.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B26.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
