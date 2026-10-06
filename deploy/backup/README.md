# B22 — Backup / PITR / restore

Trạng thái: **CODE_READY sau kiểm chứng local; off-host và nghiệm thu RPO/RTO: NEEDS_ENVIRONMENT**.
Chưa có thiết bị backup độc lập được bàn giao. Các mẫu cấu hình ở đây chưa được cài vào máy vận hành.
Chỉ diễn tập PostgreSQL tạm với dữ liệu fixture trong `/tmp`; không truy cập block device,
không format, không lấy dữ liệu thật. [Runbook](../../01_Tai_lieu/BACKUP_RESTORE.md) giải thích quy trình đích.

| Thành phần | Vai trò |
|---|---|
| `scripts/wms_backup.py` | Archive WAL bất biến + SHA256, base backup đã verify, checkpoint DB/files, chuẩn bị và đối soát DR |
| `scripts/backup_admin.py` | Cấu hình root riêng, điều phối bảo trì B21, cảnh báo, giới hạn đường dẫn DR |
| `scripts/lan_stage.py` (B21) | Kiểm tra bundle release và dependency pin trước khi backup |
| `config.example.json` | Thay placeholder bằng thông tin đã bàn giao; không dùng trực tiếp |
| `postgresql.conf.example` | Archive vào mount đã định danh, timeout WAL 60 giây |
| `systemd/` | Base mỗi ngày, checkpoint 15 phút, kiểm tra mỗi 5 phút; chưa enable trên host |
| `tests/` | PostgreSQL16 thật, mất primary giả lập, PITR + files + MFA + replay; lỗi checksum/WAL/capacity |

Chạy từ gốc worktree với interpreter đã cài dependency lock, không dùng `WMS_DATABASE_URL` thật:

```bash
rtk proxy env PYTHONPATH=. WMS_DRILL_REPORT=.reports/b22-drill.json ../wms-b18-printing-scanner/.venv/bin/python scripts/check_application.py --expected-pg-major 16 --test-path deploy/backup/tests --report .reports/b22.xml
```

Runner và fixture tạo cluster riêng, socket riêng dưới `/tmp`, không TCP. Cần ít nhất 2 GiB trống.
Fixture cố định nhỏ; repository/archive giới hạn 1 GiB, kiểm tra tổng cây diễn tập dưới 2 GiB.
Đây là giới hạn phần mềm và kiểm tra dung lượng, không phải quota filesystem cứng.
Không tăng dataset/tải khi chưa bổ sung quota giám sát tương ứng. PG `max_wal_size` không phải hard cap.
Fixture dừng PostgreSQL khi kết thúc; pytest giữ cây tạm để điều tra và quản lý retention của nó.
Report/log nằm `.reports/` (Git ignore); không commit DB, WAL, PDF fixture hoặc khóa MFA.
Không ghép test DR với một DB ngoài runner.

`--local` chỉ bỏ yêu cầu mount trong thư mục diễn tập riêng; không dùng trong profile vận hành.
CLI không có lệnh xóa backup, promote hoặc restore đè. `retention-plan` chỉ đọc/kiểm tra và báo base được ghim.
