# B18 — In chứng từ, tem và máy quét HID

- Nhánh: `agent/b18-printing-scanner`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b18-printing-scanner`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B05](./B05_master_traceability_ui.md), [B15](./B15_documents_ui.md), [B16](./B16_import_ui.md), [B17](./B17_reports_export.md)
- Issues liên quan: [#33](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/33), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) (đối chiếu snapshot local).
- Yêu cầu: FR26, NFR07, NFR01.
- Bằng chứng liên quan: T07, T22; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B18.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Đủ 4 mẫu chứng từ và 2 loại tem theo ARCHITECTURE; mapping từ dữ liệu thật, font tiếng Việt, mã vạch/QR theo chuẩn đã chọn, preview và chọn khổ/driver.
2. Print job có snapshot/version/quyền, retry/reprint có audit, tuyệt đối không gọi post lại; consumer chỉ ghi durable job, I/O/spooler chạy adapter riêng.
3. HID 1D/2D: focus/terminator/debounce, xác thực barcode/serial và lượng nhập; tích hợp receipt/pick/issue/transfer/count ở các form đã ổn định.
4. Che giá trên preview/file/spool theo quyền; giữ rõ trạng thái gửi job và máy in xác nhận, không cam kết exactly-once trên thiết bị không hỗ trợ.

## Phạm vi sửa chính

- `apps/server/application/printing.py và api/printing.py (mới)`
- `packages/contracts/printing.py (mới)`
- `apps/desktop/printing/ và scanner/ (mới)`
- `mẫu in và nhãn mới trong thư mục thiết kế/in`

Revision phát triển dành riêng: `022_b18_printing_scanner.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Reprint không thêm stock_move; timeout/spooler unavailable/duplicate event không bị báo giao hàng hay POSTED.
- Render mẫu: tiếng Việt, page breaks, barcode scan đọc lại; kiểm tra hạn truy cập snapshot/file.
- T22 scanner HID và in USB/LAN trên Windows đích, có ảnh/log mẫu/model/driver/khổ tem.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần mẫu chứng từ được chọn theo Q08 và model máy in/scanner/driver/khổ tem Q06. Có thể viết adapter/render tests trước; thiếu thiết bị thì ghi NOT_RUN cho hardware UAT.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b18-printing-scanner, nhánh agent/b18-printing-scanner. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B18_printing_scanner.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B18.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
