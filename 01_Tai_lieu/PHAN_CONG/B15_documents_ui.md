# B15 — Hoàn thiện PO/SO, phân công và màn hình duyệt

- Nhánh: `agent/b15-documents-ui`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b15-documents-ui`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#9](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/9), [#10](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/10), [#11](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/11), [#12](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/12), [#15](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/15) (đối chiếu snapshot local).
- Yêu cầu: FR05, FR08, FR19, FR30, NFR03, NFR07.
- Bằng chứng liên quan: T07, T14, T17; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B15.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Phân công người xử lý qua API assignment đang có, tra cứu/paging/filter chứng từ, so sánh các version và approval snapshot.
2. Inbox duyệt PO/SO/receipt hiện có; phân biệt grant theo kho và SOD, stale version phải đọc lại, không tái gửi ghi tự động.
3. Hiển thị received/issued/remaining/closed-partial và lỗi source rõ; trước khi issue có API thật chỉ hiển thị dữ liệu đang được hỗ trợ.
4. Hoàn thiện navigation của các màn này và điểm mở form nghiệp vụ; các agent domain sở hữu form riêng. B19 nối durable draft chung sau.

## Phạm vi sửa chính

- `apps/desktop/views/orders.py`
- `apps/desktop/presenters/orders.py`
- `apps/desktop/views/approvals.py và presenters/approvals.py (mới)`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Presenter/GUI: edit vs approve, assignment bị thu hồi, tự duyệt, paging và đổi kho khi request cũ còn chạy.
- Partial close/cancel không hiển thị thành fully posted; UNKNOWN không bị mất khi đổi màn hình.
- Giữ API thread/SQLite worker tách Tk main thread; không sửa receipt/opening form của nhánh khác trong đợt đầu.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b15-documents-ui, nhánh agent/b15-documents-ui. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B15_documents_ui.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B15.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
