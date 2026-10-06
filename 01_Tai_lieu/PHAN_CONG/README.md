# Phân công phần còn lại — trạng thái 06/10/2026

**20/26 nhánh đã tích hợp code local: B01–B20.** B19 recovery chung và B20 worker đã ghép, kiểm thử đầy đủ 1156 tests +10 subtests, 0 failed/errors/skips.
[Báo cáo kiểm chứng](../../07_Kiem_tra/B19_B20_INTEGRATION_2026_10_06.md) · [Sổ tích hợp](integration_log.json).

- **B21 LAN và B23 Windows: READY**, đã đồng bộ nền B01–B20 để giao hai agent song song.
- B22 backup chờ B21; B24 tải/bảo mật chờ B21; B25 hồ sơ chờ B21/B22/B23/B24; B26 chờ B21–B25.
- Còn 6 nhánh B21–B26 chưa tích hợp; không giao B19/B20 làm lại. Không tự khởi chạy agent.

[Brief và DAG](KE_HOACH_CON_LAI.md) · [Quy trình](QUY_TRINH_AGENT.md). Catalog/brief ban đầu là lịch sử.
Source worktree B19/B20 giữ nguyên để đối chiếu; không reset hoặc đổi lịch sử agent.
PostgreSQL 001–024 và SQLite 001–003 bất biến. B20 dev027 đã chốt thành release024.
T01–T28 vẫn PLANNED. Thiết bị/mẫu Q06/Q08 bổ sung sau theo yêu cầu người dùng.
Local tests không thay Windows/thiết bị/LAN/15 CCU/DR/UAT. Lỗi hosted CI trước đó #14/#21 và thiếu lịch sử export #19 còn được theo dõi.
Mốc GitHub trước tích hợp là B01–B18/PR46; lần này mới tích hợp local.

## Giao agent

- B21: mở `/home/kien/Đồ án KHMT2_2/worktrees/wms-b21-lan-deployment`, dùng prompt cuối [brief B21](B21_lan_deployment.md).
- B23: mở `/home/kien/Đồ án KHMT2_2/worktrees/wms-b23-windows-packaging`, dùng prompt cuối [brief B23](B23_windows_packaging.md).
- Dùng venv riêng nếu thêm dependency. Interpreter B18 có đủ lock hiện hành để dùng read-only với PYTHONPATH của worktree; venv điều phối cũ thiếu dependency PDF.
