# B22 — Sao lưu, PITR và diễn tập phục hồi

**Kích hoạt 06/10: READY trên nền B21/B23 local đã review và kiểm thử.** Đọc LAN_DEPLOYMENT và deploy/lan: profile Unix socket/peer, owner/runtime tách biệt; backup DB + private files + khóa MFA. Chỉ restore vào môi trường tách biệt; không thay service/firewall/dữ liệu vận hành. Đo RPO/RTO và ghi rõ dataset.

- Nhánh: `agent/b22-backup-restore`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b22-backup-restore`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B21](./B21_lan_deployment.md)
- Issues liên quan: [#36](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/36) (đối chiếu snapshot local).
- Yêu cầu: FR27, GR04, NFR04, NFR08.
- Bằng chứng liên quan: T09, T24; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B22.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Base backup + WAL archive/PITR PostgreSQL, kiểm tra tính toàn vẹn, quyền/secret và lịch/cảnh báo; lưu cấu hình/version để restore đúng release.
2. Bao phủ file storage/import/export/template và khóa cấu hình cần thiết nhất quán với DB; không chỉ backup database rồi bỏ file có tham chiếu.
3. Diễn tập khôi phục trong môi trường tách biệt, target timestamp, rehydrate services và đối soát ledger/balance/serial/reservation/outbox/job pending.
4. Đo RPO < 1 giờ và RTO < 4 giờ có định nghĩa start/end và log; chính sách giữ backup tách hồ sơ nghiệp vụ 5 năm, không đưa password/backup nhạy cảm vào Git.

## Phạm vi sửa chính

- `deploy/backup/ và scripts/restore drill (mới)`
- `runbook backup/restore riêng`
- `tests phục hồi và fixture reconciliation`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Hỏng/mất primary giả lập trên fixture, restore+replay WAL đến mốc chọn, reconciliation và replay job không trùng.
- Thử backup thiếu/corrupt/WAL gap và cảnh báo; retention không phá chain phục hồi.
- Báo số đo thực với cấu hình/dataset, không suy mục tiêu đạt từ script hoặc tiny fixture.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần storage backup độc lập và môi trường DR; dữ liệu/tải đại diện phải được chốt để nghiệm thu RPO/RTO.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b22-backup-restore, nhánh agent/b22-backup-restore. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B22_backup_restore.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B22.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
