# Quyết định và giả định triển khai

Cập nhật 02/10/2026 theo [baseline TL01](SCOPE_BASELINE.md) và [sổ Q01–Q08](BA/open_questions.json). Nguồn là bảng quyết định do tech lead cung cấp; không ghi thay phê duyệt doanh nghiệp.

## Đã tiếp nhận từ tech lead

- Q01: 200 triệu chưa gồm 50 triệu dự phòng; tổng số học 250 triệu, chưa có bảng phân bổ được sponsor duyệt.
- Q03/Q04: Thủ kho và Kế toán kho ký, được duyệt thay phiên không giới hạn giá trị phiếu; vẫn chặn tự duyệt và kiểm tra grant theo kho.
- Q05: một kho trung tâm/ba phân khu, tối đa 15 CCU, khoảng 20 GB trong ba năm.
- Q06: server Ubuntu/Debian x64; client Windows 10/11 x64, máy in tem nhiệt USB/LAN, máy quét 1D/2D HID; tech lead đã bỏ Mac khỏi phạm vi. OS/version/arch và model thiết bị phải được chốt trước test target.
- Q07: sai lệch tồn <0,5%, xử lý phiếu <15 phút; RPO <1 giờ, RTO <4 giờ. Đây là mục tiêu nghiệm thu, chưa có số đo.
- Q08: tham chiếu mẫu TT 133/200, giữ dữ liệu tối thiểu năm năm, ẩn dữ liệu giá theo quyền. Cần file mẫu/policy được người phụ trách kế toán xác nhận; không mở rộng thành tính giá vốn kế toán.
- Hạn bàn giao đồ án: 22/10/2026. Lịch chi tiết nằm ở các issue và bảng điều hành của nhóm.

## Giả định kỹ thuật kế thừa để phát triển

Tkinter/ttk → HTTPS LAN → FastAPI → PostgreSQL trung tâm. Không xuất âm, không nhận vượt nguồn, không ghi sổ offline, không tự duyệt; tối đa hai bước duyệt theo thiết kế hiện có. LOT và SERIAL loại trừ nhau, hạn dùng theo lô, serial số nguyên. Một dòng serial ứng với một stock_item. Chuyển kho dùng transit; kiểm kê khóa vị trí sau khi xử lý giữ chỗ; backdate trong kỳ mở.

Q02 đã làm rõ ngành điện tử/IT/văn phòng, serial theo thiết bị và lot theo đợt linh kiện, có hàng ký gửi và tra cứu bảo hành serial. FR32/FR33 và T27/T28 mô tả phần bổ sung; migration 006/007 đã bổ sung nền owner/chứng cứ/quyền theo CR; xem [TRACEABILITY.md](TRACEABILITY.md). Posting và policy xuất/chuyển ký gửi vẫn chưa triển khai. Các bất biến [INVARIANTS.md](INVARIANTS.md) tiếp tục áp dụng. Thay đổi tracking/owner hàng/quyền phải có CR và test, triển khai theo yêu cầu mới có truy vết.

## Theo dõi chi tiết và bằng chứng

Owner nội bộ Q01–Q05/Q07: Trần Trung Kiên; Q06/Q08: Lê Ngọc Quỳnh Khanh. Hạn theo dõi 04/10/2026; không phải ngày doanh nghiệp cam kết. Giữ nguyên câu trả lời và nguồn trong JSON; cập nhật follow-up khi có thông tin. Mọi quy mô, hiệu năng, restore, thiết bị và OS phải được kiểm thử, không suy ra đạt chỉ từ lựa chọn kiến trúc.
