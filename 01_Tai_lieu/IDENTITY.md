# Đăng nhập, MFA và phân quyền theo kho

Đợt triển khai BE03 (#5), BE04 (#6), UI03 (#13), tiếp nối nhánh `feat/application-foundation`.
Contract chạy thật: [OpenAPI runtime](../05_API/openapi_runtime.json). Contract nghiệp vụ lõi
ở `openapi_core.json` vẫn được giữ riêng cho các luồng chưa triển khai.

## Khởi tạo môi trường

1. Cài lại dependencies bằng `python -m pip install -r requirements-app-lock.txt`.
2. Giữ `WMS_DATABASE_URL`, chạy `python -m apps.server.infrastructure.migrations` để áp dụng 003 và 004.
   Database đã chạy nền 001/002 nâng cấp tại chỗ; runner giữ nguyên checksum hai migration cũ.
3. Sinh một khóa MFA trên máy server, lưu trong cấu hình bí mật ngoài Git và sao lưu riêng:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export WMS_MFA_ENCRYPTION_KEY='<khóa vừa sinh>'
```

PowerShell dùng `$env:WMS_MFA_ENCRYPTION_KEY='<khóa vừa sinh>'`.
Giữ cùng khóa qua các lần restart; không sinh khóa mới mỗi lần chạy. Mất khóa sẽ không giải mã được MFA
đã đăng ký. Server từ chối MFA nếu thiếu/sai khóa, không bỏ qua yếu tố thứ hai.

Trên server, tạo **hai** tài khoản quản trị ban đầu trước khi thêm người dùng thường:

```bash
python -m apps.server.bootstrap --username admin.one --display-name 'Quản trị 1'
python -m apps.server.bootstrap --username admin.two --display-name 'Quản trị 2'
python -m apps.server
```

CLI hỏi mật khẩu ẩn và yêu cầu nhập lại; không nhận mật khẩu qua command-line. Mật khẩu mới dài 12–128 ký tự.
Bootstrap chỉ dành cho lần đầu: tối đa hai user, cả hai SYSADMIN; không ghi đè user, không chạy qua HTTP,
không tạo mật khẩu mặc định, không cấp quyền kho. Trong thực tế, hai người có trách nhiệm riêng sử dụng hai
tài khoản; trong fixture kiểm thử đây là hai danh tính giả. Tài khoản duy nhất không được bỏ qua SOD.

## Dùng desktop

Chạy `python -m apps.desktop`, tab **Đăng nhập và kho**:

1. Nhập tài khoản/mật khẩu, bấm **Đăng nhập**. Khi user đã có MFA, nhập mã rồi bấm **Xác nhận MFA**.
2. User chưa có MFA: nhập lại mật khẩu, chọn **Lấy khóa MFA**, thêm khóa vào ứng dụng xác thực TOTP,
   nhập mã 6 số và bấm **Xác nhận bật MFA** trong 5 phút.
3. Mã đã dùng không được dùng lại, kể cả ở challenge khác. Nếu vừa bật MFA rồi đăng nhập lại, đợi mã kế tiếp.
4. Chọn kho trong danh sách đã được server lọc. SYSADMIN ban đầu có danh sách kho rỗng vì không có quyền kho.
5. **Tải lại phiên** kiểm tra phiên/quyền hiện tại. Khóa user/thu hồi phiên khiến lần gọi tiếp theo bị từ chối,
   desktop xóa token, danh sách kho và quyền đang hiển thị; nháp SQLite không bị xóa.

Password và mã MFA được xóa khỏi ô nhập ngay sau khi gửi. Token/challenge/khóa đăng ký chỉ nằm trong RAM,
không lưu vào SQLite/file/log. HTTP chạy trong worker; widget và hủy tài nguyên Tk trên main thread.
UUID thiết bị được giữ bền ở `WMS_LOCAL_DATA_DIR/device.sqlite3` (mặc định theo profile OS) để đăng nhập lại
mở đúng phân vùng phục hồi; không phải credential. Xem [phục hồi nhận hàng](RECEIPT_RECOVERY.md).
TLS luôn được kiểm tra. Đã có [desktop quản trị user/grant](ADMIN_DESKTOP.md) nối API thật,
phân trang, MFA/quyền, hai quản trị duyệt và thu hồi phiên/quyền. IAM write không tự replay sau timeout;
người dùng tải lại để đối chiếu. Đổi mật khẩu/reset MFA và lookup/lịch sử quản trị nâng cao còn thiếu.

## Quản trị qua API

Swagger tại `/api/v1/docs`. Lấy access token qua login/MFA, điền **Authorize** (bearer).
Các API quản trị yêu cầu `iam.manage` hoặc `role.manage` GLOBAL và phiên đã xác thực MFA.
Swagger là công cụ phát triển, không thay UI quản trị trong nghiệm thu UI03.

| Endpoint (sau `/api/v1`) | Tác dụng |
| --- | --- |
| `POST /auth/login`, `/auth/mfa`, `/auth/refresh`, `/auth/logout` | Đăng nhập hai bước, xoay refresh token, đăng xuất |
| `GET /auth/me` | Danh tính hiện hành, trạng thái MFA và các quyền GLOBAL đúng grant |
| `POST /auth/mfa/enroll`, `/auth/mfa/confirm` | Đăng ký và xác nhận TOTP; enrollment hết hạn sau 5 phút |
| `GET /warehouses`, `/warehouses/{id}/permissions` | Kho/quyền của chính phiên hiện hành |
| `GET /documents/{id}` | Projection đọc tối thiểu, quyền kho/assignment và che giá; chưa CRUD/posting |
| `GET /users`, `POST /users` | Liệt kê/tạo user; DTO không chứa hash/mật khẩu/token |
| `PATCH /users/{id}/active` | Khóa/mở user, tăng auth_version; phiên cũ không được hồi sinh khi mở khóa |
| `POST /users/{id}/revoke-sessions` | Thu hồi toàn bộ phiên qua auth_version |
| `GET /roles`, `/grants`, `/grant-requests` | Danh sách role, grant và yêu cầu đang chờ |
| `POST /grant-requests` | Yêu cầu cấp role + scope + thời hạn; chưa cấp quyền ngay |
| `POST /grant-requests/{id}/approve` | Quản trị viên thứ hai duyệt, tạo grant và audit trong cùng transaction |
| `POST /grants/{id}/revoke` | Thu hồi grant; request kế tiếp kiểm tra lại hiệu lực |

Ví dụ cấp quyền: quản trị 1 tạo user thường, tạo grant request cho user đó; quản trị 2 đăng nhập/MFA rồi
duyệt request. Không ai được yêu cầu/duyệt grant cho chính mình; người yêu cầu không được tự duyệt.
Nhấn duyệt lại cùng request không tạo grant thứ hai. Hết hạn hoặc requester đã mất quyền thì không duyệt được.
Lý do được lưu trong request/audit. Chính sách này hiện được thực thi trong hệ thống, thay phần kiểm soát
cấp quyền chỉ bằng biên bản ngoài ứng dụng trước đây.

`GET /users` dùng `after=<username cuối>`, thứ tự username, limit mặc định 100/tối đa 200.
`GET /grants` và `/grant-requests` dùng `after=<UUID cuối>`, thứ tự UUID. Đây là phân trang danh sách IAM;
chưa phải snapshot/cursor của contract nhận hàng. Không trả password hash qua API quản trị.

## Phiên và kiểm soát truy cập

- Mật khẩu: Argon2id (19 MiB, 2 iterations, parallelism 1). Refresh/access là token opaque ngẫu nhiên 256 bit;
  database chỉ lưu SHA-256 của token. Access mặc định 15 phút, session tối đa 8 giờ, cấu hình qua
  `WMS_ACCESS_TTL_SECONDS` và `WMS_SESSION_TTL_SECONDS`.
- Refresh rotation giữ lịch sử hash, không gia hạn vượt hạn session; token refresh cũ bị replay thì thu hồi
  cả phiên trong transaction được commit trước khi trả lỗi. Refresh phải khớp device đã đăng nhập.
- Mỗi request bảo vệ kiểm tra lại user active, auth_version, session/token còn hạn và chưa thu hồi.
  Không chứa quyền cố định trong token. Logout vô hiệu phiên server; desktop bỏ token local cả khi mất mạng,
  nhưng khi đó không khẳng định server đã nhận logout.
- TOTP secret được mã hóa bằng Fernet; lưu counter đã dùng để chặn replay qua challenge/phiên khác.
  Sai password hoặc MFA 5 lần trong cửa sổ 5 phút bị chặn 5 phút; counter ở PostgreSQL, dùng chung worker.
  Tạo challenge mới không reset số lần sai MFA. Triển khai LAN còn cần cấu hình giới hạn request ở proxy QA07.
- Bật MFA tăng auth_version, vô hiệu các phiên/challenge cũ, chỉ giữ phiên vừa xác nhận. Các API quản trị
  luôn yêu cầu MFA. Khôi phục/reset MFA, đổi mật khẩu và quản lý recovery code chưa có trong đợt này.
- Permission và scope được kiểm tra trên cùng **một grant**. GLOBAL không cấp quyền WAREHOUSE;
  ALL_WAREHOUSES không cấp quyền GLOBAL. Grant hết hạn/thu hồi, role không active và permission chưa có đều bị từ chối.
- RECEIVER/PICKER đọc phiếu của mình hoặc được giao; role đọc rộng phải có grant tại chính kho đó.
  Giá chỉ trả khi có cả quyền đọc chứng từ và `price.read` cùng kho. Tài nguyên ngoài scope trả 404;
  đã thấy nhưng thiếu action trả 403. Tạm thời đọc TRANSFER cần quyền đọc cả hai kho.
- `document.approve`: WAREHOUSE_MANAGER hoặc CONTROLLER theo TL01 Q04, không hạn mức. Guard SOD chặn
  creator/requester/người đếm/người đã duyệt bước trước. API workflow duyệt nghiệp vụ chưa triển khai;
  các guard này phải được gọi cùng kiểm tra version/state/policy trong BE07.

Quyết định kỹ thuật dựa trên [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[PyOTP](https://pyotp.readthedocs.io/en/stable/) và [Fernet](https://cryptography.io/en/latest/fernet/).

## Schema và kiểm thử

Migration 003 thêm `auth_token`, `auth_challenge`, `auth_throttle`, `grant_request` và ba cột MFA vào hai bảng cũ.
Migration 004 bổ sung grant permission mặc định CONTROLLER → document.approve theo TL01.
Mô hình baseline giữ 56 bảng; [model IAM](../02_CSDL/iam_extension_model.json),
[từ điển](../02_CSDL/iam_extension_dictionary.csv) và [DBML bổ sung](../02_CSDL/iam_extension.dbml) ghi phần thêm.
Schema sau IAM có 60 bảng/385 cột/113 FK; migration 005 của [danh mục](MASTER_DATA.md) nâng lên 393 cột. Sau [006/007](TRACEABILITY.md), schema có 63 bảng/424 cột/123 FK và 56 quyền/121 ánh xạ. Sau [008](ORDERS_APPROVAL.md), runtime có 63 bảng/428 cột/125 FK; số quyền không đổi.
Integration so sánh toàn bộ runtime với baseline và các model bổ sung.

Chạy `xvfb-run -a .venv/bin/python scripts/check_application.py --gui` để kiểm thử API, hai connection refresh/MFA,
grant/role/scope, mã hóa secret và desktop login/MFA/revoke qua HTTP thật. Các fixture/password đều là dữ liệu giả.
`python scripts/export_runtime_contract.py --check` xác nhận OpenAPI runtime khớp code.

T11 đã có bằng chứng API và desktop trên Linux; chưa UAT Windows. T07 đã kiểm thử đọc chứng từ/che giá/phân quyền
và revoke grant; export/download, phê duyệt nghiệp vụ và các endpoint chưa xây dựng chưa thể nghiệm thu đầy đủ.
Không đánh dấu toàn bộ T07 hoặc T01–T28 đạt từ các test thành phần này.

Sau [009](RECEIVING.md), runtime có 63 bảng/430 cột/125 FK; không thêm quyền mới.
