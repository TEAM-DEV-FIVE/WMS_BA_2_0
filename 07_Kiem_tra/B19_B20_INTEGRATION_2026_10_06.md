# Tích hợp B19/B20 — 06/10/2026

B01–B20 đã tích hợp local. Runtime kiểm chứng `1b0f12f892203e0c10c5d81719d9560e0c08f4f2`; B21/B23 đủ phụ thuộc để đồng bộ/giao song song.

- B19: `e1b10182260413a62579f2533cbc30f5f9345a34`, merge `830146198169a8ed3a5433c483d726e170db6c45`.
- B20: `37c44be04d209c3110bc912d368a289f95bcdcca`, merge `1b0f12f892203e0c10c5d81719d9560e0c08f4f2`.
- Giữ nguyên PostgreSQL 001–023 và SQLite 001–002. B20 dev027 → release024; B19 thêm SQLite003.
- Ghép recovery middleware và operations router; replay B20 được phân loại COMMAND. Ma trận120 write:99 COMMAND,19 ONLINE,2 READ_ONLY;189 API paths;26 desktop sections.
- Kiểm thử mới kiểm tra lookup trước send không ghi dữ liệu, ACK sau commit, mất ACK/lookup/same-key resend chỉ một replay/audit, thu hồi grant chặn lookup.

## Kiểm chứng

**1156 tests +10 subtests PASS**, 0 failures/errors/skips; 604 integration, 74 GUI (có giao nhau).
Linux/Python3.12.3/PostgreSQL16.15/HTTP localhost/Tk Xvfb. Chạy tại commit sạch trên nhánh điều phối, interpreter B18 dùng read-only.
Runner giữ lifecycle PG tạm của scripts/check_application.py; chia file thành 4 process pytest/Xvfb, fixture DB riêng. Collection audit 1156 expected=actual, không thiếu/thừa; chỉ chuẩn hóa UUIDv4 trong nhãn3 bài presenter có sẵn. Không sửa/skip test để đạt PASS.

```bash
rtk proxy env PYTHONPATH=. ../worktrees/wms-b18-printing-scanner/.venv/bin/python .reports/b19-b20_full_runner.py --gui --expected-pg-major 16 --report .reports/b19-b20-full.xml
```

Có thể tái lập serial bằng `scripts/check_application.py --gui --expected-pg-major 16`.
Artifacts local `.reports/b19-b20-full*`, runner `.reports/b19-b20_full_runner.py`, wheel `.reports/b19-b20-wheel*`; SHA và môi trường ghi trong JSON cùng tên báo cáo.
Ruff toàn repo, contract export/check, artifacts, migration fresh/upgrade010/023 và wheel cài ngoài checkout đạt.
Wheel SHA256 `142fb0bdbd46544ed924fc047336932af217e34065b6933eb10e51c55e399511`. Schema 101 bảng/690 cột/211FK; PostgreSQL 24 revision, SQLite 3.

## Giới hạn và giao tiếp

Đây là kiểm chứng local, chưa thay nghiệm thu Windows/thiết bị/LAN/tải/DR/UAT; T01–T28 vẫn PLANNED. Q06/Q08 thiết bị và mẫu thật làm sau theo yêu cầu người dùng.
CI trước đó đã ghi lỗi #14 (layout900px), #21 (Windows O_NOFOLLOW và timeout); kết quả Linux local không đóng các lỗi đó. #19 còn thiếu màn/API lịch sử export đầy đủ.
Không push hoặc thay issue trong lần tích hợp này. GitHub audit trước đó vẫn là snapshot B01–B18.

B21 sử dụng registry/CLI/heartbeat của B20, release024 và runbook OUTBOX_OPERATIONS.
B23 bảo toàn device identity, receipts/commands SQLite003 và backup cache; server hỗ trợ protocol B19 trước client.
B22 chờ B21; B24 chờ B21; B25 chờ B21/B22/B23/B24; B26 chờ B21–B25.
