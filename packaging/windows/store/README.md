# Microsoft Store — gói MSIX

Chủ dự án chọn hướng miễn phí/dễ triển khai: đăng ký qua
[storedeveloper.microsoft.com](https://storedeveloper.microsoft.com/), xác minh tài khoản,
đặt tên ứng dụng và gửi MSIX để Microsoft ký/phân phối sau xét duyệt.
Không cần mua chứng thư Code Signing cho gói gửi Store; EXE tự host trên GitHub là luồng khác.
Xem [Microsoft Store onboarding](https://learn.microsoft.com/en-us/windows/apps/publish/faq/open-developer-account)
và [ký MSIX qua Store](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide).

## Thông tin cần từ chủ tài khoản

Partner Center → Apps and games → ứng dụng → Product management → Product identity.
Chủ tài khoản đã cung cấp identity; bản công khai được lưu tại [identity.json](identity.json):

```json
{
  "name": "InternTechLead.WMS120",
  "publisher": "CN=201AEB57-073D-4301-BFFC-13D1EA9EBBAC",
  "publisher_display_name": "InternTechLead",
  "display_name": "Ứng dụng quản lý tồn kho"
}
```

Đây là identity công khai. Không gửi password, token, giấy tờ xác minh hoặc khóa ký.
Không lấy tên mẫu trong CI làm identity thật. Chưa có Store listing được duyệt hoặc URL tải chính thức.

Chủ tài khoản đã xác nhận tên chính xác **Ứng dụng quản lý tồn kho** trong Partner Center.
Tên được lưu nguyên văn trong `display_name` của JSON để build gói gửi Store.
`display_name` khác `name` (Package Identity) và `publisher_display_name` (tên nhà phát hành).
Script bắt buộc trường này và dùng cho cả Properties/DisplayName lẫn VisualElements/DisplayName;
không tự suy ra tên từ Package Identity. Local/SDK không truy vấn được danh sách tên Reserved.

## Đóng gói

Build desktop unsigned bằng [Build.ps1](../Build.ps1) trong Windows x64 với dependency lock.
Dùng thư mục `build/windows-<uuid>/frozen/WMS` và interpreter trong `venv` của chính build đó.

```powershell
.\packaging\windows\store\Build-Store.ps1 `
  -Bundle 'build\windows-<uuid>\frozen\WMS' `
  -Python 'build\windows-<uuid>\venv\Scripts\python.exe' `
  -MakeAppx 'C:\Program Files (x86)\Windows Kits\10\bin\<SDK-version>\x64\makeappx.exe' `
  -IdentityFile 'packaging\windows\store\identity.json' `
  -Version '2.1.0.0' `
  -OutputDirectory 'dist\store-submission-2.1.0.0'
```

Theo yêu cầu chủ dự án, bản phát hành Store là **V2.1.0**, MSIX version `2.1.0.0`.
Đây là phiên bản package của Store, runtime/protocol WMS hiện vẫn 0.1.0.
SDK kiểm manifest/pack/unpack và script kiểm lại hash mọi file ứng dụng sau unpack.
`store-package.json` ghi identity, commit, hash và trạng thái **chưa được Store ký/duyệt**.
Gói unsigned dùng để gửi Partner Center, không thay bộ cài công khai bằng sideload.

CI dùng `-TestIdentity` tạo tên gói `TEST-IDENTITY`; chỉ chứng minh SDK chấp nhận cấu trúc.
Không đăng gói thử này lên Releases và không coi đó là kiểm thử cài đặt MSIX đã đạt.

Để tạo gói gửi Store trên VM Windows: chạy workflow **Build Windows desktop package**
với `store_submission=true`. Tải artifact `store-msix-SUBMISSION-UNSIGNED-<commit>`;
file `.msix` bên trong dùng để upload tại Partner Center → submission → Packages.
Workflow không tự gửi duyệt hay xuất bản. Mặc định/PR vẫn dùng identity thử nghiệm.

## Kết quả build theo identity của chủ tài khoản

### Bản hiện tại: V2.1.0

Commit `18837b1dce7ab5ffb19618c9717cd9080b1b0456` đã đạt
[Windows CI #37497251235](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37497251235):
build desktop, cài EXE/frozen self-test, MakeAppx validation/pack/unpack và hash payload đều PASS.
Gói **WMS-Store-2.1.0.0-x64.msix** có tên **Ứng dụng quản lý tồn kho**, dùng nguyên identity/publisher
đã cung cấp. Bộ kiểm thử đóng gói local đạt 43 tests; 2 integration/GUI không thuộc lượt unit.
Trạng thái **AWAITING_STORE_SUBMISSION**; chưa có kết quả validation mới từ Partner Center.

### Lịch sử gói bị từ chối

**Partner Center đã từ chối gói 1.0.0.0:** `Package/Properties/DisplayName` là
`WMS — Quản lý kho`, chưa được đặt trước. Không gửi lại gói này; dùng
tên đã xác nhận **Ứng dụng quản lý tồn kho**, build 2.1.0.0 rồi thay gói bị lỗi trong Packages. Các kết quả SDK bên dưới
chỉ xác nhận cấu trúc/toàn vẹn, không xác nhận Store chấp nhận metadata.

Ngày 06/10/2026, commit `9772e652ed7ac043ed15bc34af579fc4424f5eb7` đã đạt
[Windows CI #37492393732](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37492393732):

- Build Windows x64 theo dependency lock; cài EXE và frozen self-test: PASS.
- Windows SDK MakeAppx kiểm manifest, pack/unpack MSIX và kiểm hash payload: PASS.
- Gói gửi: `WMS-Store-1.0.0.0-x64.msix`, identity `InternTechLead.WMS120`.
- 39 kiểm thử đóng gói local đạt; 2 kiểm thử integration/GUI ngoài phạm vi unit không chọn.

Gói hiện tại chưa được Store ký/chứng nhận;
kiểm thử cài, nâng cấp và gỡ MSIX theo package identity còn **NOT_RUN**.
Kết quả cài EXE không thay thế kết quả cài MSIX. Bản EXE TEST ONLY đang trên Releases
không tự hết cảnh báo sau khi tạo gói này.

Trong Partner Center, tạo submission cho ứng dụng tương ứng, mở **Packages** rồi upload
file `.msix` (không upload ZIP artifact GitHub hay file EXE cũ). Sau khi Store phân tích,
đối chiếu identity/version và xử lý thông báo validation trước khi gửi chứng nhận.
Tên hiển thị trong manifest cần khớp tên ứng dụng đã đặt trước tại Partner Center;
nếu Store báo không khớp, cập nhật DisplayName theo tên đã đặt rồi build lại.

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

Tên đã xác nhận bởi chủ tài khoản: **Ứng dụng quản lý tồn kho**.
Mô tả: desktop quản lý kho qua máy chủ WMS trên LAN, theo dõi nhập–xuất–tồn/lô/serial,
phê duyệt, kiểm kê, báo cáo, in phiếu/tem và phục hồi lệnh khi mất kết nối.
Ghi rõ cần máy chủ và tài khoản do đơn vị vận hành cấp; không có server công cộng/mật khẩu mặc định.

Cần ảnh chụp UI thật, support/privacy URL, age rating và hướng dẫn reviewer tiếp cận môi trường
demo riêng. Không gửi dữ liệu kho thật hoặc credential thật trong listing công khai.
Chủ tài khoản trực tiếp xác nhận điều khoản và xác minh danh tính. Chỉ đổi nút Windows sang
Store khi đã có listing được duyệt và kiểm chứng cài tải từ Store.
