# B01 — Tệp và import có kiểm tra trước khi ghi

- Nhánh: `agent/b01-import-files`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b01-import-files`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#31](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/31), [#4](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/4), [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24) (đối chiếu snapshot local).
- Yêu cầu: FR03, FR22, FR23, FR31, NFR01, NFR02.
- Bằng chứng liên quan: T07, T12, T20, T24; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B01.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Upload/storage nội bộ với hạn mức, hash nội dung, tên tệp an toàn và quyền truy cập theo user/kho; không lộ đường dẫn vật lý hoặc dùng URL công khai để bỏ kiểm tra quyền.
2. Pipeline CSV/XLSX: parse → dry-run → báo lỗi theo dòng/cột → staging → commit bằng token gắn hash, loại import và phiên bản dữ liệu. Chặn file đã đổi sau dry-run, công thức nguy hiểm khi xuất lỗi và trùng mã/serial.
3. Import danh mục, PO/SO đang mở và tồn đầu kỳ qua service nghiệp vụ; có progress/cancel trước điểm commit, retry không tạo bản ghi trùng, không bỏ qua approval hoặc tự phát sinh stock từ đơn mở.
4. Tồn đầu kỳ hiện giới hạn 200 dòng, một lần post/kho và batch key duy nhất. Thiết kế staging/cutover giữ một lần ghi sổ được duyệt; không chia thành nhiều OPENING để lách giới hạn. Giới hạn chưa mở rộng phải được báo rõ trước commit.
5. Consumer outbox nghiệp vụ đăng ký theo factory/version, chỉ enqueue durable import job trong transaction DB. Bộ thực thi file I/O tách khỏi handler outbox, có lease/retry/dedup và phục hồi sau crash; bàn giao giao diện cho B16/B20.

## Phạm vi sửa chính

- `apps/server/application/imports.py (mới)`
- `apps/server/api/imports.py (mới)`
- `apps/server/infrastructure/file_storage.py (mới)`
- `packages/contracts/imports.py (mới)`
- `06_Nhap_lieu/validators/ và fixtures import`

Revision phát triển dành riêng: `011_b01_import_files.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- PG thật: lỗi giữa batch rollback đúng cam kết, cùng hash/key không nhập hai lần, trùng serial và stale master data bị chặn.
- Upload/dry-run/download lỗi sau thu hồi quyền và qua kho khác bị từ chối; test file quá lớn/sai định dạng/path traversal.
- Crash giữa enqueue/execution/ACK phục hồi được; đối soát ledger opening, receipt và import không làm thay đổi ngoài phạm vi.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b01-import-files, nhánh agent/b01-import-files. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B01_import_files.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B01.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
