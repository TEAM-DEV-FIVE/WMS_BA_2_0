# Cài lại WMS trên Windows và kết nối MySQL

Quy trình dành cho máy đã gặp `OperationalError` khi chạy `windows_standalone setup` với MySQL **8.0.11**, hoặc cần cài mới một bộ WMS độc lập. Làm từng bước trong Windows PowerShell, không chép dấu nhắc `PS C:\...>` và không chạy toàn bộ trang như một script.

**Kết quả là một database WMS mới, chưa có dữ liệu nghiệp vụ.** Quy trình này không chuyển chứng từ từ database cũ. Bản MySQL cũ, database `wms_mysql` ở cổng 3306 và thư mục `%LOCALAPPDATA%\WMS-Server` được giữ nguyên. Nếu database cũ đã có nghiệp vụ, chỉ nhập liệu trên bản mới sau khi có kế hoạch chuyển và đối chiếu dữ liệu.

## 1. Hiểu kết nối mới

| Thành phần | Địa chỉ / vị trí |
|---|---|
| MySQL cũ, giữ để phục hồi | `127.0.0.1:3306` |
| MySQL mới 8.0.46 | `127.0.0.1:3307`, database `wms_mysql` |
| Tệp MySQL mới | `%LOCALAPPDATA%\WMS-MySQL-8046` |
| Python máy chủ mới | `%LOCALAPPDATA%\WMS-Server-Python-Recovery` |
| Cấu hình và tệp WMS mới | `%LOCALAPPDATA%\WMS-Server-Recovery` |
| API WMS mới | `http://127.0.0.1:8000/api/v1` |
| Desktop | Chỉ kết nối API; không nhập cổng 3307 vào giao diện |

Luồng thực tế: **Desktop → API 8000 → MySQL 3307**. Trong hướng dẫn này MySQL mới và API chạy ở hai cửa sổ PowerShell thường, cần giữ mở khi sử dụng. Không cài thêm dịch vụ Windows hoặc thay dịch vụ MySQL80 cũ.

MySQL 8.0.11 không có collation `utf8mb4_0900_bin` và cột `INVISIBLE` mà WMS sử dụng. Hai tính năng có từ [8.0.17](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-17.html) và [8.0.23](https://dev.mysql.com/doc/refman/8.0/en/invisible-columns.html). Chọn **8.0.46**, phiên bản đã kiểm thử cho bộ WMS Windows; không chỉ kiểm tra rằng tên phiên bản bắt đầu bằng `8.0`.

## 2. Giữ lại bản cũ và sao lưu

Đóng WMS Desktop. Nếu máy chủ WMS cũ đang chạy, yêu cầu dừng và chờ `SERVER_STOPPED` trong cửa sổ máy chủ. Nếu trước đây chỉ mới setup lỗi, chưa từng thấy `SERVER_READY`, bỏ qua lệnh dừng này:

```powershell
$oldPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $oldPy -I -m apps.server.windows_standalone stop
```

Giữ MySQL cũ chạy để sao lưu. PowerShell thường, dùng đúng tài khoản Windows đã cài WMS:

```powershell
$ErrorActionPreference = 'Stop'
$backup = Join-Path $env:LOCALAPPDATA ('WMS-Backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $backup /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'Khong dat duoc quyen thu muc sao luu.' }
$oldHome = Join-Path $env:LOCALAPPDATA 'WMS-Server'
if (Test-Path $oldHome) { Copy-Item -LiteralPath $oldHome -Destination $backup -Recurse }
$oldDump = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe'
$sqlBackup = Join-Path $backup 'wms_mysql_3306.sql'
& $oldDump -h 127.0.0.1 -P 3306 -u root -p --single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF --databases wms_mysql "--result-file=$sqlBackup"
if ($LASTEXITCODE -ne 0) { throw 'Sao luu chua thanh cong. Giu nguyen ban cu va dung tai day.' }
Get-Item $sqlBackup | Select-Object Name,Length
Get-FileHash $sqlBackup -Algorithm SHA256
Write-Host "Da luu tai: $backup"
```

Nhập mật khẩu **root cũ** ở cổng 3306. Nếu MySQL cũ nằm ở đường dẫn khác, sửa `$oldDump`. Bản dump thành công là bản sao dự phòng; chưa phải bằng chứng đã khôi phục được dữ liệu. Không đăng tệp SQL hoặc `runtime.json` lên GitHub vì có thể chứa dữ liệu và bí mật.

## 3. Tải MySQL 8.0.46 ZIP chính thức

Tại [MySQL Community Server 8.0](https://dev.mysql.com/downloads/mysql/8.0.html), chọn Windows x64 → **ZIP Archive**, tệp `mysql-8.0.46-winx64.zip`, lưu vào Downloads. Không chọn gói Debug Binaries & Test Suite. Nếu trang mặc định đổi phiên bản, chọn Archives để tìm đúng bản.

PowerShell thường:

```powershell
$mysqlZip = Join-Path $env:USERPROFILE 'Downloads\mysql-8.0.46-winx64.zip'
if (!(Test-Path $mysqlZip)) { throw 'Chua thay ZIP MySQL trong Downloads.' }
Get-FileHash $mysqlZip -Algorithm MD5
```

Đối chiếu MD5 với trang tải chính thức. Với tệp 8.0.46 ở thời điểm lập hướng dẫn: `003f527d5df61b663ff191038cd676bd`. MD5 ở đây dùng kiểm tra tệp tải đầy đủ; dùng đường dẫn HTTPS chính thức và chữ ký GnuPG của nhà phát hành khi xác thực nguồn gói.

Nếu chạy `mysqld.exe` báo thiếu `VCRUNTIME140*.dll`/`MSVCP140.dll`, cài [Microsoft Visual C++ Redistributable x64 chính thức](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) rồi thử lại; không tải riêng DLL từ trang khác.

## 4. Tạo thư mục MySQL mới

Tiếp tục trong cùng PowerShell:

```powershell
$mysqlRoot = Join-Path $env:LOCALAPPDATA 'WMS-MySQL-8046'
if (Test-Path $mysqlRoot) { throw 'Thu muc MySQL moi da ton tai; khong ghi de. Kiem tra lan cai truoc.' }
if (Get-NetTCPConnection -State Listen -LocalPort 3307 -ErrorAction SilentlyContinue) {
  throw 'Cong 3307 dang duoc su dung. Khong dung/tat tien trinh khi chua xac dinh.'
}
New-Item -ItemType Directory -Path $mysqlRoot | Out-Null
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $mysqlRoot /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'Khong dat duoc quyen thu muc MySQL.' }
Expand-Archive -LiteralPath $mysqlZip -DestinationPath $mysqlRoot
$mysqlBase = Join-Path $mysqlRoot 'mysql-8.0.46-winx64'
$mysqld = Join-Path $mysqlBase 'bin\mysqld.exe'
$mysqlData = Join-Path $mysqlRoot 'data'
& $mysqld --no-defaults --version
if ($LASTEXITCODE -ne 0) { throw 'Chua chay duoc MySQL 8.0.46.' }
```

Phải thấy `8.0.46`. Mọi đường dẫn tạo mới nằm trong `WMS-MySQL-8046`; không trỏ `datadir` vào dữ liệu MySQL80 cũ.

## 5. Khởi tạo dữ liệu MySQL mới — chỉ một lần

```powershell
& $mysqld --no-defaults --initialize --console "--basedir=$mysqlBase" "--datadir=$mysqlData"
if ($LASTEXITCODE -ne 0) { throw 'Khoi tao MySQL chua thanh cong. Khong xoa data de thu lai.' }
```

Ghi lại mật khẩu tạm sau dòng **A temporary password is generated for root@localhost**. Đây là mật khẩu của **MySQL mới**, khác mật khẩu cũ. Không gửi dòng này hoặc ảnh chứa nó cho người khác. Chờ chương trình khởi tạo thoát về dấu nhắc PowerShell.

## 6. Tạo cấu hình và mở MySQL mới

```powershell
$mysqlIni = Join-Path $mysqlRoot 'my.ini'
$baseText = $mysqlBase.Replace('\','/')
$dataText = $mysqlData.Replace('\','/')
$iniText = @"
[mysqld]
basedir="$baseText"
datadir="$dataText"
port=3307
bind-address=127.0.0.1
mysqlx=0
character-set-server=utf8mb4
collation-server=utf8mb4_0900_ai_ci
"@
[System.IO.File]::WriteAllText($mysqlIni, $iniText, (New-Object System.Text.UTF8Encoding($false)))
& $mysqld "--defaults-file=$mysqlIni" --console
```

Chờ `ready for connections` và cổng `3307`. **Giữ cửa sổ này mở**, gọi là **cửa sổ A — MySQL**. Lệnh chạy máy chủ không trở về dấu nhắc là bình thường. Không dùng nút X để tắt khi WMS đang chạy.

## 7. Đặt mật khẩu root mới và kiểm tra cổng

Mở **PowerShell thường thứ hai**, gọi là **cửa sổ B**:

```powershell
$mysqlRoot = Join-Path $env:LOCALAPPDATA 'WMS-MySQL-8046'
$mysqlBin = Join-Path $mysqlRoot 'mysql-8.0.46-winx64\bin'
$mysql = Join-Path $mysqlBin 'mysql.exe'
$mysqlAdmin = Join-Path $mysqlBin 'mysqladmin.exe'
& $mysqlAdmin --no-defaults -h 127.0.0.1 -P 3307 -u root -p password
if ($LASTEXITCODE -ne 0) { throw 'Chua doi duoc mat khau root moi.' }
```

`Enter password` → nhập mật khẩu tạm của bước 5. `New password` và `Confirm new password` → nhập mật khẩu mới riêng, đủ mạnh, lưu ở nơi an toàn. Không đặt mật khẩu trực tiếp trong dòng lệnh.

```powershell
& $mysql --no-defaults -h 127.0.0.1 -P 3307 -u root -p -e "SELECT VERSION(), @@port; SHOW DATABASES LIKE 'wms_mysql';"
if ($LASTEXITCODE -ne 0) { throw 'Chua ket noi duoc MySQL moi.' }
```

Kết quả cần: **8.0.46**, **3307**, chưa có database `wms_mysql` trên instance này. Nếu vẫn thấy 8.0.11 hoặc cổng 3306, dừng và kiểm tra lại lệnh; chưa chạy setup WMS.

## 8. Nạp múi giờ vào MySQL mới

Tải **POSIX SQL** từ [trang timezone của MySQL](https://dev.mysql.com/downloads/timezones.html). Ví dụ tên gói hiện dùng là `timezone_2026e_posix_sql.zip`, lưu Downloads. Nếu tên phiên bản khác, sửa `$tzZip` cho đúng tệp đã tải.

Trong cửa sổ B:

```powershell
$tzZip = Join-Path $env:USERPROFILE 'Downloads\timezone_2026e_posix_sql.zip'
if (!(Test-Path $tzZip)) { throw 'Chua thay ZIP mui gio.' }
$tzDir = Join-Path $env:TEMP ('WMS-Timezones-' + [guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $tzZip -DestinationPath $tzDir
$tzFiles = @(Get-ChildItem -LiteralPath $tzDir -Recurse -File -Filter 'timezone_posix.sql')
if ($tzFiles.Count -ne 1) { throw 'Can dung mot tep timezone_posix.sql trong goi POSIX chinh thuc.' }
$tzSql = $tzFiles[0].FullName.Replace('\','/')
& $mysql --no-defaults -h 127.0.0.1 -P 3307 -u root -p mysql -e "source $tzSql"
if ($LASTEXITCODE -ne 0) { throw 'Nap mui gio chua thanh cong.' }
& $mysqlAdmin --no-defaults -h 127.0.0.1 -P 3307 -u root -p shutdown
if ($LASTEXITCODE -ne 0) { throw 'MySQL moi chua dung.' }
```

Chờ cửa sổ A báo tắt xong. Tại **cửa sổ A**, chạy lại đúng một lệnh:

```powershell
& $mysqld "--defaults-file=$mysqlIni" --console
```

Tại **cửa sổ B**, kiểm tra:

```powershell
& $mysql --no-defaults -h 127.0.0.1 -P 3307 -u root -p -e "SELECT VERSION(), @@port, CONVERT_TZ('2026-01-01 00:00:00','UTC','Asia/Ho_Chi_Minh') AS gio_viet_nam;"
```

Phải có `2026-01-01 07:00:00`, không phải `NULL`. Chỉ giải nén ZIP chưa phải đã nạp múi giờ; lệnh `source` ở trên thực hiện việc nạp.

## 9. Cài Python và tải bộ WMS đã sửa

Nếu `py -3.12 --version` chạy được, giữ Python đang có. Nếu chưa có, cài [Python 3.12.10 x64](https://www.python.org/downloads/release/python-31210/), chọn pip và Python Launcher. Đây là bản installer truyền thống trong hướng dẫn, không phải bản vá Python mới nhất. Đóng/mở lại cửa sổ B nếu vừa cài.

Tải `WMS-Windows-Standalone-20261018.1.zip` và `SHA256SUMS.txt` tại [release máy chủ đã sửa](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-windows-server.20261018.1). Kiểm tra:

```powershell
$wmsZip = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018.1.zip'
Get-FileHash $wmsZip -Algorithm SHA256
```

Đối chiếu với SHA256SUMS của **cùng release**. Nhấp phải ZIP → Extract All vào `Downloads\WMS-Windows-Standalone-20261018.1`. Trong đó phải có wheel `.whl` và `requirements-app-lock.txt`.

## 10. Cài môi trường WMS riêng

PowerShell thường, cửa sổ B:

```powershell
$ErrorActionPreference = 'Stop'
$bundle = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018.1'
$venv = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery'
if (Test-Path $venv) { throw 'Moi truong Recovery da ton tai; khong ghi de.' }
py -3.12 -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc Python venv.' }
$wmsPy = Join-Path $venv 'Scripts\python.exe'
& $wmsPy -m pip install --only-binary=:all: -r (Join-Path $bundle 'requirements-app-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cai thu vien that bai.' }
& $wmsPy -m pip install --no-deps (Join-Path $bundle 'wms_lan-0.1.0-py3-none-any.whl')
if ($LASTEXITCODE -ne 0) { throw 'Cai WMS that bai.' }
```

Không cần activate venv, không sửa ExecutionPolicy. Môi trường cũ `WMS-Server-Python` được giữ nguyên.

## 11. Tạo database và kết nối WMS đúng cổng 3307

```powershell
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome setup --mysql-port 3307 --api-port 8000
if ($LASTEXITCODE -ne 0) { throw 'Setup chua thanh cong. Khong sang buoc tao tai khoan.' }
```

Nhập mật khẩu **root mới** đã đặt ở bước 7. Phải thấy **SETUP_OK**. Công cụ tạo `wms_mysql`, user `wms_runtime`, schema, khóa MFA, các thư mục tệp và `runtime.json` trong home mới. Root chỉ dùng để chuẩn bị; API dùng tài khoản runtime có quyền giới hạn.

**Không tự sửa `runtime.json` và không chép cấu hình cũ sang.** `--mysql-port 3307` quyết định kết nối database khi setup; `--home $wmsHome` phải có trong mọi lệnh sau. Nếu bỏ `--home`, công cụ sẽ tìm bản cũ ở `WMS-Server`.

Nếu setup lỗi, giữ nguyên mọi tệp và database mới để kiểm tra; không xóa marker, không đổi migration thành `COMPLETE`, không chạy lại với cùng đích.

## 12. Tạo hai tài khoản quản trị

```powershell
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome admin --username admin.one --display-name 'Quan tri mot'
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc admin.one.' }
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome admin --username admin.two --display-name 'Quan tri hai'
if ($LASTEXITCODE -ne 0) { throw 'Chua tao duoc admin.two.' }
```

Mỗi người đặt mật khẩu WMS riêng 12–128 ký tự khi được hỏi. Đây là tài khoản đăng nhập ứng dụng, không phải MySQL root. Tạo đủ hai admin ban đầu trước khi tạo người dùng nghiệp vụ để thực hiện cơ chế người đề nghị/người phê duyệt.

## 13. Kiểm tra và chạy API, worker

```powershell
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome check
if ($LASTEXITCODE -ne 0) { throw 'Chua dat CHECK_OK.' }
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome run
```

Chờ **SERVER_READY**. Giữ cửa sổ B mở. Nếu cổng 8000 bị chiếm, xác định và dừng đúng máy chủ WMS cũ trước; không kết thúc tiến trình lạ bằng force.

Mở **PowerShell thường thứ ba — cửa sổ C**:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ready'
```

Cả hai phải trả HTTP thành công. Chỉ chuyển Desktop sau bước này; chưa thấy SERVER_READY thì chưa coi việc cài đặt hoàn tất.

## 14. Kết nối giao diện Desktop

Nếu chưa có Desktop, cài `WMS-Setup-0.1.0-efa4df60261a-x64.exe` từ [release giao diện](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-ui.20261018.1), đối chiếu SHA-256 của release. Bộ cài dùng chứng thư thử nghiệm; không phải chứng thư phát hành công khai được Windows tin cậy sẵn.

Đóng Desktop trước khi đổi cấu hình. Trong cửa sổ C:

```powershell
$clientDir = Join-Path $env:LOCALAPPDATA 'wms-lan'
$clientFile = Join-Path $clientDir 'client.json'
New-Item -ItemType Directory -Force -Path $clientDir | Out-Null
if (Test-Path $clientFile) {
  $saved = $clientFile + '.before-recovery-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
  Copy-Item -LiteralPath $clientFile -Destination $saved -ErrorAction Stop
  Write-Host "Cau hinh cu: $saved"
}
$clientJson = '{"api_url":"http://127.0.0.1:8000/api/v1","http_timeout_seconds":5}'
[System.IO.File]::WriteAllText($clientFile, $clientJson, (New-Object System.Text.UTF8Encoding($false)))
```

Mở WMS từ Start Menu, đăng nhập `admin.one` bằng mật khẩu ở bước 12. Thiết lập MFA theo giao diện bằng ứng dụng TOTP trên điện thoại. Người thứ hai làm tương tự với tài khoản riêng. Không đăng nhập bằng root MySQL.

Database mới chưa có kho nên danh sách kho trống là bình thường. Làm tiếp [bước 11–13 của hướng dẫn nghiệp vụ](WINDOWS_STANDALONE.md#bước-11-tạo-nhân-viên-và-cấp-quyền): cấp quyền, tạo danh mục/kho, kỳ đầu và chứng từ. Với lệnh `first-period`, vẫn dùng Python Recovery và thêm `--home $wmsHome` trước `first-period` như các lệnh bên trên; không dùng launcher/home mặc định cũ.

## 15. Mở lại mỗi ngày

**Cửa sổ A — mở MySQL mới:**

```powershell
$mysqlRoot = Join-Path $env:LOCALAPPDATA 'WMS-MySQL-8046'
$mysqld = Join-Path $mysqlRoot 'mysql-8.0.46-winx64\bin\mysqld.exe'
$mysqlIni = Join-Path $mysqlRoot 'my.ini'
& $mysqld "--defaults-file=$mysqlIni" --console
```

**Cửa sổ B — sau khi MySQL sẵn sàng:**

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery\Scripts\python.exe'
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome run
```

Chờ SERVER_READY rồi mở Desktop. Không chạy lại initialize/setup/admin hằng ngày.

## 16. Tắt đúng thứ tự và sao lưu bản mới

Đóng Desktop. Trong cửa sổ C:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python-Recovery\Scripts\python.exe'
$wmsHome = Join-Path $env:LOCALAPPDATA 'WMS-Server-Recovery'
& $wmsPy -I -m apps.server.windows_standalone --home $wmsHome stop
```

Chờ cửa sổ B hiện **SERVER_STOPPED**. Muốn sao lưu: lặp quy trình thư mục sao lưu riêng ở bước 2, nhưng dùng `mysqldump.exe` trong `WMS-MySQL-8046\mysql-8.0.46-winx64\bin`, cổng **3307**, mật khẩu root mới và sao chép home **WMS-Server-Recovery**. Giữ MySQL chạy đến khi dump thành công; không lấy bản sao bằng cách copy thư mục data lúc MySQL đang chạy.

Sau đó tắt MySQL mới:

```powershell
$mysqlAdmin = Join-Path $env:LOCALAPPDATA 'WMS-MySQL-8046\mysql-8.0.46-winx64\bin\mysqladmin.exe'
& $mysqlAdmin --no-defaults -h 127.0.0.1 -P 3307 -u root -p shutdown
if ($LASTEXITCODE -ne 0) { throw 'MySQL moi chua dung.' }
```

Chờ cửa sổ A báo `Shutdown complete`. Bản MySQL80 cũ ở 3306 vẫn được giữ nguyên. Muốn quay lại bản cũ chỉ thực hiện khi đã kiểm chứng bản đó hoạt động; nếu nó vẫn có setup-incomplete thì chưa thể chạy WMS trên bản đó.

## Các lỗi cần phân biệt

| Kết quả | Cách xử lý |
|---|---|
| `Access denied` / MySQL 1045 | Kiểm tra cổng và mật khẩu root cũ/mới; không ghi mật khẩu vào dòng lệnh. |
| `Unknown collation ...0900_bin` / MySQL 1273 | Đang trỏ vào MySQL quá cũ. Kiểm tra `SELECT VERSION(), @@port`. |
| MySQL 1064 ở DDL / `INVISIBLE` | Kiểm tra phiên bản; không sửa migration để bỏ ràng buộc. |
| `CONVERT_TZ` trả NULL | Nạp SQL timezone vào đúng 3307 rồi dừng/mở lại MySQL mới. |
| Thư mục/database/user đã tồn tại | Dừng. Công cụ không ghi đè hoặc tiếp tục tự động một setup dở dang. |
| `setup-incomplete.json` trong home mới | Gửi mã lỗi, phiên bản và danh sách tên bảng để xác định bước lỗi. Không gửi runtime.json. |
| `check/run` tìm bản cũ | Thiếu `--home $wmsHome`, hoặc đang dùng Python cũ. |
| Desktop báo mất kết nối | Kiểm tra A chạy 3307, B có SERVER_READY, API ready trả thành công, rồi kiểm tra client.json. |

Nền kiểm thử máy chủ: MySQL 8.0.46 và Windows Server 2022; xem [bằng chứng kiểm thử](../07_Kiem_tra/release/WINDOWS_MYSQL_RECOVERY_20261018.md). Không đồng nhất kiểm thử đó với việc đã chạy thành công trên máy Windows cụ thể của người dùng. Cách cài ZIP và khởi tạo theo [tài liệu MySQL](https://dev.mysql.com/doc/refman/8.0/en/windows-install-archive.html); mật khẩu root ẩn dùng [mysqladmin password](https://dev.mysql.com/doc/refman/8.0/en/mysqladmin.html).
