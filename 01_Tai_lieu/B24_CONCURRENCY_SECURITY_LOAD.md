# B24 — Kiểm thử cạnh tranh, quyền và tải trên Linux

Harness chạy production API, PostgreSQL, Nginx TLS với CA được xác minh và quyền SQL runtime
trong database tạm. Không dùng DB vận hành. Số đo máy Linux hiện tại theo yêu cầu người dùng;
workload nhận hàng tổng hợp chưa thay thế workload Q05/Q07 đã được nghiệp vụ xác nhận.
Kết quả và commit bàn giao: [B24](PHAN_CONG/BAN_GIAO/B24.md).

## Chạy lại

Cần Python 3.12 và lock dependency của dự án, PostgreSQL 15/16, OpenSSL, Nginx; Xvfb cho hồi quy GUI.
Trong worktree B24, chọn interpreter đã cài dependency. Môi trường local dùng interpreter chỉ đọc
`../wms-b18-printing-scanner/.venv/bin/python`, `PYTHONPATH=.`. Không cài vào venv chung.
Nếu Nginx không ở PATH, đặt `WMS_TEST_NGINX_BINARY` thành đường dẫn binary đã kiểm chứng.
Máy hiện tại dùng `/tmp/wms-b21-nginx/extracted/usr/sbin/nginx`.

```bash
# Giả sử python là interpreter có dependency; mọi lệnh shell dùng rtk.
rtk proxy env PYTHONPATH=. python scripts/check_application.py --test-path tests/concurrency --test-path tests/security --test-path tests/performance --report .reports/b24-safety.xml
rtk proxy env PYTHONPATH=. WMS_B24_LOAD_PROFILE=local python scripts/check_application.py --test-path tests/performance/test_b24_load.py --report .reports/b24-load-local.xml
rtk proxy env PYTHONPATH=. WMS_B24_STRESS_PROFILE=full python scripts/check_application.py --test-path tests/performance/test_b24_stress.py --report .reports/b24-stress-full.xml
rtk proxy env PYTHONPATH=. xvfb-run -a python scripts/check_application.py --gui --test-path tests --test-path deploy/lan/tests --report .reports/b24-regression.xml
```

Runner tạo cluster/database `wms_test_*`, bỏ `WMS_DATABASE_URL`, dọn tài nguyên khi kết thúc.
Fixture mỗi test có database UUID riêng; cổng HTTPS/API, chứng chỉ, storage và cache dùng thư mục tạm.
Role runtime ngẫu nhiên có mật khẩu ngẫu nhiên trong RAM, không SUPERUSER/CREATEDB/CREATEROLE;
áp dụng đúng `deploy/lan/postgresql/runtime-grants.sql`. Không dùng tài khoản owner cho API.
Owner chỉ tạo fixture, quan sát, đối soát hoặc chèn lỗi có chủ đích trong DB bỏ được.

JUnit, collection và environment/log nằm cùng tên report. Bằng chứng chi tiết ở `.reports/b24/`:
`race-*.json`, `load-local-linux-15ccu.json`, `stress-synthetic-history-50000-skus-1000000-moves.json`.
Không lưu bearer token, header đăng nhập, mật khẩu hoặc URL DB có credential vào evidence.
Evidence cũ cần đối chiếu commit/dirty và thời điểm chạy, không lấy file tồn tại làm bằng chứng lần mới.

## Cạnh tranh và đối soát

36 test race: 12 loại posting × 2 chế độ (cùng HTTP key; khác HTTP key/cùng execution key),
5 cặp chuyển trạng thái × 2 thứ tự và serial cùng mã ở 2 kho × 2 thứ tự.
Posting bao gồm nhận PO, tồn đầu, nhận ký gửi, xuất, chuyển vị trí, trả NCC/khách,
xuất chuyển kho, nhận chuyển kho, mất transit, điều chỉnh kiểm kê và đảo giao dịch.
Cặp chuyển trạng thái gồm approve/reject, reserve vượt tồn, cancel/post, freeze/post và close-period/post.

Mỗi cạnh tranh dùng 2 interpreter process HTTP riêng, barrier trước gửi request và barrier ở lần
begin transaction đầu của mỗi thread API. Evidence lưu PID process, PID PostgreSQL thực tế phải khác nhau,
commit/rollback transaction và mã phản hồi. Các test khóa/race/failpoint của module nền vẫn được chạy
trong hồi quy, bổ sung kiểm chứng ranh giới từng thao tác. Hai thứ tự khởi chạy không bảo đảm hai thứ tự
thắng khóa; không diễn giải việc lặp thành chứng minh mọi lịch xen kẽ.

Đối soát chạy read-only REPEATABLE READ qua 5 file SQL, 25 tập kết quả phải rỗng:
ledger/balance, reservation, serial, owner, fulfillment, transit, consumption, reversal và audit/outbox.
`reconcile_b24.sql` kiểm tra vị trí serial cùng stock identity của last_move; reservation consumed bằng
truy vết; đảo giao dịch đúng lượng/đối ứng; mỗi transaction có audit và outbox chứa transaction_id.
Test chèn sai lệch 0.000001 phải phát hiện: không dùng ngưỡng 0.5% để bỏ qua sai tồn do phần mềm.

## Quyền và sửa lỗi phát hiện

Ma trận 10 role với kho có/không có grant, đọc ownership, ẩn giá và báo cáo có giá chạy qua HTTPS.
Dữ liệu COMPANY/CONSIGNOR kiểm tra lọc owner tách biệt. File export READY được tải trước revoke rồi
bị chặn sau khi thu hồi từng quyền report.read, report.export, ownership.read, serial.read, price.read.
Kiểm tra token lỗi không xuất hiện trong phản hồi/Nginx/application captured logs.
Negative SQL thử sửa lịch sử, số âm/giữ vượt tồn/tiêu thụ vượt giữ, duplicate identity, DDL,
TRUNCATE, tắt trigger và sửa lịch sử migration bằng role runtime.

Đã phát hiện runtime grant ALL DML cho phép sửa/xóa `reservation_consumption`, dù service chỉ INSERT.
Fix nhỏ ở grant script B21: REVOKE UPDATE, DELETE trên bảng này; test thử cả hai và đối soát sau từ chối.
Không đổi migration 001–024 hoặc SQLite 001–003. Điều phối review thay đổi quyền và áp dụng lại grant
script bằng migration owner sau nâng cấp; áp dụng script cũ sẽ cấp lại quyền nên phải triển khai bản mới.
Đây là bảo vệ một bảng truy vết, không khẳng định runtime role là sandbox chống mọi sửa DB trực tiếp.

## Profile 15 CCU

Profile công khai: `tests/performance/b24-local.json`. Seed lựa chọn thao tác 241006; 15 tài khoản/phiên
khác nhau, 1 kho, 3 phân khu zone/rack/bin và 3 cửa nhận. Có 150 SKU, 15 SKU nóng (mỗi phiên một SKU),
15 PO và receipt được duyệt riêng. Phiếu PO/receipt mẫu nền là dữ liệu thiết lập bổ sung.
Mỗi client giữ kết nối HTTP riêng, 40% list receipt, 30% đọc chi tiết, 30% post nhận từng phần 1 đơn vị;
sau mỗi 10 post thành công, replay cùng key/payload và đòi ACK giống hệt. Think time 50 ms.
Warmup 10 giây, đo 60 giây, closed loop; thời gian báo cáo gồm drain request cuối. UUID thay đổi mỗi lần;
seed cố định phân phối lựa chọn, không cố định lịch điều phối thread.

API pool 3/max_overflow 0. Sáu worker production (outbox/import/export/print/export-cleanup/print-cleanup)
dùng pool độc lập 3, chạy dưới thread supervision local. Cleanup cần hơn 1 connection vì storage fence
giữ connection trong lúc mở transaction khác. Đây không phải bằng chứng systemd process supervision.
Outbox xử lý sự kiện thật; các worker job/cleanup thực hiện vòng poll nhưng profile không tạo hàng đợi
import/export/print có tải. Không suy ra năng lực xử lý đồng thời các loại job từ số đo này.

Thu thập count/status/p50/p95/p99/max từng API, throughput, số post thật kể cả warmup, replay,
SQLSTATE/retry/commit/rollback API, backend PID, deadlock toàn DB và mẫu lock mỗi 50 ms.
Rollback có thể là kết thúc transaction đọc; không tự đồng nghĩa lỗi nghiệp vụ.
Observer phải hoạt động và có mẫu, mỗi phiên phải có post thật. Worker retry/exhausted được tính lỗi.
Throughput = số request kết thúc có start trong pha đo / thời lượng đo gồm drain.
Lock là số mẫu tức thời, không phải toàn bộ thời gian chờ hoặc số lần chờ chính xác.
CPU chỉ tính tiến trình Python API/driver/worker, chưa gồm PostgreSQL/Nginx.

Chạy mặc định trong hồi quy dùng 15 SKU, warmup 1 giây và đo 5 giây để phát hiện lỗi; không dùng làm benchmark.
Chạy profile local riêng, tránh các test khác khi đo. Snapshot tồn sau cùng phải đúng số post thành công,
không thêm giao dịch khi replay và 25 đối soát rỗng. Lỗi HTTP warmup cũng làm test thất bại.

## Stress riêng

Profile `b24-stress.json`: đúng 50.000 SKU, 1.000.000 stock_move, 50.000 stock_balance, 20 transaction.
Fixture nhân dữ liệu quan hệ từ 1 receipt thực đã post bằng SQL, giữ FK/check/index/trigger, phân insert
20 vòng rồi ANALYZE và đối soát. Dòng chứng từ tổng hợp vượt giới hạn API có chủ đích để thử lưu trữ;
không mô phỏng duyệt/post 1 triệu lần, không tạo lịch sử 3 năm, không chạy workers trên payload tổng hợp.
Thời gian seed/đối soát và dung lượng DB được ghi riêng; không gọi tốc độ seed là throughput nghiệp vụ.
Mặc định smoke 100 SKU/2.000 moves; chỉ biến `WMS_B24_STRESS_PROFILE=full` bật dataset lớn.

## Đo nghiệm thu nghiệp vụ còn lại

Máy Linux hiện tại đã được người dùng chọn. Chưa có tỷ lệ nghiệp vụ/dataset Q05/Q07 được xác nhận,
20 GB/3 năm, workload kéo dài/đa máy Windows qua mạng LAN hoặc kết quả kiểm kê vật lý.
Những phần này cần bằng chứng riêng; không đổi trạng thái T01–T28 chỉ từ các test local.

Thời gian phiếu <15 phút: ghi mốc bắt đầu tiếp nhận công việc và kết thúc đủ duyệt/ghi sổ/bàn giao theo
quy trình được thống nhất, gồm thời gian chờ người và hàng đợi. Báo cáo từng loại phiếu, số mẫu,
phân vị và tỷ lệ vượt 15 phút; không lấy tổng hoặc p95 API thay mốc đầu-cuối nghiệp vụ.

Sai lệch vật lý <0.5%: chốt scope/cutoff, blind count độc lập, đối chiếu lần hai và nguyên nhân.
Chốt mẫu số cùng nghiệp vụ trước nghiệm thu; đề xuất tỷ lệ dòng SKU-location-owner-lot/serial sai /
tổng dòng đã đếm, kèm sai lệch lượng tuyệt đối theo từng SKU/UOM (không cộng đơn vị khác nhau).
Nêu riêng vật lý vượt sổ/sổ vượt vật lý và xử lý dòng sổ bằng 0. Chưa có dữ liệu đếm nên NOT_RUN.
Đối soát phần mềm luôn yêu cầu chính xác tuyệt đối, bất kể tỷ lệ kiểm kê vật lý.
