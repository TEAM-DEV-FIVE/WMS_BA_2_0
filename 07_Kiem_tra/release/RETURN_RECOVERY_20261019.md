# Sửa gửi duyệt phiếu trả và phục hồi lệnh thiếu lý do — 19/10/2026

Nhánh: `fix/return-recovery-validation-20261019`. Base: `45fa0f6`.

## Vấn đề và hành vi sau sửa

Sau lưu phiếu trả, lý do trên form được xóa. Các thao tác lifecycle chưa kiểm tra
OrderAction trước khi ghi nhật ký, nên gửi lý do rỗng tới server trả 422 nhưng journal
vẫn UNKNOWN. Lần gửi với key mới bị chặn; Tra ACK tiếp tục bị lỗi validation và
màn phục hồi trước đây xóa bảng hiển thị khi có lỗi.

- ReturnView kiểm tra OrderAction trước khi tạo command cho gửi duyệt/sửa/hủy/duyệt/từ chối/ghi sổ.
- Tra cứu lỗi giữ danh sách; cập nhật lại journal nếu có thể để thấy trạng thái mới.
- Máy chủ chỉ xác nhận từ chối lệnh submit có lý do rỗng, với đúng hai trường reason,
  expected_version hợp lệ, thuộc CUSTOMER_RETURN/SUPPLIER_RETURN. Kiểm tra lại danh tính,
  quyền sửa, quyền xem phiếu, khóa actor/key và không có bất kỳ ACK cũ nào cùng key;
  phiếu phải còn DRAFT/REJECTED đúng phiên bản. Sai bất kỳ điều kiện nào vẫn UNKNOWN.
- Tra ACK không chạy handler submit. Phản hồi từ chối được ràng buộc với hash của
  đúng method/path/body/key. Client chỉ chuyển UNKNOWN sang CONFLICT khi xác minh
  X-WMS-Rejected khớp; giữ nguyên envelope và key cũ, không sửa/xóa lịch sử.
- Không thay đổi schema DB, migration, API/OpenAPI input, quyền, ledger hay balance.
  Không tự tạo/gửi duyệt/duyệt/ghi sổ phiếu nghiệp vụ trên máy vận hành.

## Áp dụng và phục hồi trên máy người dùng

Sao lưu các module cài đặt trước khi thay thế, kiểm tra chúng khớp base; cập nhật
7 module desktop/server và khởi động lại API. Desktop đang mở cần chọn **Tải lại**
hoặc đóng/mở lại để nạp mã mới.

Đăng nhập đúng tài khoản tạo phiếu, vào Nháp & phục hồi lệnh, chọn UNKNOWN
`POST documents/<id>/submit`, Tra ACK. Với lệnh thiếu lý do đã được kiểm chứng,
trạng thái chuyển CONFLICT kèm hướng dẫn. Mở lại phiếu trả đã lưu, nhập lý do
3–2000 ký tự và Gửi duyệt. Không sửa nội dung lệnh cũ, không tạo phiếu trả khác.

## Kiểm thử

- MySQL 8.0.46 tạm: `test_return_recovery_validation.py`: **31 passed** (bao gồm 3 integration, 28 unit).
- Tk/Xvfb: ca widget thật `test_real_return_widgets_block_empty_reason_before_sending`: **1 passed**.
- Hồi quy `test_return_desktop.py` (non-GUI) và `test_recovery_all.py` (non-GUI): **30 passed**.
  Lần chạy gộp ban đầu có 2 ca mới lỗi setup thiếu device_id; đã sửa setup và chạy lại đủ 31 ca mới đạt.
- Ca GUI CUSTOMER_RETURN HTTP/MySQL đi hết tạo, gửi duyệt, duyệt, ghi sổ mất ACK và phục hồi COMPLETED;
  lỗi kiểm tra layout cuối `winfo_ismapped()` tại dòng 202. Chạy gộp hai Tk có abort do GC Tk ở worker;
  đã chạy riêng CUSTOMER_RETURN để thu lỗi chính xác. Baseline `45fa0f6` tại `/tmp/wms-return-recovery-baseline` cũng lỗi đúng dòng 202, sau khi hoàn tất nghiệp vụ. Đây là giới hạn kiểm thử layout đã có trước bản sửa; không sửa/skip assertion để báo PASS.
- Ruff, `git diff --check`, `scripts/check_artifacts.py`: PASS.
- Báo cáo máy: `.reports/return-recovery.xml`, `.reports/return-widgets.xml`, `.reports/return-gui-customer.xml`.
Không dùng database vận hành để kiểm thử và không gọi các cổng nghiệm thu tổng đã đạt.
