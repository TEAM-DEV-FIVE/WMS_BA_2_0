# Thiết lập ký Windows để phát hành

## Trạng thái và nguyên nhân

Bộ EXE `97d4c510dab8` ở release `v0.1.0-handover.1` dùng chứng thư tự ký
`InternTechLead TEST ONLY`. Người dùng đã ghi nhận Edge cảnh báo ít lượt tải và Windows 11
Smart App Control chặn do không xác minh được nhà phát hành. Đây là bằng chứng bị chặn trước
khi chạy, không phải kết quả nghiệm thu WMS trên Windows 11.

Chủ dự án xác nhận chưa có chứng thư chính thức. Cần hoàn tất đăng ký/xác minh danh tính với CA
trước khi có thể tạo bộ cài ký chính thức. Không sửa hoặc ghi đè bộ cài đã niêm phong; bản sửa
sẽ có commit, tên gói và checksum mới.

## Chọn dịch vụ

- [Certum Standard Code Signing](https://www.certum.eu/en/code-signing-certificates/) có lựa chọn
  cá nhân/doanh nghiệp và cloud. Cần xác nhận nhà cung cấp nhận hồ sơ Việt Nam, gói cloud,
  tổng chi phí và cách dùng SimplySign với SignTool trước khi thanh toán.
- [SSL.com eSigner](https://www.ssl.com/products/software-integrity/signing-service/) có IV/OV,
  cloud HSM và Crypto Key Adapter tích hợp SignTool. Phí chứng thư và phí/lượt ký là các khoản riêng;
  tính số native binary cần ký, không chỉ một installer. Xác nhận hồ sơ Việt Nam với nhà cung cấp.
- [Microsoft Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
  hiện không liệt kê Việt Nam trong khu vực Public Trust; cá nhân chỉ ở Mỹ/Canada theo tài liệu
  kiểm tra ngày 06/10/2026. Không dùng địa chỉ hoặc danh tính giả để đăng ký.

Dùng danh tính cá nhân nếu không có pháp nhân phù hợp. Tên InternTechLead trong ứng dụng không
tự chứng minh tư cách pháp nhân. Chủ dự án tự nhập giấy tờ, thông tin thanh toán, PIN/OTP vào
cổng chính thức; không đưa chúng vào Git, Actions log hoặc cuộc hội thoại.
Không đăng ký gói Open Source khi chưa đáp ứng điều kiện giấy phép/phân phối của CA.

## Máy ký và lệnh build

1. Chuẩn bị máy Windows x64 riêng, Python 3.12/Tk, Windows SDK SignTool và Inno Setup 6.7.3.
2. Cài adapter cloud/token của CA; đăng nhập/mở khóa bằng tài khoản chủ chứng thư.
   Cert phải xuất hiện trong `Cert:\CurrentUser\My` hoặc `Cert:\LocalMachine\My`, có quyền ký
   qua provider. Khóa riêng ở cloud HSM/token; không xuất PFX hay gửi khóa vào repository.
3. Checkout sạch commit đã review. Lấy thumbprint công khai của chứng thư Code Signing còn hạn.
4. Chạy:

```powershell
.\packaging\windows\Build.ps1 `
  -ISCC 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
  -CertificateThumbprint '<thumbprint-chinh-thuc>' `
  -CertificateStore CurrentUser `
  -SignTool 'C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\signtool.exe'
```

Luồng chuẩn không truyền `-Unsigned` hoặc `-AllowTestCertificate`. Script từ chối chứng thư
self-signed/TEST ONLY trừ khi bật cờ lab; chain phải được máy ký xác minh. Kiểm tra này không
tự chứng nhận public trust nếu trust store máy ký đã bị sửa, nên máy đích sạch là bước bắt buộc.

Script ký WMS.exe/helper; kiểm mọi EXE/DLL/PYD, giữ chữ ký vendor hợp lệ và ký file chưa ký.
Chữ ký có sẵn không hợp lệ làm build dừng để điều tra, không bị che bằng chữ ký mới.
Manifest được lập sau ký. Inno ký cả setup, bản sao tạm và uninstaller.

## Kiểm tra và phát hành bản thay thế

Trên Windows 11 sạch bật Smart App Control, không nhập chứng thư lab:

1. Tải bộ cài mới bằng Edge từ URL phát hành, ghi hash/publisher/OS build và kết quả thực tế.
2. Chạy `Test-Install.ps1` với hash và signer thật; kiểm mọi native file đã cài cùng uninstaller.
3. Kiểm login/API, PDF/in, ảnh/Excel, upgrade giữ cache, gỡ/cài lại; xem Code Integrity logs khi có chặn.
4. Chỉ khi đạt mới phát hành bộ cài mới và cập nhật link README. Không gọi kết quả VM lab là SAC PASS.

[Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
yêu cầu chữ ký từ nhà cung cấp tin cậy.
[SmartScreen](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
còn xét uy tín file/nhà phát hành: chữ ký OV/EV không bảo đảm bỏ cảnh báo ít lượt tải ngay.
[Kiểm thử SAC chính thức](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control)
bao gồm các binary được nạp, bộ cài và trình gỡ cài đặt.
