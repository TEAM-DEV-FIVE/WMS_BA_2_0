# Phân công phần còn lại — 06/10/2026

**22/26 nhánh có mã local đã tích hợp: B01–B21 và B23.** B21 CODE_READY local; B23 mới hoàn thành phần chuẩn bị, chưa build/ký EXE hoặc kiểm thử Windows. Cả hai còn NEEDS_ENVIRONMENT; không coi là nghiệm thu target.
[Báo cáo 1210 tests +10 subtests](../../07_Kiem_tra/B21_B23_INTEGRATION_2026_10_06.md) · [Sổ tích hợp](integration_log.json).

- **B22 backup/PITR và B24 cạnh tranh/bảo mật/tải: READY**, worktree đã đồng bộ để giao song song.
- B25 hồ sơ chờ B22/B24; B26 chờ B22/B24/B25 và bằng chứng target B21/B23 còn thiếu.
- Không giao làm lại code B21/B23; giữ source handoff. Công việc Windows native tiếp tục khi có Windows đang chạy.

[Brief/DAG](KE_HOACH_CON_LAI.md) · [Quy trình](QUY_TRINH_AGENT.md). Catalog/brief ban đầu là lịch sử.
PostgreSQL 001–024 và SQLite 001–003 bất biến. T01–T28 giữ PLANNED. Q06/Q08 thiết bị/mẫu thật làm sau.
Host CI cũ #14/#21 và lịch sử export #19 vẫn được theo dõi. Chưa push hoặc cập nhật issue trong lần tích hợp này; GitHub trước đó ở B01–B18/PR46.

## Giao agent

- B22: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b22-backup-restore`, prompt cuối [brief](B22_backup_restore.md).
- B24: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b24-concurrency-security`, prompt cuối [brief](B24_concurrency_security.md).
- Interpreter B18 có đủ lock, dùng read-only với PYTHONPATH đúng worktree hoặc tạo venv riêng. Venv điều phối cũ thiếu dependency PDF.
- Suite mặc định tests không chứa deploy/lan/tests. Khi đổi LAN/compatibility, chạy thêm suite LAN với Nginx thật; không skip để xanh.
