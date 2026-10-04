# Kiểm tra và tích hợp các nhánh — 04/10/2026

Kết quả: **12/26 nhánh đã tích hợp code local**, 4 nhánh mới có báo cáo chuẩn bị và 10 nhánh vẫn ở mốc chia
nhánh. Đây là số nhánh có code được ghép, không phải phần trăm hoàn thành hệ thống hoặc nghiệm thu.
Nhánh tổng: `feat/application-foundation`. Đầu lượt rà: `1a17cc5b13377bbaafd70f025756aa8d23717ccb`.
Bản ghép kiểm chứng: `1386b2419dfa42a8dba48fc2028464d18da3d696`; metadata cập nhật sau kiểm thử, không thay mã được kiểm chứng.

## Nhánh đã bàn giao và tích hợp

Đã có B01/B02/B03/B05/B06/B09/B11/B12 trong lịch sử thực của nhánh tổng trước lượt này.
Phát hiện B04/B08/B10/B15 có code bàn giao nhưng chưa ghép; đã review, ghép trong worktree tích hợp riêng
`worktrees/wms-integration-review-20261004`, kiểm thử rồi đưa bản đó vào nhánh tổng.
Nhánh/worktree agent gốc được giữ nguyên, không reset/rebase/cherry-pick mất lịch sử.

| Nhánh | Source bàn giao | Commit ghép trong bản kiểm chứng |
| --- | --- | --- |
| B10: Soạn hàng và đóng kiện | `238a30bcd439` | `4e7db5d90d6f` |
| B04: Hoàn thiện mật khẩu, MFA và quản trị phiên | `2e844a02845a` | `5e6989f614ee` |
| B08: CI, hợp đồng API và nền kiểm thử | `b5e2685a10e4` | `dd8e62fbe5ff` |
| B15: Hoàn thiện PO/SO, phân công và màn hình duyệt | `8bb824ce4e84` | `44b72d14877c` |

Các điểm ghép: giữ hook fulfillment vào issue/reservation, thêm IAM lifecycle, giữ query tìm chứng từ cùng
filter consignment, gắn hộp thư duyệt và toàn bộ lifecycle session/drain/close/finish của **18 mục desktop**.
CI thu thập toàn bộ tests và kiểm missing Bearer trên tất cả route được bảo vệ. Hai endpoint reset password/
recover MFA dùng token/challenge riêng được nhận diện đúng là không dùng Bearer; không mở public các route khác.

Migration B10 giữ **017**, B04 đổi số phát triển 014 thành **018**. Byte 001–016 khớp nền đã tích hợp;
schema cuối **81 bảng / 542 cột / 172 FK**. Bổ sung kiểm upgrade IAM từ 010/016/017 và kiểm legacy
stock/policy từ 016/017. Không đưa migration phát triển vào DB dùng chung hoặc sửa lịch sử đã phát hành.

## Kết quả thực chạy trên bản ghép

- **823 tests + 10 subtests đạt**, 0 failed/errors/skipped, 845.52 giây.
- 395 test mang marker integration; 47 test GUI
  (hai nhóm có giao nhau, không cộng hai số làm tổng). PostgreSQL 16, HTTP thật, Tk/Xvfb và DB tạm riêng.
- Lượt đầu: 822 passed + 10 subtests, 1 failure ở khai báo OpenAPI 503 cho hai route đọc B15. Sửa router,
  regenerate schema/inventory, test hợp đồng đó đạt, rồi chạy lại toàn bộ trên commit cuối ở trên.
- Lint toàn bộ apps/packages/tests/scripts; OpenAPI 141 paths + inventory; artifact/model/dictionary/DBML/
  checksum và whitespace: PASS. Không bỏ/skip test hoặc nới tiêu chí kiểm thử.
- Build sdist/wheel và cài wheel vào prefix mới, import mọi module ngoài source, entry points, HTTP health/
  OpenAPI, 18 SQL PG + 2 SQL SQLite và nguồn resource: PASS. Dùng dependencies đã khóa của interpreter,
  không thay thế kiểm thử cài toàn bộ dependencies trên máy Windows sạch.
- Có 3 deprecation warnings của dependency nền. B04 từng có timeout migration cạnh tranh trên nhánh riêng;
  giữ bằng chứng lịch sử; ca đó đạt trong hồi quy bản ghép, không tăng timeout/skip để che lỗi.

Evidence local (ignored) tại worktree kiểm chứng: `.reports/integration-20261004-final.{xml,log,collection.json,environment.json}`,
`.reports/integration-20261004-final-wheel.*`, `.reports/integration-20261004-build-final.*`,
`.reports/integration-20261004-final-dist/`. Lượt lỗi đầu giữ ở `integration-20261004-full.*`.
[Bản JSON](BRANCH_REVIEW_2026_10_04.json) ghi hash evidence, commit, môi trường và trạng thái đủ 26 nhánh.
Các file evidence được sao chép nguyên byte về `.reports/` điều phối sau khi ghép; không gọi đó là chạy thêm lần nữa.

## Bảng trạng thái hiện tại

| ID | Phạm vi | Trạng thái sau rà | Còn chờ |
| --- | --- | --- | --- |
| B01 | Tệp và import có kiểm tra trước khi ghi | Code đã tích hợp, kiểm thử local | — |
| B02 | Giữ hàng, xuất kho và đóng phần còn lại | Code đã tích hợp, kiểm thử local | — |
| B03 | Kiểm định, cất hàng và di chuyển nội bộ | Code đã tích hợp, kiểm thử local | — |
| B04 | Hoàn thiện mật khẩu, MFA và quản trị phiên | Code đã tích hợp, kiểm thử local | — |
| B05 | Danh mục nâng cao, chủ hàng và bảo hành serial | Code đã tích hợp, kiểm thử local | — |
| B06 | Giao diện tồn đầu kỳ thủ công | Code đã tích hợp, kiểm thử local | — |
| B07 | Trường mở rộng có kiểu và phiên bản | Chỉ có báo cáo chuẩn bị; chờ dependency | B14 |
| B08 | CI, hợp đồng API và nền kiểm thử | Code đã tích hợp, kiểm thử local | — |
| B09 | Hoàn thiện nghiệp vụ hàng ký gửi và phân loại dữ liệu cũ | Code đã tích hợp, kiểm thử local | — |
| B10 | Soạn hàng và đóng kiện | Code đã tích hợp, kiểm thử local | — |
| B11 | Chuyển kho và nhận hàng đang vận chuyển | Code đã tích hợp, kiểm thử local | — |
| B12 | Khách trả hàng và trả nhà cung cấp | Code đã tích hợp, kiểm thử local | — |
| B13 | Kiểm kê, điều chỉnh và khóa kỳ | Có báo cáo chuẩn bị; đủ dependency để đồng bộ | — |
| B14 | Đảo giao dịch và bảo toàn lịch sử | Chỉ có báo cáo chuẩn bị; chờ dependency | B13 |
| B15 | Hoàn thiện PO/SO, phân công và màn hình duyệt | Code đã tích hợp, kiểm thử local | — |
| B16 | Giao diện import và theo dõi xử lý tệp | Có báo cáo chuẩn bị; đủ dependency để đồng bộ | — |
| B17 | Tám báo cáo và xuất dữ liệu có phân quyền | Chưa có commit triển khai | B13, B14 |
| B18 | In chứng từ, tem và máy quét HID | Chưa có commit triển khai | B16, B17 |
| B19 | Nháp và phục hồi mất LAN cho mọi luồng ghi | Chưa có commit triển khai | B07, B13, B14, B16, B18 |
| B20 | Consumer thực tế và vận hành worker | Chưa có commit triển khai | B17, B18 |
| B21 | Triển khai máy chủ và vận hành qua LAN | Chưa có commit triển khai | B20 |
| B22 | Sao lưu, PITR và diễn tập phục hồi | Chưa có commit triển khai | B21 |
| B23 | Bộ cài Windows và nâng cấp an toàn | Chưa có commit triển khai | B19 |
| B24 | Kiểm thử cạnh tranh, phân quyền và tải 15 CCU | Chưa có commit triển khai | B07, B13, B14, B17, B19, B20, B21 |
| B25 | Tài liệu sử dụng, vận hành và hồ sơ bàn giao | Chưa có commit triển khai | B07, B16, B17, B18, B19, B20, B21, B22, B23, B24 |
| B26 | Nghiệm thu T01–T28 và chốt bản bàn giao | Chưa có commit triển khai | B07, B13, B14, B16, B17, B18, B19, B20, B21, B22, B23, B24, B25 |

**Giao tiếp B13 và B16:** các dependency đã được kiểm chứng, nhưng worktree của hai agent còn ở nền cũ
cùng commit nghiên cứu. Điều phối cần đồng bộ riêng từng nhánh, giữ nguyên báo cáo/commit, rồi agent tiếp tục
runtime. Lượt rà này không đổi worktree agent gốc và không ghi họ đã bắt đầu triển khai.
B14 tiếp nối B13; B07 tiếp nối B14 (P3 nhưng vẫn trong phạm vi); B17 chờ B13/B14 rồi tiếp tục báo cáo/export.

Chưa chạy PostgreSQL 15, Windows 10/11, hosted CI, LAN/TLS đích, máy in/scanner thật, tải đại diện 15 CCU,
backup/restore đo RPO/RTO hoặc UAT doanh nghiệp. T01–T28 vẫn PLANNED. Ký gửi vẫn giữ policy outbound
chưa xác nhận là từ chối; recovery bền ngoài receipt.post còn chờ B19. Không push/đóng issue/deploy máy vận hành.
