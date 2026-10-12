# Đăng nhập WMS và cấu hình dịch vụ xác thực

Giao diện desktop có header xám, hình minh họa bên trái, form bên phải và footer thông tin InternTechLead. Menu mặc định phẳng; mục được chọn có nền bo góc, khi rê chuột chữ phóng nhẹ và sáng lên. Email/Google là cách xác thực tài khoản WMS hiện có; quyền kho và MFA vẫn do WMS kiểm tra.

## Đăng nhập lần đầu

1. Mở WMS từ Plank. Dùng tài khoản `kien` và mật khẩu trong file riêng `~/.config/wms-local-server/first-login.txt`.
2. Nếu chưa bật MFA, nhập lại mật khẩu, bấm **Thiết lập MFA**, mở Google Authenticator/Microsoft Authenticator → thêm tài khoản → quét QR trong WMS, rồi nhập mã 6 số để **Xác nhận bật MFA**. Nếu không quét được, dùng khóa nhập tay dưới QR.
3. Khi đã bật MFA, mỗi lần đăng nhập nhập mật khẩu trước, sau đó nhập mã trên ứng dụng xác thực.
4. Sau đăng nhập, vào **Liên hệ** để xác minh email/điện thoại. Chỉ liên hệ đã xác minh mới nhận được hướng dẫn khôi phục.
5. Trong **Bảo mật**, có thể tạo mã khôi phục MFA. Lưu mã riêng; mã chỉ hiển thị một lần.

Tài khoản `kien` là quản trị hệ thống; quyền nghiệp vụ từng kho cần được cấp theo quy trình duyệt. Không có đăng ký công khai tự cấp quyền quản trị.

## Cấu hình riêng trên máy Linux hiện tại

Trạng thái triển khai ngày 08/10/2026: đã sao lưu và khôi phục thử database riêng, cài wheel mới vào `build/local-server/venv`, áp migration **025** và runtime grants. API nạp thêm `auth.env`; `wms-local-auth-delivery.service` đã cài và bật theo target. Health/readiness trả 200, PostgreSQL/API/7 worker đều active. Gmail SMTP xác thực thành công (chưa gửi thư kiểm thử). Google đã nạp từ JSON Desktop gốc: kiểm tra client không còn `invalid_client`, endpoint khởi tạo OAuth trả 200 với PKCE S256 và callback loopback. `/api/v1/auth/options` trả email=true, google=true, sms=false. Chưa hoàn tất đăng nhập/liên kết Google bằng người dùng thật; cần mật khẩu WMS và MFA hiện tại. SMS chờ nhà cung cấp. Không lưu thông tin bí mật trong tài liệu này.

Thứ tự triển khai để tái lập trên máy khác hoặc đối chiếu cấu hình hiện tại:

1. Sao lưu DB và các file cấu hình riêng, giữ nguyên khóa MFA; kiểm tra bản sao lưu trước nâng cấp.
2. Đóng gói/cài release chứa migration **025**, API và module `apps.server.auth_delivery_worker`. Chạy migration bằng tài khoản owner và áp lại `deploy/lan/postgresql/runtime-grants.sql` cho runtime. Dùng quy trình [triển khai LAN](../deploy/lan/README.md); không chạy test hay migration thử trên DB vận hành.
3. Tạo `~/.config/wms-local-server/auth.env` quyền **0600**, thư mục quyền **0700**. Dùng dòng `KEY=value` nguyên văn, không `export`, không nội suy shell. Chỉ điền dịch vụ đã có thông tin thật, không chép placeholder. Mật khẩu SMTP, token SMS và client secret không gửi vào chat/Git.
4. Tạo drop-in `~/.config/systemd/user/wms-local-api.service.d/auth.conf`:

```ini
[Service]
EnvironmentFile=%h/.config/wms-local-server/auth.env
```

5. Tạo `~/.config/systemd/user/wms-local-auth-delivery.service` sau khi đã cài bản server mới. Mẫu riêng cho máy hiện tại:

```ini
[Unit]
Description=WMS local authentication email and SMS delivery
Requires=wms-local-api.service
After=wms-local-api.service
PartOf=wms-local.target

[Service]
Type=simple
EnvironmentFile=%h/.config/wms-local-server/runtime.env
EnvironmentFile=%h/.config/wms-local-server/mfa.env
EnvironmentFile=%h/.config/wms-local-server/auth.env
ExecStart="/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/build/local-server/venv/bin/python" -I -m apps.server.auth_delivery_worker
Restart=on-failure
RestartSec=10
UMask=0077
LimitCORE=0

[Install]
WantedBy=wms-local.target
```

6. Sau khi hoàn tất các bước trên, chạy:

```bash
rtk proxy systemctl --user daemon-reload
rtk proxy systemctl --user enable wms-local-auth-delivery.service
rtk proxy systemctl --user restart wms-local.target
rtk proxy systemctl --user is-active wms-local-api.service wms-local-auth-delivery.service
```

Đóng/mở lại WMS. Kiểm tra `/api/v1/auth/options` trả các cờ email/sms/google theo cấu hình. Nếu trả 404, API vẫn là bản cũ. Cờ `true` chỉ cho biết đủ trường cấu hình, chưa chứng minh gửi/đăng nhập thật thành công. Không thay khóa trong `mfa.env`; thay khóa sẽ làm mất khả năng giải mã MFA và thông báo đang chờ.

Không cần tên miền để dùng Gmail SMTP hoặc Google OAuth Desktop. API trong LAN vẫn cần HTTPS với chứng thư được máy khách tin cậy; callback Google chỉ chạy loopback trên máy desktop. Không mở PostgreSQL hay API HTTP trực tiếp ra Internet để cấu hình các dịch vụ này.

## Email: Gmail SMTP

Đăng nhập Gmail `trantrungkien20012006@gmail.com`, vào [Bảo mật tài khoản Google](https://myaccount.google.com/security), bật xác minh hai bước. Mở [App Passwords](https://myaccount.google.com/apppasswords), đặt tên `WMS SMTP`, tạo **App Password** theo [hướng dẫn Google](https://support.google.com/mail/answer/185833). Một số tài khoản do tổ chức quản lý hoặc có chính sách bảo mật khác có thể không có tùy chọn này.

Đặt các dòng sau vào `auth.env`, thay giá trị bằng tài khoản thật:

```ini
WMS_AUTH_SMTP_HOST=smtp.gmail.com
WMS_AUTH_SMTP_PORT=465
WMS_AUTH_SMTP_STARTTLS=false
WMS_AUTH_SMTP_USER=trantrungkien20012006@gmail.com
WMS_AUTH_SMTP_FROM=trantrungkien20012006@gmail.com
WMS_AUTH_SMTP_PASSWORD=your-app-password
```

Dùng App Password, không dùng mật khẩu đăng nhập Gmail. Bỏ khoảng trắng phân nhóm của App Password nếu màn hình Google hiển thị theo nhóm. Với SMTP của nhà cung cấp khác, dùng host/tài khoản của họ; cổng 587 cần `WMS_AUTH_SMTP_STARTTLS=true`. Không có chế độ SMTP plaintext.

Kiểm tra thật: đăng nhập + MFA → **Liên hệ** → nhập email, mật khẩu hiện tại và mã MFA mới → **Gửi mã xác minh** → nhập mã nhận được → **Xác minh liên hệ**. Sau đó đăng xuất, thử **Quên tài khoản / mật khẩu**.

## Đăng nhập Google

1. Mở [Google Cloud Console](https://console.cloud.google.com/), tạo/chọn project `WMS InternTechLead`.
2. Cấu hình Google Auth Platform: Branding (WMS/InternTechLead), Audience và thông tin hỗ trợ. Với Gmail cá nhân chọn External; khi ở chế độ Testing, thêm `trantrungkien20012006@gmail.com` vào Test users. Luồng hiện tại chỉ xin phạm vi `openid`, `email`, không cần quyền đọc Gmail/Drive.
3. Tạo OAuth client loại **Desktop app**, theo [hướng dẫn tạo thông tin xác thực](https://developers.google.com/workspace/guides/create-credentials).
4. Thêm client ID vào `auth.env`; nếu bộ thông tin tải xuống có client secret thì thêm dòng tương ứng:

```ini
WMS_AUTH_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
WMS_AUTH_GOOGLE_CLIENT_SECRET=your-desktop-client-secret
```

Ứng dụng mở trình duyệt mặc định và nhận callback tạm trên `127.0.0.1`. Không mở cổng callback ra LAN, không khai báo redirect tới địa chỉ API kho. Flow dùng PKCE S256, state và nonce; xem [OAuth cho ứng dụng native](https://developers.google.com/identity/protocols/oauth2/native-app).

**Liên kết lần đầu:** đăng nhập bằng tài khoản/mật khẩu + MFA → **Bảo mật** → nhập mật khẩu hiện tại và mã MFA mới → **Liên kết tài khoản Google** → chọn Google trên trình duyệt. Những lần sau bấm **logo Google** rồi xác nhận MFA của WMS.

WMS kiểm tra chữ ký ID token, issuer, audience, nonce, hạn dùng và email_verified theo [tài liệu OpenID Connect của Google](https://developers.google.com/identity/openid-connect/openid-connect). Liên kết theo Google subject ổn định, không tự gắn tài khoản chỉ vì trùng email. Tài khoản Google chưa liên kết sẽ nhận hướng dẫn đăng nhập bằng mật khẩu để liên kết.

## SMS: Twilio

Chủ dự án muốn triển khai SMS, nhưng hiện chưa có tài khoản Twilio hoặc hồ sơ doanh nghiệp. Trạng thái: **chờ nhà cung cấp**, chưa gửi SMS thật.

1. Tạo tài khoản tại [Twilio Console](https://console.twilio.com/). Xác nhận nhà cung cấp tiếp nhận hồ sơ trước khi nạp tiền/mua số.
2. Theo [hướng dẫn Việt Nam của Twilio](https://www.twilio.com/en-us/guidelines/vn/sms), đăng ký tên người gửi chữ và mẫu tin; cần hồ sơ doanh nghiệp, thêm bằng chứng quyền dùng thương hiệu khi được yêu cầu. Nếu chưa có hồ sơ, trao đổi trực tiếp với nhà cung cấp về điều kiện tiếp nhận; không coi tài khoản trial là đủ.
3. Xin duyệt ba mẫu bên dưới. Tên ứng dụng trong nội dung phải phù hợp tên người gửi; mã hiện tại dùng `WMS`. Nếu tên được duyệt khác, cần sửa mẫu trong ứng dụng trước khi gửi.
4. Sau khi được duyệt, lấy Account SID, Auth Token và tên người gửi chính xác, điền file riêng. Bật quyền gửi tới Việt Nam và kiểm tra giá/hạn mức trên tài khoản.

Mẫu thực tế từ ứng dụng (phần trong ngoặc nhọn là biến):

```text
WMS: Ma xac minh lien he cua ban: {code}. Het han sau 15 phut.
WMS: Tai khoan cua ban la {username}. Khong chia se mat khau hoac ma MFA.
WMS: Tai khoan {username}. Ma dat lai mat khau: {token}. Het han sau 15 phut. MFA van duoc giu nguyen.
```

Ứng dụng dùng [Messages API](https://www.twilio.com/docs/messaging/api/message-resource), không dùng Verify Service SID. Token reset dài có thể làm tăng số đoạn SMS tính phí; không tự rút ngắn token bảo mật.

```ini
WMS_AUTH_TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WMS_AUTH_TWILIO_AUTH_TOKEN=your-auth-token
WMS_AUTH_TWILIO_FROM=your-approved-sender
```

Số nhận dùng dạng quốc tế `+84...`; WMS cũng chuẩn hóa số Việt Nam dạng `0xxxxxxxxx`. Chỉ bật SMS khi người gửi/mẫu tin được duyệt. Khi chưa có, để trống cả ba biến Twilio.

## Thông tin cần chuẩn bị và kiểm thử thật

| Dịch vụ | Có thể cung cấp trong chat | Nhập trực tiếp vào file riêng |
|---|---|---|
| Gmail | Báo đã tạo App Password; email nhận thử | App Password SMTP |
| Google | Client ID Desktop; danh sách tài khoản thử | Client secret nếu bộ thông tin có |
| SMS | Tình trạng duyệt; Sender ID; số nhận thử có đồng ý | Auth Token; Account SID trong cấu hình |
| MFA | Báo đã cài ứng dụng xác thực | Quét QR/nhập khóa trực tiếp; giữ mã khôi phục riêng |

Không cần gửi mật khẩu tài khoản Google hay mã OTP cho người triển khai. Sau khi có cấu hình:

1. Đăng nhập WMS bằng mật khẩu và MFA. Xác minh email trong **Liên hệ**; kiểm tra thư nhận được, cả Spam. Thử quên tên tài khoản và reset mật khẩu một lần, xác nhận vẫn cần MFA sau reset.
2. Liên kết Google trong **Bảo mật**, đăng xuất rồi đăng nhập bằng logo Google; hoàn tất MFA. Tài khoản Google chưa liên kết không được tự cấp quyền.
3. Sau khi SMS được duyệt, xác minh số nhận thử, thử reset bằng SMS và kiểm tra điện thoại thực sự nhận được. API nhà cung cấp chấp nhận chưa đồng nghĩa SMS đến máy.
4. Kiểm tra mã sai/hết hạn/đã dùng bị từ chối, mất mạng hiện lỗi hợp lý, worker hoạt động sau restart. Lưu kết quả không kèm token hoặc mật khẩu.

## Khôi phục và bảo vệ dữ liệu

- Quên tài khoản/mật khẩu luôn trả thông báo chung, tránh tiết lộ liên hệ nào có tài khoản.
- Mã xác minh liên hệ có 6 số, hết hạn sau 15 phút. Mã reset mật khẩu ngẫu nhiên dài, dùng một lần và hết hạn sau 15 phút.
- Yêu cầu quên mật khẩu không tự đăng xuất các phiên. Chỉ khi reset thành công mới thu hồi phiên; MFA hiện có được giữ nguyên.
- Giới hạn thử/gửi mã lưu ở server. Các thao tác xác thực không được đưa vào SQLite draft/journal hoặc tự phát lại khi mất mạng.
- Nội dung gửi được mã hóa bằng khóa MFA của server trong hàng đợi riêng. Worker gửi ngoài transaction DB, tối đa 5 lần, dùng lease. Gửi thành công/hết hạn sẽ xóa ciphertext.
- Sau sự cố giữa gửi và ghi ACK, nhà cung cấp có thể gửi lặp cùng mã; mã vẫn chỉ dùng được một lần. Không hứa giao nhận exactly-once.
- Chưa xác minh liên hệ hoặc mất MFA: dùng quy trình quản trị/reset và mã khôi phục có sẵn; email reset mật khẩu không vượt qua MFA.
- Khôi phục email/SMS và đăng nhập Google thật chưa được chứng minh khi chưa có tài khoản dịch vụ. Test tự động dùng transport/JWT/SMTP fixture, không gửi tin tới người thật.

## Triển khai LAN

Nâng cấp qua bộ release, sao lưu DB và khóa MFA trước, chạy migration **025** bằng `wms_owner`, áp lại runtime grants rồi khởi động API/workers của cùng release. Không chạy migration bằng `wms_app`.

Đặt cấu hình nhà cung cấp tại `/etc/wms/auth.env`, quyền 0600. Thêm drop-in cho `wms-api.service`:

```ini
[Service]
LoadCredential=auth.env:/etc/wms/auth.env
```

Cài unit `deploy/lan/systemd/wms-auth-delivery.service`, rồi chạy `systemctl daemon-reload`, restart API và enable/start unit đó. Worker này bổ sung cho 6 worker nghiệp vụ; chỉ bật khi có dịch vụ gửi mã. Runner `scripts/lan_runtime.py` chấp nhận credential nhà cung cấp riêng và không ghi secret vào log.

## Nguồn hình ảnh

Bố cục tham chiếu từ [trang đăng nhập ShopDunk](https://shopdunk.com/login?returnUrl=%2F) theo yêu cầu chủ dự án; nội dung header/footer dùng WMS và InternTechLead.

Hình người/khóa lấy từ [ảnh trên ShopDunk](https://shopdunk.com/images/uploaded/banner/VNU_M492_08%201.jpeg), lưu tại `apps/desktop/assets/login-security.jpeg`. Biểu tượng Google lấy từ `https://developers.google.com/static/identity/images/g-logo.png`, lưu tại `apps/desktop/assets/google-g.png`. Việc tải tài nguyên công khai không tự cấp thêm quyền sở hữu; hồ sơ phát hành thương mại cần lưu quyền sử dụng tương ứng.

Bản dùng trong giao diện là `login-security-transparent.png`, tách nền bằng ImageGen theo yêu cầu chủ dự án để nền sáng/tối hiện xuyên qua phần nền ảnh. Bản JPEG nguồn được giữ nguyên; hiển thị PNG giữ tỷ lệ gốc.

Logo husky do chủ dự án cung cấp, chuyển trắng không viền bằng công cụ ImageGen tích hợp; lưu tại `apps/desktop/assets/wms-logo.png`. Bản được chọn có nền charcoal hòa với header. Prompt được lưu trong `apps/desktop/assets/LOGO_WHITE_PROMPT.txt`.

Cập nhật logo hiển thị: header, footer và icon cửa sổ dùng `wms-logo-transparent.png`, bản sáng nền trong suốt tạo lại từ logo màu gốc bằng ImageGen theo lựa chọn của chủ dự án. Bản charcoal cũ được giữ làm nguồn. Chữ WMS rời bên cạnh logo header đã bỏ; chữ WMS thuộc hình logo vẫn giữ.

Icon giao diện (mắt, tìm kiếm, hỗ trợ, tài khoản) tải từ kho [Lucide chính thức](https://github.com/lucide-icons/lucide), giữ nguyên hình học SVG; nguồn, revision và giấy phép ở `apps/desktop/assets/lucide/`. Nút Google chỉ hiển thị logo chính thức giữ nguyên tỷ lệ.

Form đăng nhập có hai ô cùng chiều rộng và liên kết quên mật khẩu trước nút đăng nhập. Bên dưới lần lượt là “Hoặc đăng nhập với”, nút Google, rồi “Chưa có tài khoản? Liên hệ quản trị viên”. Chỉ dùng nút mắt trong ô mật khẩu để hiện/ẩn, không có checkbox và không lưu mật khẩu. Góc phải header có nút chuyển sáng/tối dùng SVG mặt trời/mặt trăng chính thức của Lucide; màu áp dụng cho trang đăng nhập và các bước MFA/kho trong cùng trang, mặc định sáng khi mở ứng dụng. Menu nghiệp vụ chỉ hiện sau khi đăng nhập và xác thực MFA. Google cần OAuth hợp lệ trên máy chủ trước khi sử dụng.

Nút giao diện gồm hai nửa mặt trời/mặt trăng trong một khung, nền lựa chọn trượt trong 200 ms. Có thể chọn bằng chuột, phím trái/phải hoặc Space/Enter; đổi hướng khi đang trượt tiếp tục từ vị trí hiện tại. Timer được hủy khi đóng widget.

Footer có bốn cột: giới thiệu WMS/InternTechLead, thông tin, bảo mật và địa chỉ/liên hệ; tự chuyển hai cột ở cửa sổ nhỏ. Logo WMS dùng lại tài sản của chủ dự án, logo Zalo tải từ trang chính thức (nguồn trong `apps/desktop/assets/ZALO_SOURCE.txt`), icon điện thoại/sách dùng Lucide. Các liên kết có hover và hỗ trợ bàn phím. Hotline 0329511628 và số Zalo 0869233973 được giữ riêng.

Theo yêu cầu mới nhất, đã bỏ nút Zalo nổi và toàn bộ hiệu ứng sóng. Các liên kết Zalo trong footer vẫn mở `https://zalo.me/0869233973` khi người dùng bấm. Viền tròn footer được render UI ở độ phân giải 4× để chống răng cưa. Ảnh minh họa trên màn hình rộng có kích thước tối đa 560 px, giữ tỷ lệ và nền trong suốt.

## Trang khôi phục mật khẩu

“Quên mật khẩu?” mở một trang trong ứng dụng, dùng chung header/footer và chế độ sáng/tối, không tạo cửa sổ Toplevel hay messagebox. Trang có đường dẫn quay lại đăng nhập, minh họa bên trái và form email bên phải; cửa sổ nhỏ ưu tiên form. Có thể chuyển sang số điện thoại hoặc yêu cầu tìm lại tên tài khoản. Thông báo yêu cầu gửi luôn theo cơ chế không tiết lộ tài khoản tồn tại; nếu dịch vụ gửi chưa cấu hình thì giải thích ngay trên trang, không báo gửi thành công giả.

“Tôi đã có mã khôi phục” mở bước nhập tài khoản, mã, mật khẩu mới và xác nhận mật khẩu. Kiểm tra độ dài 12–128 ký tự, xác nhận khớp trước khi gửi; chặn gửi lặp trong khi worker đang xử lý. Mã/mật khẩu được xóa khỏi ô nhập khi gửi hoặc rời trang; lỗi mã hết hạn hiển thị ngay trên form. Đổi mật khẩu thành công quay lại đăng nhập và vẫn yêu cầu MFA.

Ảnh nguồn: [trang khôi phục ShopDunk](https://shopdunk.com/passwordrecovery), tài nguyên `https://shopdunk.com/images/uploaded/banner/TND_M402_02%201.jpeg`, lưu `recovery-security.jpeg`. Bản hiển thị `recovery-security-transparent.png` tách nền bằng ImageGen theo cùng quy trình ảnh đăng nhập. Nội dung form dùng WMS/InternTechLead, không dùng thương hiệu ShopDunk.

Kiểm thử GUI tại `tests/foundation/test_password_recovery_view.py` dùng phản hồi API giả lập, xác minh điều hướng, lỗi tại form và xóa dữ liệu nhạy cảm. Kiểm thử này không thay thế kiểm tra gửi email/SMS thực tế; các dịch vụ vẫn cần cấu hình trên máy chủ.

QR MFA được tạo trong bộ nhớ bằng thư viện [qrcode](https://pypi.org/project/qrcode/), không gửi khóa đến website tạo QR hoặc lưu ảnh QR ra đĩa. QR giữ nền trắng, ô vuông nguyên pixel và quiet zone bốn ô để dễ quét ở cả sáng/tối. QR và khóa nhập tay bị xóa khi hết hạn thiết lập, đăng xuất, xác nhận thành công hoặc đóng giao diện. Kiểm thử giải mã dùng khóa giả và zxing-cpp; chưa thay thế kiểm tra quét bằng điện thoại thật.
