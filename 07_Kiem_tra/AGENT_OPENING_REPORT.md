# Bàn giao Agent 1 — OPENING backend

Ngày 03/10/2026. Worktree `worktrees/wms-opening`, nhánh `agent/opening`, nền `d5ba723`.
Commit bàn giao được trả trong thông điệp cuối; chỉ commit local, không push/merge.

## Kết quả và phạm vi

Đã có tạo/sửa/đọc/danh sách OPENING, submit/approve/reject/revise/assign/cancel qua workflow chung,
và post toàn bộ phiếu trên PostgreSQL. Ledger, balance, serial position, document version, audit, outbox,
execution ACK và HTTP idempotency record cùng transaction. Tra ACK tại `/api/v1/openings/operations/{key}`.

Đối chiếu UC23, RBAC và ma trận quyền: dùng `opening.draft`, `opening.approve`, `opening.post` hiện có;
không seed thêm quyền. DIRECTOR duyệt được OPENING mà không cần `document.approve`; WAREHOUSE_MANAGER
không được dùng quyền duyệt phiếu thông thường để duyệt tồn đầu kỳ. SOD creator/requester/prior approver,
thứ tự hai bước, role snapshot, version và quyền hiện hành khi replay được kiểm tra.

Policy mặc định một bước CONTROLLER hoặc DIRECTOR độc lập; giữ khả năng cấu hình hai bước. Các nguồn
hiện có không quy định OPENING luôn hai bước, khác T05 kiểm kê. Migration không thay policy cũ kể cả
policy đang tắt hoặc dùng trùng ID dự kiến seed. Không mượn policy RECEIPT/Q04.

Cutover đợt này là một lần ghi toàn bộ tồn cho kho chưa có lịch sử transaction/move hoặc số dư/giữ chỗ
khác 0. Một batch UUID duy nhất trong kho; mã giữ cả sau hủy. Không nạp bổ sung vào kho đang hoạt động;
lịch sử đã đảo không mở lại cutover. Post khóa độc quyền warehouse để cạnh tranh an toàn với shared
warehouse lock của nhận hàng ở bất kỳ kỳ/vị trí nào. Nếu receipt commit trước, OPENING bị chặn; nếu
OPENING trước, receipt được tiếp tục. Tham chiếu biên bản kiểm kê/ký bắt buộc và nằm trong snapshot.

Quyết định phạm vi, nguồn và API được ghi tại [OPENING.md](../01_Tai_lieu/OPENING.md).

## File thay đổi và contract

| Nhóm | File / nội dung |
| --- | --- |
| Module mới | `apps/server/application/openings.py`, `apps/server/api/openings.py`, `packages/contracts/openings.py` |
| Tích hợp | `apps/server/api/app.py`; `apps/server/application/orders.py` thêm loại/snapshot/workflow; `authorization.py` chọn quyền duyệt theo OPENING |
| DTO dùng chung | `packages/contracts/orders.py`: thêm literal OPENING để response workflow/danh sách hợp lệ; không đổi payload PO/SO/RECEIPT |
| Migration | Chỉ thêm `migrations/010_opening.sql`; giữ 001–009 và baseline |
| Model | `02_CSDL/opening_extension_model.json`, `opening_extension_dictionary.csv`, `opening_extension.dbml` |
| Tests | `tests/foundation/test_openings.py`; cập nhật số bảng/cột/FK runtime trong `test_postgres.py`, giữ kiểm tra baseline |
| Artifact | Sinh `05_API/openapi_runtime.json` từ code; sinh `SHA256SUMS.txt` bằng script chuẩn |
| Tài liệu | `01_Tai_lieu/OPENING.md` và báo cáo riêng này |

Migration thêm hai bảng: `opening_document` (4 cột; document/kho/batch/biên bản), `opening_line`
(6 cột; dòng/vị trí/lô/serial/ngày), thêm đối ứng WMS-OPENING và seed policy khi chưa có. Tổng runtime
65 bảng, 440 cột, 129 FK; 10 roles, 56 permissions và 121 ánh xạ giữ nguyên. Model checker tự phát hiện
`*_extension_model.json` nên không cần sửa `scripts/check_artifacts.py`.

65 API paths, thêm 4 paths OPENING (GET/POST list, GET/PUT detail, POST post, GET operation) và mở rộng
workflow hiện có. Create/PUT nhập quantity_base chuỗi decimal theo UOM cơ sở, owner COMPANY bắt buộc;
tracking/vị trí lưu bảng typed riêng, không thêm namespace JSON. Post chỉ nhận expected_version,
execution_key, reason; không đổi dòng/lượng sau duyệt. Không tạo NCC/receipt/chứng cứ bảo hành từ OPENING.

## Kiểm thử đã thực chạy

Interpreter dependency dùng chỉ đọc từ repo điều phối; `PYTHONPATH="$PWD"` trỏ đúng worktree và đã
assert nguồn `apps`, `packages`, `migrations` đều thuộc worktree này. Không cài/đổi dependency chung.
Runner tạo PostgreSQL cluster và từng database tạm, không dùng `WMS_DATABASE_URL` vận hành.
Sandbox chặn Unix socket ở lần đầu; các lần chạy DB/GUI sau dùng escalation được cho phép.

Lệnh chính từ thư mục worktree:

```bash
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/export_runtime_contract.py --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m build --no-isolation
rtk proxy git diff --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
```

Kết quả full suite: **227 passed, 10 subtests passed, 0 failed/skip**, 188.88 giây; XML tại
`.reports/application.xml` trong worktree (artifact local bị gitignore). Bao gồm 37 ca OPENING mới,
PO/SO, receipt, IAM, migration fresh/re-run/concurrent runners, GUI/HTTP và recovery process chết sau
server commit. Ba cảnh báo deprecation của thư viện hiện có: Starlette/httpx và jsonschema.RefResolver.

Các nhóm chứng cứ trong `test_openings.py`:

- IAM thật: kho sai/thiếu quyền, creator tự duyệt, DIRECTOR dùng quyền riêng, manager bị chặn;
  thu hồi quyền trước replay create/submit/decide/post và tra ACK; không đọc ACK actor khác.
- Một/hai bước duyệt đúng role/thứ tự, không cùng người hai bước, không post khi mới duyệt bước một;
  thay policy sau submit vẫn dùng snapshot; hai quyết định cạnh tranh chỉ một thành công.
- Tạo/sửa/reject/revise/cancel, version cũ, snapshot lệch, batch trùng và mã batch bất biến.
- Kỳ đóng, count lock, vị trí ngừng dùng/sai kho/GROUP, đối ứng sai, precision/scale/float sai,
  owner ngoài COMPANY, tracking sai, serial lặp và serial lượng khác 1.
- NONE, LOT hết hạn theo ngày hiện tại không vượt bằng backdate, nạp khu cách ly, metadata lô xung đột;
  hai kho cùng lô tạo đúng một stock identity; hai kho/vị trí cùng serial chỉ một lần có tồn.
- Hai kết nối cùng HTTP key/cùng execution key trả ACK giống nhau, chỉ một hiệu ứng;
  khác execution hoặc khác phiếu cùng kho chỉ một OPENING được post; cạnh tranh với receipt khác kỳ.
- Failpoint thực sau INSERT ledger, UPDATE balance, INSERT audit, INSERT outbox: rollback transaction,
  balance/serial/stock item/ACK và version; gửi lại đúng key/body thành công một lần.
- Đối soát `reconcile.sql`, `reconcile_ownership.sql`; không có balance đối ứng;
  serial OPENING trả receipt/NCC null, warranty UNKNOWN và không có warranty record giả.
- Nâng cấp 009 → 010 giữ document legacy/policy tùy chỉnh đang tắt/bước duyệt, kể cả trùng ID seed;
  re-run không phát sinh lại. Full suite còn kiểm tra legacy ledger/balance và migration cạnh tranh.

Ruff, `git diff --check`, runtime OpenAPI check và build wheel/sdist đã đạt. Đã mở wheel kiểm tra có đủ
module OPENING và `010_opening.sql`. Kiểm tra artifact/checksum đã đạt sau review: 65 bảng/440 cột runtime,
baseline 56 bảng/355 cột/105 FK giữ nguyên, ZIP khớp nguồn và 375 checksum hợp lệ. Kiểm tra riêng xác nhận
nội dung migration 001–009 và toàn bộ các API path cũ không đổi; chỉ bổ sung paths/schema OPENING.

## Giới hạn, ca chưa chạy và việc điều phối

- Chưa làm UI tồn đầu kỳ, import CSV/Excel, dry-run/staging/hash file/chunk pipeline, ký gửi, xuất kho,
  điều chỉnh/đảo hay worker. T20 và T01–T28 giữ nguyên trạng thái nghiệm thu; không đổi sang PASS.
- Không có kiểm thử UAT Windows, tải production, nâng cấp DB vận hành, biên bản/chữ ký thực tế hoặc
  recovery desktop OPENING. Mỗi phiếu 1–200 dòng và một lần post/kho; cần thiết kế mở rộng cho import lớn.
- Biên bản là tham chiếu do người có quyền nhập/duyệt; API không xác minh chữ ký và chưa có cửa sổ cutover
  cấu hình theo thời gian. Cách khóa cutover bằng lịch sử cần nghiệp vụ/điều phối review trước triển khai.
- Chưa cài thử wheel vào môi trường độc lập trong nhánh này; đã build và kiểm tra nội dung wheel.
  Điều phối thực hiện build/cài wheel và full suite sau tích hợp theo phân công.
- Điều phối review thêm thay đổi literal trong `packages/contracts/orders.py` vì các response workflow
  hiện dùng DTO chung; không cần sửa `api/orders.py` hay receipt service/command kernel/fixture chung.
- Các tài liệu tổng/ma trận tiến độ và những đoạn cũ nói “OPENING chưa triển khai” thuộc điều phối cập nhật
  sau tích hợp. Regenerate checksum khi tích hợp; không chọn bừa một phía của conflict `SHA256SUMS.txt`.
- Không có dependency, CI hoặc desktop change. Không sửa worktree khác, không gửi thông báo GitHub.
