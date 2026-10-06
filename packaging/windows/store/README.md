# Microsoft Store — gói MSIX

Chủ dự án chọn hướng miễn phí/dễ triển khai: đăng ký qua
[storedeveloper.microsoft.com](https://storedeveloper.microsoft.com/), xác minh tài khoản,
đặt tên ứng dụng và gửi MSIX để Microsoft ký/phân phối sau xét duyệt.
Không cần mua chứng thư Code Signing cho gói gửi Store; EXE tự host trên GitHub là luồng khác.
Xem [Microsoft Store onboarding](https://learn.microsoft.com/en-us/windows/apps/publish/faq/open-developer-account)
và [ký MSIX qua Store](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide).

## Thông tin cần từ chủ tài khoản

Partner Center → Apps and games → ứng dụng → Product management → Product identity.
Lưu ba giá trị **đúng nguyên văn** vào JSON ngoài repository:

```json
{
  "name": "<Package/Identity/Name>",
  "publisher": "<Package/Identity/Publisher>",
  "publisher_display_name": "<Package/Properties/PublisherDisplayName>"
}
```

Đây là identity công khai. Không gửi password, token, giấy tờ xác minh hoặc khóa ký.
Không lấy tên mẫu trong CI làm identity thật. Chưa có identity, Store listing hoặc URL tải chính thức.

## Đóng gói

Build desktop unsigned bằng [Build.ps1](../Build.ps1) trong Windows x64 với dependency lock.
Dùng thư mục `build/windows-<uuid>/frozen/WMS` và interpreter trong `venv` của chính build đó.

```powershell
.\packaging\windows\store\Build-Store.ps1 `
  -Bundle 'build\windows-<uuid>\frozen\WMS' `
  -Python 'build\windows-<uuid>\venv\Scripts\python.exe' `
  -MakeAppx 'C:\Program Files (x86)\Windows Kits\10\bin\<SDK-version>\x64\makeappx.exe' `
  -IdentityFile 'C:\Release\store-identity.json' `
  -Version '1.0.0.0' `
  -OutputDirectory 'dist\store-submission-1.0.0.0'
```

MSIX version khởi đầu `1.0.0.0`; đây là phiên bản package của Store, runtime WMS vẫn 0.1.0.
SDK kiểm manifest/pack/unpack và script kiểm lại hash mọi file ứng dụng sau unpack.
`store-package.json` ghi identity, commit, hash và trạng thái **chưa được Store ký/duyệt**.
Gói unsigned dùng để gửi Partner Center, không thay bộ cài công khai bằng sideload.

CI dùng `-TestIdentity` tạo tên gói `TEST-IDENTITY`; chỉ chứng minh SDK chấp nhận cấu trúc.
Không đăng gói thử này lên Releases và không coi đó là kiểm thử cài đặt MSIX đã đạt.

## Quyền và dữ liệu

- `runFullTrust`: Tkinter, HTTP LAN, SQLite, PDFium và helper in là ứng dụng desktop hiện có.
- `unvirtualizedResources` cùng FileSystemWriteVirtualization disabled: giữ dữ liệu
  `%LOCALAPPDATA%\wms-lan` ngoài vùng bị dọn khi gỡ MSIX, tương thích bản EXE.
  Đây là restricted capability cần giải trình/được Store duyệt.
- Minimum OS của package: Windows 10 build 19041. SDK pack không chứng nhận ứng dụng chạy
  trên mọi Windows 10/11; phải thực hiện kiểm thử máy đích.

Trước gửi xét duyệt: kiểm tra cài/launch theo package identity, API/LAN/CA, mở helper in/PDF,
upgrade, gỡ/cài lại giữ device/nháp/UNKNOWN và tránh chạy song song bản EXE với bản Store.
Chưa thử thực tế thì trạng thái vẫn NOT_RUN; không đổi đường dẫn cache tự động để né lỗi.

## Nội dung Store cần hoàn thiện

Tên gợi ý: **WMS — Quản lý kho InternTechLead** (chưa xác nhận còn trống).
Mô tả: desktop quản lý kho qua máy chủ WMS trên LAN, theo dõi nhập–xuất–tồn/lô/serial,
phê duyệt, kiểm kê, báo cáo, in phiếu/tem và phục hồi lệnh khi mất kết nối.
Ghi rõ cần máy chủ và tài khoản do đơn vị vận hành cấp; không có server công cộng/mật khẩu mặc định.

Cần ảnh chụp UI thật, support/privacy URL, age rating và hướng dẫn reviewer tiếp cận môi trường
demo riêng. Không gửi dữ liệu kho thật hoặc credential thật trong listing công khai.
Chủ tài khoản trực tiếp xác nhận điều khoản và xác minh danh tính. Chỉ đổi nút Windows sang
Store khi đã có listing được duyệt và kiểm chứng cài tải từ Store.
