# B05 — Danh mục nâng cao, chủ hàng và bảo hành serial

- Nhánh: `agent/b05-master-traceability-ui`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b05-master-traceability-ui`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#8](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/8), [#14](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/14) (đối chiếu snapshot local).
- Yêu cầu: FR03, FR04, FR24, FR32, FR33, NFR07.
- Bằng chứng liên quan: T07, T12, T13, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B05.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Hoàn thiện form SKU/UOM/barcode, cây Warehouse→Zone→Rack→Bin, đối tác/giá tham chiếu với quyền; paging/search/version và lỗi validation.
2. Form owner/hợp đồng ký gửi, truy vấn stock tách physical/owned/consigned theo API đang có; phối hợp B09 khi thêm policy.
3. CRUD chứng cứ thời hạn bảo hành có nguồn, tra serial→receipt→NCC→ngày nhập; thiếu nguồn hiển thị Chưa xác định, không tự suy số tháng.
4. Keyboard/tab order, tiếng Việt, dropdown tra dữ liệu lớn và phản hồi phiên cũ; không chỉnh UI quản trị của B04 hoặc UI orders của B15.

## Phạm vi sửa chính

- `apps/desktop/views/master_data.py, serial_lookup.py`
- `apps/desktop/presenters/master_data.py, serial_lookup.py`
- `apps/desktop/views/ownership.py và presenters/ownership.py (mới)`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Presenter + GUI qua API thật cho tạo/sửa/trùng/stale và quyền giá; lookup không chỉ hoạt động với fixture nhỏ.
- T28 có/không có chứng cứ, hết/còn bảo hành, serial không tồn tại/khác kho; không tiết lộ dữ liệu.
- T27 company 10 / consigned 5 hiển thị đúng tổng 15 và từng owner.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Nguồn thời hạn bảo hành và hợp đồng ký gửi thật cần chủ kho cung cấp để UAT; fixture chỉ là dữ liệu giả.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b05-master-traceability-ui, nhánh agent/b05-master-traceability-ui. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B05_master_traceability_ui.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B05.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
