# Quy trình cho 26 nhánh còn lại

Đọc brief Bxx của nhánh trước khi sửa. Danh sách có máy đọc được: [backlog.json](backlog.json).
Các brief ghi **phần còn thiếu**, không yêu cầu viết lại các module đã chạy. Mốc hiện tại là
`d4676b6`, chứa mã đã kiểm chứng `1386b24`: 823 tests + 10 subtests local, 0 failed/skip.
Mốc `06041b7` với 301 tests là lịch sử chia việc ban đầu. T01–T28 vẫn PLANNED; số test này
không thay thế nghiệm thu Windows, thiết bị, tải, backup/restore hoặc xác nhận nghiệp vụ.

## Bắt đầu và phụ thuộc

1. Mở đúng thư mục worktree trong brief. Chạy `rtk proxy pwd`, `rtk proxy git branch --show-current`,
   `rtk proxy git status --short`. Không sửa khi nhầm nhánh hoặc có thay đổi chưa rõ nguồn.
2. Đọc `AGENTS.md`, brief, [baseline](../SCOPE_BASELINE.md), [bất biến](../INVARIANTS.md),
   [triển khai hiện tại](../IMPLEMENTATION.md), [kiến trúc](../ARCHITECTURE.md) và code/test liên quan.
3. READY trong sổ tích hợp hiện tại nghĩa là được triển khai trên `activated_base` đã đồng bộ.
   Trạng thái trong catalog/brief ban đầu chỉ là lịch sử chia việc. WAITING_DEPENDENCIES nghĩa là
   **chưa được lập trình phần phụ thuộc từ checkout ban đầu**. Có thể đọc, rà contract và soạn kế hoạch
   ở báo cáo riêng; chưa nhận mock/stub làm đầu ra hoàn tất.
4. Kiểm tra [sổ tích hợp](integration_log.json) **trên nhánh điều phối mới nhất** bằng:
   `rtk proxy git show feat/application-foundation:01_Tai_lieu/PHAN_CONG/integration_log.json`.
   Chỉ kích hoạt khi mọi phụ thuộc đã có commit tích hợp và được điều phối review. Nhánh/worktree đã tạo
   sẵn không có nghĩa các API phụ thuộc đã tồn tại.
5. Điều phối cập nhật nhánh tính năng từ commit tổng đã chứa phụ thuộc trước khi giao tiếp. Nếu chưa có
   commit riêng, fast-forward nhánh đó đến mốc tổng; nếu đã có nghiên cứu/code thì tích hợp có review,
   không reset mất công việc. Agent tính năng không tự merge/rebase nhánh khác, không cherry-pick riêng migration.
6. Không push, đóng issue, gửi tin GitHub hoặc triển khai vào máy vận hành. Commit local và bàn giao hash.
   Người dùng tự phân agent; tài liệu này không tự khởi chạy agent.

## Sở hữu file và giao diện giữa các nhánh

- Các `owned_paths` là phạm vi chính; tên module mới là đề xuất theo cấu trúc repo, có thể tách nhỏ nếu cần.
  Mỗi nhánh sở hữu thêm test/fixture, tài liệu module và báo cáo Bxx riêng của mình.
- Router `apps/server/api/app.py`, shell `apps/desktop/views/shell.py`, authorization, DTO dùng chung,
  orders, source/stock locks và command kernel là điểm tích hợp chung. Chỉ thêm hook nhỏ thật cần thiết
  cho chức năng chạy end-to-end, ghi diff trong bàn giao; không viết lại hoặc làm rộng API của người khác.
- B02 sở hữu issue/reservation; B03 quality/move; B09 owner; B10 picking/packing; B11 transfer;
  B12 returns; B13 count/period; B14 reversal. Mỗi nhánh có cả API và UI được chỉ định.
- B01 sở hữu file storage/import và import job; B17 export job; B18 print job. Các nhánh này bàn giao
  consumer factory/version, payload schema, dedup key và job executor. B20 ghép registry/vận hành.
  Không đặt file I/O/network/spooler trong handler outbox transaction DB.
- B04 sửa IAM UI/API; B05 master/owner/warranty UI; B06 opening UI; B15 orders/approval UI.
  B19 chờ các form ổn định rồi nối recovery chung, là chủ sở hữu migration SQLite 003.
- B08 sở hữu CI/runner/contract review. B23 được mở rộng build Windows sau B08.
  Dependency mới cần venv riêng, mô tả lý do và lock diff; điều phối chốt bản lock khi tích hợp.
- Điều phối sở hữu tiến độ/nghiệm thu tổng, sổ tích hợp, AGENTS và kế hoạch này. B25/B26 đề xuất thay đổi
  có bằng chứng; không tự sửa trạng thái issue/acceptance tổng. `SHA256SUMS.txt` và runtime OpenAPI sinh
  tự động có thể regenerate trên từng nhánh; điều phối sinh lại khi ghép, không chọn bừa một phía khi conflict.
- Mỗi agent ghi contract đầu ra và dependency thực tế vào báo cáo riêng. Nếu phát hiện phụ thuộc mới,
  dừng riêng phần đó và báo điều phối; tiếp tục phần độc lập, không tự dựng chính sách hoặc API giả.

## Migration khi phát triển song song

Giữ nguyên PostgreSQL 001–018 và SQLite 001–002 đã tích hợp. Các tên `development_migration` trong
catalog được **dành riêng để các worktree phát triển trên DB tạm**, không phải thứ tự release đã cam kết.
Không cần tạo migration rỗng nếu schema hiện có đủ dùng. Nhánh không được cấp tên mà phát sinh nhu cầu
DDL phải báo điều phối cấp tên; không tự dùng số của nhánh khác.

Ví dụ B01 dùng `011_b01_import_files.sql`, B02 dùng `012_b02_issue_reservation.sql`. Mỗi worktree có DB
tạm riêng: việc B02 chưa có 011 trong checkout ban đầu không cho phép đưa DB đó lên môi trường dùng chung.
Runner yêu cầu lịch sử migration là prefix của release. Vì vậy:

- Trước mỗi merge, điều phối chọn **số tăng tiếp theo trên nhánh tổng** cho revision chưa tích hợp;
  nếu khác số phát triển, đổi tên và cập nhật model/dictionary/DBML/tests trong cùng bản ghép.
- Chỉ được đổi revision chưa phát hành và chỉ từng dùng trên DB kiểm thử bỏ được. Không sửa tên/checksum
  migration đã tích hợp hoặc đã chạy trên DB dùng chung; tình huống đó phải thêm revision forward.
- Sau khi đồng bộ nhánh có thứ tự migration mới, tạo lại **DB test tạm** thay vì ép sửa lịch sử DB.
  Không chạy migration thử nghiệm trên dữ liệu vận hành.
- Test fresh install **và upgrade từ 001–010 có dữ liệu**, sau đó upgrade từ mốc tổng ngay trước merge.
  Kiểm tra legacy/owner/serial, rollback, readiness và artifact package migration.
- SQL, model bổ sung, dictionary, DBML, policy/permission/seed và contract liên quan đi cùng nhau.
  Giữ baseline model001 bất biến; seed không ghi đè policy người dùng đã chỉnh.
- B19 chỉ được đổi số SQLite mới nếu có phát sinh được điều phối ghi nhận. Không sửa migration cache đã phát hành.

## Bất biến nghiệm thu chung

PostgreSQL là dữ liệu chính thức; desktop chỉ gọi API, không chứa DB credential.
Decimal chính xác, thứ tự khóa theo INVARIANTS (warehouse/period/location/product/source...), quyền hiện tại,
scope kho/owner, approval/SOD/version/idempotency phải kiểm tra ở server. Ledger/balance/reservation/
serial/audit/outbox/ACK nguyên tử; rollback không để lại phần commit. Ledger không sửa/xóa.

Mỗi luồng mới cần test success, validation/permission/stale, retry/cùng key khác payload, atomic rollback
và race phù hợp bằng PostgreSQL thật. Các flow UI phải dùng API thật, không chỉ mock.
GUI/Tk ở main thread, HTTP/SQLite qua worker, bỏ response của phiên/user/kho cũ.

Owner là chiều dữ liệu xuyên suốt; không hòa COMPANY và CONSIGNED, không dùng ghi chú thay owner.
Thiếu policy tiêu thụ/chuyển chủ ký gửi thì chặn có lý do và báo phần còn chờ. Serial warranty thiếu chứng cứ
thì trả Chưa xác định; không suy thời hạn. Không ghi password/TOTP/token vào journal/log.

Target: server Linux Ubuntu/Debian x64, Windows 10/11 x64 client, không Mac. Tải đại diện 15 CCU / 1 kho / 3 phân khu /
20 GB / 3 năm; lưu hồ sơ ít nhất 5 năm cần sizing riêng. RPO < 1 giờ / RTO < 4 giờ phải đo. Thời gian xử lý phiếu<15min
là cả quy trình, không phải latency một API. Ngưỡng sai lệch nghiệp vụ<0.5% không cho phép phần mềm tạo sai tồn.
Không mở rộng sang kế toán giá vốn/công nợ, sản xuất, đa pháp nhân/3PL, RFID/PDA/mobile hoặc offline posting.

## Chạy kiểm tra đúng nguồn worktree

Các worktree mới không có venv. Dùng interpreter của repo điều phối ở chế độ chỉ đọc với PYTHONPATH đúng
worktree, hoặc venv riêng nếu cần thêm dependency. Không pip install/upgrade/editable-install vào venv dùng chung.
Chạy từ **gốc worktree được giao**; tất cả lệnh shell bắt đầu bằng `rtk`:

```bash
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -c 'import pathlib, apps, packages, migrations; root=pathlib.Path.cwd(); assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) for m in (apps, packages, migrations)); print(root)'
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m pytest tests -q -m 'not integration and not gui'
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy git diff --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
```

Lint cả module/test mới nếu nằm ngoài các đường dẫn mẫu. API/schema thay đổi thì export/check runtime
contract bằng script của repo và kiểm thử migration thích hợp. Runner tạo PG tạm và report riêng
`.reports/application.xml`; cache/port/server/storage phải riêng worktree. HTTP/PG/Xvfb bị sandbox chặn
thì dùng cơ chế escalation của môi trường, không skip test. Không thay HOME/CODEX_HOME.
Không dùng DB vận hành hoặc share cache/server giữa agent.

Thiếu Windows/hardware/DR/hosted CI thì ghi NOT_RUN kèm lý do và các bước cần chạy, vẫn làm phần local
review được. Không gán PASS cho bằng chứng không có, không tự yêu cầu user xác nhận lại tác vụ đã giao.

## Bàn giao

Tạo file báo cáo đúng đường dẫn trong brief. Báo cáo gồm:

1. Nhánh, base commit, commit bàn giao; dependent commits thực dùng, phạm vi đã làm/chưa làm.
2. Contract/routes/payload/event/consumer factory, migration tên/schema/backfill và thay đổi file chung.
3. Lệnh test, actual result/count/environment, link log tương đối hoặc vị trí artifact; NOT_RUN/giới hạn rõ.
4. Đối chiếu các Txx trong brief với bằng chứng thành phần; không tự đổi Txx tổng sang PASS.
5. Rủi ro còn lại, phụ thuộc mới và hướng dẫn điều phối tái lập/review/tích hợp.

Commit local tất cả code/test/docs của nhiệm vụ (không secret/runtime data). Kết thúc trả hash và đường dẫn
báo cáo. Không gọi một nhánh hoàn tất nếu còn mock thay production dependency hoặc test bắt buộc chưa chạy:
phân biệt CODE_READY, NEEDS_ENVIRONMENT và ACCEPTED rõ ràng.

Điều phối tích hợp theo DAG, review migration/contract/file chung, test nhánh và regression tổng tại mốc
nghiệp vụ thích hợp; cập nhật sổ tích hợp bằng commit thật và SHA artifacts sau ghép. Giữ worktree cũ để review.
