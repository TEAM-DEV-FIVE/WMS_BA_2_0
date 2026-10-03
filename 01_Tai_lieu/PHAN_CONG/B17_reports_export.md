# B17 — Tám báo cáo và xuất dữ liệu có phân quyền

- Nhánh: `agent/b17-reports-export`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b17-reports-export`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B01](./B01_import_files.md), [B02](./B02_issue_reservation.md), [B03](./B03_move_quality.md), [B09](./B09_consignment.md), [B10](./B10_fulfillment.md), [B11](./B11_transfer.md), [B12](./B12_returns.md), [B13](./B13_count_period.md), [B14](./B14_reversal.md)
- Issues liên quan: [#32](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/32), [#19](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/19), [#6](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/6) (đối chiếu snapshot local).
- Yêu cầu: FR24, FR32, FR33, NFR01, NFR05.
- Bằng chứng liên quan: T07, T21, T26, T27, T28; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B17.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. R01: physical/eligible/reserved/available theo SKU/baseUOM/location/owner, transit riêng. R02: nhập-xuất theo tập ranh giới kho/vị trí, không đếm hai lần move nội bộ.
2. R03: sổ theo posted_at,id, business_date là filter riêng. R04: reservation remaining=quantity-consumed-released và nhu cầu mở. R05: dispatch/received/transit/missing có chứng cứ.
3. R06: expiry/tuổi theo lần dịch chuyển phù hợp, không giả lập FIFO cost layers. R07: snapshot/rounds/approved/delta/người duyệt kiểm kê. R08: hoạt động và reference price theo effective_on, che giá theo quyền, không gọi là giá vốn kế toán.
4. UI filter/sort/paging, API truy vấn ổn định, export jobs CSV/XLSX theo contract và PDF nếu baseline mẫu yêu cầu; snapshot/query criteria được ghi lại.
5. Consumer enqueue export job trong DB transaction; thực thi file I/O tách riêng, download kiểm tra lại phiên/quyền hiện tại, owner/kho và quyền giá, kể cả đã tạo file trước thu hồi quyền.

## Phạm vi sửa chính

- `apps/server/application/reports.py, exports.py (mới)`
- `apps/server/api/reports.py, exports.py (mới)`
- `packages/contracts/reports.py (mới)`
- `apps/desktop/views/reports.py và presenters/reports.py (mới)`

Revision phát triển dành riêng: `021_b17_reports_export.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- T21 boundary move nội bộ/liên kho, price permission trước/sau export; cộng dồn đúng Decimal và transit.
- R01–R08 đối chiếu ledger/reservation/count fixture thật; keyset/paging ổn định.
- File CSV/XLSX an toàn với dữ liệu bắt đầu bằng công thức; cancel/retry/job crash không tạo tác động tồn; sizing theo workload Q05.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b17-reports-export, nhánh agent/b17-reports-export. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B17_reports_export.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B17.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
