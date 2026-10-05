# B07 — Trường mở rộng có kiểu và phiên bản

- Nhánh: `agent/b07-custom-fields`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b07-custom-fields`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P3**.
- Phụ thuộc: [B14](./B14_reversal.md)
- Issues liên quan: [#30](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/30) (đối chiếu snapshot local).
- Yêu cầu: TR04, NFR08, FR30.
- Bằng chứng liên quan: T14, T24; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B07.md`.

**Tích hợp 05/10/2026:** INTEGRATED local trên mã `005f4c81f78c`; chưa ACCEPTED.
[Báo cáo bản ghép](../../07_Kiem_tra/B07_B17_INTEGRATION_2026_10_05.md) ghi kết quả và số migration release.
Mốc kích hoạt và trạng thái ban đầu là lịch sử; không giao lại nhánh này từ checkout cũ.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.
BE09 vẫn thuộc phạm vi nhưng ưu tiên sau an toàn tồn kho. Không tự bỏ/hoãn vô thời hạn khi chưa có quyết định thay đổi.

## Phạm vi cần hoàn thành

1. Định nghĩa trường kiểu dữ liệu/ràng buộc/phạm vi/phiên bản/quyền; UI quản trị và nhập giá trị theo metadata.
2. Validation server, snapshot/version schema với chứng từ; thay definition không phá dữ liệu/approval đã phát sinh.
3. Không cho custom JSON override quantity/baseUOM/owner/warehouse/price permission/ledger; receipt_plan phải theo contract typed.
4. Ghi kế hoạch migrate definition, audit thay đổi và contract cho import/export, cập nhật extension model nếu cần.

## Phạm vi sửa chính

- `apps/server/application/custom_fields.py (mới)`
- `apps/server/api/custom_fields.py (mới)`
- `packages/contracts/custom_fields.py (mới)`
- `apps/desktop/views/custom_fields.py và presenters/custom_fields.py (mới)`

Revision phát triển dành riêng: `025_b07_custom_fields.sql`, chỉ dùng DB tạm. Điều phối chốt số release khi tích hợp theo quy trình chung. Không tạo DDL rỗng nếu không cần.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Đổi kiểu/xóa definition có dữ liệu cũ không làm mất lịch sử; stale approval/version bị chặn.
- Payload giả để ghi trường lõi hoặc lộ giá bị từ chối; kiểm tra giới hạn độ sâu/kích thước/kiểu.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b07-custom-fields, nhánh agent/b07-custom-fields. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B07_custom_fields.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B07.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
