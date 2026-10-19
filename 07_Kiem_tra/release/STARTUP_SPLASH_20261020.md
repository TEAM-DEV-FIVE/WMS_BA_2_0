# Logo khi khởi động WMS — 20/10/2026

Base: `8fc5c37`; nhánh `feat/startup-splash-20261020`.

Theo yêu cầu người dùng, ẩn cửa sổ chính và hiện logo trước khi kiểm tra cache,
import các view và dựng giao diện. Thanh trạng thái biểu diễn từng bước khởi tạo,
không biểu diễn tiến độ kết nối máy chủ. Khi giao diện sẵn sàng, đóng splash và
hiện cửa sổ chính; thời gian logo tối thiểu một giây, dùng Tk after, không sleep UI.
Tất cả cập nhật/hủy Tk ở main thread. Khi preflight lỗi, đóng splash, báo lỗi và
nhả khóa ứng dụng. Giữ cơ chế chờ worker/khởi động lại hiện tại.

Phạm vi: desktop entry point, view splash, kiểm tra startup/lifecycle.
Không thay đổi API, quyền, chứng từ, migration hoặc dữ liệu nghiệp vụ.

## Kiểm chứng

- Xvfb, Python 3.12: `test_startup_splash.py` và `test_desktop_lifecycle.py`:
  **11 passed**, bao gồm ẩn/hiện cửa sổ, hủy timer, preflight lỗi và tải lại.
- Chạy entry point thật với thư mục dữ liệu tạm, chặn startup network:
  xác nhận root còn withdrawn suốt lúc dựng DesktopShell, chỉ hiện sau khi
  splash bị hủy. Đã xem ảnh splash render thực tế.
- Kiểm tra bổ sung `test_windows_packaging.py` và `test_macos_packaging.py`:
  **28 passed**, một ca API/MFA integration không chạy được vì không cấu hình
  database kiểm thử dùng một lần. Đây không phải bằng chứng native Windows/macOS
  hay kiểm thử API. Không dùng database vận hành và không sửa/bỏ test.
- Đã kiểm tra diff và manifest SHA256 sau thay đổi.

Bản tương ứng KWS được cập nhật riêng với logo KWS và thanh tiến độ xanh lá;
11 kiểm tra startup/lifecycle và smoke entry point tương tự cũng đạt tại KWS.
Không thay đổi mốc nghiệm thu T01–T28 hay các cổng phát hành hiện hành.

## Điều chỉnh hình thức theo phản hồi

Thu nhỏ splash từ 420×340 xuống 340×280, logo tối đa 114×124; bo góc 22 px
và viền ngoài 2 px (WMS xanh dương, KWS xanh lá). Canvas vẽ khung; X11 Shape
cắt thực sự góc cửa sổ trên Linux. Windows dùng transparent color, chưa kiểm
thử native Windows; nền tảng không hỗ trợ giữ cửa sổ thường.

Kiểm chứng lại: 11/11 test startup/lifecycle mỗi ứng dụng; smoke entry point
với dữ liệu tạm xác nhận main window ẩn đến khi splash đóng. Ảnh Xvfb của cả
hai ứng dụng xác nhận kích thước mới, góc cắt và viền. Ruff và diff check đạt.
