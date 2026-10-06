# B23 — Build, ký và kiểm thử Windows

**Trạng thái 06/10/2026: đã build/ký thử và cài bộ EXE native thành công trên VM Windows Server 2022.** Commit `d9b547184626`, [workflow bằng chứng](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37464123861), [báo cáo](../../07_Kiem_tra/NATIVE_VM_2026_10_06.md). Chữ ký dùng chứng thư TEST ONLY tạo trong VM, SHA-256/RFC3161 và verify đạt; không phải chứng thư phát hành công khai. Windows 10/11, upgrade với API thật, DPI và máy in/quét vẫn cần nghiệm thu riêng.

## Smart App Control và cảnh báo tải của Edge

Bản tải `97d4c510dab8` dùng chứng thư tự ký **InternTechLead TEST ONLY**. Máy VM đã thêm
chứng thư này vào trust store phục vụ kiểm thử; điều đó không cấp uy tín nhà phát hành trên máy nhận.
Ảnh báo lỗi từ máy người dùng xác nhận Smart App Control chặn bộ cài trước khi WMS chạy.
Edge đồng thời cảnh báo file ít lượt tải; đây là cơ chế reputation riêng.

Để phát hành trực tiếp: cần chứng thư Code Signing từ CA được Windows tin cậy, xác minh danh tính
nhà phát hành, ký lại bộ cài cùng mọi native dependency và kiểm tra trên Windows 11 có Smart App Control.
Chữ ký chính thức không bảo đảm Edge ngừng cảnh báo ngay. Không coi đổi tên file, đóng ZIP hay
checksum là cách sửa chữ ký. Tham khảo [Microsoft Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
và [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

Xem [thiết lập ký chính thức](PUBLIC_SIGNING.md). Chưa có chứng thư chính thức; bản sửa quy trình
ký không tự biến bộ EXE cũ thành bản được Windows tin cậy.

## Chuẩn bị máy build

- Windows x64, CPython **3.12 x64** từ python.org, có launcher `py` và Tcl/Tk, Git; PowerShell 5.1 trở lên. Máy nhận bộ cài không cần Python/Git.
- Inno Setup **6.7.3**, kiểm tra chữ ký nhà phát hành trước khi cài. Workflow tải đúng release và yêu cầu chữ ký hợp lệ `Pyrsys B.V.`. [Hướng dẫn xác minh chính thức](https://jrsoftware.org/isdl-verify.php).
- Khi ký: Windows SDK `signtool.exe`, chứng thư Code Signing còn hiệu lực trong `Cert:\CurrentUser\My` hoặc `Cert:\LocalMachine\My`, có private key/token đang truy cập được. Không xuất PFX hoặc đưa password/private key vào repo/chat. Token phần cứng có thể yêu cầu PIN tại máy ký.
- Checkout sạch commit B23 đã review hoặc commit tích hợp có B23. Không build từ checkout còn thay đổi. Trên Windows dùng clone/worktree Windows riêng, không chạy venv Linux trên phân vùng dùng chung.
- Cập nhật server chứa handshake B23 trước khi mở client mới. B19/B20, PostgreSQL 001–024 và SQLite 001–003 là dependency; không phát sinh migration mới.

`requirements-build-lock.txt` khóa 22 wheel cùng SHA-256 cho CPython 3.12 / Windows AMD64, bao gồm runtime desktop, PyInstaller 6.22.3 và hooks. Script tạo venv riêng dưới `build/`; không sửa venv đang dùng. Tk/Python lấy từ interpreter máy build, được ghi phiên bản trong smoke; chưa cam kết binary reproducibility giữa các bản patch Python/Windows SDK khác nhau.

## Build có ký

Chạy tại gốc checkout trong PowerShell. Thay đường dẫn SDK và thumbprint bằng giá trị thật; thumbprint không phải private key.

```powershell
.\packaging\windows\Build.ps1 `
  -ISCC 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
  -CertificateThumbprint '<40-hex-thumbprint>' `
  -CertificateStore CurrentUser `
  -SignTool 'C:\Program Files (x86)\Windows Kits\10\bin\<SDK-version>\x64\signtool.exe'
```

Script ký `WMS.exe`, `WMSHelper.exe` bằng SHA-256/RFC3161; duyệt mọi EXE/DLL/PYD, giữ chữ ký nhà cung cấp đang hợp lệ, ký file chưa ký và dừng nếu chữ ký có sẵn không hợp lệ. Manifest chứa hash **sau ký**. Inno Setup ký cả installer, bản sao setup tạm và uninstaller; kiểm thử cài kiểm lại toàn bộ native dependency và chữ ký/timestamp của uninstaller. Timestamp mặc định `http://timestamp.digicert.com` theo [hướng dẫn DigiCert](https://knowledge.digicert.com/tutorials/ev-authenticode-using-signtool) và [Microsoft SignTool](https://learn.microsoft.com/windows/win32/seccrypto/signtool); SDK trên VM từ chối endpoint HTTPS cũ. RFC3161 timestamp có chữ ký được xác minh bằng `signtool verify /pa /all /tw` và bắt buộc có `TimeStamperCertificate`; không thay TLS của API WMS. Có thể truyền `-TimestampUrl` HTTP(S) của dịch vụ được tổ chức chấp nhận. Lỗi ký, timestamp hoặc verify làm build thất bại, không âm thầm xuất unsigned.

Chứng thư tự ký/TEST ONLY mặc định bị từ chối; chỉ VM kiểm thử cách ly được truyền `-AllowTestCertificate`. Xác minh chain trên máy build không thay kiểm chứng public trust trên máy Windows sạch.

Build thử không ký phải chỉ định rõ:

```powershell
.\packaging\windows\Build.ps1 -Unsigned -ISCC 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

Đầu ra dự kiến `dist\windows-0.1.0-<commit12>\`:

- `WMS-Setup-0.1.0-<commit12>-x64.exe`: bộ cài per-user, không cần quyền admin.
- `WMS-0.1.0-<commit12>-x64.zip`: bundle cùng phiên bản.
- `manifest.json`, `SHA256SUMS.txt`, `frozen-smoke.json`, `Test-Install.ps1`, `Rollback.ps1`.
- Bundle có inventory/hash/size, commit, version, protocol, cache maximum, trạng thái ký; `dependencies.json`, license notices, CA roots, SQL cache, Tk và PDFium/Pillow/font tiếng Việt.

Không dùng thư mục build lỗi làm release. Nếu build thất bại, giữ log và đổi tên thư mục output lỗi trước khi chạy lại; script từ chối ghi đè output cùng commit. Hash chỉ chứng minh nội dung khớp bản tham chiếu; lấy hash/thumbprint từ nguồn phát hành đã xác thực. Manifest tự thân không thay chữ ký. Bản unsigned chỉ dùng kiểm thử, có thể bị Windows cảnh báo. Ký hợp lệ không bảo đảm SmartScreen bỏ cảnh báo ngay.

`Build.ps1` chạy helper từ `%TEMP%` và xóa PYTHONPATH trong bước smoke để tránh vô tình lấy source thay tài nguyên frozen. [PyInstaller giải thích sys.executable của ứng dụng frozen](https://pyinstaller.org/en/stable/runtime-information.html); vì vậy in Windows dùng console helper riêng, không gọi `WMS.exe -m ...`.

## Cấu hình và dữ liệu người dùng

Mỗi phiên bản cài dưới `%LOCALAPPDATA%\Programs\WMS\0.1.0-<commit12>`. Nháp, journal và device identity ở `%LOCALAPPDATA%\wms-lan`; có thể đặt `WMS_LOCAL_DATA_DIR` ngoài thư mục cài. Giữ nguyên đường dẫn này và URL server khi upgrade để dùng đúng partition hiện có.

Tạo `client.json` trong thư mục dữ liệu (không sửa file dưới thư mục cài):

```json
{
  "api_url": "https://wms.example.internal/api/v1",
  "ca_file": "company-ca.pem",
  "http_timeout_seconds": 5
}
```

Copy public CA chain vào `company-ca.pem` cùng thư mục, hoặc bỏ `ca_file` nếu server dùng CA được Python trust store tin cậy. Cấu hình chỉ chấp nhận ba trường trên; không chứa credential DB/password/token. Biến `WMS_API_URL`, `WMS_CA_FILE`, `WMS_HTTP_TIMEOUT_SECONDS` ưu tiên hơn file. LAN bắt buộc HTTPS; HTTP chỉ cho loopback. CA tùy chỉnh phải có SAN/hostname và chain đúng, không tắt TLS verification.

Entrypoint luôn bật compatibility gate dù biến môi trường cố tắt. `GET /api/v1/health` và `/ready` thành công trả:

```text
X-WMS-API-Protocol: 1
X-WMS-Recovery-Protocol: lookup-v1,send-v1
```

Client kiểm tra trước login/MFA và mỗi HTTP mutation (gồm lookup phục hồi); thiếu hoặc lệch protocol thì chặn, giữ dữ liệu nháp/pending. Endpoint/body Health giữ nguyên. Recovery ACK vẫn có proof/hash B19, handshake không thay kiểm tra ACK. Khi mạng đứt/chứng chỉ sai, không tự retry lệnh chưa rõ kết quả.

Trước khi tạo shell, client khóa application và kiểm tra cache read-only: không mở cache revision >3 hoặc hỏng; không migrate/downgrade trong installer. Migration v1/v2 sang v3, backup và chuyển SENDING→UNKNOWN thực hiện bởi LocalStore B19 lúc mở đúng partition. Khi báo lỗi, giữ nguyên dữ liệu và bản sao điều tra; không xóa DB, không khôi phục backup cũ để né UNKNOWN.

## Cài mới và nâng cấp

Dùng tài khoản thử nghiệm user thường, tên/đường dẫn có tiếng Việt. Đóng WMS bình thường; installer dùng named mutex để chặn cài/gỡ khi app còn chạy. Không kill tiến trình để cài.

```powershell
.\packaging\windows\Test-Install.ps1 `
  -Installer 'D:\Release\WMS-Setup-0.1.0-<commit12>-x64.exe' `
  -ExpectedSha256 '<64-hex-tu-kenh-tin-cay>' `
  -ExpectedSigner '<40-hex-thumbprint>' `
  -VersionDirectory "$env:LOCALAPPDATA\Programs\WMS\0.1.0-<commit12>"
```

Chỉ với bản thử unsigned, thay `-ExpectedSigner ...` bằng `-AllowUnsigned`. Script xác minh trước khi thực thi installer, chụp hash tất cả file dữ liệu trước/sau cài, yêu cầu inventory không đổi, chạy cache preflight và frozen self-test. Đây là kiểm thử cài/bundle, chưa phải nghiệp vụ với API thật.

Để kiểm thử upgrade có baseline, thêm `-PreviousInstaller <path>` và `-PreviousSha256 <hash>`; script cài baseline, dừng cho chuẩn bị dữ liệu rồi mới upgrade. Baseline và target dùng cùng signer (hoặc cùng unsigned test policy). Nếu chưa có baseline đóng gói, build hai commit review riêng có hỗ trợ protocol/cache tương thích; không giả nhận nghiệm thu upgrade khi chỉ cài mới.

Chuẩn bị baseline với API/PG **thử nghiệm**:

1. Đăng nhập, MFA, ghi lại device UUID; lưu nháp có tiếng Việt, scan và số lượng thập phân. Ghi key/document/execution ID, hash payload, trạng thái và số ledger trước nâng cấp; không ghi token/password/TOTP vào evidence.
2. Tạo lệnh bị mất ACK sau khi server đã commit bằng fault injection/proxy trong môi trường thử nghiệm; journal phải UNKNOWN. Tạo tình huống dừng tiến trình thử nghiệm giữa gửi/ACK để còn SENDING. Giữ key gốc, không phát sinh key mới cho cùng thao tác.
3. Đóng app, chụp dữ liệu, chạy upgrade. Trước mở app, script yêu cầu dữ liệu byte-for-byte không đổi. Mở app, nháp/scan/device UUID còn nguyên, SENDING chuyển UNKNOWN, mở màn hình Phục hồi lệnh.
4. Khôi phục từng lệnh bằng lookup/retry hợp lệ, so ACK với DB. Xác nhận số ledger/audit/outbox theo key không tăng lần hai; nhận lại cùng kết quả khi lookup lặp. Kiểm tra không lẫn user/server/warehouse khác.
5. Reboot Windows, đăng nhập lại, kiểm tra các nháp/chưa rõ kết quả còn nguyên và token không lưu trên đĩa. Gỡ ứng dụng trên tài khoản thử nghiệm và xác minh dữ liệu ngoài thư mục cài còn nguyên trước khi cài lại.

## Đổi lại app version tương thích

Giữ version cũ trong thư mục cài. Chỉ chọn bản đã xác minh hỗ trợ protocol server hiện tại và đọc cache003; không quay về client pre-B19 hoặc restore snapshot SQLite cũ. Chạy khi WMS đã đóng:

```powershell
.\packaging\windows\Rollback.ps1 `
  -VersionDirectory "$env:LOCALAPPDATA\Programs\WMS\0.1.0-<oldcommit12>" `
  -ExpectedHelperSha256 '<hash-WMSHelper.exe-tu-release-cu-da-xac-thuc>' `
  -ExpectedSigner '<40-hex-thumbprint>'
```

Helper được kiểm hash/signature trước khi chạy; self-test kiểm toàn bộ manifest, sau đó đọc cache hiện tại để kiểm phiên bản. Script chỉ đổi shortcut, không thay cache/device/commands/receipts. API compatibility được kiểm khi app kết nối. Nếu bản cũ không có helper/gate hoặc không đọc được cache, dừng rollback; dùng bản sửa forward. Có `-AllowUnsigned` cho baseline thử nghiệm rõ nguồn.

## Ma trận target cần ghi evidence sau khi boot Windows

Chạy độc lập trên Windows 10 x64 và Windows 11 x64, ghi edition/build/patch, user privilege, Python build host, signer/timestamp/hash và tên driver/thiết bị. Không ghi PASS nếu chưa chạy.

| Ca | Kỳ vọng / evidence |
|---|---|
| Cài mới, user thường, Unicode | Không cần Python/admin; manifest/hash/version và frozen-smoke PASS; mở từ shortcut ở cwd khác |
| Login/MFA/API thật | Đúng quyền/kho; MFA sai bị từ chối; không lưu secret |
| Server cũ/protocol sai trong phiên | Chặn trước credential/mutation; pending còn; nâng server rồi phục hồi không double-post |
| Mất LAN, CA thiếu/sai, SAN sai | Lỗi rõ; không bỏ TLS, không retry mù |
| Baseline v1/v2→003 | Backup trước migration; nháp/scan/device còn; SENDING→UNKNOWN; fail migration vẫn giữ DB |
| Cache hỏng/revision4 | Thử trên bản sao dữ liệu; app từ chối, không xóa/đổi version DB |
| Upgrade có nháp/SENDING/UNKNOWN | Inventory trước mở app không đổi; đối chiếu ACK/ledger sau phục hồi |
| Reboot/gỡ/cài lại | Dữ liệu user còn; session mới yêu cầu login |
| App đang mở | Installer từ chối do mutex; không kill app |
| Scale 100/150/200%, nhiều màn hình | Tiếng Việt không mất dấu/cắt nội dung, focus/Tk main thread đúng |
| Máy quét HID thật Enter/Tab | Focus đúng ô, debounce, mã trùng/invalid không gửi ngoài ý muốn |
| Máy in thật + PDF preview | A4/A5/tem, tiếng Việt, barcode đọc được; SUBMITTED không đồng nghĩa đã in giấy; timeout UNKNOWN không tự in lại |
| Rollback app tương thích | Shortcut đổi, cache không downgrade; protocol/cache không phù hợp bị chặn |
| Authenticode | WMS.exe/helper/installer Valid + đúng signer/timestamp; bản bị sửa bị từ chối |
| Hosted Windows regression #21 | Chạy suite hiện có; native no-follow/DACL test không skip, ghi kết quả thực |

Workflow `windows-package.yml` build unsigned trên Windows Server 2022, cài per-user và chạy installed smoke, upload artifact/log 14 ngày. Nó không chạy chứng thư local và không thay Windows 10/11/hardware acceptance. Theo dõi CI `application.yml` cho toàn bộ unit/gui Windows, gồm lỗi O_NOFOLLOW #21: adapter mở handle với OPEN_REPARSE_POINT, kiểm reparse trước đọc, DACL owner+SYSTEM cho file mới; Linux vẫn O_NOFOLLOW/0600/fsync. Chưa có bằng chứng chạy nhánh Win32 cho đến khi CI/Windows thực thi.
