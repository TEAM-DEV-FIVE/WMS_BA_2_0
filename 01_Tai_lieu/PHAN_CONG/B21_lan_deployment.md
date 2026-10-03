# B21 — Triển khai máy chủ và vận hành qua LAN

- Nhánh: `agent/b21-lan-deployment`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b21-lan-deployment`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B08](./B08_ci_contracts.md), [B20](./B20_outbox_operations.md)
- Issues liên quan: [#34](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/34), [#21](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/21) (đối chiếu snapshot local).
- Yêu cầu: TR01, TR02, TR03, GR04, NFR01, NFR05, NFR08.
- Bằng chứng liên quan: T07, T11, T24, T26; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B21.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Chọn và ghi distro/version Ubuntu/Debian x64, PostgreSQL15/16 có kiểm chứng; cấu hình HTTPS LAN, chứng thư tin cậy client, firewall, service account và quyền file tối thiểu.
2. Service API/outbox/job executors, thứ tự startup/migrate/readiness, log rotation, health checks, restart/shutdown/drain và nâng cấp có dữ liệu.
3. Template cấu hình không secret trong Git; bootstrap user an toàn, client không DB credential, API không migrate tự động.
4. Sizing1 kho / 3 phân khu / 15 CCU / 20 GB / 3 năm và dự báo retention ít nhất 5 năm tách backup; inventory server/storage/backup mounts và runbook rollout/rollback ứng dụng tương thích.

## Phạm vi sửa chính

- `deploy/lan/ (mới)`
- `scripts vận hành/migration/readiness cho môi trường đích`
- `tài liệu riêng về TLS/service/firewall/storage`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Cài từ artifact sạch trên target Linux, reboot services, LAN client kết nối TLS và từ chối chứng thư sai.
- Service account permissions, DB ngoài mạng client không truy cập, logs không chứa secret, migration thất bại giữ release trước/readiness 503.
- Smoke UI/API qua LAN và tài liệu tái lập với version/config/checksum.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần máy/VM Linux đích, mạng LAN/chứng thư và thông số dung lượng; không thực hiện thay đổi máy vận hành thật khi chưa được giao môi trường cụ thể.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b21-lan-deployment, nhánh agent/b21-lan-deployment. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B21_lan_deployment.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B21.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
