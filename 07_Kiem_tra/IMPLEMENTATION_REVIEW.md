# Kết quả kiểm tra nền tảng, IAM, danh mục, PO/SO, nhận hàng và phục hồi

Cập nhật ngày 03/10/2026; nhánh local `feat/application-foundation`, nền `e4de9e5` (PR #40 đã merge).
Mã đã kiểm thử được lưu ở commit local `c57a743` để chia worktree; chưa push/chạy CI/review nghiệm thu mới.
Phân công đợt tiếp theo tại [hướng dẫn worktree](../01_Tai_lieu/PHAN_CONG/README.md).
Môi trường: Linux x64, Python 3.12.3, PostgreSQL 16.15, Tkinter qua Xvfb.

## Kết quả thực chạy

| Kiểm tra | Kết quả | Phạm vi bằng chứng |
| --- | --- | --- |
| `xvfb-run -a .venv/bin/python scripts/check_application.py --gui` | 190 tests + 10 subtests đạt | Unit, contract, static acceptance, IAM/RBAC, danh mục, owner/bảo hành, PO/SO/duyệt/nhận hàng/phục hồi, desktop, SQLite và PostgreSQL thật; 0 skip |
| Desktop → HTTP → FastAPI → PostgreSQL | Đạt | Mở cửa sổ Tk, gọi readiness qua socket TCP thật, nhận trạng thái DB sẵn sàng, đóng worker/server |
| Migration từ DB trống, chạy lại, 2 runner đồng thời | Đạt | 9 revisions; runtime 63 bảng/430 cột/125 FK khớp baseline + IAM/master/ownership/order models; 10 vai trò/56 quyền/121 ánh xạ |
| Nâng cấp từ revisions 001–002, 001–004, 001–005 hoặc 001–007 lên 009 | Đạt | Giữ user/MFA/UOM/category; ledger/số dư cũ giữ nguyên, owner UNCLASSIFIED, không tạo chứng cứ bảo hành giả; policy/approval cũ giữ nguyên, snapshot legacy null |
| Migration lỗi ở revision sau, checksum bị đổi, schema không được quản lý | Đạt | Rollback cả schema/history khi lỗi; từ chối checksum sai/schema unmanaged |
| Command kernel với 2 connection | Đạt | Cùng actor/key/payload chỉ tạo một hiệu ứng/record/audit/outbox; replay giữ body/status; khác payload bị chặn |
| Lỗi giữa transaction, FK hoặc stale version | Đạt | Không để lại dữ liệu/audit/outbox/record dở dang; UoW chưa commit tự rollback |
| SQLite restart khi SENDING | Đạt | Process thật bị dừng, mở lại UNKNOWN, giữ key/payload/execution key; device bền, tách server/user/device; không lưu credential |
| Process chết sau receipt commit, trước lưu ACK | Đạt | HTTP + PostgreSQL thật; desktop mới tra operation và tải phiếu; một transaction/move, tồn 40/100, không cộng lần hai |
| HTTP worker/presenter | Đạt | Main thread không chờ HTTP; response cũ bị bỏ; widget chỉ cập nhật trên main thread; timeout có lỗi rõ |
| `python scripts/check_postgres.py` | Đạt | SQL smoke/trigger, cột model, seed quyền và đối soát DB rỗng |
| Ruff | Đạt | Mã mới, tests nền tảng, runner |
| Build sdist/wheel | Đạt | Gói Python 0.1.0 chứa entry points, SQL migration và schema SQLite |
| Cài wheel ngoài repository | Đạt | Import mã từ thư mục cài tạm, đủ chín migration PostgreSQL/hai schema SQLite, import màn phục hồi, 61 paths runtime; device ID bền và SQLite v2 giữ lệnh khi mở lại |

## Bổ sung IAM / BE03–BE04–UI03

- Login/logout, hết hạn access, Argon2id, token không xuất hiện trong log/audit payload; audit xác thực có actor/request ID.
- Login rate limit dùng PostgreSQL; refresh đúng device, rotation, replay thu hồi phiên; hai connection refresh đồng thời
  không để lại phiên hợp lệ sau replay.
- Đăng ký MFA, secret mã hóa, challenge hết hạn, code đã dùng và challenge dùng lại bị từ chối; sai MFA trên challenge mới
  vẫn bị throttle; hai connection hoàn tất cùng challenge chỉ tạo một phiên.
- Khóa/mở user và revoke auth_version có hiệu lực với phiên đang mở; mở khóa không hồi sinh token cũ.
- Scope GLOBAL/WAREHOUSE/ALL_WAREHOUSES không trộn; grant hết hạn, tương lai, thu hồi, role inactive và permission không có bị từ chối.
- API đọc chứng từ kiểm tra quyền kho, ownership/assignment; che trường giá ở response. SYSADMIN không mặc nhiên thấy kho.
- API quản trị yêu cầu MFA; tạo grant cần hai quản trị viên khác nhau và khác target; approve lại không nhân grant;
  revoke có hiệu lực ở lần gọi sau. Guard phê duyệt nghiệp vụ cho CONTROLLER vẫn chặn tự duyệt/người duyệt bước trước.
- Tkinter đăng nhập và MFA, chọn kho/quyền qua HTTP thật; khóa user trong DB làm desktop xóa trạng thái phiên/quyền.
  Đã sửa cleanup Tk trên main thread; lần chạy cuối không còn cảnh báo finalizer Tk.
- OpenAPI runtime được validate và kiểm tra khớp code; client chỉ refresh GET một lần, bỏ token khi refresh timeout,
  không tự gửi lại lệnh nghiệp vụ.

## Bổ sung BE05 / UI04

- CRUD mềm cho sản phẩm/category/UOM/đối tác/kho/vị trí/barcode; phân trang keyset, lọc và tìm kiếm Unicode
  trên cluster locale C. Không tạo stock move/balance từ danh mục.
- Lệnh API dùng CommandBus với RBAC thật; test cùng key đồng thời, khác payload, stale version, thu hồi quyền
  trước replay và failpoint sau outbox đều đạt. Hai cập nhật category cạnh tranh không tạo chu kỳ.
- Chặn sai kho/cây Zone–Rack–Bin; ngừng cây rỗng từ con lên cha. Tracking/base UOM khóa khi có phát sinh.
- Quy đổi decimal/revision cũ và giá append bất biến ở DB; revision mới vô hiệu barcode cũ. Barcode giữ số 0 đầu,
  không tái gán. Giá không có trong product/scan; price GET cần đúng scope kho.
- Tk → HTTP → PostgreSQL: tạo/sửa/tìm UOM, hiển thị lỗi mã trùng và giữ form; logout xóa danh mục. Presenter giữ
  key/payload sau timeout, reload cùng user khôi phục yêu cầu chưa rõ kết quả; client không gửi lệnh cũ bằng phiên user mới.
- Đã kiểm tra ảnh chụp bố cục form sản phẩm bằng Xvfb với dữ liệu giả ở 900×690. Chưa UAT Windows.
- Wheel/sdist build đạt; cài wheel ngoài repo và import/migration/runtime route đạt. OpenAPI export khớp code.

## Bổ sung owner / bảo hành — UC32/UC33

- Owner/hợp đồng có version/idempotency/audit; thông tin hệ thống, danh tính và hợp đồng đã dùng bất biến.
  Stock item resolver giữ owner/hợp đồng và tracking. Hai kết nối tạo cùng danh tính nhận cùng ID.
- Fixture cùng SKU/vị trí: vật lý 15 = doanh nghiệp 10 + ký gửi 5; đối soát baseline và ownership không sai lệch.
  Dữ liệu cũ 005 nâng lên 007 giữ nguyên stock move/balance và được đánh dấu UNCLASSIFIED.
- Move/reservation sai owner, hợp đồng sai kho/ngày, giữ chỗ/xuất ký gửi và sửa lịch sử bị từ chối.
  Hai kết nối nhận cùng serial ở hai owner/vị trí chỉ một balance dương được commit.
- Bảo hành cần nguồn RECEIVE/RECEIPT đúng serial, chưa đảo; ngày đủ chứng cứ mới xác định VALID/EXPIRED.
  Kiểm tra ngày cuối còn hạn, ngày tương lai, thiếu chứng cứ, múi giờ nghiệp vụ và fallback tzdata khi OS thiếu dữ liệu.
- Scope kho + serial/ownership permissions; RECEIVER cần phiếu được giao; sai kho/thiếu quyền/revoke không lộ chứng cứ.
  Warranty idempotency/replay, stale version đồng thời và failpoint sau outbox đều kiểm tra rollback/atomicity.
  Hai ca giả lập nguồn mất hiệu lực sau authorization (trước/sau khóa) trả 409, không lưu revision/outbox dở dang.
- Tk → HTTP thật → PostgreSQL hiển thị ba trạng thái cùng số phiếu/tên NCC; logout xóa dữ liệu. Ảnh bố cục đã xem
  bằng Xvfb ở 900×690 với dữ liệu giả. Không suy từ đây ra UAT Windows hoặc máy quét.
- Fixture cũ dựng receipt bằng SQL; test_receipts.py nay bổ sung receipt.post thực tế và tra nguồn bảo hành. Chưa có workflow chuyển owner;
  trigger/GET không chứng minh đã hoàn tất T27/T28. Form ghi chứng cứ/owner/hợp đồng chưa có.

## Bổ sung PO/SO và duyệt — BE06/BE07/UI05

- API create/PUT/list/read PO/SO có scope/assignment/version, decimal và quy đổi snapshot do server tính.
  PO/SO không tạo stock move/balance/reservation. Giá không có trong DTO; sửa legacy có giá/nguồn bị chặn để bảo toàn dữ liệu.
- Submit lưu snapshot header/dòng/attributes/phân công và role từng bước. WAREHOUSE_MANAGER/CONTROLLER duyệt thay
  theo Q04; cấm creator/requester/người duyệt bước trước. Hai bước độc lập kiểm tra role/thứ tự và giữ policy snapshot.
- Hai connection cạnh tranh update hoặc approve/reject chỉ một thành công; cùng key create chỉ một phiếu.
  Replay giữ body/status; revoke chặn replay; failpoint sau outbox rollback cả phiếu/approval/audit/idempotency.
- Revise về nháp vô hiệu approval cũ; quyết định và snapshot bất biến. Sửa ngoài API làm lệch nội dung/version bị chặn duyệt.
- Fixture SQL: PO 100, receipt 80 → còn 20; đóng thiếu giữ posted 80, closed 20, còn 0. Reversal loại đúng một lần.
  Hủy đóng lượng chưa thực hiện; reservation mở trên đơn hoặc phiếu con chặn close. Đây chưa phải test posting service.
- Nâng cấp 007 → 008 giữ policy tùy chỉnh và request cũ; không tạo snapshot/duyệt giả. Fresh schema và hai runner migration đạt.
- Tk → HTTP → PostgreSQL: tạo PO, stale form giữ lượng nhập, tải lại, submit, đổi user, approve và logout xóa dữ liệu.
  Presenter giữ key/payload theo user; thiếu quyền GLOBAL danh mục vẫn xem được phiếu có quyền.
- Đã xem ảnh bố cục 900×690 bằng Xvfb với dữ liệu giả. Chưa UAT Windows, chưa GUI phân công hoặc SQLite phục hồi lệnh PO/SO.

JUnit chi tiết tại `.reports/application.xml` khi chạy local; CI sẽ upload báo cáo bằng workflow mới.
Phiên bản dependencies được khóa trong `requirements-app-lock.txt`.

## Liên hệ với nghiệm thu

- **T02:** receipt.post có idempotency/execution dedup/lookup/revoke/concurrent replay; process chết sau commit, mở desktop mới tra cứu vẫn chỉ một hiệu ứng. Chưa nghiệm thu LAN/Windows đủ ca.
- **T12/T13:** API danh mục và desktop có bằng chứng thành phần; import/full UAT còn thiếu.
- **T08:** receipt.post đã nối SQLite v2, tab tra cứu/retry sau restart, kiểm tra lỗi ổ đĩa/file và đổi user.
  Nháp nghiệp vụ và luồng xuất bị thiếu tồn chưa đủ để xác nhận toàn ca T08.
- **T24:** schema/FK/UNIQUE/trigger, UoW và failpoint sau receipt ledger/balance/serial/audit/outbox đạt; chưa nghiệm thu toàn bộ các loại posting.
- **T27/T28:** owner/schema/đối soát/quyền/chứng cứ/desktop có bằng chứng thành phần tại `test_traceability.py`; chưa chạy đủ luồng nhập/xuất/import/báo cáo/UAT.
- **T10/T14/T17:** có bằng chứng thành phần PO/SO, snapshot/SOD/revise/cancel/close và Linux desktop; đã thêm receipt/posting và tranh chấp nguồn; issue/release và UAT đủ luồng còn thiếu.
- **T01–T28:** giữ PLANNED trong ma trận nghiệm thu gốc. Các ca còn lại chưa chạy nghiệp vụ.
- **T07:** có kiểm thử IAM/RBAC thật ở API đọc/quyền/giá/revoke; export/download và duyệt các loại phiếu ngoài PO/SO/receipt chưa triển khai nên chưa nghiệm thu toàn ca.
- **T11:** có kiểm thử API và desktop qua HTTP thật cho khóa user/phiên/MFA/refresh replay trên Linux. Chưa UAT Windows.
- Callback authorization trong test kernel vẫn là fixture; không lấy riêng test kernel làm bằng chứng IAM.

Chưa thực chạy PostgreSQL 15, Windows 10/11, máy in/scanner, tải 15 CCU, backup/WAL restore hoặc bộ cài EXE.
Workflow đã cấu hình Linux/Windows và PostgreSQL 15/16, nhưng chưa push/kích hoạt CI mới. Không suy ra
Windows đạt từ kiểm thử Tk trên Linux. Các cảnh báo deprecation của Starlette/httpx và jsonschema.RefResolver
không làm test thất bại; cần xử lý khi nâng dependencies hoặc sửa contract test đầu vào.

Xem [hướng dẫn IAM](../01_Tai_lieu/IDENTITY.md) và [kế hoạch](../01_Tai_lieu/IMPLEMENTATION.md).
Tiếp theo: tồn đầu kỳ/import, phục hồi nháp/các lệnh ngoài receipt.post, worker outbox và giữ chỗ/xuất kho. GUI quản trị UI03, form bổ sung UI04 và phân công UI05 còn thiếu.
Xem [PO/SO và phê duyệt](../01_Tai_lieu/ORDERS_APPROVAL.md) cho API, cách dùng desktop và giới hạn.
Xem [hướng dẫn owner/bảo hành](../01_Tai_lieu/TRACEABILITY.md) cho giới hạn dữ liệu legacy và policy ký gửi.
Xem [hướng dẫn danh mục](../01_Tai_lieu/MASTER_DATA.md) để biết giới hạn RAM/recovery, dropdown và các form chưa có.

## Bổ sung nhận hàng — TL03/TL04/TL05/UI06

- PO/receipt có bản duyệt thật; tracking/vị trí kế hoạch nằm trong snapshot. Lượng cơ sở và owner COMPANY do server xác minh.
- API partial/complete, cùng HTTP key hoặc execution key không cộng tồn hai lần; lookup ACK gốc; revoke chặn replay/lookup.
- Hai receipt cạnh tranh PO 100 cùng nhận 80: một commit, một SOURCE_EXCEEDED. Cùng execution chỉ một transaction.
- Create receipt cạnh tranh cancel PO dùng cùng source lock, không để receipt hợp lệ trên PO đã hủy.
- Kỳ đóng, vị trí kiểm kê, stale version/snapshot, lượng sai precision/vượt, lô hết hạn/metadata và serial đã hiện hữu bị chặn.
- Ngày backdate không vượt kiểm tra hạn dùng theo ngày hiện tại ở timezone doanh nghiệp. Nhận cách ly vẫn trừ lượng PO theo T01.
- Failpoint sau ledger/balance/serial position/tiến độ/audit/outbox rollback toàn bộ, kể cả serial vừa tạo; retry cùng key thành công.
- Fault injection SQLSTATE 40P01: retry transaction cùng key; hết ba attempt trả 503 retryable, không có tồn dở dang. Đây không phải benchmark deadlock thực tế.
- Batch serial sau post chạy cả reconcile.sql và reconcile_ownership.sql: không có dòng sai lệch.
- Bootstrap kỳ đầu tiên chỉ cho kho chưa có kỳ/lịch sử ghi sổ; audit tài khoản DB, không mở lại kỳ.
- Tk → HTTP thật → PostgreSQL: tạo receipt từ PO, submit, đổi user duyệt, nhận một phần, logout xóa dữ liệu.
- Xem ảnh bố cục 900×690 bằng Xvfb với dữ liệu giả. Presenter kiểm tra giữ execution key/body sau timeout và tách user.

Xem [RECEIVING.md](../01_Tai_lieu/RECEIVING.md). Tồn đầu kỳ, ký gửi, scanner, Windows UAT, worker và workflow kỳ/kiểm kê đầy đủ còn thiếu.

## Bổ sung phục hồi nhận hàng — UI08/TL03/UI06

- `test_receipt_recovery.py`: device ID giữ qua restart, device hỏng không sinh lại; SQLite 001 → 002 giữ hash/key/body,
  rollback cả ALTER khi migration lỗi và từ chối version mới hơn. OS lock ngăn hai store cùng phân vùng;
  process chết giải phóng khóa và lần mở sau đổi SENDING → UNKNOWN.
- Lỗi ghi READY/SENDING không phát HTTP; lỗi lưu ACK sau server commit giữ dữ liệu để tra cứu. Hash sai,
  endpoint ngoài receipt.post, context/ACK hỏng không được gửi lại hoặc coi đã thành công.
- Timeout sau commit: lookup dùng đúng key; 404 giữ UNKNOWN, chặn lệnh mới. Người dùng retry thì GET trước,
  chỉ khi chưa thấy mới POST cùng endpoint/body/HTTP key/execution key. ACK sai phiếu/version/status bị chặn.
- Thiếu quyền/phiên hết hạn/execution mismatch/server bận giữ lệnh chưa rõ kết quả; stale version được lưu là
  từ chối. Đổi user/phiên loại response cũ khỏi UI và không dùng credential user mới cho lệnh cũ.
- Đóng cửa sổ khi HTTP đang chạy vẫn cho worker hoàn tất checkpoint, rồi đóng connection trên chính worker.
  Mở lại không tự POST. Logout xóa dữ liệu đang hiển thị, không xóa journal trên ổ đĩa.
- `test_receipts.py`: process con gửi receipt.post qua HTTP thật tới PostgreSQL, rồi `os._exit(17)` ngay sau
  server commit, trước lưu ACK. Desktop mới dùng device cũ, đăng nhập, nạp UNKNOWN và bấm tra cứu;
  kết quả COMMITTED khớp request/transaction ID gốc. Chỉ một transaction/move, tồn 40, PO remaining 60.
- Đã kiểm tra ảnh tab Phục hồi nhận hàng ở 900×690 qua Xvfb; bảy tab và các nút/chi tiết hiển thị đủ.
  Chưa chạy nhánh khóa file Windows hoặc nghiệm thu trên thiết bị đích.

Xem [RECEIPT_RECOVERY.md](../01_Tai_lieu/RECEIPT_RECOVERY.md). Đợt này chỉ nối lưu bền `receipt.post`;
các lệnh tạo/sửa/duyệt và nháp nghiệp vụ còn ở RAM. Không đổi API runtime hoặc schema PostgreSQL.
