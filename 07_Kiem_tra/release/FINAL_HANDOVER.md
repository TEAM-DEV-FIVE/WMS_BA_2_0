# Bàn giao WMS — InternTechLead

**Quyết định bổ sung 06/10/2026:** chủ dự án chấp thuận bản bàn giao và yêu cầu đóng backlog,
tích hợp PR #46 vào `main`. Xem [OWNER_ACCEPTANCE.md](OWNER_ACCEPTANCE.md).
Quyết định này không thay đổi các kết quả thực nghiệm, cổng kỹ thuật và checksum bên dưới.

Runtime: `97d4c510dab8370643b7d55e85d6788443b5e209`, ứng dụng 0.1.0; protocol 1,
PostgreSQL 001–024, SQLite 001–003. Người nhận: Trần Trung Kiên.

## Phần mềm đã hoàn thiện

B01–B26 đã tích hợp mã, tài liệu, công cụ triển khai và đóng gói. Bản cuối sửa lỗi bố cục
master #14 ở cửa sổ 900 px với font rộng; thêm lịch sử import/export #19 theo tài khoản,
loại/kho/ngày/trạng thái, phân trang, mở lại job và kiểm tra quyền hiện tại.
Job hết hạn không tải lại file; metadata tối thiểu giữ đủ thông tin để áp quyền giá/hai kho/kiểm kê.
Tombstone đã bị bản cũ xóa scope không được dựng lại bằng suy đoán. Lệnh ghi/recovery cùng key không đổi.

## Bằng chứng phiên bản này

- Hồi quy local: **1.320 test + 10 subtest đạt, không lỗi hoặc skip**; thu cả `tests`, `deploy/lan/tests`,
  `deploy/backup/tests`, audit không thiếu/thừa node. Linux/Tk/Xvfb, PostgreSQL 16.15, Nginx 1.24 thật.
- [CI ứng dụng](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37471975858):
  Ubuntu/Windows unit/package, Windows GUI, PostgreSQL 15/16 đều đạt. Windows: 586 unit test + 10 subtest và 14 GUI test; PG15/16: 1.266 test + 10 subtest mỗi phiên bản.
- [Native VM](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37471976127):
  Windows Server 2022 x64 build/ký lab có timestamp/cài per-user/selftest/cache;
  macOS 15 ARM64 build/ký ad-hoc/deepstrict/selftest ngoài checkout đều đạt. Đã tải về và xác minh 1.069 hash trong Windows portable, checksum installer và archive Mac.
- [CI hồ sơ](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/actions/runs/37471975842) đạt.
- Wheel mới cài sạch ngoài checkout; module/entrypoint, health/OpenAPI 189 path, PGSQL/SQLite/PDF đạt.
- 49 yêu cầu / 28 scenario được mapping; verifier gói có 7 ca kiểm hash, thiếu/thừa file,
  traversal, duplicatekey và symlink. Chỉ test thành phần đạt, không tự đổi UAT sang PASS.

Evidence: [local environment](final-evidence/regression.environment.json),
[JUnit](final-evidence/regression.xml), [coverage](final-evidence/regression.coverage.json),
[nodes](final-evidence/regression.expected.json), [PITR](final-evidence/handover-final-drill.json),
[native jobs](final-evidence/native-final.run.json), [CI jobs](final-evidence/application-final.run.json),
[PG15](final-evidence/postgres-15.environment.json), [PG16](final-evidence/postgres-16.environment.json),
[native hashes](final-evidence/native-final.artifacts.json),
[wheel](final-evidence/handover-wheel.environment.json).

Lệnh hồi quy tái lập (interpreter đã cài lock, PG16tools và Nginx có trong PATH):

```bash
rtk proxy python scripts/check_application.py --gui --jobs 4 --expected-pg-major 16 --test-path tests --test-path deploy/lan/tests --test-path deploy/backup/tests --report .reports/final.xml
```

CI dùng 2 shard cho từng PG15/16, thu toàn bộ `tests`. Local bổ sung 54 test LAN/backup.
Mỗi shard dùng DB tạm riêng; runner đối chiếu toàn bộ collection, lỗi/skip/thiếu test đều làm fail.
Chỉ chuẩn hóa UUIDv4 ngẫu nhiên trong 3 test presenter cũ khi so nodeid.

## Gói giao

Thư mục `dist/wms-handover-97d4c51/` chứa:

- `server/`: wheel WMS, 58 dependency wheel có lock, script/config LAN và backup,
  HTTPS/API/6 worker và tài liệu vận hành.
- `clients/windows/`: installer EXE, portable ZIP,manifest,Install/Rollback,public cert TEST ONLY và selftest.
- `clients/macos/`: ZIP chứa WMS.app ARM64,release metadata và selftest.
- `source-<docscommit>.tar.gz`: mã nguồn/tài liệu đã commit; fullcommit ở deliverymanifest.
- `delivery-manifest.json`: hash từng file, runtime/source/native commit và migration.

Native và runtime cùng 97d4c51. Sourcecommit có thêm hồ sơ, không đổi mã ứng dụng/migration/lock.
`assemble.py` kiểm byte wheel theo Git và hash native trước ghép; `verify_delivery.py` kiểm sau chuyển.
Không chứa DB vận hành, mật khẩu, MFA/privateCA/PFX/signingkey.
Giữ nguyên gói sau khi chốt checksum; binary local cần tự lưu lâu dài vì artifact CI có hạn 14 ngày.

Lệnh kiểm sau nhận: `python 07_Kiem_tra/release/verify_delivery.py <gói> --manifest-sha256 <hash-bàn-giao>`.
Wheel và 58 dependency đã cài với `--no-index --only-binary=:all:` vào
`/tmp/wms-offline-final-97d4c51`, `pip check` đạt. Probe Python-I từ `/tmp` đạt 209 module,
189 path, 24 migration PG, SQLite/PDF. Các input đã cài được đối chiếu từng hash với gói server cuối;
config/scriptLAN+backup còn lại được kiểm bằng manifest và hồi quy LAN/backup.
[Log cài offline](final-evidence/offline-final-stage.log) · [Smoke](final-evidence/offline-final-smoke.json).
Hash và kết quả cài offline cuối được ghi trong `DELIVERY.json` cạnh báo cáo này sau khi ghép gói.
Cài server vào prefix mới bằng `scripts/lan_stage.py --bundle <gói>/server --destination <prefix-mới>
--manifest-sha256 <server_manifest_sha256>`; chạy `smoke_installed.py` bằng Python-I của prefix.
Không dùng prefix đang phục vụ để thử stage.

## Tiếp nhận và vận hành

Đọc [hướng dẫn bàn giao](../../01_Tai_lieu/HANDOVER.md),
[hướng dẫn người dùng](../../01_Tai_lieu/USER_GUIDE.md),
[sổ vận hành/nâng cấp/rollback](../../01_Tai_lieu/OPERATIONS_RUNBOOK.md),
[LAN](../../01_Tai_lieu/LAN_DEPLOYMENT.md), [backup/PITR](../../01_Tai_lieu/BACKUP_RESTORE.md).
Cấu hình đơn vị đã có: InternTechLead; Đông Thạnh,Hóc Môn,TP.HCM; MST 0869233973;
điện thoại 0329511628; tên người ký Trần Trung Kiên, ô chữ ký vẫn để trống.

G06 (lịch sử) và G08 (bố cục/CI) đã xử lý. **SOFTWARE_HANDOVER_READY / NEEDS_ENVIRONMENT**:
G01 UAT với người dùng; G02 Windows 10/11/LAN/máy in/quét/giấy thực; G03 DR độc lập/off-host;
G04 dữ liệu 20 GB / 3 năm/tải dài hạn; G05 chứng thư phát hành Windows / Apple Developer ID / notarization;
G07 host DNS/CA/firewall/alerting/đào tạo/bàn giao bí mật còn cần môi trường/người phụ trách.
User đã cho bổ sung thiết bị sau. Windows TEST ONLY và macOS ad-hoc là bản lab, không phải chữ ký công khai.
Không triển khai vào DB/host sản xuất, không ghi chữ ký hoặc giả kết quả thực tế.
T01–T28 giữ PLANNED; [recordUAT](uat-records.json) giữ scenario/steps gốc và actual/reviewer trống.
Các báo cáo tại 7b168c0/d9b5471 giữ nguyên là lịch sử; kết quả phiên bản này thay thế hai khoảng trống phần mềm cũ.

## Biên nhận gói đã chốt

Bản nén `dist/WMS-InternTechLead-97d4c51.tar.gz`, 138.180.025 byte, chứa hướng dẫn bắt đầu và
gói 116 file + manifest. Đã đọc lại toàn bộ 118 file trong tar và đối chiếu hash, không có symlink.
SHA256 archive: `45f0bf247ffb846b334819a29f2a9ce64e20a22a20b8ad381f80d4b836e4ab37`.
[Biên nhận đầy đủ](DELIVERY.json) · [Hướng dẫn bắt đầu](BAT_DAU_TAI_DAY.md).
Source archive giữ snapshot158f9da; biên nhận này được tạo sau ghép/nén, không đổi runtime97d4c51.
Issue #14/#19 đã cập nhật bằng chứng và đóng phần triển khai; các cổng nghiệm thu thực vẫn giữ mở.
