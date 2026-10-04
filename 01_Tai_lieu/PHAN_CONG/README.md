# Phân công phần còn lại — trạng thái 04/10/2026

Đã kiểm tra lịch sử nhánh, code bàn giao và kiểm thử bản ghép. Xem
[báo cáo hiện tại](../../07_Kiem_tra/BRANCH_REVIEW_2026_10_04.md) và [sổ tích hợp](integration_log.json).

- **12 nhánh đã tích hợp code local:** B01/B02/B03/B04/B05/B06/B08/B09/B10/B11/B12/B15.
- **READY, đã đồng bộ để giao triển khai:** [B13 kiểm kê/kỳ](B13_count_period.md) và
  [B16 giao diện import](B16_import_ui.md), nền đã kiểm chứng `d4676b6`.
  Đã giữ commit nghiên cứu của hai nhánh; chưa có implementation riêng của B13/B16.
- **Đã chuẩn bị, còn chờ:** B14 chờ B13; B07 chờ B14, ưu tiên P3.
- **10 nhánh chưa có code riêng:** B17–B26; tiếp tục theo dependency trong catalog.

Mỗi nhánh có brief, worktree, phạm vi, kiểm thử và prompt trong [kế hoạch đầy đủ](KE_HOACH_CON_LAI.md).
Trạng thái READY trong catalog/brief là **mốc phân công ban đầu**, không phải trạng thái hiện tại.
Đọc [quy trình agent](QUY_TRINH_AGENT.md), đặc biệt revision/DB tạm, import đúng nguồn và bàn giao.
Ba nhánh opening/outbox/admin-ui đợt trước vẫn được giữ; [hồ sơ lịch sử](DOT_1_DA_TICH_HOP.md).

Chưa push/đổi issue GitHub. Kết quả local không thay thế nghiệm thu Windows, thiết bị, tải và phục hồi.
