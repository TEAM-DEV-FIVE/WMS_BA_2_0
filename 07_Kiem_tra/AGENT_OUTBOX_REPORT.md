# Bàn giao Agent Outbox

Ngày 03/10/2026. Nhánh `agent/outbox`, base `d5ba723`; worktree `worktrees/wms-outbox`.
Phạm vi theo [phân công](../01_Tai_lieu/PHAN_CONG/AGENT_OUTBOX.md). Commit bàn giao được trả trong hội thoại;
không push, merge, đóng issue hoặc cập nhật trạng thái nghiệm thu tổng.

## Kết quả triển khai

- Worker độc lập `python -m apps.server.worker`, chế độ một lượt giới hạn batch, cấu hình riêng
  `WMS_OUTBOX_*`, factory registry từ mã triển khai tin cậy, dừng sạch SIGINT/SIGTERM, dispose engine.
- Registry versioned nhiều consumer, không có fallback/no-op thành công mặc định. Chưa cấu hình consumer
  thì CLI thoát 2 trước kết nối DB. Handler phải xác nhận `HandlerResult.APPLIED` sau hiệu ứng DB thực tế.
- Adapter dùng khóa PostgreSQL `FOR UPDATE SKIP LOCKED` bên ngoài savepoint. Hiệu ứng, receipt và ACK
  cùng transaction; các consumer cùng event cùng thành công hoặc rollback toàn bộ hiệu ứng mới.
- Receipt UNIQUE theo event/consumer và kiểm tra trước handler chặn replay tạo hiệu ứng đã commit lần hai.
  Event không có handler, chưa tới hạn, đã processed hoặc hết retry không bị thay đổi.
- Lỗi rollback savepoint trước khi ghi attempts/backoff và mã lỗi không chứa exception/payload/secret.
  Retry hữu hạn, backoff lũy thừa có trần, exhausted quan sát qua attempts và last_error.
- Hướng dẫn vận hành/retry, giới hạn transaction, chính sách registry đồng nhất và bảo đảm ngoài DB tại
  [OUTBOX_WORKER.md](../01_Tai_lieu/OUTBOX_WORKER.md).

## File thay đổi

| File | Mục đích |
| --- | --- |
| `apps/server/application/outbox.py` | Contract event/consumer/registry/retry, orchestration batch |
| `apps/server/infrastructure/outbox.py` | Claim và transaction delivery trên PostgreSQL |
| `apps/server/worker.py` | Entry point, settings, factory loading, shutdown và logging |
| `tests/foundation/test_outbox.py` | Fixture riêng, unit/integration/process tests |
| `01_Tai_lieu/OUTBOX_WORKER.md` | Hướng dẫn vận hành và hợp đồng consumer |
| `07_Kiem_tra/AGENT_OUTBOX_REPORT.md` | Báo cáo riêng của nhánh |
| `SHA256SUMS.txt` | Sinh lại bằng script sau review |

Không sửa migration 001–009, producers, command kernel, API, desktop, fixture chung, pyproject, lock, CI
hay tài liệu tiến độ/acceptance tổng. Không cần DDL bổ sung để hoàn tất engine trong phạm vi này.

## Kiểm thử

Interpreter dependencies lấy chỉ đọc từ venv của repo điều phối; `PYTHONPATH` trỏ đúng worktree, đã kiểm tra
`apps`, `packages`, `migrations` đều import từ worktree outbox. Không cài/chỉnh dependencies dùng chung.
DB dùng runner tạo cluster PostgreSQL 16.15 tạm và fixture tạo database `wms_test_*` riêng cho từng test.
Sandbox chặn Unix socket PostgreSQL; đã chạy runner qua escalation được cho phép. Không kết nối DB vận hành
hoặc dịch vụ ngoài. Các subprocess worker chỉ nhận URL database test từ fixture, loại bỏ `WMS_*` kế thừa.

Các tình huống được kiểm tra:

- Phân loại due/future/processed/unknown/exhausted; unknown xử lý được khi đăng ký đúng event version.
- Hai worker cùng tranh queue: event đang khóa bị skip; mỗi event/consumer chỉ có một hiệu ứng đã commit.
- Khóa event vẫn giữ sau rollback savepoint tới khi metadata retry commit; worker cạnh tranh không chen vào.
- Batch commit riêng từng event, không thử lại một event hai lần trong lượt.
- Lỗi consumer thứ hai rollback cả hiệu ứng và receipt mới của consumer thứ nhất; audit, outbox gốc và ACK
  command đã commit trước đó giữ nguyên. Handler SQL error không để transaction lỗi làm mất metadata retry.
- Backoff tăng và chạm trần, hết budget không chạy lại, mã lỗi không lộ secret, no-op không được ACK.
- Failpoint trước receipt, trước ACK và sau ACK trước commit rollback; restart tạo đúng một hiệu ứng.
- Replay có receipt cũ không lặp hiệu ứng; processed chỉ sau đủ consumers; payload mỗi consumer độc lập.
- CLI `--once` qua process thật, exit code thành công/lỗi; SIGTERM lúc xử lý/rảnh, SIGKILL/restart.
- Cấu hình sai, registry trùng/không versioned/rỗng, signal handler khôi phục, lỗi DB đóng engine/log redacted.

Lần chạy phát triển đầu đã bắt lỗi UUID ở biểu thức `NOT IN` khi exclude rỗng; đã sửa bind parameter có
kiểu `Uuid` và chạy lại thành công. Ruff đã bắt một lambda gán biến trong test; đã sửa theo quy tắc dự án.
Không xóa/skip test để có kết quả xanh.

Kết quả xác minh cuối:

| Kiểm tra | Kết quả |
| --- | --- |
| Ruff `apps packages tests/foundation scripts/check_application.py` | PASS |
| Full suite `scripts/check_application.py --gui` qua Xvfb | **221 passed + 10 subtests passed**, 135,15 giây |
| Test outbox nằm trong full suite | **31 tests**, gồm 17 integration PostgreSQL/process tests |
| `python -m apps.server.worker --help` | Exit 0; CLI hiển thị đúng chế độ một lượt/factory |
| `git diff --check` | PASS |
| `scripts/update_artifacts.py` rồi `scripts/check_artifacts.py` | PASS định dạng/model/RBAC/OpenAPI/ZIP và **371 SHA-256 checksums** |

Full suite không deselect/skip test. Ba cảnh báo deprecation hiện có đến từ Starlette/TestClient và
`jsonschema.RefResolver`; không đổi dependency chung để xử lý chúng trong nhánh outbox.
JUnit được runner ghi tại `.reports/application.xml` trong worktree (artifact local, không commit).

Lệnh chạy chính từ root worktree:

```bash
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy git diff --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
```

## Giới hạn và việc cần điều phối

**Chưa có consumer nghiệp vụ thực tế** được requirement chỉ định; chỉ có consumer kiểm thử tạo bảng hiệu ứng
DB thật. Engine/adapter là bằng chứng thành phần cho T02/T24, không kết luận #22/QA03 hoàn tất. T01–T28 vẫn
giữ trạng thái PLANNED theo quy trình nghiệm thu, không cập nhật ma trận bằng kết quả unit/integration này.

Điều phối cần chốt projection/tác vụ DB thực sự cho từng event, payload contract, quyền DB và package factory;
review handler không tự commit/ghi ledger hoặc gọi dịch vụ ngoài. Chưa thêm service unit/metric endpoint/UI
retry/retention. Effects ngoài DB cần adapter at-least-once và dedup phía nhận riêng, không có bảo đảm
exactly-once từ cờ processed/receipt đơn thuần.

Tất cả worker phải chạy cùng registry và retry budget. Không có consumer-set version trong schema để bảo vệ
rolling deploy có registry khác nhau. Consumer mới không tự nhận event đã processed; đổi tên consumer có
nguy cơ lặp hiệu ứng. Dừng worker cũ và thiết kế backfill/dedup trước thay subscriptions. Không bảo đảm thứ tự
event cùng aggregate. Retry budget đếm lần đã commit kết quả, không đếm process chết trước commit.

Khi tích hợp, review cả code/test/docs và regenerate checksum ở nhánh điều phối theo quy tắc phân công.
Các bảng lịch sử retry/dead-letter hay metadata version registry chỉ là nhu cầu mở rộng nếu vận hành yêu cầu,
không đề xuất một migration thiết yếu để engine này hoạt động.
