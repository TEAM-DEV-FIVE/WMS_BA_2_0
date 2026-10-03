# Triển khai WMS — nền tảng, IAM, danh mục và truy vết

Ngày bắt đầu: 02/10/2026. Nhánh: `feat/application-foundation`.
Người thực hiện hiện tại: Trần Trung Kiên, có Codex hỗ trợ theo yêu cầu.
Phân công nhiều thành viên trong issue/hồ sơ cũ là lịch sử kế hoạch, không phải năng lực thực hiện hiện tại.

## Hiện trạng đã đối chiếu

Repository ban đầu chỉ có hồ sơ, SQL, contract và công cụ kiểm tra. Snapshot GitHub đã đọc có 40 issue, gồm 37 issue mở (không phải trạng thái live);
#1/#39/#41 đã đóng và #40 là PR đã merge. Các PR đang mở được sử dụng làm đầu vào tại commit:

- [BE01 / PR #42](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/pull/42): `0157240`, contract/coverage/flow/test contract.
- [QA01 / PR #43](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/pull/43): `799fdfe`, kế hoạch T01–T28, fixtures, ma trận và test tĩnh.
- [UI01 / PR #44](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/pull/44): xem commit trong [trạng thái triển khai](../07_Kiem_tra/implementation_status.json), luồng màn hình.

Các file đầu vào được đưa vào nhánh local, giữ tác giả/nguồn; thao tác này không merge hay đóng PR trên GitHub.
Chưa gửi thông báo, đổi assignee hoặc ghi giờ công thay người khác.

## Phần đã có mã chạy

| Issue | Phần triển khai | Giới hạn còn lại |
| --- | --- | --- |
| #3 TL02 | Cấu trúc server/domain/application/infrastructure, desktop, contracts; cấu hình; health/readiness; entry point; lỗi/request ID | Nghiệm thu chính thức và tích hợp module tiếp theo |
| #4 BE02 | Migration 001–009, IAM/danh mục/owner/hợp đồng/chứng cứ bảo hành; nâng cấp giữ sổ cũ ở UNCLASSIFIED | Phân loại/chuyển owner dữ liệu cũ và kiểm chứng đầy đủ với posting còn thiếu |
| #5 BE03 | Login/refresh/logout, phiên live, TOTP/enrollment, throttle và audit; mã hóa secret | Recovery/reset MFA, đổi mật khẩu và UAT Windows còn thiếu |
| #6 BE04 | Grant theo kho/thời hạn/role; đọc chứng từ và che giá; user/grant APIs, hai quản trị viên duyệt cấp quyền | Export/download và tích hợp các nghiệp vụ còn chưa xây dựng |
| #7 TL03 | Command kernel, receipt.post/execution ACK/operation lookup, retry deadlock và desktop phục hồi cùng key/body | Posting khác và recovery cho các loại lệnh còn lại |
| #8 BE05 | API danh mục/owner/hợp đồng, UOM/barcode/giá, tồn theo owner, serial/bảo hành có chứng cứ và scope | Import, policy xuất/chuyển ký gửi và UAT |
| #9 BE06 | PO/SO create/read/list/update, quy đổi snapshot, assignment, lượng ròng và đóng thiếu | Đã nối receipt và khóa nguồn; issue, release reservation và UAT còn thiếu |
| #10 BE07 | Submit/approve/reject/revise, snapshot nội dung/role, SOD một/hai bước | Đã nối PO/SO/receipt; policy kiểm kê/điều chỉnh/tồn đầu kỳ còn thiếu |
| #15 UI05 | Tab PO/SO tạo/sửa/gửi/duyệt/từ chối, giữ form khi stale, retry đúng key và lịch sử duyệt | GUI phân công, issue, so sánh revision, recovery SQLite và UAT Windows |
| #14 UI04 | Sáu form danh mục và tab tra serial/bảo hành qua API thật | Form owner/hợp đồng/ghi chứng cứ/barcode/quy đổi/giá, dropdown lớn, SQLite recovery và UAT Windows |
| #12 UI02 | Tk shell, HTTP worker/queue, bỏ response cũ, timeout, TLS, presenter tests | Navigation nghiệp vụ, phân trang và các màn hình tiếp theo |
| #13 UI03 | Login/MFA/logout, đăng ký MFA, chọn kho, refresh token trong RAM, xóa dữ liệu phiên bị thu hồi | GUI quản trị user/grant và nghiệm thu Windows |
| #18 UI08 | Device ID bền, SQLite v2 tách server/user/device, checkpoint receipt.post, tab tra cứu/gửi lại sau crash, khóa file | Phục hồi nháp và lệnh ngoài receipt.post, UAT Windows |
| #23 TL04 | Resolver ownership và nhận hàng nguyên tử: ledger/balance/serial position/tiến độ/audit/outbox | Chưa có các engine xuất/chuyển/đảo và benchmark tải |
| #24 TL05 | Nhận từ PO đã duyệt, kế hoạch lô/serial/vị trí, nhận từng phần, source lock, kỳ/kiểm kê, execution dedup | Tồn đầu kỳ/import và nhận ký gửi chưa có |
| #16 UI06 | Tab nhận hàng nối API thật, duyệt/ghi sổ từng phần và phục hồi receipt.post qua SQLite | Máy quét, workflow kho khác, UAT Windows |
| #21 QA02 | Workflow unit/contract/Linux+Windows/wheel/PostgreSQL 15+16, runner DB tạm, JUnit | Cần push để chạy CI; chưa có bằng chứng Windows/CI từ đợt này |

Server đã có 61 paths runtime gồm health/readiness, IAM, danh mục, PO/SO/duyệt, tồn theo owner và bảo hành có giới hạn theo quyền.
[Nhận hàng](RECEIVING.md) mô tả revision 009, setup kỳ kho đầu tiên và giới hạn.
[Phục hồi nhận hàng](RECEIPT_RECOVERY.md) mô tả lưu bền lệnh post, tab tra cứu/retry và thư mục dữ liệu desktop.
[PO/SO và phê duyệt](ORDERS_APPROVAL.md) mô tả phần thêm ngày 03/10/2026, migration 008 và giới hạn của BE06/BE07/UI05.
[Hướng dẫn truy vết](TRACEABILITY.md) ghi rõ cách nâng cấp 006/007, API mới và giới hạn nghiệp vụ.
[Hướng dẫn danh mục](MASTER_DATA.md) mô tả API, màn hình và giới hạn của BE05/UI04.
[Hướng dẫn IAM](IDENTITY.md) giải thích bootstrap, cấu hình MFA, API quản trị và desktop.
`05_API/openapi_runtime.json` được sinh/kiểm tra từ code; `05_API/openapi_core.json` vẫn là hợp đồng đích
cho nghiệp vụ nhận/xuất. CRUD/duyệt PO/SO và receipt.post đã có; issue/posting khác chưa có.

## Cài đặt môi trường phát triển

Python 3.12, PostgreSQL 15+ với ICU; Tkinter cho desktop. Ubuntu cần gói `python3-tk`; test cửa sổ không
có màn hình dùng `xvfb-run`. Trong thư mục repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-app-lock.txt
python -m pip install --no-deps --no-build-isolation -e .
```

Windows PowerShell: tạo venv bằng `py -3.12 -m venv .venv`, kích hoạt
`.\.venv\Scripts\Activate.ps1`, sau đó dùng cùng hai lệnh pip. Wheel là gói Python,
chưa phải bộ cài Windows EXE của QA10. File lock ghi các phiên bản đã chạy ở môi trường Linux này;
job Windows kiểm tra tính tương thích khi CI chạy.

Chỉ cài desktop trên máy người dùng: `python -m pip install -c requirements-app-lock.txt ".[desktop]"`.
Máy server: `python -m pip install -c requirements-app-lock.txt ".[server]"`.
Desktop không cần SQLAlchemy, psycopg hay thông tin kết nối DB.

## Chạy server và desktop

Chuẩn bị database phát triển **mới**, role sở hữu database; chọn cơ chế credential phù hợp ở máy local.
Ví dụ dưới dùng database `wms_dev` và user `wms_dev`; thay bằng cấu hình của bạn.
`.env.example` chỉ là mẫu, ứng dụng không tự nạp file `.env`.

```bash
export WMS_DATABASE_URL='postgresql+psycopg://wms_dev@localhost:5432/wms_dev'
python -m apps.server.infrastructure.migrations
python -m apps.server
```

API lắng nghe `127.0.0.1:8000`. Mở terminal thứ hai, kích hoạt venv:

```bash
export WMS_API_URL='http://127.0.0.1:8000/api/v1'
python -m apps.desktop
```

PowerShell đặt biến bằng `$env:WMS_DATABASE_URL='...'` hoặc `$env:WMS_API_URL='...'` rồi chạy
các module tương ứng. Health xác nhận process sống; readiness chỉ 200 khi DB kết nối được và đủ
migration/checksum. Chưa migrate hoặc DB lỗi trả 503. Schema/seed không tạo tài khoản đăng nhập.

LAN phải dùng HTTPS qua reverse proxy; desktop chỉ chấp nhận HTTP trên loopback để phát triển.
CA nội bộ cấu hình `WMS_CA_FILE`; không có tùy chọn tắt TLS verification. Cấu hình khóa MFA và bootstrap
theo [IDENTITY.md](IDENTITY.md) trước khi quản trị. QA07 còn phải triển khai LAN/backup/firewall.

## Chạy kiểm thử

```bash
# Unit, contract, presenter, SQLite và các bài kiểm tra hồ sơ hiện có
python -m pytest tests -q -m 'not integration and not gui'

# Tạo cluster PostgreSQL tạm qua Unix socket, chạy toàn bộ test không GUI, rồi dọn cluster
python scripts/check_application.py

# Thêm cửa sổ Tk và desktop → HTTP thật → FastAPI → PostgreSQL
xvfb-run -a python scripts/check_application.py --gui

python -m ruff check apps packages tests/foundation scripts/check_application.py
python -m build --no-isolation
python scripts/check_postgres.py
python scripts/check_artifacts.py
```

Chỉ khi sửa artifact/code: rà `git status`, chạy `python scripts/update_artifacts.py`, rồi kiểm tra artifact lại.
JUnit ở `.reports/application.xml` (không commit). Log kết quả tóm tắt và phạm vi ở
[báo cáo triển khai](../07_Kiem_tra/IMPLEMENTATION_REVIEW.md).

CI hoặc Windows có DB test riêng: đặt `WMS_TEST_DATABASE_URL` dùng database tên `wms_test_*`, role có
CREATEDB, rồi chạy runner. Fixture tạo/drop **chỉ database có UUID do lần test tạo**, mỗi test độc lập.
Runner không đọc `WMS_DATABASE_URL` vận hành. Chạy integration mà thiếu cấu hình phải fail, không skip xanh.

## Ranh giới transaction và ứng dụng

View → Presenter → HTTP worker → API → Application service → UoW → PostgreSQL.
Domain và contracts không import UI, HTTP hay persistence. Main thread sở hữu widget, worker chỉ đưa
kết quả vào queue. HTTP timeout không biến thành thông báo đã commit.

CommandBus nhận callback authorization bắt buộc, chạy **trước khi trả replay**. Handler khóa tài nguyên,
kiểm tra version và bất biến, ghi dữ liệu/audit/outbox cùng connection; bus ghi idempotency rồi commit.
Thoát UoW khi chưa commit luôn rollback. Không gọi HTTP, gửi thông báo hay in trong transaction.
Test kernel dùng thao tác tạo organization giả; test_receipts.py bổ sung posting thực tế, rollback và đối soát.
IAM/RBAC đã chạy thật; receipt.post có execution dedup/operation lookup/retry deadlock, còn phải nối các posting khác.

LocalStore dùng một connection trên storage worker, lưu trong `WMS_LOCAL_DATA_DIR` hoặc profile OS mặc định.
Giữ device.sqlite3 và receipts/ khi nâng cấp; không đặt trên network share. Khóa OS chặn mở đồng thời
hai process cùng partition. Receipt.post lưu key/payload trước HTTP; UNKNOWN giữ nguyên lệnh để tra cứu
và retry khi người dùng chủ động chọn. Các lệnh khác chưa nối nhật ký bền; xem hướng dẫn phục hồi ở trên.

## Thứ tự thực hiện tiếp khi chỉ còn một người

1. **Hoàn thiện nhập kho và phục hồi:** receipt từ PO, UI #16 và phục hồi receipt.post #18 đã có; tiếp tục tồn đầu kỳ/import #24/#31, worker #22 và recovery nháp/lệnh còn lại #18.
   Tiếp tục GUI quản trị #13, form owner/hợp đồng/chứng cứ #14 và tích hợp quyền từng endpoint; hoàn thiện T07/T11 trên môi trường đích.
2. **Nghiệm thu luồng nhập và triển khai xuất:** kiểm thử đích #8 → #9 → #10 → #23 → receipt #24 đã có bằng chứng local; hoàn thiện worker/outbox và UI phụ trợ.
   Sau đó giữ chỗ/xuất #25 dùng cùng khóa nguồn/vị trí/product, version, owner và kiểm tra quyền.
   Nghiệm thu T01/T02/T06/T13/T14/T20/T24 trước mở rộng xuất kho.
3. **Nghiệp vụ còn lại:** #25–#30, #31–#33 cùng UI #17–#19; mỗi luồng phải có kiểm thử transaction,
   quyền và retry; hoàn thiện T03–T05/T10/T12/T15–T19/T21/T25/T27/T28.
4. **Vận hành và nghiệm thu:** #34 LAN → #35 concurrency/reconcile → #36 restore → #37 Windows packaging
   → #38 UAT/performance. Chạy T08/T09/T22/T23/T26 trên thiết bị/môi trường đích và tổng hợp đủ T01–T28.

780 giờ trong lịch nhóm cũ không chuyển thành cam kết hoàn thành của một người. Hạn 22/10 được giữ làm
mốc kế hoạch; phạm vi chưa làm hoặc chưa kiểm thử phải hiển thị rõ. Không tự đóng issue, ghi %/giờ giả,
hoặc biến test thành phần thành nghiệm thu toàn hệ thống.
