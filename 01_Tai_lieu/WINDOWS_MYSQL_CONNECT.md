# Kết nối WMS với MySQL đang có trên Windows

**Không cần cài đúng một phiên bản MySQL duy nhất.** WMS kiểm tra dòng phiên bản và các tính năng cần thiết trước khi tạo database. Nếu MySQL đang có phù hợp, dùng luôn instance đó; không bắt cài lại hoặc mở thêm cổng 3307.

| MySQL trên máy | Xử lý |
|---|---|
| Dòng 8.0, từ 8.0.23 trở lên | Chạy `preflight`; nếu đạt thì dùng bản đang có. |
| Dòng 8.4 LTS | Chạy `preflight`; nếu đạt thì dùng bản đang có. |
| 8.0 trước 8.0.23, ví dụ 8.0.11 | Thiếu tính năng schema cần dùng; phải nâng cấp hoặc cài instance mới riêng. |
| MySQL dòng khác / MariaDB, XAMPP dùng MariaDB | Chưa thuộc phạm vi hỗ trợ; công cụ dừng trước khi tạo dữ liệu WMS. |

8.0.46 là mốc kiểm thử, không phải điều kiện duy nhất để cài. Không thể cam kết mọi phiên bản hoặc cấu hình database đều tương thích. Kiểm tra đầu vào giúp phát hiện thiếu tính năng trước khi để lại database WMS dở dang; lỗi ổ đĩa, mất điện hay quyền thay đổi giữa chừng vẫn cần xử lý riêng. Xem [phạm vi và bằng chứng](../07_Kiem_tra/release/WINDOWS_MYSQL_RECOVERY_20261018.md).

Quy trình dưới đây tạo **database WMS mới** trong MySQL đang chạy; không nhập lại hoặc sửa database cũ. Desktop nối API ở 8000; chỉ API và worker nối MySQL. Không cần Ubuntu, WSL hoặc Docker.

## 1. Tải bộ máy chủ mới và cài Python

Tải `WMS-Windows-Standalone-20261018.1.zip` và `SHA256SUMS.txt` tại [release Windows Server](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-windows-server.20261018.1). Kiểm tra SHA-256 rồi Extract All vào `Downloads\WMS-Windows-Standalone-20261018.1`.

```powershell
$wmsZip = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018.1.zip'
Get-FileHash $wmsZip -Algorithm SHA256
py -3.12 --version
```

Đối chiếu hash với tệp SHA256SUMS của cùng release. Nếu chưa có Python 3.12 x64, làm [bước 4 cài Python](WINDOWS_STANDALONE.md#bước-4-cài-python-cho-phần-máy-chủ) trước. Dùng PowerShell thường của tài khoản Windows sẽ chạy WMS.

Nếu đã cài đúng bộ máy chủ của release này trong `WMS-Server-Python-Recovery`, bỏ qua khối cài thư viện dưới đây. Nếu chưa, tạo môi trường riêng; môi trường cũ `WMS-Server-Python` giữ nguyên:

```powershell
$ErrorActionPreference = 'Stop'
$bundle = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018.1'
$venv = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery'
if (Test-Path $venv) { throw 'Moi truong da ton tai. Xac dinh ban da cai truoc khi tiep tuc; khong ghi de.' }
py -3.12 -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc Python venv.' }
$wmsPy = Join-Path $venv 'Scripts\python.exe'
& $wmsPy -m pip install --only-binary=:all: -r (Join-Path $bundle 'requirements-app-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cai thu vien that bai.' }
& $wmsPy -m pip install --no-deps (Join-Path $bundle 'wms_lan-0.1.0-py3-none-any.whl')
if ($LASTEXITCODE -ne 0) { throw 'Cai WMS that bai.' }
```

## 2. Kiểm tra MySQL đang có

Đặt $mysqlPort bằng cổng MySQL thực tế. Dùng 3306 nếu MySQL đang chạy ở cổng đó; chỉ đổi thành 3307 khi đã có MySQL chạy ở 3307.

$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
$mysqlPort = 3306

if (-not (Test-Path -LiteralPath $wmsPy -PathType Leaf)) {
    throw "Khong tim thay Python: $wmsPy"
}

& $wmsPy -I -m apps.server.windows_standalone preflight --mysql-port $mysqlPort

if (-not $?) {
    throw 'Preflight khong thanh cong. Doc loi o tren va khac phuc truoc khi setup.'
}

Nhập mật khẩu root của đúng instance ở cổng đã chọn. Không cần gửi mật khẩu cho người hỗ trợ.

- Thấy MYSQL_COMPATIBLE: dùng MySQL đang có, sang bước 3. Không cần cài lại chỉ vì phiên bản khác 8.0.46.
- Báo thiếu múi giờ: thực hiện bước nạp POSIX SQL timezone vào đúng instance, dùng đúng cổng và đường dẫn mysql.exe; khởi động lại instance đó rồi chạy lại preflight.
- Báo MySQL quá cũ hoặc ngoài phạm vi: giữ bản cũ; dùng hướng dẫn cài riêng ở 3307 nếu cần.
- Báo 1045, không kết nối được hoặc thiếu quyền: kiểm tra dịch vụ, cổng, tài khoản và mật khẩu root; chưa thể kết luận do phiên bản.

Đoạn kiểm tra lỗi mới cũng tránh dùng nhầm $LASTEXITCODE từ lệnh trước khi Python không khởi chạy được.
## 3. Tạo database WMS mới, giữ database cũ

Nếu máy chủ WMS cũ đang chạy, dùng lệnh `stop` của bản đó và chờ SERVER_STOPPED để giải phóng cổng 8000. Sao lưu bản cũ theo [bước sao lưu](WINDOWS_MYSQL_RECOVERY.md#2-giữ-lại-bản-cũ-và-sao-lưu) trước khi bắt đầu lại. Không dừng MySQL mà bản mới sắp dùng.

Tiếp tục trong cửa sổ đã đặt `$wmsPy` và `$mysqlPort`:

```powershell
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome setup --mysql-port $mysqlPort --api-port 8000 --database wms_mysql_recovery --runtime-user wms_runtime_recovery
if ($LASTEXITCODE -ne 0) { throw 'Setup chua thanh cong. Giu nguyen du lieu va cau hinh.' }
```

Nhập mật khẩu root của instance đã kiểm tra. Phải thấy **SETUP_OK**. Tên mới `wms_mysql_recovery`/`wms_runtime_recovery` tránh ghi đè `wms_mysql` cũ đang dở dang. Nếu tên hoặc home mới đã tồn tại, công cụ dừng; không tự xóa chúng hoặc đổi marker thành COMPLETE.

`runtime.json` mới lưu đúng cổng/database và tài khoản runtime tự sinh. Root không được lưu. Không chép runtime.json cũ đè lên bản mới và không tự đặt mật khẩu database trong Desktop.

## 4. Tạo tài khoản WMS và chạy máy chủ

```powershell
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome admin --username admin.one --display-name 'Quan tri mot'
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc admin.one.' }
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome admin --username admin.two --display-name 'Quan tri hai'
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc admin.two.' }
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome check
if ($LASTEXITCODE -ne 0) { throw 'Chua dat CHECK_OK.' }
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome run
```

Đặt mật khẩu WMS riêng cho từng quản trị viên, 12–128 ký tự. Chờ **SERVER_READY** rồi giữ cửa sổ này mở. Trong PowerShell thứ hai:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ready'
```

Cả hai phải trả thành công. Nếu chưa đạt, chưa đổi cấu hình Desktop.

## 5. Kết nối Desktop và đăng nhập

Cài Desktop nếu chưa có từ [release giao diện WMS](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-ui.20261018.1). Bộ cài sử dụng chứng thư thử nghiệm, chưa phải chứng thư phát hành công khai được Windows tin cậy sẵn.

Đóng Desktop trước khi đổi cấu hình. PowerShell thứ hai:

```powershell
$clientDir = Join-Path $env:LOCALAPPDATA 'wms-lan'
$clientFile = Join-Path $clientDir 'client.json'
New-Item -ItemType Directory -Force -Path $clientDir | Out-Null
if (Test-Path $clientFile) {
  Copy-Item -LiteralPath $clientFile -Destination ($clientFile + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) -ErrorAction Stop
}
$clientJson = '{"api_url":"http://127.0.0.1:8000/api/v1","http_timeout_seconds":5}'
[System.IO.File]::WriteAllText($clientFile, $clientJson, (New-Object System.Text.UTF8Encoding($false)))
```

Mở Desktop, đăng nhập admin.one/admin.two bằng mật khẩu **WMS**, bật MFA theo giao diện. Không dùng mật khẩu root. Database mới chưa có kho/chứng từ; làm tiếp [tạo người dùng, cấp quyền và danh mục](WINDOWS_STANDALONE.md#bước-11-tạo-nhân-viên-và-cấp-quyền). Lệnh first-period phải dùng Python Recovery và `--home $wmsHome` như phía trên.

## 6. Dùng hằng ngày và sao lưu

MySQL phải đang chạy ở cổng đã chọn. Mỗi lần mở WMS:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery\Scripts\python.exe'
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome run
```

Khi tắt: đóng Desktop, mở PowerShell khác và chạy:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery\Scripts\python.exe'
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome stop
```

Chờ SERVER_STOPPED. Không chạy setup/admin lại hằng ngày. Khi sao lưu, dùng mysqldump của instance đang chạy, đúng cổng đã chọn, tên database **wms_mysql_recovery** và sao chép home **WMS-Server-Recovery**; không nhầm database cũ. Không dừng dịch vụ MySQL dùng chung khi các ứng dụng khác còn sử dụng.

Nếu cần mang dữ liệu cũ sang, thực hiện quy trình chuyển dữ liệu riêng có đối chiếu. Hướng dẫn này chỉ tạo kết nối và database mới; không coi database cũ đã bị xóa hoặc đã được phục hồi sang bản mới.
