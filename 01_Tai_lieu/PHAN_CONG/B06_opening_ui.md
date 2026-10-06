# B06 — Giao diện tồn đầu kỳ thủ công

- Nhánh: `agent/b06-opening-ui`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b06-opening-ui`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24), [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) (đối chiếu snapshot local).
- Yêu cầu: FR23, FR30, NFR03.
- Bằng chứng liên quan: T02, T07, T14, T20; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B06.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Form tồn đầu kỳ theo API đã tích hợp: batch key, kho, ngày, dòng SKU/UOM/location/lô/serial; validate giới hạn trước submit.
2. Tạo/sửa/gửi/duyệt riêng người, post, tra execution/ACK và kết quả đối soát; stale version làm mới dữ liệu, timeout hiển thị UNKNOWN.
3. Dùng COMPANY đúng phạm vi backend hiện tại, không tự mở consignment/import. B09 mở owner; B16 nối import; B19 bổ sung journal bền.
4. Phân biệt lập nháp/sync/ghi sổ; tra trạng thái trước khi người dùng retry. Không tạo batch mới để thử lại cùng tác vụ.

## Phạm vi sửa chính

- `apps/desktop/views/openings.py (mới)`
- `apps/desktop/presenters/openings.py (mới)`
- `apps/desktop/api/openings.py (nếu cần, mới)`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Presenter/GUI + PG/API: tự duyệt bị chặn, batch/serial trùng và kho đã có tồn bị từ chối.
- Timeout sau commit → lookup chỉ có một transaction; giữ UI không báo POSTED khi chưa có ACK.
- 201 dòng bị báo giới hạn rõ; pending phản hồi phiên cũ không ghi đè màn hình.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b06-opening-ui, nhánh agent/b06-opening-ui. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B06_opening_ui.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B06.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
