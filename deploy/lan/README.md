# B21 — Bộ triển khai LAN

Profile đích: **Ubuntu Server 24.04 LTS amd64, Python 3.12, PostgreSQL 16,
Nginx 1.24, systemd 255**. Cài security updates từ repository của distro và ghi version
thực tế vào inventory; không cố giữ một patch cũ. Local kiểm chứng trên Linux Mint 22.3
(Ubuntu noble), PostgreSQL 16.15; không thay bằng chứng cài/reboot Ubuntu Server thật.

Đọc [runbook](../../01_Tai_lieu/LAN_DEPLOYMENT.md) trước khi áp dụng. Không có secret trong bộ
này, không có installer tự sửa firewall/service/DB. Người vận hành chỉ chạy trên máy đích
được giao. B21 không cài service vào máy phát triển. T01–T28 vẫn giữ trạng thái tổng hiện tại.

| Đầu ra | Mục đích |
| --- | --- |
| `runtime.env.example` | Cấu hình chung API + sáu worker, release 024 và registry B20 |
| `systemd/` | API, template worker, target và timer quan sát; không tự migrate |
| `postgresql/` | Peer auth, owner tách runtime, không mở TCP, grants sau migration |
| `nginx/wms.conf.example` | TLS, status-only log, không retry upstream, giữ header B19 |
| `firewall.nft.example` | Allow-list SSH quản trị/HTTPS client trên server riêng |
| `journald/wms-limits.conf` | Giới hạn log host riêng; không phải retention hồ sơ kho |
| `inventory.example.json` | Sizing dự kiến, mounts, TLS và bằng chứng cần điền |
| [lan_stage.py](../../scripts/lan_stage.py) | Verify manifest tin cậy, cài wheel offline vào release mới |
| [lan_runtime.py](../../scripts/lan_runtime.py) | Secret injection, preflight, migrate riêng, API/worker/monitor/bootstrap |
| [lan_probe.py](../../scripts/lan_probe.py) | Kiểm TLS chain + hostname, health và exact-schema readiness |

Unit/API/PG tests bổ sung nằm ở `deploy/lan/tests/test_runtime.py`. Suite Linux riêng
dùng API/desktop/PG thật, CA tạm, port loopback không đặc quyền; không dùng CA tạm vào vận hành.
Cần executable `nginx` hoặc `WMS_TEST_NGINX_BINARY`; thiếu sẽ fail, không skip:

```bash
rtk proxy env PYTHONPATH=. WMS_TEST_NGINX_BINARY=/usr/sbin/nginx python scripts/check_application.py --expected-pg-major 16 --test-path deploy/lan/tests --report .reports/b21-lan.xml
```

Suite này không chứng minh boot/systemd sandbox/nftables hoặc LAN/Windows thật.
