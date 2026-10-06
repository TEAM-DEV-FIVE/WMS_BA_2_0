# Tích hợp local B21/B23 — 06/10/2026

22/26 nhánh có mã local đã tích hợp: B01–B21 và B23. B21 CODE_READY local; B23 chỉ hoàn thành phần chuẩn bị Windows. Chưa nghiệm thu môi trường đích hoặc tạo/ký EXE. T01–T28 giữ PLANNED.

- B21 bàn giao `e7177e013e957c4eb3a2b1696de40b107971fae9`, merge `74ad87ffa523828fc73b91a8da9ff8cef7f0901a`.
- B23 bàn giao `8399359ad79b699527f59b4e80ad74f3d40d49f6`, merge/runtime kiểm chứng `626e4a84a7e31aa9d012fb4320ab50d7e4d0e433`.
- Giữ nguyên PostgreSQL 001–024 và SQLite 001–003. Không đổi route/body, 189 API paths; 26 desktop sections.
- Client B23 kiểm API/recovery protocol qua health headers trước credentials/mutation. Tích hợp bật require_compatibility trong test desktop recovery qua HTTPS/Nginx thật của B21; same-key một kết quả và revoked grant bị chặn.
- Giữ nguyên bàn giao/worktree nguồn. Chỉ giải quyết checksum bằng script, không chọn một phía.

## Kiểm chứng trên bản ghép

**1210 tests +10 subtests PASS**, 0 failures/errors/skips: 1182 application +28 LAN. Có 611 integration và 75 GUI, các nhóm có giao nhau.
Linux/Python3.12.3/PostgreSQL16.15, HTTP/HTTPS loopback, Nginx 1.24.0 giải nén riêng, Tk/Xvfb. Không cài service hoặc áp firewall lên máy hiện tại.
Runner `.reports/b21-b23_full_runner.py` dùng lifecycle PG tạm chính thức và 4 pytest processes, DB fixture riêng. Collection audit 1210 expected=actual; chỉ chuẩn hóa UUIDv4 trong 3 nhãn presenter cũ. Không bỏ bài/skip; environment ghi commit sạch ở trên.

```bash
rtk proxy env PYTHONPATH=. WMS_TEST_NGINX_BINARY=/tmp/wms-b21-nginx/extracted/usr/sbin/nginx ../worktrees/wms-b18-printing-scanner/.venv/bin/python .reports/b21-b23_full_runner.py --gui --expected-pg-major 16 --report .reports/b21-b23-full.xml
```

Tái lập serial bằng runner được commit (cung cấp Nginx đã cài hoặc binary riêng):

```bash
rtk proxy env PYTHONPATH=. WMS_TEST_NGINX_BINARY=/usr/sbin/nginx python scripts/check_application.py --gui --expected-pg-major 16 --test-path tests --test-path deploy/lan/tests --report .reports/combined.xml
```

Ruff toàn apps/packages/tests/scripts và LAN suite, contract check 189 paths, artifact/checksum đều đạt.
Build sdist/wheel và cài wheel vào prefix mới ngoài checkout: module/entry points/health/OpenAPI/PG SQL/SQLite/fonts/PDF PASS. Wheel SHA256 `b7d96a258723799071b55391092f4f7361483fc60cfe025b8bc5969bef7dbc60`. Đây là Linux package regression, không phải EXE Windows.
Bundle LAN đã được tạo lại từ đúng bản ghép: `.reports/b21-b23-delivery`, 84 files, 58 wheel dependency được đối chiếu manifest B21 trước khi tái dùng. Offline install/no-index/pip check tại `/tmp/wms-b21-b23-installed` đạt. Manifest SHA256 `66f8eb3111fd524f77dbeeaf3ee71a5b3b0f47e75d59c6792d418b2167f1850d`. Không dùng bundle B21 cũ với client B23: server cũ chưa có compatibility headers.
Artifacts `.reports/b21-b23-full*`, `.reports/b21-b23-wheel*`, runner ignored; môi trường, counts, thời gian từng shard và SHA bằng chứng ghi tại JSON cùng tên báo cáo.

## Phần còn chờ

B21: Ubuntu Server target, service accounts/peer mapping, LoadCredential/systemd sandbox/reboot, nft/LAN ports/DNS/CA/mounts thực; load/backup do B22/B24 bổ sung. Bằng chứng stage và proxy local không thay rollout target.
B23: build EXE/installer, ký/timestamp, PowerShell/Inno/Win32 DACL, Windows 10/11 install/upgrade/rollback/reboot/DPI và máy in/scanner thật. Windows hiện dual boot chưa chạy; không khởi động lại máy trong phiên tích hợp.
B23 đã bổ sung xử lý O_NOFOLLOW trên Windows, nhưng #21 vẫn chờ hosted/native Windows. #14 layout 900px và #19 lịch sử export vẫn là phần tồn đã ghi trước đó. Không thay issue/GitHub hoặc push trong lần này.

## Kích hoạt tiếp

B22 backup/PITR và B24 concurrency/security được đồng bộ từ bản ghép đã kiểm chứng để người dùng giao song song. B22 phải bảo toàn DB/private files/MFA và restore vào môi trường tách biệt, theo peer/socket profile B21. B24 dùng TLS/health protocol và runtime role thật; load laptop không thay nghiệm thu 15 CCU trên máy đích.
B25 chờ B22/B24; B26 chờ B22/B24/B25 và các bằng chứng target còn thiếu. Có thể tiếp tục Windows trên nhánh nối tiếp từ nền tích hợp khi boot Windows; không dùng checkout B23 cũ để ghi đè bản ghép.
