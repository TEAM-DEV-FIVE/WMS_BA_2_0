> Bản hiện hành: [FINAL_HANDOVER.md](FINAL_HANDOVER.md), runtime97d4c51.
> Nội dung dưới đây là bằng chứng lịch sử tại7b168c0; hai lỗi phần mềm G06/G08 đã sửa
> và bộ cài đã rebuild. Giữ nguyên hash/kết quả cũ để truy xuất nguồn gốc.

# B26 — Bản bàn giao ứng viên và hồ sơ nghiệm thu

**RELEASE_CANDIDATE — chưa nghiệm thu/phát hành vận hành.** Phần chuẩn bị local B25/B26 đã được thực hiện;
T01–T28 giữ PLANNED. [Hướng dẫn bàn giao](../../01_Tai_lieu/HANDOVER.md),
[ma trận49yêu cầu](../handover/requirements.csv), [record28scenario](uat-records.json).

## Định danh gói

| Phần | Commit/nguồn |
| --- | --- |
| Runtime đã ghép B22/B24 | `7b168c010756c194a33872571cd59d6258712b06` |
| Source archive có B25 | `fb2e3d8` (full hash trong manifest) |
| Client native VM | `d9b547184626c168e54d7250b310568866e8cd41` |
| Giao thức/migration | client protocol1; PG001–024; SQLite001–003 |

`apps/`, `packages/`, `migrations/`, lock và pyproject ở nativecommit và runtimecommit có byte
giống nhau; `assemble.py` đã kiểm Gitdiff và từng file package trong wheel. B22 thêm backup/scripts,
B24 sửa runtime grants và test; bộ cài client cũ được giữ đúng commit, không gắn nhãn build mới giả.
Windows TEST ONLY, macOS ad-hoc không notarized. [Evidence native](../NATIVE_VM_2026_10_06.md).

Gói local ở `dist/b26-candidate-7b168c0/` trên coordinator,116file + `delivery-manifest.json`:
server/wheelhouse58wheel, LAN+backup+script/config mẫu; clients/windows; clients/macos;
source archive B25. Không chứa MFA/CAprivatekey/PFX/runtimeDB. File `.cer` là chứng thư public lab.

SHA256 manifest giao:
`ff43cc2a59d6bca4dc5df51f7b4cb9b7ff89d79eecbc806b9a069377b964b6a9`.
SHA256 manifest server:
`0b6a104e1016e81cecaeef5196a854e62295b4175064b85ea776256c1ea4d9e1`.
Người nhận cần lấy hash qua kênh tin cậy; hash trong cùng gói chỉ phát hiện thay đổi, không chứng minh danh tính.

Kiểm sau chuyển từ rootrepo:

```bash
rtk proxy python3 07_Kiem_tra/release/verify_delivery.py dist/b26-candidate-7b168c0 --manifest-sha256 ff43cc2a59d6bca4dc5df51f7b4cb9b7ff89d79eecbc806b9a069377b964b6a9
```

`assemble.py --help` mô tả cách tái lập; wheel input phải khớp commit từng byte, wheelhouse có
manifest đã tin cậy, native input phải khớp evidence. Destination mới hoàn toàn; không sửa gói sau khi
chốt hash. Source tar.gz gồm mã đã commit và B25; hồ sơ B26 hiện hành nằm riêng trong thư mục này.

## Kiểm thử/cài sạch

Hồi quy dùng PostgreSQL16 tạm, API/Nginx TLS thật và Tk/Xvfb; thu toàn bộ `tests`, `deploy/lan/tests`,
`deploy/backup/tests`. Bản bằng chứng cuối tại [báo cáo](VERIFICATION.md). Test load default trong
regression không thay số đo60s/1triệu move riêng của [B24](../../01_Tai_lieu/PHAN_CONG/BAN_GIAO/B24.md).

Stage đã chạy ở prefix mới `/tmp/wms-b26-offline-7b168c0`: `lan_stage.py`, pip `--no-index`
với58wheel và `pip check` đạt. Smoke bằng interpreter đã cài, `-I`, cwd`/tmp`:206modules đều từ prefix,
health/OpenAPI189paths,24PGSQL, SQLite nháp và PDF tiếng Việt đạt. Không migrate/start dịch vụ máy thật.

Lệnh tái lập trên **thư mục mới**, không dùng prefix đang phục vụ:

```bash
rtk proxy python3 scripts/lan_stage.py --bundle dist/b26-candidate-7b168c0/server --destination /tmp/wms-offline-NEW --manifest-sha256 0b6a104e1016e81cecaeef5196a854e62295b4175064b85ea776256c1ea4d9e1
rtk proxy /tmp/wms-offline-NEW/venv/bin/python -I 07_Kiem_tra/release/smoke_installed.py
rtk proxy python3 07_Kiem_tra/handover/check.py
rtk proxy python3 07_Kiem_tra/release/check_tools.py
```

Runbook máy đích: [LAN](../../01_Tai_lieu/LAN_DEPLOYMENT.md),
[vận hành/nâng cấp/rollback](../../01_Tai_lieu/OPERATIONS_RUNBOOK.md),
[backup](../../01_Tai_lieu/BACKUP_RESTORE.md). Cần áp grants B24 bằng owner khi triển khai;
chưa áp vào DB vận hành ở lần này.

## Cổng phát hành còn mở

| ID | Loại | Điều kiện đóng | Người phụ trách cần xác nhận |
| --- | --- | --- | --- |
| G01 | Nghiệm thu | Chạy đúng28scenario, actual/log/ảnh, người thực hiện/reviewer/decision thật | Người dùng kho + Trần Trung Kiên điều phối |
| G02 | Thiết bị | Windows10/11/LAN, máy in/HID/driver/giấy/DPI, Q06/Q08 và mẫu ký duyệt | IT + quản lý kho |
| G03 | DR | Backup độc lập/off-host, mã hóa, restore toàn chuỗi, RPO<1h/RTO<4h, retention5năm | IT/DBA + người quyết định cutover |
| G04 | Tải | Dữ liệu đại diện20GB/3năm,15CCU/soak, cả6worker có công việc, quy trình<15phút | QA + quản lý kho |
| G05 | Ký phát hành | Chứng thư phát hành Windows và AppleDeveloperID/notarization nếu phát hành Mac | Chủ tài khoản/chứng thư |
| G06 | Phần mềm còn thiếu | #19 danh sách lịch sử export đầy đủ: hiện UI chỉ job đang mở | Trần Trung Kiên; chưa tự defer requirement |
| G07 | Vận hành | Host inventory, DNS/CA/firewall/reboot/alerting, đào tạo và bàn giao bí mật thực | IT + người nhận bàn giao |
| G08 | Phần mềm/HostedCI | #14 master form tràn914px ở cửa sổ900px trên Ubuntu runner; PG15 có1fail, PG16cancelled; sửa layout và chạy lại CI | Trần Trung Kiên/người phụ trách UI |

Đây không phải danh sách được phép bỏ qua. Nếu thay scope phải có quyết định/CR thật; user đã cho
thiết bị bổ sung sau, nhưng chưa có nghĩa T22 hoặc bản production được nghiệm thu.

## Ghi kết quả UAT

`uat-records.json` giữ nguyên fixture/precondition/steps/expected từ CSV gốc và liên kết thành phần.
Các ô executor/reviewer/actual/commit/hash/time/evidence cố ýnull/rỗng. Người chạy ghi environment
thực, artifact hash, kết quả từng bước và tệp evidence đã lọc bí mật; lỗi ghi defect ID và chạy lại saufix.
`prepare_uat.py` chỉ tạo template, từ chối ghi đè record đã thay đổi để không làm mất bằng chứng.
Trước ký: kiểm đủ49requirements,28scenario, không còn gate/defect chưa có quyết định và thử rollback.
Agent không điền chữ ký hoặc đổi PASS thay người nhận.

Chưa push/tag/đóng issue/triển khai production trong đợt B25/B26 này. Các binary chỉ lưu local;
artifact GitHub native có thời hạn, cần giữ bản đã tải và hash cho bàn giao dài hạn.
