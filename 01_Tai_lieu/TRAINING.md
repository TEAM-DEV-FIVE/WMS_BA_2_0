# Kịch bản đào tạo và xác nhận sử dụng

Trạng thái: **PREPARED — chưa tổ chức/chưa ký**. Người hướng dẫn dự kiến Trần Trung Kiên;
người tham gia, thời lượng và lịch thực tế để trống. Chỉ dùng tenant/DB thử riêng, không seed vào DB vận hành.
Fixture gốc: [acceptance_fixtures.json](../07_Kiem_tra/fixtures/acceptance_fixtures.json).

## Chuẩn bị lớp

IT chuẩn bị bản đã cài từ artifact, HTTPS/CA đúng và6worker ready. Quản trị tạo người dùng riêng cho
RECEIVER, PICKER, WAREHOUSE_MANAGER, CONTROLLER, DIRECTOR và SYSADMIN, cấp kho theo bài tập;
không dùng cùng người cho cả hai lần đếm hoặc các bước duyệt. Tạo WH01/WH02, vị trí INB/STORAGE/
QUARANTINE/SHIPPING/TRANSIT phù hợp; base UOM, SKU-NONE-01 và SKU-SERIAL-01, đối tác, kỳ mở,
owner COMPANY và một chủ ký gửi có hợp đồng. Mật khẩu do người dùng đặt, không in trong tài liệu.
Tham khảo cách dựng fixture tự động tại `tests/foundation/test_integrated_workflows.py` và
`tests/foundation/test_consignments.py`; đó là mã test, không phải CLI nạp dữ liệu production.

## Bài tập theo nhóm

| Bài | Thao tác và số liệu | Kết quả phải giải thích được | Test liên quan |
| --- | --- | --- | --- |
| Nhận/chất lượng | PO100, nhận80, cất75, cách ly5 | Physical80, PO còn20, hàng cách ly không tự xuất được | T01 |
| Xuất cạnh tranh | Tồn10, hai người cùng yêu cầu7 | Một lệnh thắng, không âm tồn; người thua đọc lại | T03 |
| Chuyển thiếu | Dispatch20, receive18 | Transit còn2; biên bản chênh lệch không tự xóa tồn | T04 |
| Kiểm kê | Sổ100, hai người độc lập đếm98 | Mù; SOD; hai bước duyệt; delta−2 và giải khóa | T05 |
| Mất phản hồi | IT tiêm lỗi trên lab sau commit, mở recovery | Tra ACK/same key; không ghi trùng; không giả lập bằng bấm post mới | T02/T08 |
| Import | SaiUOM, barcode trùng, decimal lỗi; sửa tệp sau dry-run | Đọc lỗi dòng/hash; commit nguyên tử; chứng từ tạo là DRAFT | T12/T20 |
| Owner | Cùng SKU/vị trí: COMPANY10, CONSIGNED5 | Physical15, doanh nghiệp10, ký gửi5; không hòa để xuất | T27 |
| Bảo hành | Serial có nguồn thời hạn, một serial thiếu nguồn | Truy NCC/receipt/ngày nhập; thiếu nguồn là Chưa xác định | T28 |
| Báo cáo/quyền | Snapshot/export có giá rồi thu hồi grant | Tải bị chặn ngay, file cũ lưu ngoài hệ thống không thu hồi từ xa | T07/T21 |
| In/quét | In mẫu đủ6loại, quét lại, mô phỏng mất ACK | Đúng mã/khổ/dấu Việt; UNKNOWN cần kiểm giấy trước in lại | T22 |
| Nâng cấp/DR | IT theo runbook ở VM/host thử | Giữ nháp, kiểm hash, restore DB+files+MFA, đo đủRPO/RTO | T09/T23/T24 |

## Checklist người học

- [ ] Chọn đúng kho/người dùng và hiểu quyền theo kho; tự duyệt bị từ chối.
- [ ] Phân biệt nháp cục bộ, lưu máy chủ, duyệt, ghi sổ và trạng thái đơn hàng đã đóng phần còn lại.
- [ ] Đọc SKU/UOM/owner/serial trước xác nhận; không suy bảo hành khi thiếu nguồn.
- [ ] Tự tra một UNKNOWN, chỉ retry cùng key và biết khi nào phải gọi IT.
- [ ] Biết lấy mã job, lỗi dòng/hash và không coi import COMMITTED là tồn đã ghi sổ.
- [ ] Phân biệt READY PDF, SUBMITTED spool và giấy đã in; không tự in lại sau crash.
- [ ] Tạo ticket không chứa password/OTP/token; đăng xuất và kiểm lệnh chờ cuối ca.

## Biên bản lớp và mẫu góp ý

Ngày/môi trường/OS/màn hình/DPI ______; commit và artifact SHA256 ______;
người hướng dẫn ______; người tham gia/vai trò/kho ______; bài đã làm ______;
actual/evidence ______; sai sót/ticket ______; cần học lại ______; xác nhận người học ______.

Mẫu chứng từ: người duyệt ______; mẫu/khổ ______; file hash ______; máy in/driver/scanner ______;
ảnh giấy/quét lại ______; nội dung cần đổi ______. Ghi tên Trần Trung Kiên vào ô cấu hình người ký
không điền thay các trường xác nhận này. Không đổi Txx sang PASS khi mới đọc tài liệu hoặc tick checklist.
