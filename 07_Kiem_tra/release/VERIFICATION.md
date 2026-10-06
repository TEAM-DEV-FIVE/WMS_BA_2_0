# Kiểm chứng bản ghép B22/B24 và chuẩn bị B26 — 06/10/2026

Runtime **7b168c010756c194a33872571cd59d6258712b06**, worktree sạch khi chạy và khi ghi report.
B22 merge473ceb2, B24 merge7b168c0. B25fb2e3d8 chỉ thêm hồ sơ/checker, không đổi runtime.

## Kết quả local

**1.313 test +10subtest đạt,0failure/error/skip.** Bộ kiểm tra thu chính xác1313node từ
`tests`, `deploy/lan/tests`, `deploy/backup/tests`; chia4nhóm file không giao nhau. Counter expected/actual
khớp, không thiếu/thừa node. Chỉ chuẩn hóa UUIDv4 ngẫu nhiên trong3testpresenter hiện có khi so collection.
JUnit có1323record do gồm10subtest, không cộng thành1323test độc lập.

| Nhóm | Kết quả | Thời gian |
| --- | --- | --- |
| 0 | 407PASS | 866,19s |
| 1 | 284PASS | 781,02s |
| 2 | 358PASS | 851,11s |
| 3 | 264PASS +10subtest | 921,57s |

Linux6.14x64/glibc2.39, Python3.12.3, PostgreSQL16.15, Nginx1.24, Tk/Xvfb; disposableDB/HTTP/TLS.
Evidence có thể kiểm lại: [JUnit](evidence/regression.xml), [môi trường](evidence/regression.environment.json),
[collection audit](evidence/regression.coverage.json), [nodes](evidence/regression.expected.json).
Không dùng retry để bỏ lỗi; cả4shard exit0 ngay lần này.

Lệnh đã chạy trên coordinator (runner được lưu lại trong evidence):

```bash
rtk proxy env PYTHONPATH=. WMS_TEST_NGINX_BINARY=/tmp/wms-b21-nginx/extracted/usr/sbin/nginx WMS_DRILL_REPORT=.reports/b26-drill.json ../worktrees/wms-b18-printing-scanner/.venv/bin/python .reports/b26_full_runner.py --gui --expected-pg-major 16 --report .reports/b26-full.xml
```

Để tái lập sau checkout, dùng `evidence/regression_runner.py` từ rootrepo, interpreter có lock,
Nginxpath đúng máy và PG16binaries; `.reports/` là đầu ra bỏ được. Runner dựa trên runner chuẩn
`scripts/check_application.py`, không đọc `WMS_DATABASE_URL` vận hành.

PITR trong cùng lượt chạy: [báo cáo fixture](evidence/backup-drill.json),RPO0,62413s,
DBpaused+reconcile2,586s,API+pending replay4,462s, tất cả invariants0 và replay1lần.
Đây là fixture nhỏ cùng host, **không phải** RPO/RTO môi trường vận hành/off-host.

Lint apps/packages/tests/scripts đạt; runtimeOpenAPI189paths và contract inventory khớp;
model101tables/690columns, checksum814files tại runtimecommit đạt. Checkartifact ban đầu chạy song song
build báo inventorydiff; sau build kiểm lại sạch đạt, không thay checksum để né lỗi. Không lưu được
diff của thời điểm lỗi nên chưa xác định chính xác file tạm gây khác biệt.

## Artifact và cài đặt

Buildsdist/wheel đạt. WheelSHA256:
`effa3689d7371d1a478d34f402b704dacc2b9440bbb5b81e3c72a0e1d6ae8866`.
[Evidence cài wheel](evidence/wheel.environment.json): freshprefix ngoài checkout, nhập module/entrypoint,
health/OpenAPI, PGSQLresources/SQLite nháp/PDF đạt. TestClient bị treo trong sandbox, dừng lần đó;
hostrun ngoài sandbox đạt và là report được dùng.

Gói116files verify toàn bộ hash, appsource byte của wheel khớp7b168c0, nativecode khớpd9b5471.
Offline stage58dependencywheels bằng `--no-index --only-binary=:all:`, pipcheck đạt;
`smoke_installed.py` bằng Python-I đã cài ngoài checkout đạt206modules,189routes,24PGSQL,SQLite/PDF.
Prefix `/tmp/wms-b26-offline-7b168c0`; manifest trust/hash ở [README](README.md).
Test verifier7case đạt: valid,tamper,missing,extra,path traversal,badmanifest/duplicatekey,symlink.

B25check49requirements/28scenario/47local links đạt. B26template28record giữ nguyên scenario/fixture/
precondition/steps/expected và để trống actual/reviewer. Không ảnh GUI/giấy giả hoặc chữ ký tự điền.

## CI/native trước bản ghép

NativeVM [37464123861](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37464123861)
WindowsServer2022 và macOS15ARM64 đạt tại d9b5471; [báo cáo chi tiết](../NATIVE_VM_2026_10_06.md).
Windows unit584+10subtest,13GUI và package đạt trong applicationworkflow cùng commit.

ApplicationCI [37464123932](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37464123932)
đã kết thúc **FAILURE**: Ubuntu/Windows unit-packagePASS;PG15 **1202PASS+10subtest,1FAIL**;
PG16CANCELLED. Failure tại `test_b05_forms_fit_default_window_and_clear_user_state`:
buttonright=849+65=914 vượt900px trên Ubuntu runner. Đây là lỗi UI#14 còn mở;
localfonts/Xvfb đạt không xóa failurehost. Không gọi workflow này xanh hoặc đổ lỗiDB/timeout.
CI này ở d9b5471 chưa chứa testB22/B24; hồi quy7b168c0 ở trên là bằng chứng local riêng.

## Kết luận bàn giao

Localintegration và gói ứng viên đã kiểm chứng. **Chưa ACCEPTED**: G01–G08 ở README còn mở, gồm
hai khoảng trống phần mềm#14layout/#19exporthistory và targetUAT/thiết bị/DR/tải/kýpháthành.
Không chạy deployment thật, không thay dữ liệu/khóaDBvận hành, không đóng issue/tag/push trong đợt này.
File `acceptance_tests.csv` vẫn PLANNED; các báo cáo cũ giữ nguyên theo commit của chúng.
