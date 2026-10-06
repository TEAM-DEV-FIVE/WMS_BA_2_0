# B21 — Runbook máy chủ LAN

Profile chọn Ubuntu Server 24.04 LTS amd64 / Python 3.12 / PostgreSQL 16 / Nginx 1.24 /
systemd 255, một server active, một kho/ba phân khu, tối đa 15 CCU. Ubuntu Server target
chưa được cung cấp; xem bằng chứng/giới hạn ở [bàn giao B21](PHAN_CONG/BAN_GIAO/B21.md).
Các lệnh dưới là runbook **cho máy đích đã được giao**, không phải ghi nhận đã thực thi.
Không chuyển máy vận hành trước khi có inventory, CA/DNS, cửa sổ bảo trì và restore plan.

## 1. Đầu vào, artifact và sizing

Điền bản ngoài Git của [inventory](../deploy/lan/inventory.example.json): hostname/IP/CIDR,
OS/kernel/architecture, CPU/RAM, version PostgreSQL/Python/Nginx/systemd/OpenSSL, UUID filesystem,
mount options, dung lượng/free/inodes, UPS, NTP, SAN/issuer fingerprint/expiry, wheel/commit,
manifest checksum, backup off-host và người vận hành. Lệnh đọc thực tế:

```bash
rtk proxy cat /etc/os-release
rtk proxy uname -a
rtk proxy lscpu
rtk proxy free -h
rtk proxy lsblk -f
rtk proxy findmnt
rtk proxy df -hT
rtk proxy df -i
rtk proxy timedatectl status
rtk proxy python3 --version
rtk proxy psql --version
rtk proxy nginx -V
rtk proxy systemd --version
```

Đề xuất ban đầu **4 vCPU, 8 GiB RAM**, disk SSD có UPS, root 40 GiB, PG 120 GiB,
file private 80 GiB, **backup mount riêng và bản off-host**. Đây là sizing cần đo B24, không
phải kết quả benchmark hay tư vấn mua phần cứng. 20 GB/3 năm → 6,67 GB/năm → **33,34 GB/5 năm**
với tăng trưởng tuyến tính; chưa tính index/bloat/WAL/temporary/report và chưa biết 20 GB gồm
file hay chỉ DB. Ngân sách thận trọng DB: 33,34 × 2 cho index/bloat + 20 WAL/temp, rồi giữ
25% trống → khoảng 116 GB, chọn 120 GiB. 80 GiB file là dự phòng độc lập cần chỉnh theo
import/PDF/print thực tế; không cộng hai số như một phép đo. Nếu số liệu đầu vào khác,
tính lại trước rollout. 7 process × pool 3 = tối đa 21 connection steady; monitor + migration
và quản trị dự phòng trong max_connections=60. Không tăng worker/pool tùy tiện.

Hồ sơ nghiệp vụ giữ ít nhất 5 năm, hiện ứng dụng không purge ledger/audit/ACK/outbox/receipt/
import/print snapshot; xem [B20](OUTBOX_OPERATIONS.md). TTL export/PDF dẫn xuất và log vận hành
30 ngày không phải hạn lưu hồ sơ. Backup không thay retention dữ liệu gốc. Dung lượng backup:
`số full giữ × kích thước full đo + WAL/ngày đo × số ngày giữ + overhead + 25% headroom`.
B22 chốt lịch/base+WAL/off-host/encryption và đo **RPO <1h / RTO <4h**; B21 chưa tuyên bố đạt.
Cảnh báo vận hành khi disk/inodes >=75%, khẩn >=85%; theo dõi tăng trưởng hàng tuần, dự báo
tháng hết chỗ. Không giải phóng bằng cách xóa pending/audit/receipt. Khi backup mount mất,
job backup phải fail closed thay vì ghi xuống root (B22).

## 2. Chuẩn bị release offline

Build từ commit được kiểm chứng, không chạy source checkout trong service. Mỗi release dùng
directory `/opt/wms/releases/<commit>`; version wheel 0.1.0 chưa đủ định danh, luôn ghi commit
và SHA256. Trên builder Linux amd64/Python3.12 tin cậy:

```bash
rtk proxy python -m build --wheel --no-isolation --outdir /tmp/wms-bundle
rtk proxy python -m pip download --only-binary=:all: -r requirements-app-lock.txt --dest /tmp/wms-bundle/wheels
rtk proxy cp requirements-app-lock.txt scripts/lan_runtime.py /tmp/wms-bundle/
rtk proxy cp scripts/lan_probe.py scripts/lan_stage.py /tmp/wms-bundle/
rtk proxy python -c 'import shutil; shutil.copytree("deploy/lan", "/tmp/wms-bundle/deploy/lan", ignore=shutil.ignore_patterns("__pycache__"))'
```

Giữ `deploy/lan` và các script probe/stage trong bundle để có đủ cấu hình trên target; mọi file phải có trong
`manifest.json` dạng `{relative_path: sha256}`. Manifest được tạo trên builder từ byte thực,
gửi **hash manifest qua kênh bàn giao tin cậy**; hash đi cùng gói không tự chứng minh nguồn gốc.
Không thêm secret/config máy đích vào bundle. Ví dụ tạo manifest:

```bash
rtk proxy python -c 'import pathlib,hashlib,json; p=pathlib.Path("/tmp/wms-bundle"); entries={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob("*")) if f.is_file() and f.name!="manifest.json"}; (p/"manifest.json").write_text(json.dumps(entries,sort_keys=True,indent=2)+"\n"); print(hashlib.sha256((p/"manifest.json").read_bytes()).hexdigest())'
```

Chuyển bundle theo kênh được giao. Trên server dùng script `lan_stage.py` đã review từ cùng
handoff, đường dẫn đích chưa tồn tại; kiểm tra SHA script riêng trước khi chạy quyền root:

```bash
rtk proxy sudo python3 /path/to/reviewed/lan_stage.py --bundle /path/to/bundle --destination /opt/wms/releases/COMMIT --manifest-sha256 TRUSTED_SHA256
```

Script kiểm mọi file/no symlink/no path traversal/no extra wheel, lock chỉ pin chính xác,
copy snapshot rồi kiểm lại, cài venv mới **offline/no-index/binary-only**, `pip check`.
Không đổi `current`, không migrate hay khởi động service. Stage lỗi để lại thư mục chẩn đoán,
không dùng lại làm release; tạo tên đích mới. Không sửa/move venv sau cài. Chown release root:root,
directories 0755/files non-writable bởi service; không `chmod -R 644` làm mất executable.
Không chép `.venv` phát triển lên server. Bundle đầy đủ dependency phải build/test lại trên target.

## 3. Tài khoản, storage và PostgreSQL

Cài các package `python3.12-venv`, `postgresql-16`, `postgresql-client-16`, `nginx`, `nftables`,
`ca-certificates`, `rtk` theo quy trình IT; RTK chỉ bọc lệnh runbook, service không phụ thuộc RTK.
Profile dùng cluster riêng `16-main`. Không áp cấu hình này lên cluster dùng chung.

```bash
rtk proxy sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin wms
rtk proxy sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin wms-migrate
rtk proxy sudo install -d -o root -g root -m 0755 /opt/wms/releases /etc/wms /srv/wms
rtk proxy sudo install -d -o wms -g wms -m 0700 /srv/wms/import /srv/wms/export /srv/wms/print
rtk proxy sudo install -m 0644 deploy/lan/runtime.env.example /etc/wms/runtime.env
rtk proxy sudo install -m 0644 deploy/lan/postgresql/wms.conf /etc/postgresql/16/main/conf.d/wms.conf
```

Mount `/var/lib/postgresql` và `/srv/wms` từ UUID trong inventory trước tạo dữ liệu. API/worker có
`RequiresMountsFor=/srv/wms /var/lib/postgresql`; phải có mount units/fstab đúng layout để phụ
thuộc này bảo vệ khi mount mất. Kiểm tra bằng reboot/unmount có kiểm soát. Không đặt storage
lên SMB client. Runtime user không vào group postgres/sudo, không sở hữu code/config.

DB dùng peer qua `/var/run/postgresql`: OS `wms` → DB `wms_app`; OS `wms-migrate` → DB
`wms_owner`. Không có DB password, không mở TCP và không cung cấp DSN cho desktop.
Review/copy hai template HBA/ident, giữ admin postgres local, kiểm đúng thứ tự first-match.
Chạy `roles.sql` **một lần**, tạo DB mới; không tự nhận schema unmanaged:

```bash
rtk proxy sudo -u postgres psql -X -v ON_ERROR_STOP=1 -f deploy/lan/postgresql/roles.sql
rtk proxy sudo install -o postgres -g postgres -m 0600 deploy/lan/postgresql/pg_hba.conf.example /etc/postgresql/16/main/pg_hba.conf
rtk proxy sudo install -o postgres -g postgres -m 0600 deploy/lan/postgresql/pg_ident.conf.example /etc/postgresql/16/main/pg_ident.conf
rtk proxy sudo -u postgres psql -X -c 'SELECT line_number,error FROM pg_hba_file_rules WHERE error IS NOT NULL'
rtk proxy sudo systemctl restart postgresql@16-main
rtk proxy sudo ss -lntp
```

PG phải không listen 5432. Runtime chỉ DML/sequence/function cần ứng dụng, không superuser,
owner/membership/CREATE/TRUNCATE/TRIGGER, không sửa migration history. Trigger bất biến vẫn
chạy. HBA/role privileges là bảo vệ tầng OS/DB; quyền kho/owner/MFA vẫn kiểm ở API.

## 4. MFA secret, migrate riêng và bootstrap

Khóa Fernet dùng chung mọi process/release và phải được B22 backup mã hóa tách biệt. Mất/đổi
khóa tùy tiện làm mất khả năng đọc MFA đã lưu. Tạo **chỉ lần cài mới** bằng Python của candidate,
không in ra terminal/history, không ghi đè file đang có:

```bash
rtk proxy sudo /opt/wms/releases/COMMIT/venv/bin/python -I -c 'import os; from cryptography.fernet import Fernet; fd=os.open("/etc/wms/mfa.env",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); f=os.fdopen(fd,"wb"); f.write(b"WMS_MFA_ENCRYPTION_KEY="+Fernet.generate_key()+b"\n"); f.flush(); os.fsync(f.fileno()); f.close()'
```

`mfa.env` root:root 0600; systemd `LoadCredential` cấp bản read-only riêng cho service.
Không đặt secret trực tiếp trong unit, command line, Git hoặc desktop. Runtime vẫn cần biến
môi trường trong process để dùng contract cũ; root/cùng service UID có thể đọc process, vì
vậy không dùng UID đó cho tác vụ không tin cậy. Không truyền secret qua shell `source`.

Tạo `/etc/wms/migration.env` root:root0644 từ runtime.env, chỉ đổi `wms_app` thành `wms_owner`.
Migration timeout mặc định30s cần đo trên restore dữ liệu trước rollout (tối đa config60s);
không tự mở rộng budget để bỏ qua failure. Run candidate explicit:

```bash
rtk proxy sudo systemd-run --wait --collect --unit=wms-migrate-release --uid=wms-migrate --property=LoadCredential=mfa.env:/etc/wms/mfa.env /opt/wms/releases/COMMIT/venv/bin/python -I /opt/wms/releases/COMMIT/lan_runtime.py migrate --config /etc/wms/migration.env
rtk proxy sudo -u wms-migrate psql -X -U wms_owner -d wms -v ON_ERROR_STOP=1 -f deploy/lan/postgresql/runtime-grants.sql
rtk proxy sudo systemd-run --wait --collect --unit=wms-preflight --uid=wms --property=LoadCredential=mfa.env:/etc/wms/mfa.env /opt/wms/releases/COMMIT/venv/bin/python -I /opt/wms/releases/COMMIT/lan_runtime.py check
```

Migration runner khóa advisory, kiểm prefix/checksum và transaction toàn bộ pending revisions.
Release **001–024 PostgreSQL, 001–003 SQLite** bất biến, không `dev027`, không sửa history bằng tay.
Grants chạy sau **mỗi** migration vì bảng mới không tự có grants. `check` kiểm PG16, exact schema,
role không đặc quyền/DDL, private roots tách nhau và ghi/fsync/xóa probe thật. API/worker start
đều tự check; **không tự migrate**. Nếu candidate migration lỗi thì giữ `current`/config cũ,
transaction rollback; candidate readiness503, bản cũ chỉ được mở lại sau preflight đúng release.

Bootstrap hai SYSADMIN ban đầu bằng terminal tại máy đích, từng username riêng, mật khẩu nhập
ẩn hai lần; không đặt password vào argv/env. CLI chỉ bootstrap theo giới hạn hiện có, không bypass
IAM. Dùng lần đầu, sau đó quản trị qua MFA và quy trình cấp quyền hai người:

```bash
rtk proxy sudo systemd-run --pty --wait --collect --unit=wms-bootstrap --uid=wms --property=LoadCredential=mfa.env:/etc/wms/mfa.env /opt/wms/releases/COMMIT/venv/bin/python -I /opt/wms/releases/COMMIT/lan_runtime.py bootstrap --username admin-one --display-name 'Quản trị một'
```

Lặp tên thứ hai. Đăng nhập và enroll MFA; SYSADMIN chưa có quyền kho tự động. Chốt policy/kho/kỳ
qua runbook module; không seed dữ liệu mẫu vào DB vận hành.

## 5. HTTPS, firewall và desktop

IT cấp DNS LAN ổn định, chứng thư serverAuth có **SAN đúng hostname/IP thực dùng**, chain đầy đủ,
private key root0600. CA private key **không đặt trên WMS server**. Copy chain/key vào
`/etc/wms/tls/server-chain.pem`, `server-key.pem`, thư mục root0700. Nginx master root đọc key,
worker www-data không được đọc storage/MFA. Review fingerprint CA qua kênh tin cậy; kiểm expiry
và lịch renew trước hạn30ngày. Dùng CA doanh nghiệp hoặc CA riêng được quản lý; không dùng
chứng thư test tự ký từ suite vào production.

Trước mở Nginx, tạo marker root0644 `/etc/wms/maintenance.on`; marker sống qua reboot và chỉ
xóa sau khi API/đủ sáu worker/TLS/smoke đều đạt. Sửa đúng `server_name` và Host guard trong
template, cài site rồi `nginx -t`; bỏ default site
HTTP80 trên host riêng. Không có redirect để che cấu hình HTTP client sai. Private API bind
127.0.0.1:8000; upstream không retry/cache; headers Authorization/Idempotency-Key/
X-WMS-Recovery/X-WMS-ACK/X-WMS-Rejected đi xuyên proxy. Body tối đa21MiB so với giới hạn
file ứng dụng tối đa20MiB; timeout có thể làm client UNKNOWN, chỉ phục hồi cùng key B19.

```bash
rtk proxy sudo nginx -t
rtk proxy sudo systemctl reload nginx
rtk proxy python scripts/lan_probe.py --url https://HOSTNAME/api/v1 --ca /path/to/trusted-ca.pem
```

Firewall template có CIDR **documentation-only**: thay theo inventory, không chạy nguyên xi.
Allow SSH22 chỉ admin CIDR, HTTPS443 chỉ client LAN; deny5432/8000 từ client. IPv6 HTTPS/SSH
đóng đến khi có range được giao; ICMPv6 vẫn cho phép để mạng hoạt động. Với console cứu hộ
sẵn sàng, `nft -c -f` rồi áp rules đã review và cấu hình persistence. Không flush firewall chung.
Từ máy client kiểm 443 OK, 5432/8000 không kết nối; từ mạng không được cấp,443 phải bị chặn.

Desktop Windows: cấu hình `WMS_API_URL=https://HOSTNAME/api/v1`, `WMS_CA_FILE=C:\...\ca.pem`,
local cache đúng profile người dùng. Bản tin cậy CA có thể nằm Windows trust store, hoặc file
CA chỉ đọc do IT phân phối theo cấu hình app. **Không dùng verify=False/-k**, không gửi MFA key,
DSN hoặc DB credential xuống client. Kiểm CA sai/hostname sai/expired cert đều thất bại;
login/MFA, quyền chéo kho, upload/export và nháp/phục hồi qua HTTPS thật. UI Windows thuộc
B23/B26; B21 loopback chưa thay smoke UI qua LAN.

## 6. Services, quan sát và shutdown

Sau migration/grants/check đạt, tạo `current` symlink tới release đã chọn (initial install),
cài các file systemd root0644. Một target gồm API + outbox/import/export/print/export-cleanup/
print-cleanup; mỗi kind một process cùng interpreter/registry/retry budget/storage.

```bash
rtk proxy sudo ln -s /opt/wms/releases/COMMIT /opt/wms/current
rtk proxy sudo cp deploy/lan/systemd/wms.target deploy/lan/systemd/wms-api.service deploy/lan/systemd/wms-worker@.service deploy/lan/systemd/wms-monitor.service deploy/lan/systemd/wms-monitor.timer /etc/systemd/system/
rtk proxy sudo systemctl daemon-reload
rtk proxy sudo systemd-analyze verify /etc/systemd/system/wms.target /etc/systemd/system/wms-api.service /etc/systemd/system/wms-worker@outbox.service
rtk proxy sudo systemctl enable --now wms.target
rtk proxy sudo systemctl status wms.target wms-api 'wms-worker@*' wms-monitor.timer
rtk proxy sudo journalctl -u wms-api -u 'wms-worker@*' --since '-10min'
```

`active` target/Type=simple không đồng nghĩa ready: yêu cầu HTTPS `/health`, `/ready`, monitor
exit0 và operations/workers `ready=true`, đủ sáu kind, không còn process hash cũ. Monitor mỗi60s
kiểm schema/storage/API và heartbeat120s. Failure ghi exit1/log metadata; IT nối cảnh báo
`systemctl --failed`, disk/inodes, TLS expiry, NTP và queue lag/dead-letter vào công cụ vận hành.
Timer không tự gửi thông báo và không tự restart service BUSY. BUSY >120s cần điều tra/benchmark,
không tự kill/cướp lease. API operations chỉ grant GLOBAL config.manage + MFA, không dùng token
quản trị tĩnh cho healthcheck. Restart on-failure backoff10s/5 lần300s; sau sửa lỗi dùng reset-failed.

Journal host riêng giới hạn1GiB/30ngày/giữ2GiB trống; copy drop-in journald sau review và restart
journald. Nginx status-only access log dùng rotation của package Ubuntu `/etc/logrotate.d/nginx`
(daily, compressed,14 rotations): xác minh glob bao gồm wms-access.log bằng logrotate --debug.
Error log request Nginx bỏ để không lộ URI/token; startup/config lỗi giữ theo log master có quyền
root. WMS không log payload/query/credential; PG ERROR có thể chứa giá trị DB, giữ log DBA-only,
không đưa log thô vào handoff. Log OS không phải audit nghiệp vụ5năm. Test log sentinel và quyền
đọc từ account không có quyền trước nghiệm thu target.

SIGTERM API drain tối đa60s, unit stop90s; worker dừng claim rồi hoàn thành/rollback batch,
unit stop360s, lease300s (giá trị ban đầu cần đo). KillMode control-group, không để process con cũ.
Nếu SIGKILL sau timeout, chờ lease hết và điều tra task/file/receipt trước restart. Không sửa
attempt/status/receipt bằng SQL để ép drain; không tự spool in lại.

## 7. Nâng cấp có dữ liệu và rollback

1. Stage/verify candidate trước maintenance; restore bản backup gần nhất vào **DB thử riêng**, chạy
   upgrade từ current có dữ liệu, đối chiếu stock/audit/job/ACK và migration checksum. Ghi hash
   current/candidate/config, compatibility matrix; chỉ B22 chứng minh restore/RPO/RTO.
2. Tạo `/etc/wms/maintenance.on` root0644 chặn toàn bộ LAN ingress503; thông báo cửa sổ vận hành
   theo người được giao. Giữ API loopback cho quản trị qua console, không cấp exception LAN tùy ý.
3. Quan sát operations/outbox/jobs bằng phiên quản trị MFA local tin cậy: registered pending/retry
   về0, task READY/RUNNING về0; dead-letter/EXHAUSTED có xử lý riêng. UNHANDLED giữ nguyên. Dừng
   cleanup/monitor khi cần snapshot nhất quán; không gọi `--once` là drain. Sau drain dừng target.
4. `systemctl stop wms.target`; xác minh API và **cả sáu worker** inactive, không process ngoài units.
   Snapshot/backup phối hợp DB+private storage+MFA/config theo B22; giữ secret tách artifacts công khai.
5. Chạy migrate của **candidate path**, grants và preflight (mục4) khi symlink current còn trỏ cũ.
   Failure: giữ symlink/config cũ; kiểm lại schema/data và start bản cũ nếu ready. Không start
   candidate ở trạng thái mismatch; proxy lỗi upstream503.
6. Migration thành công: chỉ đổi symlink lúc toàn bộ process cũ đã dừng. Tạo `current.next` rồi
   `mv -T` trên cùng filesystem `/opt/wms` để thay nguyên tử. Không rolling deploy hai registry.
   Áp config đã review chung mọi process; tuyệt đối không tăng retry budget để mở lại dead-letter.
7. Start target; kiểm 6 heartbeat/hash, schema, TLS và smoke nghiệp vụ; giữ maintenance đến khi
   các cổng đạt. Sau đó bỏ marker và kiểm desktopLAN. Reboot thật trong cửa sổ nghiệm thu,
   ghi systemctl/status/port/probe sau boot; verify mounts/account/sandbox.

Rollback ứng dụng chỉ khi wheel cũ `is_ready` với **exact revision+checksum hiện hành**, contract/
registry và dữ liệu mới tương thích. Với cùng schema có thể stop, đổi symlink+config về bộ trước,
start/check lại. Nếu schema đã tiến lên, runner cũ **cố ý từ chối extra revision**; không xóa lịch
sử/đổi checksum/downgrade SQL để chạy được. Chọn forward fix đã review hoặc B22 restore DB+files+
MFA đồng bộ vào môi trường cách ly, đối soát dữ liệu phát sinh trong cửa sổ và xin quyết định
nghiệp vụ trước thay dữ liệu vận hành. Không tự restore gây mất giao dịch mới. Giữ maintenance
khi chưa có phương án tương thích. API B19+ phải có trước client recovery mới.

## 8. Cổng nghiệm thu và nguồn kỹ thuật

T07: quyền kho/owner qua TLS thật; T11: MFA/revoke/token/cache/log/CA sai; T24: migration fail giữ
old release, startup fail closed, rollback và reboot; T26: workload15CCU và sizing/storage đo trên
target. Thành phần local không tự chuyển Txx sang PASS. NEEDS_ENVIRONMENT: máy/VM được giao,
LAN/client Windows, CA thực, console/firewall/reboot, mounts/backup và bài đo tải.

Tham khảo primary docs: [systemd credentials](https://github.com/systemd/systemd/blob/main/docs/CREDENTIALS.md),
[systemd sandbox directives](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml),
[Nginx proxy headers/retry](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[PostgreSQL16 HBA](https://www.postgresql.org/docs/16/auth-pg-hba-conf.html).
Đối chiếu thêm `man systemd.exec`, `nginx -t`, `pg_hba_file_rules` trên **version đích thực tế**.
