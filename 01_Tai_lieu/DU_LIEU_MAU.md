# Dữ liệu mẫu để thực hành WMS

## Bộ dữ liệu trên máy local

Ngày thiết lập: 08/10/2026. Database đang dùng: `wms_demo_20261008`.
Tài khoản `kien` giữ nguyên mật khẩu, cấu hình MFA và thông tin liên kết của database cũ.
Phiên đăng nhập cũ đã được thu hồi; đăng nhập lại để tải danh sách kho mới.

| Kho | Mã kho | Số SKU có tồn | Tổng số chiếc |
|---|---|---:|---:|
| Kho mẫu Đông Thạnh | DEMO-DT | 200 | 9.181 |
| Kho mẫu Thủ Đức | DEMO-TD | 200 | 9.181 |
| Kho mẫu Bình Dương | DEMO-BD | 200 | 9.181 |

Danh mục chung có **200 mã sản phẩm**, cùng hiện diện trong cả ba kho: 40 SSD,
40 USB, 40 bàn phím, 40 chuột và 40 cáp mạng. Đây là 600 số dư sản phẩm/kho,
không phải 600 SKU khác nhau. 40 SSD mỗi kho được quản lý theo serial riêng.
Từng kho có cây Zone → Rack → Bin và khu nhận, xuất, cách ly.

Mỗi sản phẩm có thương hiệu/model mô phỏng, mô tả sử dụng, thông số biến thể,
đóng gói/phụ kiện, bảo quản, kiểm tra nhập kho, ghi chú bảo hành và nguồn gốc.
Các trường lưu tại PostgreSQL qua API trường mở rộng, có lịch sử thay đổi.

**Dữ liệu DEMO, không phải số liệu kho thực tế.** Mã/model, thông số biến thể,
bảo hành và số lượng đều dùng để thực hành. Chứng từ tồn đầu kỳ ghi rõ tham chiếu
kiểm đếm mô phỏng; không dùng làm chứng từ kiểm kê hoặc cam kết thương mại.

## Xem trong ứng dụng

1. Đóng rồi mở lại WMS từ Plank để nạp giao diện mới.
2. Đăng nhập `kien` bằng mật khẩu hiện có và mã MFA.
3. Chọn một trong ba kho mẫu.
4. Vào **Danh mục → Sản phẩm**, bấm **Tìm / tải lại**, chọn sản phẩm rồi bấm **Ảnh & mô tả**.
5. Dùng **Trang sau** để xem tiếp danh mục; xem số lượng tại phần tồn kho.
6. Chỉnh mô tả tại **Trường mở rộng → Sản phẩm** theo quyền hiện tại.

Ảnh được đóng gói cùng desktop, không cần tải từ Internet khi mở sản phẩm.
Bộ mẫu có **5 ảnh minh họa nhóm hàng**, mỗi ảnh dùng chung cho 40 biến thể;
không phải ảnh chụp riêng của từng model. Nguồn Wikimedia Commons, tác giả và
giấy phép Creative Commons được ghi trong cửa sổ hồ sơ và
`apps/desktop/assets/catalog/sources.json`. Nút **Nguồn ảnh và giấy phép** mở trang nguồn.
Các bộ cài đã phát hành trước thay đổi này cần build lại để có nút và ảnh mới.

## Quyền và kiểm chứng

Tài khoản `kien` được cấp quyền danh mục và các vai trò nghiệp vụ trong ba kho mẫu.
Quy tắc không tự duyệt chứng từ của mình vẫn áp dụng. Hai tài khoản kỹ thuật
`demo_loader` và `demo_reviewer` chỉ phục vụ nhập/duyệt bộ mẫu, đã bị vô hiệu hóa
và thu hồi phiên sau khi hoàn tất.

Tồn kho được tạo bằng API tồn đầu kỳ: tạo → gửi duyệt → người khác duyệt → ghi sổ.
Không sửa trực tiếp bảng số dư hoặc ledger. Ba phiếu OPENING đã COMPLETED;
hai bộ SQL đối soát ledger/số dư và quyền sở hữu đều không có sai lệch.
Kiểm thử tự động trên PostgreSQL tạm và Xvfb: **7 đạt**, gồm tạo toàn bộ dữ liệu,
giữ nguyên mật khẩu/MFA, chặn seed nhầm DB/seed lại, tải ảnh và đóng hồ sơ khi đổi phiên.

## Sao lưu và quay lại database cũ

Database `wms` vẫn giữ dữ liệu trước khi tạo mẫu. Bản dump và cấu hình kết nối cũ:

`/home/kien/.local/share/wms-local-server/backups/before-demo-20261008-203324/`

Thư mục này chứa dữ liệu xác thực nhạy cảm, chỉ dùng cục bộ, không đưa lên Git.
Muốn trở về DB cũ, quản trị viên khôi phục `runtime.env` từ thư mục trên vào
`~/.config/wms-local-server/runtime.env` (quyền `0600`) rồi khởi động lại
`systemctl --user restart wms-local.target`. Thao tác này chỉ đổi DB đang kết nối,
không hợp nhất nghiệp vụ đã phát sinh trên hai DB; cần đăng nhập lại.

## Tạo lại bộ dữ liệu trên môi trường khác

`scripts/seed_demo_catalog.py` chỉ chấp nhận DB bắt đầu bằng `wms_demo_` hoặc
`wms_test_`, đã migrate đầy đủ, chưa có kho/sản phẩm/chứng từ, có tài khoản đích
đang hoạt động. Môi trường chạy cần dependency kiểm thử FastAPI TestClient.
Operator cấp kết nối và khóa MFA qua cấu hình riêng; không đưa khóa lên Git.
Chạy script với `--username` tương ứng. Nếu sao chép tài khoản từ DB khác,
phải giữ đúng khóa mã hóa MFA. Không chạy seeder vào DB vận hành thật.
