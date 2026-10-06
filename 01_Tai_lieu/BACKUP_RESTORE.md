# Sao lưu và phục hồi WMS — B22

## Trạng thái và phạm vi

**CODE_READY local; backup off-host và nghiệm thu RPO < 1 giờ / RTO < 4 giờ: NEEDS_ENVIRONMENT.**
Người dùng chưa bàn giao thiết bị backup độc lập. Không cài service, sửa PostgreSQL vận hành,
mount/format đĩa hoặc thao tác `/dev/nvme0n1*`. Toàn bộ diễn tập dùng DB sinh mới, dữ liệu giả và
thư mục riêng dưới `/tmp`. [Bàn giao](PHAN_CONG/BAN_GIAO/B22.md) ghi commit và bằng chứng.

B22 kế thừa [B21 LAN](LAN_DEPLOYMENT.md): PG16 local Unix socket/peer, owner/runtime tách biệt,
API + sáu worker và monitor dưới `wms.target`, cờ `/etc/wms/maintenance.on` ngăn truy cập qua nginx.
Không đổi migration PG001–024/SQLite001–003, route, DTO, consumer hoặc thuật toán nghiệp vụ.

## Điểm phục hồi nhất quán

- Base vật lý `pg_basebackup --wal-method=stream --manifest-checksums=SHA256`, kiểm tra bằng
  `pg_verifybackup` trước khi công bố. Từ chối PG khác major16, standby và custom tablespace.
- WAL liên tục: tên hợp lệ, copy tạm + fsync + công bố bất biến, SHA256 riêng từng segment;
  ghi lại cùng byte được chấp nhận, cùng tên khác byte thất bại. Không chép đè hoặc xóa WAL cũ.
- Checkpoint ứng dụng: bật maintenance, dừng API, sáu worker **kể cả cleanup**, monitor/timer;
  kiểm tra không còn client DB, chụp tất cả private files/config/release và fingerprint 101 bảng WMS.
  Fingerprint trước/sau phải giống nhau; timestamptz chuẩn UTC. Không có DBA/migration/writer ngoài
  `wms.target` trong cửa sổ này. Snapshot không có khả năng khóa một DBA cố ý ghi song song.
- Kiểm tra file `stored_file` đúng import/export/print root, size/hash; upload chưa ready chưa phải
  file hoàn chỉnh. Bao gồm file chưa được tham chiếu để giữ job đang chờ. Từ chối symlink/special file.
  Release bundle gồm wheel chứa template/font, dependency wheels/lock và `lan_runtime.py`;
  kiểm tra manifest SHA đã nhận từ bàn giao trước base/checkpoint.
- Sau snapshot, lấy giờ DB, tạo commit boundary sau mốc đó, switch WAL và chờ archive. Manifest
  checkpoint ghim đủ WAL từ base đến boundary, system identifier, timeline, migration checksum,
  release, file hash và fingerprint. Thiếu segment thì không công bố checkpoint.
- Khởi động lại `wms.target`, chờ B21 monitor xác nhận API/sáu worker rồi mới gỡ maintenance do
  B22 tạo. Marker đã tồn tại thì cycle từ chối; restart không sẵn sàng thì giữ maintenance.
  Tiến trình bị kill/timeout cần vận hành điều tra, không tự gỡ marker.

**Chỉ phục hồi timestamp của checkpoint đã công bố**, chuỗi timestamp phải khớp chính xác manifest.
WAL đơn lẻ không đủ đảm bảo file đã bị cleanup còn tồn tại ở timestamp tùy ý. Đây là PITR đến
checkpoint ứng dụng, không cam kết restore nhất quán ứng dụng tại bất kỳ giây nào. Mỗi checkpoint
có dừng ghi; thời gian quét/hash tăng theo dữ liệu và phải đo trước khi bật lịch trên host thật.
Fingerprint hiện quét toàn bảng và sắp xếp hash, cần sizing RAM/IO ở tải 20 GB.

## Cấu hình đích khi có môi trường

Không thực hiện những bước này trên máy hiện tại. DBA/điều phối nhận volume và quyền quản trị riêng:

1. Một mount đã được cấp tại `/mnt/wms-backup` (root:root0755). Không có mount thì script từ chối,
   không fallback ghi vào filesystem chính. Provision `catalog` root:root0700 và `archive`
   postgres:postgres0700; cùng `.repository-id` ngẫu nhiên, file0600. Khởi tạo thư mục `wal`0700
   trong archive. ID/mount chỉ chống dùng nhầm đường dẫn, không chứng minh off-host hay mã hóa.
2. `/var/lib/wms-backup-staging` postgres:postgres0700, đủ dung lượng base tạm; `/srv/wms-dr`
   root:root0700 là root DR tách mọi PGDATA/storage/repository. Không dùng custom tablespace.
3. Cài ba script `wms_backup.py`, `backup_admin.py`, `lan_stage.py` đã kiểm checksum vào
   `/opt/wms/backup`, owner root, thư mục0755/file0644. Python hệ thống >=3.12, PG16 tools.
   `postgres` chỉ thực thi archive/fetch; root collector đọc MFA/private storage. Không cấp quyền
   đọc catalog chứa secret cho tài khoản ứng dụng hoặc client desktop.
4. Cấu hình `/etc/wms-backup/config.json` root:root0600 từ mẫu trong `deploy/backup`, thay UUID,
   commit40hex và manifestSHA64hex, xác nhận root import/export/print trùng cấu hình đang chạy.
   Backup đầy đủ `/etc/wms`, PG config, backup config/tools và bundle release bất biến.
   Repo catalog mẫu500GiB, archive mẫu100GiB là giới hạn cần sizing lại, không phải dung lượng yêu cầu.
5. Áp dụng mẫu archive config vào PG16 đích theo quy trình DBA (archive_mode cần restart), không đổi
   B21 peer/noTCP. Dùng cluster chuyên dụng WMS: physical backup chứa mọi database/role của cluster. Kiểm `pg_stat_archiver` và thử WAL trên môi trường được phép trước lịch tự động.
6. Chạy base đầu tiên, cycle đầu tiên, kiểm tra restore cô lập. Sau đó mới cài/enable ba timer mẫu:
   base02:00 hàng ngày, checkpoint mỗi15phút, monitor mỗi5phút. Không copy placeholder vào service.

Lệnh vận hành mẫu (sau provision; cần root):

```bash
rtk proxy sudo /usr/bin/python3 -I /opt/wms/backup/backup_admin.py base
rtk proxy sudo /usr/bin/python3 -I /opt/wms/backup/backup_admin.py cycle
rtk proxy sudo /usr/bin/python3 -I /opt/wms/backup/backup_admin.py monitor
```

Monitor fail khi checkpoint >=45phút, base >=36giờ, clock sai, archive lỗi mới hơn lần thành công,
thiếu/hỏng object/WAL, repository đầy hoặc system identifier/timeline không khớp primary.
Service thoát khác0 và journal chỉ event/code/metadata, không dump nội dung config/table/key.
Cần nối failed units/journal vào kênh cảnh báo người trực và thử nhận cảnh báo thực tế:
**NEEDS_ENVIRONMENT**. Kiểm thêm dung lượng PGDATA/staging/archive, backup chưa hoàn chỉnh và
service bị timeout; WAL của primary tiếp tục tăng khi archive lỗi. `max_wal_size` không giới hạn cứng.
Monitor kiểm base metadata/manifest; kiểm toàn byte PG bằng `pg_verifybackup` tại lúc tạo base và restore.
Cấu hình scheduler có hardening systemd; thao tác stop/start thực tế trên host chưa nghiệm thu.

## Retention và off-host

Hồ sơ nghiệp vụ tối thiểu5năm là chính sách dữ liệu WMS, không đồng nghĩa giữ mỗi WAL/base5năm.
Đề xuất cửa sổ phục hồi35ngày với base hàng ngày/checkpoint15phút, cần chủ hệ thống chốt dung lượng
và chính sách. Bản này **không tự purge**: mọi checkpoint đã công bố ghim base/WAL/objects của nó;
`retention-plan` verify tất cả checkpoint rồi báo pinned bases. Không dùng `find -mtime -delete`
hoặc `pg_archivecleanup` chung cho repository nhiều chain. Không sửa/xóa manifest để né verify.
Base tạm staging được giữ để điều tra; kiểm dung lượng và dọn đúng bản tạm sau khi catalog verify,
không xóa PGDATA. Hết dung lượng thì fail và cảnh báo, không tự xóa dependency.

Trước retention thực tế: có bản off-host đã verify+restore, xác định checkpoint còn giữ, tính hợp
base/WAL/timeline history/object được tham chiếu, review danh sách và chạy lại restore chain biên.
Chưa có thuật toán purge tự động được nghiệm thu; cần làm trước vận hành dài hạn theo lịch này.
Storage phải mã hóa at rest, quyền tối thiểu, truyền bảo mật và một bản độc lập/off-host với credential
và failure domain khác primary. Script local chưa mã hóa hoặc gửi off-host. Khóa MFA nằm trong
backup riêng0700/0600; không Git/email/journal. Checksum phát hiện hỏng byte, không thay chữ ký
hay immutable storage chống tài khoản đặc quyền sửa cả dữ liệu lẫn manifest.

## Diễn tập/khôi phục cô lập

1. Ghi UTC bắt đầu sự cố, target/checkpoint, phạm vi mất primary và dataset. Giữ primary mất kết nối
   với client; không để hai primary nhận lệnh. Không sửa bản backup nguồn.
2. Trên máy DR, dùng đúng PG16 và bộ script trusted đã review; mount bản backup độc lập read/write
   cho metadata khóa nếu cần, giữ quyền riêng. Cấu hình collector trỏ repository đúng ID và DR root
   mới; không cần primary online. Chọn checkpoint gần nhất trước sự cố, verify chain/checksum.
3. `restore-prepare` chỉ tạo một thư mục **chưa tồn tại** trong DR root:

```bash
rtk proxy sudo /usr/bin/python3 -I /opt/wms/backup/backup_admin.py restore-prepare --checkpoint CHECKPOINT_ID --target-time 'TIMESTAMP_EXACTLY_AS_MANIFEST' --destination /srv/wms-dr/drill-001
```

4. Chuyển ownership cây DR cho postgres, thư mục socket riêng0700; dùng `pg_ctl -D .../pg`
   với `-c config_file=.../postgresql.conf`, `-k .../socket`, cổng local riêng55432 và log riêng0600.
   Không dùng file config source để chạy server. Config sinh mới tắt TCP/archive/preload,
   xóa auto.conf cũ, sử dụng HBA riêng và **chỉ đọc WAL copy trong DR**. Socket trust được bảo vệ
   bởi directory0700 và OS owner; không mở TCP/client. Không đăng ký service vận hành tại bước này.
5. Chờ `pg_is_in_recovery()` và `pg_is_wal_replay_paused()` cùng true rồi:

```bash
rtk proxy sudo /usr/bin/python3 -I /opt/wms/backup/backup_admin.py restore-check --destination /srv/wms-dr/drill-001 --dr-socket /srv/wms-dr/drill-001/socket --dr-port 55432
```

   Kiểm chính xác migration/fingerprint toàn bảng, ledger/balance, reservation, serial/location và
   file đã tham chiếu. Không rebuild balance, xóa pending/outbox hoặc chỉnh ledger để làm số khớp.
   Lỗi WAL gap/base/object thì dừng, giữ log riêng và chọn chain lành khác; không promote để lờ lỗi.
6. Chỉ sau review thành công mới cho DBA resume/promote trên DR. Công cụ B22 không tự promote.
   Dựng release B21 từ bundle được verify, khôi phục config/MFA bằng quyền root0600 và storage cho
   wms0700, giữ maintenance. Dùng đúng PG peer/roles, không chạy migration mới để ép qua readiness.
7. Rehydrate API, outbox, import, export, print rồi hai cleanup workers; kiểm readiness/registry,
   heartbeat, job pending và file download. Đối soát lại sau replay. Không tự spool/in giấy lại;
   trạng thái in UNKNOWN cần người vận hành kiểm máy in. Không phát sinh execution/idempotency key mới.
8. Phục hồi tới quá khứ làm mất cả giao dịch **và ACK** sau target. Journal desktop có thể vẫn giữ ACK
   COMMITTED của dữ liệu đã mất; B19 không có cơ chế tự phát hiện một lần rollback toàn DB. Giữ client
   ngừng ghi, đối chiếu khoảng mất dữ liệu với journal/chứng từ thực tế trước mở LAN. Không tự replay
   mọi lệnh sau PITR hoặc coi NOT_FOUND/UNCONFIRMED là bằng chứng chưa có tác động ngoài hệ thống.
9. Sau khi hoàn tất đối soát, readiness/TLS từ client, xác nhận nghiệp vụ và cutover tách primary cũ,
   mới mở maintenance. Tạo base/checkpoint chain mới trên timeline mới; kiểm cảnh báo/off-host.
   Dừng và gỡ môi trường diễn tập sau khi đã lưu report không chứa secret.

## Đo lường và bằng chứng

RPO = thời điểm sự cố UTC trừ timestamp checkpoint thực sự phục hồi. Nếu timestamp gần nhưng
checkpoint không verify/restore được thì không tính là có recovery point. RTO bắt đầu từ sự cố
(mất primary), kết thúc khi dịch vụ được xác minh sẵn sàng cho nghiệp vụ sau đối soát/cutover.
Report local tách thời gian tới DB paused+đối soát và tới API+pending print replay; không gồm hardware,
provision, sao chép off-host, TLS, sáu worker systemd, 15CCU hoặc xác nhận nghiệp vụ.

Fixture có opening NONE+SERIAL, reservation, issue commit nằm trong WAL sau base, giao dịch sau target
bị loại, MFA mã hóa, PDF đã tạo, outbox print chờ và replay ACK đúng key. Snapshot thêm bytes import/export
và template/font; không suy đã test pending import/export workflow chỉ từ file fixture đó.
Đối soát toàn101bảng ở checkpoint. Thử sai timestamp/release, đích đã tồn tại, WAL thiếu/hỏng,
base/object corrupt, symlink, sai repository/permission, giới hạn dung lượng, monitor quá hạn và
retention không xóa chain. Lỗi vận hành systemd được test logic cô lập; không thay việc chạy host thật.

Nghiệm thu còn cần: volume/off-host/DR độc lập, tải đại diện15CCU/20GB/3năm, bandwidth/IO thực,
chu kỳ backup liên tục, cảnh báo tới người trực, retention biên, thao tác failover/tái lập sáu worker,
nghiệp vụ/desktop/thiết bị và số đo end-to-end. T09/T24 vẫn PLANNED theo điều phối.

Thiết kế dựa trên tài liệu PostgreSQL16: [continuous archiving/PITR](https://www.postgresql.org/docs/16/continuous-archiving.html),
[pg_basebackup](https://www.postgresql.org/docs/16/app-pgbasebackup.html),
[backup manifest](https://www.postgresql.org/docs/16/backup-manifest-format.html),
[WAL settings](https://www.postgresql.org/docs/16/runtime-config-wal.html).
