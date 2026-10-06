# Hoàn thiện từ Linux: môi trường, chứng thư và chứng từ

Ngày 06/10/2026. Nhánh `feat/linux-release-validation`, base `6480be4`.
Đây là phần bổ sung của điều phối; không thay đổi phạm vi đang giao B22/B24.

## Phương án môi trường

| Công việc | Nơi thực hiện | Trạng thái |
|---|---|---|
| API, worker, PDF, kiểm thử dữ liệu, tạo chứng thư lab | Linux hiện tại | Có thể chạy local |
| Build EXE / cài thử / smoke Windows | Workflow `windows-package.yml` trên Windows Server 2022 | Đã có mã B23; chưa chạy bản mới trên hosted runner |
| Windows 10/11 GUI, nâng cấp, DACL, máy in/quét | VM Windows hoặc Windows dual boot sẵn có | NEEDS_ENVIRONMENT |
| Thăm dò tương thích macOS, build `.app`, ký/notarize | Mac thật hoặc thuê Mac, điều khiển từ Linux | Chưa có pipeline/packaging macOS; ngoài baseline ban đầu |

Máy Linux đã kiểm tra: i5-1135G7, 8 GB RAM, VT-x/KVM có trên host; RAM trống khoảng
1,9 GiB và phân vùng workspace chỉ còn khoảng 9,3 GB tại thời điểm khảo sát.
Chưa nên tạo VM Windows trên phân vùng này. Windows 11 yêu cầu tối thiểu 4 GB RAM,
64 GB lưu trữ, UEFI/Secure Boot và TPM 2.0. Phương án local sau khi bổ sung dung lượng/RAM:
QEMU/KVM + virt-manager + OVMF + swtpm, ổ ảo mới 80–100 GB, 2–4 vCPU, 4–6 GB RAM,
mạng NAT trước; không trỏ VM vào phân vùng Windows dual boot hoặc ổ dữ liệu đang dùng.
Chỉ số cấu hình VM là đề xuất, chưa phải kết quả đo tải WMS.

Đề xuất hiện tại: phát triển và điều phối trên Linux, dùng Windows hosted CI để build,
Windows có sẵn cho nghiệm thu cuối; thuê Mac khi cần kiểm chứng macOS. Chưa tạo VM,
chưa mua dịch vụ, chưa mount/sửa phân vùng, chưa cài trust vào hệ điều hành.
Theo giấy phép macOS, môi trường ảo hóa cần phần cứng Apple; không dùng macOS VM trên
laptop Intel thông thường làm phương án phát hành. MacInCloud có máy managed từ khoảng
25 USD/tháng tại lúc khảo sát, cần kiểm tra quyền cài tool/Tk và gói thuê trước khi mua.

Nguồn chính thức:

- [Windows 11 requirements](https://www.microsoft.com/en-us/windows/windows-11-specifications)
- [Windows Enterprise evaluation](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise)
- [Ubuntu libvirt](https://ubuntu.com/server/docs/how-to/virtualisation/libvirt/)
- [GitHub hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [macOS Tahoe SLA](https://www.apple.com/legal/sla/docs/macOSTahoe.pdf)
- [MacInCloud managed](https://www.macincloud.com/pages/managed.html)
- [MacInCloud RDP](https://support.macincloud.com/support/solutions/articles/8000051073-access-macincloud-managed-servers-through-rdp-client)

## Chứng thư kiểm thử

Chạy từ gốc checkout, dùng venv có dependency server/desktop/dev của dự án.
Trong worktree local hiện tại có thể dùng interpreter B18 chỉ đọc
`../wms-b18-printing-scanner/.venv/bin/python` thay `.venv/bin/python`.

```bash
rtk proxy env PYTHONPATH=. .venv/bin/python scripts/create_test_certificates.py
```

Tool Linux tạo thư mục mới `.local-test-pki/` mode 0700, file 0600, không ghi đè đường dẫn có sẵn/symlink:

- `tls-ca.pem`: CA công khai riêng cho HTTPS lab; private key CA không được lưu.
- `tls-server.pem`, `tls-server.key`: serverAuth với SAN `localhost`, `wms.test`, `127.0.0.1`.
- `windows-test-signing.cer`, `windows-test-signing.pfx`: chứng thư self-signed có EKU Code Signing,
  danh tính **InternTechLead TEST ONLY**, PFX mã hóa bằng mật khẩu ngẫu nhiên.
- `pfx-password.txt`: mật khẩu riêng của lab. Không in nội dung vào log/chat; lưu cùng PFX chỉ thích hợp
  cho môi trường thử do cùng tài khoản sở hữu. Không xem đây là kho bí mật cho release.
- `public-manifest.json`: fingerprint SHA-256 và thumbprint SHA-1 dùng chọn chứng thư Windows,
  hạn dùng 30 ngày, `native_authenticode=NOT_RUN`. SHA-1 chỉ định danh chứng thư; chữ ký sử dụng SHA-256.

Có `--dns`, `--ip` lặp lại cho tên/IP server thử thật, `--days` từ 1 đến 30; output mới phải có
thư mục cha tồn tại. Ví dụ `--output .local-test-pki-lan --dns wms.test --ip 192.168.1.50`.
Tránh để các bundle tự đặt tên trong Git; `.pfx`, `.p12`, `.key`, `.pem` được ignore nhưng file
mật khẩu ngoài `.local-test-pki/` cần đặt dưới `.reports/` hoặc thư mục riêng ngoài checkout.
Không upload cả bundle lên CI. Tool không đăng ký DNS, mở cổng hoặc cấu hình Nginx.

HTTPS lab: cấu hình Nginx thử dùng server PEM/key; desktop cấu hình `ca_file` trỏ đến CA công khai,
`api_url` dùng tên/IP đúng SAN. Không dùng code-signing CER làm CA HTTPS, không tắt verify TLS.
Thay chứng thư hết hạn bằng bundle mới và cập nhật CA lab trên client.

Windows lab: chuyển PFX/CER và mật khẩu qua kênh riêng tới **VM/tài khoản kiểm thử bỏ được**.
Đối chiếu fingerprint với manifest lấy từ nguồn tin cậy. Sau đó, PowerShell trên máy thử:

```powershell
$lab = 'C:\WMS-Lab\certificates'
$password = Read-Host 'Mat khau PFX lab' -AsSecureString
$cert = Import-PfxCertificate -FilePath "$lab\windows-test-signing.pfx" `
  -CertStoreLocation Cert:\CurrentUser\My -Password $password
Import-Certificate -FilePath "$lab\windows-test-signing.cer" -CertStoreLocation Cert:\CurrentUser\Root
Import-Certificate -FilePath "$lab\windows-test-signing.cer" -CertStoreLocation Cert:\CurrentUser\TrustedPublisher
$thumbprint = $cert.Thumbprint
# Truyen $thumbprint vao -CertificateThumbprint cua Build.ps1 theo README B23.
```

Chỉ tạo trust self-signed trong máy lab. Chạy `packaging/windows/Build.ps1` theo
[hướng dẫn B23](../packaging/windows/README.md), với Windows SDK signtool và Inno đã xác minh.
Build giữ kiểm tra EKU/expiry/thumbprint, ký SHA-256 + timestamp và verify; không thêm bypass chữ ký.
Chưa chạy quy trình native này thì không ghi PASS. Sau test, bỏ VM snapshot hoặc gỡ đúng thumbprint
lab khỏi ba store trên, không đụng chứng thư khác.

Chứng thư phát hành công khai cần được nhà cung cấp xác minh danh tính và cấp; tool không tạo public trust
hoặc bảo đảm SmartScreen. Microsoft Artifact Signing Public Trust có giới hạn thị trường; cần kiểm tra
tính đủ điều kiện tại [trang chính thức](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
Mac phát hành ngoài App Store cần quy trình Developer ID/notarization trên môi trường Apple và tài khoản
phù hợp: [Developer ID](https://developer.apple.com/developer-id/). PFX lab này không thay Developer ID.

## Mẫu phiếu và tem InternTechLead

Thông tin người dùng cung cấp, giữ MST/điện thoại dưới dạng chuỗi để không mất số 0 đầu:

- Đơn vị: **InternTechLead**.
- Địa chỉ: **Đông Thạnh, Hóc Môn, TP. Hồ Chí Minh**.
- MST: **0869233973**. Điện thoại: **0329511628**.
- Tên người ký: **Trần Trung Kiên**. Chỗ ký vẫn trống, không mô phỏng chữ ký.

Server đọc `WMS_PRINT_ISSUER_NAME`, `WMS_PRINT_ISSUER_ADDRESS`, `WMS_PRINT_ISSUER_TAX_CODE`,
`WMS_PRINT_ISSUER_PHONE`, `WMS_PRINT_ISSUER_SIGNER`. Đã điền mẫu tại `deploy/lan/runtime.env.example`;
file này là cấu hình literal UTF-8 của `lan_runtime.py`, **không source như shell script**.
Mặc định các trường rỗng. Cần áp dụng cấu hình vào API thử/nghiệm thu mới có thông tin trên lệnh in mới;
chưa tự thay cấu hình dịch vụ đang chạy. Client không được gửi/tự sửa thông tin đơn vị trong payload in.

Thông tin được đóng vào phần header tùy chọn của snapshot v1 ngay lúc tạo print job.
Worker/reprint không đọc lại cấu hình; job cũ không có header này giữ nội dung cũ.
Giữ template_version=1 đồng nhất với contract/constraint đã phát hành; không đổi API/schema hay migration.
Phiếu có tên/địa chỉ/MST/điện thoại/người ký.
Tem có tên/địa chỉ/điện thoại; không in MST/người ký để giữ vùng mã và cỡ chữ. Trường tem quá dài cắt dấu
ba chấm, không cắt giá trị barcode; thông tin đầy đủ nằm trên phiếu.

```bash
rtk proxy env PYTHONPATH=. .venv/bin/python scripts/preview_print_templates.py
```

Tạo `output/pdf/wms-phieu-tem-mau.pdf`: một trang giới thiệu và 12 trang giữ khổ thật.
Các PDF riêng/manifest nằm ở `tmp/pdfs/native/` để so sánh/in thử, đều là dữ liệu giả lập `MAU-*`.
Phiếu nhập/xuất/chuyển/kiểm kê A4/A5; tem hàng Code128 và vị trí QR 100×50/80×40 mm.
Kiểm kê luôn đếm mù; không in tồn hệ thống/chênh lệch. Giá chỉ có khi quyền/tiêu chí hiện có cho phép;
bộ mẫu không in giá. Các mẫu này là phiếu kho nội bộ, không triển khai hóa đơn điện tử hoặc chữ ký số PDF.

Các file PDF/PKI sinh local được ignore. Preview dùng production renderer, không chạm DB hoặc gửi máy in.
Khi in thử chọn 100%/Actual size, không Fit. Q06/Q08, máy in/máy quét thật, đồng ý mẫu nghiệp vụ và
các T01–T28 chưa được nghiệm thu từ ảnh PDF hoặc kết quả decode máy tính.
