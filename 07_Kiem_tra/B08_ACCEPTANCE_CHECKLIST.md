# B08 — Checklist flow UI và traceability để tích hợp

Mốc review `45e51a5`; nguồn [UI01 gốc](../01_Tai_lieu/DESKTOP_FLOWS.md),
[baseline](../01_Tai_lieu/SCOPE_BASELINE.md), [kế hoạch T01–T28](KE_HOACH_NGHIEM_THU.md),
[contract review](../05_API/CONTRACT_REVIEW.md), mã `apps/desktop/views/shell.py` và tests/foundation.
Trạng thái API MISSING/PARTIAL trong bảng UI01 cũ là lịch sử thiết kế; bảng này đối chiếu runtime tại B08.
Mọi mục dưới là **checklist còn phải nghiệm thu**, không sửa trạng thái PLANNED trong acceptance_tests.csv.
Các suite hiện có là bằng chứng thành phần khi chạy trên commit cụ thể, không thay thế Windows/UAT.

## Đối chiếu màn hình và domain

| Flow UI01 / phần mở rộng | Runtime tại B08 | Checklist khi tích hợp | T / nhánh nhận tiếp |
| --- | --- | --- | --- |
| SC01–03 đăng nhập/MFA/chọn kho | API + UI có | Đổi user/kho khi request đang chạy; bỏ response phiên cũ; grant bị thu hồi có hiệu lực ngay; không log token | T07,T11 / B04,B19,B24 |
| SC04 IAM | API + UI có; đổi mật khẩu/reset còn thiếu | SOD cấp quyền, MFA, phân trang >200; mất ACK không tự gửi lại; khóa/thu hồi phiên; form không lộ secret | T07,T11,T14 / B04,B19 |
| SC05 cập nhật client | Chưa có installer/update flow | Cài/nâng cấp N-1→N trên Windows 10/11 x64 sạch; giữ nháp/pending; TLS CA nội bộ | T23 / B23 |
| SC06 nháp/pending | Recovery receipt.post có; domain khác chưa có | Kill process trước/sau ACK; lookup 404 giữ UNKNOWN; retry cùng key/execution/payload; logout không ghi kết quả vào phiên mới | T02,T08,T23 / B19 |
| SC07–08 danh mục/kho/vị trí | API đủ nhiều hơn UI sáu form | Trùng code/barcode, UOM chính xác, giữ factor snapshot; owner/agreement và chứng cứ không dùng ghi chú thay typed fields | T12,T13,T24 / B05,B07 |
| SC09–10 chứng từ | PO/SO/receipt UI; opening backend | Đọc đúng assignment/kho; chặn stale; phân trang không ngụ ý snapshot; giữ nội dung form lỗi; test mọi loại chứng từ mới qua API thật | T01,T03,T06,T14 / B02,B06,B15 |
| SC11 hộp duyệt | PO/SO/receipt có; opening duyệt backend | Creator/requester không tự duyệt; hai quyết định cạnh tranh chỉ một thắng; sửa sau duyệt vô hiệu snapshot; quyền opening riêng | T14 / B06,B13,B15 |
| SC12 nhập từng phần | API + UI có, COMPANY | Đối soát 80/100; lô/serial/nguồn; post kế hoạch đã duyệt; race không vượt PO; rollback đầy đủ | T01,T02,T06,T24,T25 / B09,B24 |
| SC13 quality/putaway | Planned | Kho/vị trí/owner đúng; cách ly chưa available; quality decision và move/post có quyền/version/replay | T06,T10 / B03 |
| SC14–16 reserve/pick/pack/issue | Planned | Reserve không ghi ledger; không vượt tồn/reservation; pick/print không giảm tồn; serial/expiry tại thời điểm post | T03,T15,T17,T25 / B02,B10 |
| SC17–18 transfer | Planned | Dispatch→transit→arrive từng phần; tồn nguồn+đích+transit bảo toàn; scope hai kho; owner/serial giữ nguyên | T04,T10 / B11 |
| SC19 returns | Planned | Không vượt lượng giao dịch gốc; nguồn/owner đúng; unlinked chỉ quyền ngoại lệ và lý do; rollback/replay | T10 / B12 |
| SC20 hủy/đóng phần còn lại | PO/SO action có; xuất/giữ chỗ còn thiếu | Không sửa lịch sử đã post; race cancel/post, giải phóng reservation đúng lượng; assignment/UI theo API mới | T17 / B02,B15 |
| SC21 reversal | Planned | Một reversal toàn giao dịch; không đảo hai lần; chặn hàng đã đi tiếp/đang reserve; lịch sử append-only | T18 / B14 |
| SC22–25 kiểm kê/kỳ | Planned; đã có bootstrap kỳ đầu | Blind count không lộ snapshot; freeze/post và close/post race; đếm lại/ngoài snapshot; SOD; mở kỳ MFA | T05,T16,T19 / B13 |
| SC26 import/file | Validator CSV local; API/job planned | Validate trước commit, quyền tải, hash, sai dòng; retry và batch trùng; không đổi tồn khi chỉ upload/preview | T12,T20,T24 / B01,B16 |
| SC27 opening | Backend COMPANY có, UI/import thiếu | Kho chưa hoạt động; batch/serial trùng; creator khác approver; race với receipt; snapshot tracking; đối soát | T20,T24 / B01,B06,B09,B16 |
| SC28 reports/export | Planned | R01–R08; ranh giới NXT không cộng move nội bộ; owner; che giá ở payload/download, không chỉ widget | T07,T21,T27 / B17 |
| SC29 print/scanner | Planned | HID Enter đúng focus; Unicode/khổ tem driver thật; reprint không tạo thêm transaction | T15,T22 / B18 |
| Owner/consignment (FR32/UC32) | API owner/stock query; posting ký gửi thiếu | 10 COMPANY+5 CONSIGNED=15 vật lý; tách chủ/hợp đồng mọi domain; chặn tiêu thụ thiếu policy | T27 / B09,B17 |
| Warranty (FR33/UC33) | API + tab tra serial; append UI thiếu | Còn/hết/UNKNOWN từ chứng cứ; quyền kho/nguồn/giá; append có version và không sửa lịch sử | T28 / B05 |
| Outbox/triển khai/DR/tải | Worker engine có; consumer/vận hành chưa đầy đủ | Consumer dedup và rollback; restore DB+tệp; chứng minh RPO<1h/RTO<4h; workload 15 CCU, 1 kho/3 khu; lưu hồ sơ ≥5 năm | T09,T23,T24,T26 / B20,B21,B22,B24 |

## Checklist chung cho mỗi flow có mutation

- [ ] Ghi commit ứng dụng/client/server, OS/arch, PG major, migration checksums, cấu hình và dữ liệu fixture;
  nêu rõ PG15/PG16, Linux/Windows đã thực chạy. Không lấy YAML hoặc mock làm bằng chứng production.
- [ ] Thành công qua UI → HTTP → API → PostgreSQL; main thread giữ Tk, HTTP/SQLite worker trả queue;
  đổi phiên/kho hoặc đóng form giữa request không cập nhật nhầm widget/ACK.
- [ ] Thiếu quyền, grant thu hồi, khác kho/owner, tự duyệt, stale version và input không hợp lệ đều bị chặn;
  server kiểm soát ngay cả khi gọi API trực tiếp. Error có code/request_id, không lộ secret/giá ngoài quyền.
- [ ] Replay cùng key trả kết quả gốc; cùng key khác body lỗi; post thêm execution_key; UNKNOWN không tạo key mới.
- [ ] Fault injection sau ghi từng phần chứng minh ledger/balance/reservation/serial/audit/outbox/ACK rollback chung;
  race phù hợp domain và đối soát sau commit, không chỉ assert status HTTP.
- [ ] Fresh install và upgrade từ 001–010 có dữ liệu, rồi từ mốc tổng ngay trước merge; readiness đúng history;
  SQLite nâng cấp giữ nháp. Wheel có đầy đủ SQL và import ngoài source.
- [ ] Log/screenshot/trace gắn đúng T, môi trường và commit; giải thích giới hạn, không thay status tổng thành PASS.

## Bằng chứng thành phần sẵn để B24/B26 nối tiếp

| T ưu tiên của B08 | Suite tại base + bổ sung B08 | Chưa được suy thành đạt toàn T |
| --- | --- | --- |
| T02 | test_receipts.py: replay/race/post mất ACK; test_receipt_recovery.py; test_api_contracts.py | Các domain ngoài receipt và thiết bị Windows |
| T07 | test_identity.py, test_traceability.py, test_api_contracts.py | Export/download các domain B01/B17 |
| T11 | test_identity.py, test_admin_desktop.py: MFA/revoke/grant/UI | Lifecycle B04 và Windows |
| T14 | test_orders.py, test_receipts.py, test_openings.py: SOD/snapshot/race | Các approval policy count/adjustment/returns/transfer |
| T24 | test_postgres.py, test_openings.py, test_receipts.py; B08 migration-history readiness | Revision mới sau ghép, PG15 và toàn domain chưa triển khai |

TR02: guard kiến trúc desktop/API + GUI/API tests; TR03: review key/version/transaction và các lỗ hổng còn lại;
TR04: runtime schema, inventory, migration/package checks; NFR08: workflow/runner/log tái lập và ranh giới
module. Đây là mapping công việc B08, không thay ma trận yêu cầu chính thức.
B24 hoàn thiện race/security/load sau tích hợp; B26 thu thập và xác nhận T01–T28 trên môi trường target.
