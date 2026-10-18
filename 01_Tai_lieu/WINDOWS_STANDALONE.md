# Cài WMS chạy độc lập trên Windows

Hướng dẫn cài mới WMS trên máy Windows x64: giao diện, API, sáu worker và MySQL cùng chạy trên một máy. Không cần Ubuntu, WSL, Docker, Git hoặc VS Code. Cần Internet trong lúc tải và cài thư viện; sau đó các nghiệp vụ nội bộ dùng máy chủ cục bộ.

Đây là **cài database mới**, không tự mang dữ liệu của máy Linux sang. Database mới có cấu trúc và danh mục quyền của WMS, chưa có tài khoản, kho hoặc chứng từ nghiệp vụ. Nếu cần dữ liệu WMS đang dùng, thực hiện một đợt sao lưu và phục hồi riêng có đối chiếu, trước khi nhập liệu trên Windows.

Mô hình kết nối: **WMS Desktop → API tại 127.0.0.1:8000 → MySQL tại 127.0.0.1:3306**. Desktop không kết nối trực tiếp MySQL. Máy chủ API và sáu worker chạy trong cửa sổ riêng; MySQL chạy bằng dịch vụ Windows.

## Bước 1 Chuẩn bị máy và hiểu các cửa sổ lệnh

1. Vào Settings → System → About, kiểm tra máy dùng Windows x64. Hướng dẫn không dành cho Windows 32 bit hoặc ARM64.
2. Dùng tài khoản Windows sẽ vận hành WMS. Cần quyền Administrator khi cài MySQL và khởi động lại dịch vụ; các bước WMS và Python dùng tài khoản thường này.
3. Bật ngày giờ tự động trên Windows và điện thoại để mã MFA khớp giờ. Chuẩn bị ứng dụng xác thực TOTP trên điện thoại.
4. Dành dung lượng cho phần mềm, database và bản sao lưu. Với máy thực hành, khuyến nghị 8 GB RAM và ít nhất 20 GB trống; đây không phải số liệu kiểm thử tải.
5. Mở Start → gõ **Windows PowerShell**. Chỉ chọn **Run as administrator** ở bước ghi rõ cần quyền quản trị. Sao chép từng khối lệnh, chờ xong rồi mới sang khối tiếp theo. Không chép dấu nhắc `PS C:\...>`.

Các lệnh bên dưới chạy trực tiếp trong PowerShell; không cần RTK. Mật khẩu được hỏi riêng và không hiện ký tự khi gõ là bình thường.

## Bước 2 Cài MySQL Server

Mở [MySQL Installer chính thức](https://dev.mysql.com/downloads/windows/installer/8.0.html), tải `mysql-installer-web-community-8.0.46.0.msi`. Tên installer có chữ x86/32-bit nhưng có thể cài Server x64. Chọn **Server only** hoặc **Custom → MySQL Server 8.0 x64**; chỉ cài Workbench là chưa đủ.

Trong trình cấu hình:

1. Chọn Development Computer; bật TCP/IP, port **3306**.
2. Máy dùng độc lập: bỏ chọn mở port trong Windows Firewall để truy cập từ máy khác.
3. Giữ xác thực mạnh; đặt mật khẩu **MySQL root** riêng và lưu ở nơi an toàn.
4. Đặt tên dịch vụ **MySQL80**, bật tự chạy cùng Windows; hoàn tất Execute → Finish.
5. Nếu được yêu cầu Visual C++ Runtime, cài từ liên kết Microsoft do trình cài đặt cung cấp. [Yêu cầu cài MySQL trên Windows](https://dev.mysql.com/doc/refman/8.0/en/windows-installation.html).

PowerShell thường — kiểm tra dịch vụ và chương trình:

```powershell
Get-Service MySQL80
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
& $mysql --version
& $mysql -h 127.0.0.1 -P 3306 -u root -p -e "SELECT VERSION();"
```

Kết quả cần có dịch vụ `Running`, phiên bản `8.0.x`, và đăng nhập MySQL thành công. Đây là mật khẩu root vừa đặt, không phải mật khẩu Windows hay tài khoản WMS. Nếu cài đường dẫn khác, sửa biến `$mysql` cho đúng.

## Bước 3 Nạp múi giờ cho MySQL

Windows cần gói SQL múi giờ do MySQL cung cấp. Tải bản **POSIX** trên [trang múi giờ chính thức](https://dev.mysql.com/downloads/timezones.html). Bộ lệnh dưới đây cố định gói đã kiểm tra; nếu nguồn tải thay đổi, đối chiếu trang chính thức thay vì dùng tệp SQL không rõ nguồn.

PowerShell thường:

```powershell
# Duong dan file ZIP da tai
$tzZip = "C:\Users\tkien\Downloads\timezone_2026e_posix_sql.zip"

# Thu muc se giai nen
$tzDir = "C:\Users\tkien\Downloads\WMS_Timezones"

# Kiem tra file ZIP
Test-Path $tzZip

# Giai nen file ZIP
Expand-Archive -LiteralPath $tzZip -DestinationPath $tzDir -Force

# Tim file SQL
Get-ChildItem $tzDir -Recurse -Filter "*.sql"
```

Mở một PowerShell **Run as administrator**, khởi động lại dịch vụ để MySQL dùng dữ liệu múi giờ vừa nạp:

```powershell
Restart-Service MySQL80
Get-Service MySQL80
```

Quay lại PowerShell thường, kiểm tra:

```powershell
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
$tzQuery = "SELECT CONVERT_TZ('2026-01-01 00:00:00'," +
  "'UTC','Asia/Ho_Chi_Minh') AS gio_viet_nam;"
& $mysql -h 127.0.0.1 -P 3306 -u root -p -e $tzQuery
```

Phải trả `2026-01-01 07:00:00`, không phải `NULL`. Thời điểm trên chỉ dùng kiểm tra múi giờ, không tạo chứng từ hoặc đặt ngày hệ thống.

## Bước 4 Cài Python cho phần máy chủ

Từ [Python 3.12.10 chính thức](https://www.python.org/downloads/release/python-31210/), chọn **Windows installer 64-bit**. Chạy installer, chọn **Add python.exe to PATH**, giữ pip và Python Launcher, rồi Install Now. Đóng và mở lại PowerShell.

```powershell
py -3.12 --version
py -3.12 -c "import struct; print(struct.calcsize('P') * 8)"
```

Kết quả cần là Python `3.12.x` và `64`. Bản 3.12.10 là bản installer truyền thống dùng trong hướng dẫn; Python đã có các bản vá bảo mật mới hơn. Khi đổi runtime, kiểm tra lại bộ phụ thuộc trước khi đưa vào vận hành. Desktop có Python đóng gói riêng, còn server cần Python ở bước này.

## Bước 5 Tải bộ máy chủ WMS

Tải [bộ Windows Standalone](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-windows-server.20261018), gồm `WMS-Windows-Standalone-20261018.zip` và tệp SHA-256 kèm theo. Trong PowerShell:

```powershell
$wmsZip = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018.zip'
Get-FileHash $wmsZip -Algorithm SHA256
```

Đối chiếu với SHA-256 ở release. Nhấp phải ZIP → Extract All; đặt thư mục giải nén là `Downloads\WMS-Windows-Standalone-20261018`. Thư mục này phải chứa `requirements-app-lock.txt`, tệp `wms_lan-0.1.0-py3-none-any.whl` và hướng dẫn.

PowerShell thường — tạo môi trường cài mới:

```powershell
$wmsBundle = Join-Path $env:USERPROFILE 'Downloads\WMS-Windows-Standalone-20261018'
$wmsVenv = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python'
if (Test-Path $wmsVenv) { throw 'Moi truong da ton tai. Khong ghi de.' }
py -3.12 -m venv $wmsVenv
if ($LASTEXITCODE -ne 0) { throw 'Tao moi truong Python that bai.' }
$wmsPy = Join-Path $wmsVenv 'Scripts\python.exe'
& $wmsPy -m pip install --only-binary=:all: -r "$wmsBundle\requirements-app-lock.txt"
if ($LASTEXITCODE -ne 0) { throw 'Cai thu vien that bai. Chua sang buoc tiep.' }
& $wmsPy -m pip install --no-deps "$wmsBundle\wms_lan-0.1.0-py3-none-any.whl"
if ($LASTEXITCODE -ne 0) { throw 'Cai WMS Server that bai.' }
& $wmsPy -I -m apps.server.windows_standalone --help
```

Nếu mất mạng ở pip, sửa kết nối rồi chạy lại hai lệnh pip với cùng biến đường dẫn; không tạo lại hoặc xóa database. Không cần kích hoạt venv hay đổi ExecutionPolicy. Luôn dùng `$wmsPy` để tránh chạy nhầm Python.

## Bước 6 Tạo database WMS mới

PowerShell thường:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $wmsPy -I -m apps.server.windows_standalone setup
```

Nhập mật khẩu **MySQL root** khi được hỏi. Công cụ tạo database `wms_mysql`, tài khoản `wms_runtime`, schema, quyền nghiệp vụ, khóa MFA và ba thư mục tệp. Tài khoản chạy ứng dụng chỉ có quyền dữ liệu và EXECUTE; không dùng root để vận hành hằng ngày. Mật khẩu root không được lưu.

Chỉ sang bước tiếp theo khi thấy **SETUP_OK**. Công cụ từ chối nếu đã có database, user hoặc thư mục đích; không xóa hoặc ghi đè dữ liệu để cài lại. Nếu xuất hiện `setup-incomplete.json`, giữ nguyên database và cấu hình để kiểm tra, chưa mở ứng dụng nhập liệu.

Cấu hình riêng nằm tại `%LOCALAPPDATA%\WMS-Server\runtime.json`. Tệp chứa mật khẩu database và khóa MFA, được giới hạn quyền truy cập. Không đưa tệp này lên GitHub, gửi nhóm hoặc sửa khóa MFA tùy ý. Bộ cài chỉ khởi tạo hệ thống mới, không chứa dữ liệu kinh doanh từ máy Linux.

## Bước 7 Tạo hai quản trị viên ban đầu

Tạo cả hai tài khoản trước khi thêm nhân viên thông thường. Mỗi quản trị viên đặt mật khẩu riêng, dài 12–128 ký tự, nhập lại để xác nhận.

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $wmsPy -I -m apps.server.windows_standalone admin `
  --username admin.one --display-name 'Quan tri mot'
& $wmsPy -I -m apps.server.windows_standalone admin `
  --username admin.two --display-name 'Quan tri hai'
```

Cần thấy thông báo đã tạo SYSADMIN cho từng lệnh. Đây là hai người quản trị độc lập để yêu cầu và duyệt quyền; không dùng một tài khoản chung cho cả nhóm. Không có mật khẩu WMS mặc định. SYSADMIN chưa có quyền thao tác kho.

## Bước 8 Kiểm tra và bật máy chủ

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $wmsPy -I -m apps.server.windows_standalone check
if ($LASTEXITCODE -ne 0) { throw 'May chu chua san sang.' }
& $wmsPy -I -m apps.server.windows_standalone run
```

Chờ **SERVER_READY**. Giữ cửa sổ này mở; nó quản lý API cùng các worker outbox, import, export, print và hai worker dọn tệp. Không mở thêm một bản server trùng cấu hình.

Mở PowerShell thường thứ hai:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ready'
```

Kết quả lần lượt `status: ok` và `status: ready`. `ready` kiểm tra database/schema; việc xử lý import, export và PDF còn phụ thuộc sáu worker đang chạy. Nhật ký từng tiến trình ở `%LOCALAPPDATA%\WMS-Server\logs`.

## Bước 9 Cài giao diện WMS và kết nối vào máy này

Tải [bộ Desktop ngày 18 tháng 10](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/releases/tag/v0.1.0-ui.20261018.1), chọn `WMS-Setup-0.1.0-efa4df60261a-x64.exe`. Bộ cài đã có logo màu mới. Kiểm tra tệp trong Downloads:

```powershell
$wmsExe = Join-Path $env:USERPROFILE 'Downloads\WMS-Setup-0.1.0-efa4df60261a-x64.exe'
$expected = '55d285129a625ebd8d1c2cd3aa66af9c471018a29f31c681467c66c6b782939b'
if ((Get-FileHash $wmsExe -Algorithm SHA256).Hash -ne $expected) {
  throw 'Sai SHA256 bo cai Desktop.'
}
Start-Process -FilePath $wmsExe -Wait
```

Làm theo installer, rồi đóng WMS nếu nó tự mở. Đây là prerelease với chứng thư **TEST ONLY**, chưa có chứng thư phát hành công khai được Windows tin cậy. Nếu chính sách máy chặn, nhờ người quản trị kiểm tra nguồn và hash; không tắt Defender để ép chạy.

Tạo cấu hình cho máy mới bằng PowerShell thường:

```powershell
$wmsClientDir = Join-Path $env:LOCALAPPDATA 'wms-lan'
New-Item -ItemType Directory -Force $wmsClientDir | Out-Null
$wmsClient = Join-Path $wmsClientDir 'client.json'
if (Test-Path $wmsClient) { throw 'client.json da ton tai. Sao luu va kiem tra truoc khi sua.' }
$wmsConfig = '{"api_url":"http://127.0.0.1:8000/api/v1","http_timeout_seconds":5}'
[IO.File]::WriteAllText($wmsClient, $wmsConfig, [Text.UTF8Encoding]::new($false))
```

Mở shortcut **WMS Desktop** mới ở Start hoặc Desktop. Nếu taskbar đang ghim bản cũ, bỏ ghim shortcut cũ rồi ghim bản vừa cài. Không nhập port 3306 hay mật khẩu MySQL vào giao diện đăng nhập WMS.

## Bước 10 Đăng nhập và bật MFA

1. Đăng nhập `admin.one` bằng mật khẩu đã đặt ở bước 7.
2. Mở phần tài khoản/MFA, chọn **Thiết lập MFA**, xác nhận mật khẩu. Thêm mã QR hoặc khóa được cấp vào ứng dụng TOTP trên điện thoại.
3. Nhập mã 6 số và chọn **Xác nhận bật MFA**. Nếu vừa dùng mã đó, chờ mã mới trước khi đăng nhập lại; hệ thống từ chối dùng lại mã đã xác nhận.
4. Đăng xuất và làm tương tự cho `admin.two`, bằng thiết bị/tài khoản xác thực của người quản trị thứ hai.

Đăng nhập được nhưng chưa thấy kho là bình thường ở hệ thống mới. Chưa tạo kho và chưa cấp quyền kho thì không có dữ liệu để hiển thị.

## Bước 11 Tạo nhân viên và cấp quyền

1. `admin.one` → **Tài khoản & phân quyền** → tạo người quản lý danh mục, chẳng hạn tên đăng nhập riêng của thành viên phụ trách.
2. Lập yêu cầu cấp vai trò **MASTER_DATA**, phạm vi **GLOBAL**, nêu lý do.
3. `admin.two` đăng nhập/MFA → tải yêu cầu chờ → kiểm tra và duyệt. Người yêu cầu không tự duyệt; người được cấp không tự yêu cầu hoặc duyệt quyền cho chính mình.
4. Người quản lý danh mục đăng nhập, tải lại phiên, tạo dữ liệu nền ở bước 12.
5. Sau khi có kho, hai quản trị viên cấp các vai trò nghiệp vụ theo phạm vi **WAREHOUSE** và đúng kho đó.

Các vai trò thường dùng: BUYER lập đơn mua; SELLER lập đơn bán; RECEIVER nhận hàng; PICKER soạn/xuất; WAREHOUSE_MANAGER quản lý kho; CONTROLLER và DIRECTOR kiểm soát/duyệt theo chính sách; AUDITOR đọc và kiểm tra. Một người có thể có nhiều vai trò khi phù hợp nhưng người lập và người duyệt chứng từ vẫn phải độc lập theo quy tắc hệ thống.

## Bước 12 Tạo danh mục và kỳ kho đầu tiên

Người có MASTER_DATA vào **Danh mục sản phẩm**, tạo lần lượt: kho → vị trí → đơn vị tính và quy đổi → sản phẩm → nhà cung cấp/khách hàng/chủ hàng theo nhu cầu. Dùng mã, tên và hệ số thật; cấu hình lô/serial theo cách quản lý hàng. Tải lại sau khi lưu để kiểm tra.

Với kho mới chưa có kỳ hoặc lịch sử ghi sổ, mở PowerShell thường trên máy chủ:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
$maKho = Read-Host 'Ma kho vua tao'
$tuNgay = Read-Host 'Tu ngay YYYY-MM-DD'
$denNgay = Read-Host 'Den ngay YYYY-MM-DD'
$lyDo = Read-Host 'Ly do tao ky dau tien'
& $wmsPy -I -m apps.server.windows_standalone first-period `
  --warehouse-code $maKho --starts-on $tuNgay --ends-on $denNgay --reason $lyDo
```

Chọn khoảng ngày nghiệp vụ đã thống nhất. Công cụ ghi audit và từ chối tạo lại kỳ đầu cho kho có kỳ/lịch sử. Các kỳ tiếp theo dùng màn hình **Kỳ kho**, không dùng lệnh trên để mở lại kỳ đã khóa.

## Bước 13 Dùng các luồng nghiệp vụ

**Nhập hàng:** chọn kho → lập đơn mua khi nghiệp vụ có đơn nguồn → hoàn thiện và gửi duyệt → người có quyền duyệt xử lý hộp thư → lập phiếu nhận gắn đơn → nhập đúng hàng, lượng, vị trí, lô/serial → duyệt và ghi sổ theo trạng thái được phép. Kiểm tra tồn và lịch sử sau khi hoàn tất.

**Tồn đầu kỳ:** chỉ dùng để khởi tạo kho phù hợp điều kiện hệ thống, có biên bản và người duyệt. Không nhập lặp tồn đầu kỳ để tăng số dư đã vận hành.

**Xuất hàng:** lập đơn bán/nhu cầu → duyệt → giữ hàng, soạn/đóng kiện nếu quy trình dùng → lập/kiểm tra phiếu xuất → hoàn tất theo quyền. Lượng khả dụng có thể thấp hơn tồn vật lý vì giữ hàng, cách ly hoặc khóa kiểm kê.

**Kiểm kê và báo cáo:** chọn kho/phạm vi/ngày đúng → tải số liệu; kiểm kê cần luồng đếm, duyệt và điều chỉnh. Báo cáo CSV/XLSX và in PDF cần server cùng worker còn chạy. Khi tạo tệp, theo dõi trạng thái đến hoàn tất rồi tải/xem trước.

**In chứng từ:** chọn mẫu, khổ giấy và chứng từ → tạo PDF → xem trước → lưu PDF hoặc gửi máy in đã cài driver Windows. Không coi một yêu cầu đang chờ là đã in thành công.

**Mất phản hồi khi ghi:** xem trạng thái/tra ACK hoặc dùng luồng phục hồi của ứng dụng. Không bấm tạo phiếu mới để thay một yêu cầu chưa rõ kết quả. Xem thêm [hướng dẫn nghiệp vụ đầy đủ](USER_GUIDE.md).

## Bước 14 Bật và tắt mỗi ngày

**Bật:** MySQL80 tự chạy khi Windows khởi động. Mở PowerShell thường, chạy hai dòng sau; chờ SERVER_READY rồi mở WMS Desktop.

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $wmsPy -I -m apps.server.windows_standalone run
```

**Tắt:** hoàn thành/lưu thao tác, thoát WMS Desktop bình thường. Trong cửa sổ server nhấn **Ctrl+C một lần**, hoặc chạy ở PowerShell khác:

```powershell
$wmsPy = Join-Path $env:LOCALAPPDATA 'WMS-Server-Python\Scripts\python.exe'
& $wmsPy -I -m apps.server.windows_standalone stop
```

Chờ cửa sổ server in **SERVER_STOPPED** rồi mới đóng cửa sổ hoặc tắt Windows. Không bấm X cửa sổ server khi đang làm việc. Launcher không ép kill tiến trình đang hoàn tất giao dịch; nếu chờ lâu, kiểm tra logs. MySQL có thể tiếp tục chạy như dịch vụ Windows.

Nút **Tải lại** trong Desktop khởi động lại giao diện của bản đang cài, không tải bản phát hành mới và không thay việc bật server.

## Bước 15 Sao lưu trước khi dùng dữ liệu quan trọng

Dừng Desktop và server theo bước 14, giữ MySQL80 đang chạy. Bản sao lưu phải có **database + runtime.json và khóa MFA + các thư mục import/export/print**, đồng thời giữ bộ cài/wheel đúng phiên bản. Không chỉ chép thư mục mã nguồn.

PowerShell thường — tạo thư mục backup riêng, không ghi đè:

```powershell
$backup = Join-Path $env:LOCALAPPDATA ('WMS-Backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory $backup | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $backup /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) { throw 'Chua bao ve duoc thu muc backup.' }
$dump = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe'
& $dump -h 127.0.0.1 -P 3306 -u root -p --single-transaction `
  --routines --triggers --events --hex-blob --set-gtid-purged=OFF `
  --databases wms_mysql --result-file="$backup\wms_mysql.sql"
if ($LASTEXITCODE -ne 0) { throw 'Backup database that bai. Khong coi day la ban sao luu hoan tat.' }
Copy-Item (Join-Path $env:LOCALAPPDATA 'WMS-Server') "$backup\WMS-Server" -Recurse
Get-FileHash "$backup\wms_mysql.sql" -Algorithm SHA256
Write-Host "Da sao luu tai $backup"
```

Sao chép bản backup sang thiết bị lưu trữ được bảo vệ; bản chỉ nằm cùng ổ chưa bảo vệ được khi hỏng ổ. Thử phục hồi trên database/máy tách biệt trước khi dựa vào bản backup. Phục hồi cần tạo lại user runtime với thông tin phù hợp và xử lý DEFINER của trigger/routine; không chạy setup lên database đã phục hồi hoặc đổi khóa MFA. Dữ liệu MySQL trên Linux không tự đồng bộ với bản Windows.

## Tra lỗi thường gặp

| Hiện tượng | Việc cần làm |
|---|---|
| Không nhận lệnh py | Đóng/mở PowerShell sau cài Python; kiểm tra Python Launcher và bản x64 3.12. |
| Access denied for root | Kiểm tra mật khẩu MySQL root và port; không nhập mật khẩu Windows. |
| CONVERT_TZ trả NULL | Làm lại bước 3, kiểm tra import thành công và restart MySQL80. |
| SETUP báo đã tồn tại | Không xóa database hoặc cấu hình để thử lại. Nếu đã cài thành công, dùng check/run. |
| Có setup-incomplete.json | Dừng thiết lập; kiểm tra quyền root, log MySQL, dung lượng. Giữ nguyên dữ liệu để xử lý có kiểm soát. |
| API không lên hoặc port đã dùng | Chỉ chạy một launcher; kiểm tra port 8000 và logs/api.log. |
| Không thấy kho | Hoàn thành tạo danh mục và cấp quyền WAREHOUSE, sau đó đăng nhập/tải lại phiên. |
| MFA sai | Đồng bộ giờ máy và điện thoại, dùng mã mới, chờ hết khóa nếu đã thử sai liên tiếp. |
| PDF hoặc xuất tệp cứ chờ | Cửa sổ server phải còn chạy; kiểm tra logs của print/export và trạng thái tác vụ. |
| Giao diện/logo còn cũ | Mở shortcut mới, bỏ ghim bản cũ rồi ghim lại; không xóa dữ liệu cá nhân. |
| Đóng/mở Windows lại thì app mất kết nối | MySQL là dịch vụ tự chạy; API/worker vẫn cần mở bằng lệnh run ở bước 14. |

## Phạm vi kiểm chứng

Xem [bằng chứng kiểm thử máy chủ Windows](../07_Kiem_tra/release/WINDOWS_SERVER_20261018.md). Bộ này là phương án cài thủ công và chạy server trong phiên đăng nhập Windows; chưa tự đăng ký API/worker thành Windows Service. Kiểm thử trên Windows Server 2022 không thay thế nghiệm thu Windows 10/11 trên thiết bị của người dùng, máy in hoặc phục hồi sau mất điện.
