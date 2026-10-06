# Bộ tài liệu bàn giao WMS — InternTechLead

Tài liệu hiện hành cho mã nguồn đã ghép B01–B24 tại `7b168c010756c194a33872571cd59d6258712b06`.
Đơn vị: **InternTechLead**, Đông Thạnh, Hóc Môn, TP. Hồ Chí Minh.
Mã số thuế: **0869233973**; điện thoại: **0329511628**.
Đầu mối triển khai: **Trần Trung Kiên**. Tên này trên mẫu phiếu là tên người ký được cấu hình,
không phải chữ ký hoặc bằng chứng đã nghiệm thu.

## Tài liệu theo người dùng

| Người đọc | Đọc và thực hành |
| --- | --- |
| Nhân viên nhận/soạn/xuất/đếm | [Hướng dẫn thao tác](USER_GUIDE.md), [bài tập đào tạo](TRAINING.md) |
| Quản lý kho, kiểm soát, người duyệt | Hướng dẫn thao tác, [kiểm kê/kỳ](COUNTING_PERIODS.md), [đảo](REVERSALS.md), [owner](CONSIGNMENT.md) |
| IT vận hành | [Sổ vận hành](OPERATIONS_RUNBOOK.md), [LAN](LAN_DEPLOYMENT.md), [backup/PITR](BACKUP_RESTORE.md) |
| Người nhận mã nguồn/QA | [Ma trận 49 yêu cầu](../07_Kiem_tra/handover/requirements.csv), [ghi chú kiến trúc hiện hành](../03_So_do/RUNTIME_GUIDE.md), [contract](../05_API/RUNTIME_HANDOVER.md) |

Đọc `07_Kiem_tra/release/README.md` khi B26 đã được ghép để biết commit,
checksum, kiểm thử cuối và các cổng còn mở. Mọi status trong hồ sơ là status thành phần hoặc
release candidate; chỉ người nghiệm thu thật mới xác nhận nghiệm thu nghiệp vụ.

## Phạm vi và lịch sử

Runtime dùng API FastAPI, PostgreSQL tập trung, desktop Tkinter và SQLite cho nháp/nhật ký lệnh.
Server profile đã chuẩn bị: Ubuntu 24.04 x64, PostgreSQL 16, Python 3.12, Nginx HTTPS và systemd.
Client đích vẫn Windows 10/11 x64. Theo yêu cầu bổ sung của người dùng, đã có bản build lab
macOS 15 ARM64; việc này không tự đổi baseline và không chứng minh hỗ trợ mọi phiên bản Mac.

[PDF thiết kế](Thiet_ke_WMS_Tkinter_LAN.pdf), các sơ đồ thiết kế ban đầu,
[traceability v1.1](../07_Kiem_tra/traceability_v1_1.csv) và các brief Bxx là hồ sơ lịch sử.
Các số bảng/route, ghi chú B19 "sẽ triển khai", owner "PENDING" hoặc "chưa có EXE" trong hồ sơ
cũ đã được thay thế bởi tài liệu runtime và evidence có commit. Không sửa tài liệu gốc thành
bằng chứng mới. Xem [phục hồi B19](RECOVERY_ALL.md), [native VM](../07_Kiem_tra/NATIVE_VM_2026_10_06.md).

## Những gì cần giao

1. Source archive tại commit ghi trong manifest, kèm lock, license, migration PG001–024/SQLite001–003,
   contract runtime, templates/font và các script triển khai/backup đã review.
2. Wheel server cùng wheelhouse offline, config mẫu, unit/Nginx/grants, manifest SHA-256;
   ghi lại kết quả cài vào prefix sạch ngoài checkout. Không bàn giao `.venv` của lập trình viên.
3. Bộ cài Windows/macOS với **commit riêng của từng artifact**, hash và loại chữ ký. Windows lab
   dùng chứng thư TEST ONLY; Mac ký ad-hoc, chưa Developer ID/notarization. Không biến chúng
   thành bộ cài công khai bằng việc đổi tên hoặc bỏ cảnh báo hệ điều hành.
4. Config vận hành đã điền và CA public phân phối qua kênh quản trị. DSN, mật khẩu, MFA key,
   private signing key, DB dump và dữ liệu doanh nghiệp **không nằm trong gói mã nguồn công khai**.
   IT lập biên bản chuyển giao bí mật riêng, không ghi giá trị bí mật vào đây.
5. Tài liệu, evidence regression, checklist nâng cấp/rollback, danh sách lỗi/cổng còn mở,
   biểu mẫu UAT chưa ký và lịch đào tạo do người phụ trách xác nhận.

## Giới hạn phải giữ trong bàn giao

- T01–T28 vẫn PLANNED; test tự động không thay chữ ký người dùng, diễn tập cutover hay đo trên thiết bị.
- Tải B24 đo 15 phiên trong 60 giây trên Linux; stress riêng 50.000 SKU/1 triệu move khoảng 303 MiB.
  Chưa chứng minh 20 GB/3 năm, tải dài hạn hoặc xử lý phiếu dưới 15 phút cả quy trình.
- B22 đã PITR ở fixture cách ly cùng máy; chưa có thiết bị backup độc lập/off-host và chưa đo DR đích.
- Q06/Q08 model máy in, máy quét, giấy/tem và mẫu thật được người dùng cho bổ sung sau.
  Mẫu InternTechLead hiện có cần duyệt bố cục/nghiệp vụ; không coi PDF render thành công là in giấy đạt.
- Import/export có tab lịch sử theo người dùng, loại/kho, ngày UTC và trạng thái; mở lại job kiểm tra
  quyền hiện tại. Export hết hạn chỉ còn metadata, không tải lại tệp. Nháp/lệnh được B19 lưu bền;
  upload tệp/IAM không thuộc journal replay tự động.
- Không có offline posting, không hỗ trợ tự chuyển quyền hàng ký gửi thiếu policy/hợp đồng;
  bảo hành thiếu nguồn trả "Chưa xác định". Giá tham chiếu không phải giá vốn/kế toán.

Biên bản bàn giao: người giao ______; người nhận IT ______; người nhận nghiệp vụ ______;
thời điểm ______; commit/hash manifest ______; phần chấp thuận ______; phần hoãn/lý do ______.
Các ô này cố ý để trống đến khi có người thực hiện.
