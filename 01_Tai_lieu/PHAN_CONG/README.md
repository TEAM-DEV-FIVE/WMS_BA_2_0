# Phân công worktree — đợt đã tích hợp

Ngày 03/10/2026. Người dùng đã điều động và nhận bàn giao ba agent. Mốc ứng dụng `c57a743`, mốc chia
nhánh `d5ba723`. Điều phối đã merge outbox `849a97a`, admin UI `f126186`, opening `0393849` vào
`feat/application-foundation`, giữ nguyên nhánh/worktree bàn giao. Bản ghép đạt 301 tests + 10 subtests;
xem [báo cáo tích hợp](../../07_Kiem_tra/IMPLEMENTATION_REVIEW.md). Chưa push/cập nhật issue GitHub.

Phạm vi và prompt dưới đây là hồ sơ đợt đã hoàn tất. Khi giao đợt mới cần lấy mốc tích hợp mới và phân
lại phạm vi; không tự tiếp tục từ nhánh agent cũ đang thiếu hai nhánh còn lại.

## Bảng giao việc

Thư mục cha: `/home/kien/Đồ án KHMT2_2`.

| Vai trò | Thư mục từ thư mục cha | Nhánh | Phạm vi đợt này |
| --- | --- | --- | --- |
| Điều phối | `WMS_BA_2_0` | `feat/application-foundation` | Review, tích hợp, kiểm thử tổng, cập nhật tiến độ |
| Agent 1 | `worktrees/wms-opening` | `agent/opening` | Backend tồn đầu kỳ #24; chưa import file/UI |
| Agent 2 | `worktrees/wms-outbox` | `agent/outbox` | Worker outbox #22 trên schema hiện có |
| Agent 3 | `worktrees/wms-admin-ui` | `agent/admin-ui` | Desktop quản trị user/quyền #13 qua API hiện có |

Mở đúng thư mục làm workspace của từng agent, rồi gửi một trong các câu sau:

```text
Bạn là Agent 1. Đọc AGENTS.md và 01_Tai_lieu/PHAN_CONG/AGENT_OPENING.md, triển khai nhiệm vụ trong nhánh agent/opening, chạy kiểm thử và bàn giao commit local cùng báo cáo.
```

```text
Bạn là Agent 2. Đọc AGENTS.md và 01_Tai_lieu/PHAN_CONG/AGENT_OUTBOX.md, triển khai nhiệm vụ trong nhánh agent/outbox, chạy kiểm thử và bàn giao commit local cùng báo cáo.
```

```text
Bạn là Agent 3. Đọc AGENTS.md và 01_Tai_lieu/PHAN_CONG/AGENT_ADMIN_UI.md, triển khai nhiệm vụ trong nhánh agent/admin-ui, chạy kiểm thử và bàn giao commit local cùng báo cáo.
```

## Phân vùng sửa mã

- Opening sở hữu module mới `openings`, tích hợp router server, mở rộng workflow duyệt cần thiết,
  migration `010_opening.sql`, model bổ sung tương ứng và kiểm tra schema/OpenAPI. Chưa sửa desktop.
- Outbox sở hữu module worker/outbox và test riêng. Dùng `outbox_event`, `consumer_receipt` hiện có;
  không thay event producer, migration, app router hay command kernel trong đợt này.
- Admin UI sở hữu view/presenter quản trị mới và chỗ gắn tab vào `apps/desktop/views/shell.py`.
  API IAM và core identity client dùng như hiện có; chưa sửa backend/schema.
- Điều phối sở hữu tài liệu tổng (`IMPLEMENTATION.md`, `IMPLEMENTATION_REVIEW.md`, `implementation_status.json`,
  README chính, ma trận nghiệm thu), dependency lock, CI, `pyproject.toml`, fixture chung và command kernel.
  Mỗi agent viết fixture riêng trong test mới, không mở rộng `conftest.py` nếu chưa thống nhất.
- `SHA256SUMS.txt` là output sinh tự động: mỗi nhánh được regenerate để tự kiểm tra;
  điều phối sinh lại khi tích hợp, không giải quyết xung đột checksum bằng cách chọn bừa một phía.

Không thêm đồng thời các migration có thứ tự khác nhau lên DB đang dùng chung. Đợt này chỉ opening thêm
migration; mỗi worktree chạy DB tạm riêng. Không dùng chung server, cache desktop hoặc report khi chạy test.

## Chạy kiểm thử trên máy hiện tại

Các worktree không có `.venv` riêng. Có thể dùng interpreter đã cài dependencies ở repo điều phối theo chế độ
chỉ đọc, nhưng phải đặt `PYTHONPATH` về đúng worktree. Không `pip install`, upgrade hay editable-install vào
venv dùng chung. Nếu cần dependency khác, tạo venv riêng trong worktree và báo thay đổi dependency.

Chạy từ thư mục gốc worktree đang được giao; các lệnh dưới dùng Bash trên máy này:

```bash
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -c 'import pathlib, apps, packages, migrations; root=pathlib.Path.cwd(); assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) for m in (apps, packages, migrations)); print(root)'
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m pytest tests -q -m 'not integration and not gui'
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy git diff --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
```

Runner đầy đủ tự tạo cluster PostgreSQL tạm, chạy integration/GUI và ghi `.reports/application.xml`
ngay trong worktree. HTTP/GUI/PostgreSQL có thể cần quyền chạy ngoài sandbox; dùng cơ chế escalation
của môi trường nếu bị chặn. Không skip test để vượt chặn môi trường. Không thay `HOME`/`CODEX_HOME`.

OpenAPI sinh lại bởi Agent 1 khi thay API. Đường dẫn tuyệt đối trong lệnh chỉ dành cho máy này;
không đưa chúng vào mã runtime của sản phẩm.

## Bàn giao và tích hợp

Mỗi agent hoàn tất một nhánh review được, gồm mã, test và tài liệu riêng. Tạo báo cáo theo brief với:
phần đã làm, file thay đổi, lệnh/kết quả test, giới hạn chưa làm, thay đổi contract/migration, việc cần điều phối.
Commit local rồi trả commit hash ở câu trả lời cuối; không tự push/merge.

Điều phối review diff và test; ưu tiên tích hợp outbox → admin UI → opening. Opening đổi schema/route nên
tích hợp cùng cập nhật model/contract sau cùng trong đợt này. Nếu xuất hiện phụ thuộc thực tế thì đổi thứ tự
có ghi lý do; không cherry-pick rời một migration khỏi phần code/test cần nó.
Sau tích hợp: chạy full suite, export/check runtime OpenAPI, build/cài wheel, kiểm tra artifact/checksum và
cập nhật báo cáo tổng. Giữ nguyên worktree/nhánh agent cho đến khi người dùng xác nhận không cần nữa.

Đợt kế tiếp mới phân import #31, giữ hàng/xuất #25, UI tồn đầu kỳ và mở rộng phục hồi; tránh triển khai
đồng thời khi contract tồn đầu kỳ/worker chưa ổn định.
