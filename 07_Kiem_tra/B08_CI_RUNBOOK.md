# B08 — Chạy CI tương đương local

Dùng Python 3.12 và dependencies từ requirements-app-lock.txt. B08 **không thêm dependency, không đổi lock**.
Kích hoạt venv của worktree hoặc dùng interpreter chung chỉ đọc với PYTHONPATH trỏ đúng worktree;
không pip install/editable-install vào venv của điều phối. PostgreSQL 15/16, Tk, Xvfb/xauth trên Linux.

```bash
rtk proxy env PYTHONPATH="$PWD" python scripts/ci_support.py --name lint -- python -m ruff check apps packages tests scripts
rtk proxy env PYTHONPATH="$PWD" python scripts/export_runtime_contract.py --check
rtk proxy env PYTHONPATH="$PWD" python scripts/check_application.py --suite unit --report .reports/unit.xml
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a python scripts/check_application.py --gui --expected-pg-major 16
rtk proxy env PYTHONPATH="$PWD" python scripts/ci_support.py --name sql -- python scripts/check_postgres.py --expected-pg-major 16
rtk proxy env PYTHONPATH="$PWD" python scripts/ci_support.py --name build -- python -m build --no-isolation
rtk proxy env PYTHONPATH="$PWD" python scripts/check_wheel.py
rtk proxy env PYTHONPATH="$PWD" python scripts/check_artifacts.py
```

Chọn PG local bằng `--pg-bindir /usr/lib/postgresql/15/bin --expected-pg-major 15` cho cả hai runner.
Không có binary PG15 thì ghi NOT_RUN; không gọi PG16 là bằng chứng PG15.
Runner application mặc định chạy mọi test dưới tests/, trừ gui nếu không thêm --gui.
`--suite gui` chọn **tất cả** GUI tests không cần DB (Windows và Linux), không hardcode test_desktop.py.
GUI có integration marker chạy ở full suite `--gui`, qua API/PG thật.

Runner tự tạo Unix-socket cluster/DB tạm, dọn trong finally. CI service/Windows có thể truyền
WMS_TEST_DATABASE_URL trỏ PostgreSQL+psycopg với DB `wms_test_*`; fixture tạo DB UUID riêng mỗi test,
role test phải có CREATEDB. Runner xác nhận PG major thực tế bằng SHOW server_version_num.
Không dùng WMS_DATABASE_URL; runner loại biến này khi chạy pytest. Khi sandbox chặn socket/HTTP/Xvfb,
chạy qua cơ chế escalation của môi trường thay vì skip test.

## Thu thập test và chống kết quả xanh thiếu bài

- Fixture dùng chung chuyển từ tests/foundation/conftest.py lên tests/conftest.py, nên module domain mới
  ở bất kỳ thư mục con nào dùng được cùng fixture/isolated storage và GUI cleanup.
- `--strict-markers` biến marker viết sai thành lỗi collection. Plugin scripts/pytest_checks.py kiểm tra
  transitive fixture closure **trước deselection**: test dùng empty_database/database/actor/iam phải có
  integration marker. Không tự gắn marker để che lỗi phân loại.
- Full suite phải chọn ít nhất một integration; suite GUI phải chọn GUI. Sau chạy, runner lỗi nếu
  JUnit vắng, 0 test hoặc selected test bị skipped (kể cả xfail). Deselected do suite unit/gui là có chủ đích.
- tests/test_ci_discovery.py dựng module domain mới trong thư mục tạm và chạy pytest con để kiểm chứng
  auto-discovery, thiếu marker qua fixture gián tiếp và marker sai. Không dựa số test hardcode để thu thập.
- Domain thêm fixture DB riêng không dùng fixture chung phải khai báo integration rõ; plugin không thể
  suy mọi network/DB call động. Reviewer phải đối chiếu collection report khi ghép domain.

## Artifact và môi trường

Mỗi runner ghi `.reports/<name>.xml`, `.log`, `.collection.json`, `.environment.json`.
Metadata có commit, dirty flag, UTC, Python/OS/arch, versions dependency, SHA256 lock và PG version thực.
Không dump environment, connection URL, password hoặc token. Log chứa stdout/stderr lệnh kiểm tra,
không truyền credential qua argv. `ci_support.py --name <name> -- <command>` dùng cho lint/build/design
và ghi log + metadata cả khi command trả lỗi. Runner trả nonzero nếu setup DB fail.

Wheel check cài wheel thật vào prefix mới và chạy Python `-I` ở thư mục tạm ngoài checkout;
verify mọi module WMS ở prefix đó, entry points load được, health/OpenAPI, SQL checksum và SQLite migrations.
Để chạy offline/local, dùng lại third-party dependencies đã khóa từ interpreter gọi script qua .pth path
(không chạy .pth của venv cha); không dùng lại module WMS từ source. Đây không phải kiểm thử cài dependencies
trên máy Windows sạch hoặc installer EXE — phần đó thuộc B23.

application.yml: Ubuntu 24.04 + Windows Server 2022 runner/Python3.12 lint/unit/contract/build/installed-wheel;
Windows Tk non-DB; Linux PG15+PG16 services chạy full suite + Xvfb. Windows Server runner là smoke CI,
không thay Windows 10/11 x64 UAT. validate.yml giữ kiểm tra artifact/design/SQL nền riêng.
Mỗi job có timeout, matrix fail-fast=false, upload .reports và wheel khi có, artifact mang commit SHA.
Workflow chỉ read contents; không publish/push. File YAML tồn tại chưa phải hosted CI PASS.

## Khi tích hợp

Regenerate runtime + inventory từ nhánh tổng bằng export_runtime_contract.py; không chọn bừa bản merge.
Review docs/test/code rồi chạy update_artifacts.py và check_artifacts.py. Nếu có file xóa/rename, stage
đúng thay đổi trước update_artifacts.py vì danh sách artifact lấy từ Git index và untracked files.
Điều phối chạy lại full suite ở commit ghép; bảo toàn migration đã phát hành 001–010.
PG15/Windows/hosted CI chưa có môi trường phải ghi NOT_RUN/NEEDS_ENVIRONMENT với owner và bước chạy.
