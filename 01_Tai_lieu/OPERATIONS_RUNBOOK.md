# Sổ vận hành và xử lý sự cố

Đầu mối triển khai hiện tại: Trần Trung Kiên; IT trực ca và người phê duyệt cutover cần điền trước vận hành.
Đây là mục lục thao tác theo tình huống, dùng cùng lệnh chính thức trong [LAN_DEPLOYMENT](LAN_DEPLOYMENT.md)
và [BACKUP_RESTORE](BACKUP_RESTORE.md). Không chạy các lệnh cấu hình máy thật trên máy phát triển.

## Kiểm tra đầu ca và cảnh báo

| Kiểm tra | Điều kiện bình thường | Khi không đạt |
| --- | --- | --- |
| TLS/health/ready | SAN/CA/expiry đúng, health200 và ready200 | Giữ maintenance; kiểm giờ, cert, API và schema; không tắt TLS |
| `wms.target`, API và 6 worker | outbox/import/export/print/export-cleanup/print-cleanup đúng release, heartbeat mới | Xem unit/journal/operations; active target không đủ kết luận ready |
| Jobs/outbox | Không tích tụ retry/dead-letter không được xử lý | Dùng [Outbox operations](OUTBOX_OPERATIONS.md); không sửa attempt/status trực tiếp |
| Backup/WAL | Monitor thành công, checkpoint dưới45phút, base dưới36giờ, archive không lỗi | Kiểm mount/ID/quota/disk/PG archiver; không xóa WAL để lấy chỗ |
| Disk/inode/log/time | Đủ headroom cho DB+WAL+storage+backup, NTP đúng | IT xử lý dung lượng, giữ audit/retention; không purge lệnh UNKNOWN |

API operations cần GLOBAL `config.manage` và MFA. Thu hồi phiên/grant có hiệu lực ở request tiếp theo.
Token quản trị không được nhúng trong script cron. Log gửi ra ngoài chỉ metadata đã lọc; PG ERROR có
thể có dữ liệu nên chỉ DBA đọc. Ghi ticket, thời điểm, release, unit/kind và mã lỗi trước can thiệp.

## Nâng cấp

1. Nhận gói có manifest/hash qua kênh tin cậy; verify trước stage. Stage vào prefix mới, cài offline,
   `pip check`; ghi commit và hash. Không thay `current` khi stage chưa đạt.
2. Restore vào môi trường thử riêng, chạy migration/contract/đối soát với dữ liệu; giữ PG001–024 và
   SQLite001–003 đúng checksum. Không đưa migration từ worktree chưa ghép lên máy vận hành.
3. Vào cửa sổ đã thống nhất, tạo maintenance marker; quan sát drain rồi dừng API và đủ6worker/monitor.
   Chụp backup phối hợp DB/private files/MFA/config/release. `--once` không thay drain.
4. Chạy migration bằng owner; chạy **bản mới** `deploy/lan/postgresql/runtime-grants.sql` sau đó.
   B24 thu hồi UPDATE/DELETE trên `reservation_consumption`; script cũ sẽ cấp lại quyền sai.
   Đây là thay đổi grants triển khai, không sửa migration đã phát hành.
5. Candidate preflight đạt mới chuyển symlink nguyên tử, start/check API+6heartbeat+TLS+nghiệp vụ.
   Giữ maintenance nếu có failure. Client B19 cần server hỗ trợ recovery trước nâng cấp.
6. Cài client đúng user, bảo toàn cache ngoài thư mục chương trình; chạy tự kiểm bộ cài.
   Kiểm phiên, nháp, UNKNOWN và khả năng phục hồi trước kết ca nâng cấp.

Lệnh đầy đủ và vị trí config: [LAN mục4–7](LAN_DEPLOYMENT.md),
[Windows build/install/rollback](../packaging/windows/README.md),
[macOS lab](../packaging/macos/README.md).

## Rollback

Nếu schema/checksum và giao thức còn tương thích: dừng toàn bộ process, đưa symlink/config về bản
đã kiểm chứng, start/check rồi mới mở maintenance. Không chạy đồng thời hai registry worker khác bản.
Nếu đã có revision mới: bản cũ cố ý không ready; không xóa lịch sử migration hoặc sửa checksum.
Chọn forward fix hoặc phục hồi phối hợp B22 vào nơi cách ly, đối chiếu giao dịch phát sinh rồi người
có thẩm quyền quyết định cutover. Không tự ghi đè DB hoặc SQLite đang hoạt động.

## Backup và DR

Repository thật phải độc lập failure domain, mount/ID/mode/quota đã kiểm; dữ liệu backup chứa MFA key
và dữ liệu doanh nghiệp, cần hạn chế quyền và mã hóa theo vận hành. Dung lượng5năm cần sizing riêng.
Timer base hằng ngày/checkpoint15phút/monitor5phút là lịch mẫu; checkpoint dừng writer ngắn, cần
đo gián đoạn thực tế. Staging giữ lại, không có tự purge; lập lịch kiểm dung lượng và review retention.

Theo [runbook B22](BACKUP_RESTORE.md): verify base/WAL/object → prepare vào thư mục DR mới → khởi
PG cách ly → dừng replay đúng checkpoint → restore-check/reconcile → DBA review/promote → kiểm
MFA/files/ACK/jobs/client → quyết định cutover. Không dùng arbitrary timestamp nếu không có checkpoint
DB+files phù hợp. Không dùng `restore_command` hay preload của máy nguồn trên máy DR.

RPO đo từ giao dịch cuối cứu được đến sự cố; RTO tính hết provision/transfer/DB/reconcile/API/6workers/
TLS/client đăng nhập, không chỉ `pg_ctl start`. B22 local đạt thành phần, chưa đo toàn chuỗi máy đích.
Sau PITR, client có thể giữ ACK của giao dịch nằm sau target đã bị mất: giữ maintenance, đối chiếu
journal và tác động ngoài hệ thống; không tự replay/spool hàng loạt.

## Xử lý sự cố thường gặp

| Triệu chứng | Đọc/kiểm trước | Cách xử lý có kiểm soát |
| --- | --- | --- |
| QUEUED lâu | heartbeat, registered consumer, outbox/task generation, storage/quota | Sửa nguyên nhân; retry qua API có quyền/lý do/version, giữ key và fencing |
| Dead-letter/EXHAUSTED | mã lỗi, attempt, event/consumer receipt | Review nguyên nhân và hậu quả; không tăng budget để tự chạy lại hàng loạt |
| Client UNKNOWN | partition đúng server/user/device, operation key, ACK | Người dùng tra ACK; không xóa cache hoặc tạo key mới |
| In UNKNOWN | print attempt, spool ID, giấy/thiết bị | Kiểm giấy trước in lại; ACK chỉ là DB/spool claim |
| STORAGE/READY failure | quyền private roots, dung lượng, manifest/schema, DB peer mapping | Giữ maintenance, sửa cấu hình bằng runbook; không mở rộng quyền toàn thư mục |
| Số dư lệch | reconcile chỉ đọc và ledger/source/serial | Dừng ghi liên quan, lưu evidence; sửa qua nghiệp vụ đã duyệt, không UPDATE balance |
| Mất grant/MFA | IAM audit/phiên, role đúng kho | Quản trị cấp/thu hồi qua quy trình hai người; không mượn tài khoản |

Diễn tập sự cố trên môi trường bỏ được; không kill production hoặc rút thiết bị đang dùng để tạo evidence.
Biên bản mỗi lần: người thao tác/người kiểm ______; thời điểm ______; release/hash ______;
trước/sau ______; giao dịch bị ảnh hưởng ______; quyết định mở dịch vụ ______.
