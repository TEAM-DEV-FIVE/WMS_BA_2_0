"""Editorial sections for the root README; feature inventory is generated separately."""

REPOSITORY = 'https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0'
RELEASE = REPOSITORY + '/releases/download/v0.1.0-handover.1/'
TECHNOLOGIES = [
    ('Python · Tkinter', 'python', 'https://www.python.org/', 'Ngôn ngữ · Desktop'),
    ('FastAPI', 'fastapi', 'https://fastapi.tiangolo.com/', 'HTTP API'),
    ('PostgreSQL', 'postgresql', 'https://www.postgresql.org/', 'Dữ liệu máy chủ'),
    ('SQLite', 'sqlite', 'https://www.sqlite.org/', 'Nháp cục bộ'),
    ('SQLAlchemy', 'sqlalchemy', 'https://www.sqlalchemy.org/', 'Truy cập dữ liệu'),
    ('Nginx', 'nginx', 'https://nginx.org/', 'HTTPS · Reverse proxy'),
    ('pytest', 'pytest', 'https://docs.pytest.org/', 'Kiểm thử'),
]
DOWNLOADS = [
    ('Windows', 'windows', 'WMS-Setup-0.1.0-97d4c510dab8-x64.exe', 'Tải Windows (.exe)', 'Desktop x64'),
    ('macOS', 'macos', 'WMS-macos-arm64-TEST-ONLY.zip', 'Tải macOS (.zip)', 'Desktop ARM64 · bản thử nghiệm'),
    ('Linux Server', 'linux', 'WMS-Server-0.1.0-97d4c510dab8-linux-x64.tar.gz',
     'Tải Linux Server (.tar.gz)', 'Máy chủ Linux x64'),
]


def introduction():
    logos = ['<table align="center">', '  <tr>']
    for title, icon, url, purpose in TECHNOLOGIES:
        source = f'https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/{icon}/{icon}-original.svg'
        logos += [f'    <td align="center" width="115"><a href="{url}">'
                  f'<img src="{source}" height="44" width="44" alt="{title}"><br><strong>{title}</strong>'
                  f'</a><br><sub>{purpose}</sub></td>']
    logos += ['  </tr>', '</table>']
    downloads = ['<table align="center">', '  <tr>']
    for title, icon, filename, label, purpose in DOWNLOADS:
        url = RELEASE + filename
        downloads += [f'    <td align="center" width="260"><strong>{title}</strong><br><br>'
                      f'<a href="{url}"><img src="assets/platforms/{icon}.svg" width="60" height="60" '
                      f'alt="{label}"></a><br><br><a href="{url}"><strong>{label}</strong></a>'
                      f'<br><sub>{purpose}</sub></td>']
    downloads += ['  </tr>', '</table>']
    return '''<p align="center"><img src="apps/desktop/assets/wms-logo-navy.png" alt="Logo WMS" width="150"></p>

# WMS — Hệ thống quản lý kho

**Quản lý hàng hóa, chứng từ và vận hành kho trên ứng dụng desktop kết nối máy chủ qua mạng LAN.**

''' + '\n'.join(logos) + '''

WMS được viết bằng **Python**, dùng **Tkinter/ttk** cho giao diện, **FastAPI** cho API và **PostgreSQL** làm cơ sở dữ liệu trung tâm. Hệ thống theo dõi quá trình từ đơn mua, nhận hàng, lưu kho, soạn/đóng kiện đến xuất kho, trả hàng, kiểm kê và đối soát; đồng thời quản lý người dùng, phê duyệt, truy vết và phục hồi các lệnh bị gián đoạn.

<a id="tai-ung-dung"></a>

## Tải ứng dụng

''' + '\n'.join(downloads) + f'''

**[Xem tất cả bản phát hành]({REPOSITORY}/releases)** · **[Tải mã nguồn main (.zip)]({REPOSITORY}/archive/refs/heads/main.zip)** · [Hướng dẫn cài đặt](01_Tai_lieu/OPERATIONS_RUNBOOK.md) · [Hướng dẫn sử dụng](01_Tai_lieu/USER_GUIDE.md)

Ba bộ cài trên thuộc bản bàn giao **0.1.0 tại `97d4c51`**; mã nguồn `main` có các thay đổi giao diện và tính năng bổ sung sau mốc này. Windows đã thử trên Server 2022 x64, macOS trên 15 ARM64; phạm vi kiểm chứng nằm trong [biên bản bàn giao](07_Kiem_tra/release/FINAL_HANDOVER.md). Tải bộ cài theo hệ điều hành của máy, rồi cấu hình kết nối API do người quản trị cung cấp.

<a id="muc-luc"></a>

## Nội dung README

[Tổng quan](#tong-quan) · [Công nghệ](#cong-nghe) · [Kiến trúc và dữ liệu](#kien-truc) · [Chức năng kèm ảnh](#chuc-nang) · [Vận hành và cấu trúc mã](#van-hanh) · [Chạy từ mã nguồn](#chay-tu-ma-nguon) · [Kiểm chứng](#kiem-chung)

<a id="tong-quan"></a>

## Hệ thống giải quyết những công việc gì?

Một chứng từ trong WMS không chỉ là danh sách sản phẩm: hệ thống theo dõi người lập, kho, nguồn hàng, định danh lô/serial, phiên bản và các bước phê duyệt trước khi ghi nhận thay đổi tồn. Nhân viên thao tác trên desktop; máy chủ kiểm tra quyền và điều kiện nghiệp vụ rồi lưu kết quả vào cơ sở dữ liệu chung.

| Nhóm người sử dụng | Công việc được hệ thống hỗ trợ |
|---|---|
| Mua hàng và bán hàng | Lập PO/SO, theo dõi lượng thực hiện và tình trạng chứng từ |
| Nhân viên kho | Nhận hàng, kiểm định, cất/di chuyển, soạn, đóng kiện, xuất và trả hàng |
| Quản lý kho | Phân công, phê duyệt trong phạm vi được cấp, chuyển kho, kiểm kê và xử lý chênh lệch |
| Kiểm soát và kiểm toán | Đối soát kỳ, tra sổ phát sinh, báo cáo và dấu vết thao tác theo quyền |
| Quản trị | Quản lý danh mục, tài khoản, phiên đăng nhập, vai trò, quyền và cấu hình triển khai |

Nhóm công việc trên giúp định hướng sử dụng; quyền thực tế được cấp riêng theo vai trò, kho và thời hạn. Hệ thống có hàng doanh nghiệp và hàng ký gửi; các nghiệp vụ được phép trên từng loại sở hữu do máy chủ kiểm tra.

### Các luồng nghiệp vụ chính

| Luồng | Các bước trong phần mềm |
|---|---|
| Nhập hàng | PO → phê duyệt → lập phiếu nhận → duyệt phiếu → ghi nhận từng phần hoặc đủ → kiểm định/cất hàng theo nghiệp vụ |
| Xuất hàng | SO → lập và duyệt phiếu xuất → giữ hàng khả dụng → soạn và đóng kiện → ghi sổ xuất |
| Chuyển kho | Lập và duyệt phiếu → xuất vào transit → nhận tại kho đích → xử lý chênh lệch nếu có |
| Kiểm kê | Chọn/khóa phạm vi → snapshot tồn → ghi đếm → nộp kết quả → xét duyệt → điều chỉnh được phép |
| Nhập dữ liệu | Chọn mẫu CSV/XLSX → kiểm tra tệp → tải lên → dry run → xem lỗi → xác nhận commit → tiếp tục chứng từ nếu cần |
| Mất phản hồi | Giữ nhật ký lệnh → tra ACK của yêu cầu cũ → nhận kết quả hoặc gửi lại đúng key/nội dung theo xác nhận |

Các luồng mô tả chức năng đã có trong mã nguồn. Điều kiện quyền, trạng thái, loại hàng và nhánh lỗi được trình bày trong [hướng dẫn người dùng](01_Tai_lieu/USER_GUIDE.md) và [tài liệu nghiệp vụ](01_Tai_lieu/HIEN_TRANG_BAO_CAO.md). Phạm vi hiện tại tập trung vào quản lý kho; giá tham chiếu phục vụ quản trị, chưa phải hệ thống kế toán giá vốn/công nợ.
'''


SYSTEM = '''<a id="cong-nghe"></a>

## Công nghệ và vai trò trong hệ thống

| Lớp / công việc | Công nghệ sử dụng | Vai trò cụ thể trong WMS |
|---|---|---|
| Ngôn ngữ | Python 3.12+ | Desktop, API, dịch vụ nghiệp vụ, worker và công cụ triển khai |
| Giao diện | Tkinter / ttk, Pillow | Cửa sổ desktop, form/bảng/tab, xử lý ảnh sản phẩm và ảnh đại diện |
| Giao tiếp | HTTPX | Client gọi API với timeout và xử lý phản hồi ngoài luồng giao diện |
| Máy chủ HTTP | FastAPI, Uvicorn | Khai báo route, xử lý yêu cầu và phục vụ API |
| Hợp đồng dữ liệu | Pydantic, pydantic-settings | Kiểm tra DTO, kiểu dữ liệu và cấu hình môi trường |
| Truy cập PostgreSQL | SQLAlchemy 2.0, psycopg 3 | Kết nối, truy vấn có tham số, transaction và khóa dữ liệu |
| Dữ liệu trung tâm | PostgreSQL 15/16, SQL migrations | Chứng từ, sổ/số dư, định danh hàng, quyền, audit và job |
| Dữ liệu trên desktop | SQLite qua thư viện chuẩn Python | Nháp và nhật ký lệnh phục hồi tách theo máy chủ/tài khoản/thiết bị |
| Xác thực | argon2-cffi, cryptography, PyOTP, keyring | Băm mật khẩu, bảo vệ dữ liệu bí mật, MFA và lưu phiên trong vault hệ điều hành |
| Chứng từ và mã | ReportLab, pypdfium2, qrcode | Tạo PDF, xem trước PDF và mã QR; adapter hệ điều hành gửi máy in |
| Triển khai LAN | Nginx, systemd | HTTPS/reverse proxy và quản lý các tiến trình trên profile Linux |
| Đóng gói | PyInstaller; cấu hình Windows/macOS | Tạo gói desktop theo nền tảng; bộ Linux phục vụ triển khai server |
| Kiểm tra chất lượng | pytest, Ruff, GitHub Actions | Kiểm thử, kiểm tra mã và các workflow CI có trong repository |

Danh sách dựa trên [pyproject.toml](pyproject.toml), [dependency lock](requirements-app-lock.txt), [mã desktop](apps/desktop), [mã server](apps/server), [đóng gói](packaging) và [triển khai LAN](deploy/lan). Phiên bản cài đặt cụ thể xem lockfile; logo ở đầu trang biểu thị các công nghệ chính, không biểu thị chứng nhận của nhà cung cấp. Biểu tượng công nghệ lấy từ [Devicon v2.17.0](https://github.com/devicons/devicon/tree/v2.17.0) ([trang chính thức](https://devicon.dev/)).

<a id="kien-truc"></a>

## Kiến trúc và cách hệ thống xử lý dữ liệu

![Kiến trúc WMS theo mã nguồn](03_So_do/Hien_hanh/svg/ARCHITECTURE.svg)

| Thành phần | Trách nhiệm và kết nối |
|---|---|
| Desktop | Hiển thị màn hình theo quyền, nhận thao tác và gọi HTTP API; widget cập nhật ở main thread, I/O chạy qua executor |
| Nginx | Nhận HTTPS và chuyển yêu cầu đến FastAPI trong cấu hình triển khai LAN |
| FastAPI và application services | Xác thực phiên, kiểm quyền/scope, trạng thái, phiên bản và quy tắc từng nghiệp vụ |
| PostgreSQL | Nguồn dữ liệu chính thức, lưu dữ liệu nghiệp vụ và kết quả chống trùng trong transaction |
| SQLite và OS vault | SQLite lưu nháp/nhật ký; vault hệ điều hành giữ thông tin phiên khi người dùng bật nhớ đăng nhập |
| Worker và kho tệp riêng | Xử lý job, tạo/tải tệp và dọn tệp dẫn xuất theo policy; API kiểm quyền khi tải |

### Một thao tác ghi sổ được xử lý ra sao?

1. Desktop chuẩn bị nội dung, phiên bản chứng từ và khóa chống trùng (*idempotency key*); nhật ký phục hồi ghi lại yêu cầu trước khi gửi.
2. Server xác thực, kiểm tra quyền hiện tại và phạm vi tài nguyên. `CommandBus` tuần tự hóa cùng key và so khớp hash nội dung; key đã có kết quả hợp lệ được trả lại theo quyền hiện tại.
3. Handler nghiệp vụ kiểm tra trạng thái, nguồn hàng, lượng còn lại, kỳ kho và các điều kiện liên quan; khóa dữ liệu cần thiết trước khi cập nhật.
4. Dữ liệu nghiệp vụ và kết quả chống trùng được commit cùng đơn vị công việc; handler ghi sổ/số dư/audit/outbox tương ứng. Giao dịch không hợp lệ bị từ chối.
5. Desktop nhận kết quả xác nhận. Nếu mất phản hồi, trạng thái giữ là chưa rõ; tra ACK bằng yêu cầu gốc với `X-WMS-Recovery: lookup-v1` trước khi quyết định gửi lại.

Nguồn: [CommandBus](apps/server/application/commands.py), [Unit of Work PostgreSQL](apps/server/infrastructure/database.py), [recovery API](apps/server/api/recovery.py), [journal desktop](apps/desktop/local_store/recovery.py).

### Dữ liệu kho được tổ chức thế nào?

| Nhóm dữ liệu | Các đối tượng chính | Ý nghĩa |
|---|---|---|
| Danh mục | Sản phẩm, UOM/quy đổi, barcode, nhóm hàng, kho/vị trí, đối tác | Dữ liệu tham chiếu dùng khi lập và thực hiện chứng từ |
| Định danh hàng | Sản phẩm + lô hoặc serial + chủ sở hữu/hợp đồng | Phân biệt hàng thường, hàng theo lô/hạn dùng, serial và hàng ký gửi |
| Chứng từ | Phiếu, dòng phiếu, liên kết nguồn, phân công và snapshot phê duyệt | Theo dõi phiên bản, nguồn phát sinh và lượng đã/chưa thực hiện |
| Tồn và vận hành | Stock move, balance, reservation, pick task, package, transit | Ghi phát sinh, số dư, lượng giữ, soạn/kiện và hàng đang chuyển |
| Kiểm soát | Phiên kiểm kê, quan sát đếm, quyết định, kỳ kho, phiếu đảo | Đối soát và điều chỉnh có căn cứ; đảo bằng giao dịch bù |
| Hệ thống | User/role/permission, phiên, audit, idempotency, outbox và job | Quản lý truy cập, truy vết và xử lý tác vụ nền |

Số lượng trao đổi qua API bằng chuỗi decimal. Phân loại sở hữu được giữ trong định danh hàng. Sổ tồn đã ghi được bảo vệ theo các bất biến; sửa sai đi qua nghiệp vụ điều chỉnh/đảo được phép. Chi tiết tại [bất biến dữ liệu](01_Tai_lieu/INVARIANTS.md), [schema](02_CSDL/README.md) và [API runtime](05_API/README.md).

### Phân quyền và bảo vệ thao tác

Quyền được kiểm tra trên máy chủ, kể cả khi tra lại kết quả cũ; việc ẩn nút ở giao diện chỉ hỗ trợ sử dụng. Hệ thống kiểm soát phạm vi kho, thời hạn cấp quyền, tách nhiệm vụ lập/duyệt, quyền xem giá và phiên bản chứng từ. MFA và các thao tác quản trị phiên bổ sung kiểm soát tài khoản; email/SMS/Google hoạt động khi máy chủ đã có cấu hình tương ứng.

Desktop gọi API và không mang thông tin kết nối PostgreSQL. Nháp/journal không lưu mật khẩu hoặc token; nhớ phiên sử dụng kho bí mật hệ điều hành. Nút **Tải lại** chạy quy trình đóng có xác nhận và chờ tài nguyên nền, rồi khởi động lại bản ứng dụng đang cài. Nút này không tự tải bộ cài mới từ Internet.
'''

OPERATIONS = '''<a id="van-hanh"></a>

## Vận hành hệ thống và cấu trúc mã nguồn

### Bảy loại worker

| Worker | Nhiệm vụ |
|---|---|
| Outbox | Nhận sự kiện đã commit và điều phối consumer/tác vụ |
| Import | Thực hiện các bước job nhập tệp theo trạng thái và quyền |
| Export | Tạo kết quả xuất báo cáo CSV/XLSX |
| Print | Render tài liệu PDF phục vụ tải/xem/in |
| Export cleanup | Dọn tệp export dẫn xuất theo chính sách giữ tệp |
| Print cleanup | Dọn tệp PDF dẫn xuất theo chính sách giữ tệp |
| Auth delivery | Gửi thông báo/mã xác thực qua kênh được cấu hình |

Job có trạng thái, cơ chế nhận việc và kiểm soát xử lý lại trong mã server. Các worker chạy thành tiến trình riêng theo cấu hình triển khai. Gửi tới máy in là bước tương tác thiết bị, không thể suy ra giấy đã in thành công chỉ từ việc giao dịch DB đã commit.

### Cấu trúc repository

| Đường dẫn | Nội dung |
|---|---|
| [apps/desktop](apps/desktop) | Giao diện, presenter, API client, nhật ký SQLite, in/quét mã và tài nguyên ảnh |
| [apps/server](apps/server) | Route API, application services, hạ tầng PostgreSQL, worker và tác vụ tệp |
| [packages/contracts](packages/contracts) | DTO dùng chung giữa desktop và server |
| [migrations](migrations) | SQL nâng schema và seed theo revision có checksum |
| [tests](tests) | Các bộ kiểm thử ứng dụng, giao dịch, API và desktop |
| [deploy](deploy), [packaging](packaging) | Triển khai LAN, cấu hình dịch vụ và đóng gói nền tảng |
| [scripts](scripts) | Vận hành, kiểm tra artifact, trích schema/API, dựng tài liệu và chụp ảnh |
| [01_Tai_lieu](01_Tai_lieu) | Hồ sơ nghiệp vụ, kiến trúc, hướng dẫn người dùng và runbook |
| [02_CSDL](02_CSDL), [03_So_do](03_So_do), [05_API](05_API) | Catalog dữ liệu, ERD/lớp/luồng và OpenAPI |
| [assets/readme](assets/readme), [07_Kiem_tra](07_Kiem_tra) | Ảnh chức năng, manifest và bằng chứng kiểm tra |

### Triển khai và bảo trì

Cấu hình LAN có HTTPS, kiểm tra health/readiness, quyền DB runtime riêng, service/worker, kho tệp riêng và công cụ backup/PITR, nâng cấp, rollback. PostgreSQL và kho tệp cần được quản lý cùng quy trình sao lưu/khôi phục. Kết nối email/SMS/Google, vault và máy in phụ thuộc môi trường; chỉ bật khi đã cấu hình.

[Runbook máy chủ LAN](01_Tai_lieu/LAN_DEPLOYMENT.md) · [Cài đặt/vận hành](01_Tai_lieu/OPERATIONS_RUNBOOK.md) · [Cấu hình runtime mẫu](deploy/lan/runtime.env.example) · [Hướng dẫn người dùng](01_Tai_lieu/USER_GUIDE.md)
'''
