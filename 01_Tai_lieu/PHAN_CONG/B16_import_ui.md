# B16 — Giao diện import và theo dõi xử lý tệp

- Nhánh: `agent/b16-import-ui`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b16-import-ui`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Trạng thái hiện tại 04/10/2026: **READY**. Đã đồng bộ nền `d4676b67e1302e0ea545d22da5ec16c4f9453840`,
  giữ commit nghiên cứu `90773d976ae440ec55d80df2937c3ae8f73f1178`; đủ dependency để triển khai.
  Xem commit đồng bộ và dependency thực trong [sổ tích hợp](integration_log.json).
- Phụ thuộc: [B01](./B01_import_files.md), [B06](./B06_opening_ui.md), [B09](./B09_consignment.md), [B15](./B15_documents_ui.md)
- Issues liên quan: [#19](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/19), [#31](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/31), [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24) (đối chiếu snapshot local).
- Yêu cầu: FR22, FR23, FR31, NFR03, NFR07.
- Bằng chứng liên quan: T07, T12, T20; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B16.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Chọn loại import/mẫu, upload, dry-run, bảng lỗi theo dòng, tải lỗi, xác nhận commit bằng hash/token, progress/cancel/resume lookup.
2. Nối import opening vào approval/post của B06; hiển thị owner/hợp đồng, hạn mức và cutover theo B01/B09.
3. Phân biệt lỗi từng dòng với failure toàn job; mất LAN không tạo lại job/file/batch mới. B19 chịu journal bền, B16 cung cấp adapter contract.
4. UI theo quyền kho/file và nguồn tệp; không tự đọc/ghi server storage hoặc DB.

## Phạm vi sửa chính

- `apps/desktop/views/imports.py (mới)`
- `apps/desktop/presenters/imports.py (mới)`
- `apps/desktop/api/imports.py (nếu cần, mới)`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Sửa file sau dry-run, quyền bị thu hồi trước download/commit, file invalid/duplicate và job cancel đúng điểm được xử lý.
- Timeout sau tạo/commit job → lookup/resume không trùng; quá giới hạn opening báo trước hành động.
- GUI tiếng Việt/bàn phím, bảng lỗi lớn có phân trang và không block main thread.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b16-import-ui, nhánh agent/b16-import-ui. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B16_import_ui.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B16.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
