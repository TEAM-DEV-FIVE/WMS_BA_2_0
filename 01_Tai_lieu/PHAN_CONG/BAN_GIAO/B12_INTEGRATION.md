# Tích hợp B12 vào nhánh điều phối

Ngày 2026-10-04. Người dùng giao trực tiếp “tích hợp b12”, sau khi đã cho phép đồng bộ và triển khai B12.

## Mốc ghép và phạm vi

- B12 bàn giao: `f37c0bb80fbd9f82c26494a71c9e00574f121039` trên `agent/b12-returns`.
- Base B12 đã đồng bộ: `ef99946038539483ed3e740b2dbd60594c7394c5`; giữ các commit nghiên cứu cũ.
- Khi bắt đầu tích hợp, phiên điều phối khác đang merge B11. Chuẩn bị tại worktree riêng
  `worktrees/wms-integrate-b12`, nhánh `integration/b12-returns`, không sửa/abort merge của phiên đó.
- Nền điều phối sau B11: `de729247ae4dc9f46e65863b428742e1411f30cb`, chứa merge `dce35f92b32015146f23d48229d641b558715b8c`
  và code `cc45621be81249e229655b1899f76bf1dbf4b313`. Đã đưa nền này vào bản ghép B12.
- Merge chuẩn bị `997aeac` giải quyết các hook B11/B12: lifecycle, snapshot, quyền, namespace sự kiện,
  direct posted progress, router và desktop. Giữ 16 mục menu cùng session/drain/close/finish cho cả ba tab mới.
- QC nhận RECEIPT/CUSTOMER_RETURN qua RECEIVE và TRANSFER qua ARRIVE, kiểm quyền theo kho nhận;
  đọc lại nguồn sau khóa để loại nguồn vừa bị đảo. Move khóa SO/PO → ISSUE/RECEIPT/TRANSFER →
  CUSTOMER_RETURN trước phiếu thực hiện. Quyền riêng kho đích của B11 vẫn được giữ.
- Không đổi nghiệp vụ returns đã bàn giao: khách trả về cách ly, serial/owner/bảo hành nguồn giữ nguyên;
  trả NCC bảo vệ reservation, COMPANY-only, không tự mở remaining PO/SO.

## Migration release

Revision phát triển chưa phát hành `018_b12_returns.sql` đổi thành **`016_b12_returns.sql`**,
nối tiếp B11 release 015. Chỉ đổi tên/comment của migration B12; DDL giữ nguyên.
Model/DBML/tài liệu cập nhật số release; catalog/brief và báo cáo lịch sử giữ số phát triển.
Schema tổng: **78 bảng, 514 cột, 164 FK**, 16 migration release liên tục 001–016.

Đối chiếu byte 001–015 với nền B11; không sửa revision đã tích hợp. Bổ sung upgrade từ prefix **015**
cho kiểm legacy ledger/UNCLASSIFIED/checksum và bảo toàn approval policy tùy chỉnh, ngoài các mốc 005/010/013/014.
Runner chỉ dùng PostgreSQL tạm riêng; không đổi lịch sử DB từng chạy 018 hoặc DB vận hành.

## Kiểm chứng trên bản ghép

Linux, Python 3.12, PostgreSQL 16, Tk/Xvfb, HTTP thật. Dùng venv điều phối chỉ đọc và PYTHONPATH trỏ
worktree tích hợp. Không thêm dependency. Các thay đổi nhập từ commit cuối B11 khi test đang chạy
chỉ gồm tài liệu/DBML/checksum, không đổi mã, tests hoặc SQL đã đưa vào lượt kiểm thử.

- Hồi quy toàn bộ: **551 passed + 10 subtests, 0 failed/errors/skipped**, 639.09s.
  JUnit tại `.reports/b12-integration-full.xml` trong worktree tích hợp, sao chép nguyên byte sang điều phối
  khi chốt merge; không gọi đây là lượt chạy riêng tại điều phối. Có 3 deprecation warnings của thư viện; không skip hoặc xóa test.
- Ruff apps/packages/tests/foundation/runner: PASS.
- Runtime OpenAPI export/check: PASS, 116 paths.
- Build sdist/wheel: PASS; gói ở `.reports/b12-integration-dist/`. Cả hai chứa đúng 16 migrations
  001–016, byte SQL và 12 module B11/B12/hooks khớp nguồn; không có 017/018 phát triển.
  Kết quả và SHA gói tại `.reports/b12-integration-package.json`.
- Artifacts/model/dictionary/DBML/import ZIP/528 SHA và whitespace: PASS; regenerate sau cập nhật
  kết quả cuối và sổ tích hợp. Byte 001–015 khớp nền B11; DDL 016 khớp 018 ở commit B12.

Lệnh tái lập từ worktree tích hợp (hoặc dùng `.venv/bin/python` tại điều phối):

```bash
rtk proxy env -u WMS_DATABASE_URL -u WMS_TEST_DATABASE_URL -u PYTEST_ADDOPTS PYTHONPATH="$PWD" xvfb-run -a '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_application.py --gui
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m ruff check apps packages tests/foundation scripts/check_application.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/export_runtime_contract.py --check
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' -m build --no-isolation --outdir .reports/b12-integration-dist
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/update_artifacts.py
rtk proxy env PYTHONPATH="$PWD" '/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/.venv/bin/python' scripts/check_artifacts.py
rtk proxy git diff --check
```

## Trạng thái và giới hạn

Đã merge vào `feat/application-foundation` tại **`97947c9d0202e73ef56a67b19535f7e105adb5d1`**,
ghi **INTEGRATED** cùng source và commit thực vào `integration_log.json`. Tree của merge khớp hoàn toàn
với commit bản ghép đã kiểm chứng `5ddf830`; sau đó chỉ cập nhật báo cáo/sổ tích hợp/checksum. Giữ worktree/commit B12 tính năng để review; không kích hoạt nhánh khác.
Bằng chứng lịch sử trước tích hợp ở [B12.md](B12.md); contract ở [RETURNS.md](../../RETURNS.md).

Windows, thiết bị, LAN mục tiêu, 15 CCU, DR, hosted CI và UAT: **NOT_RUN**.
T01–T28 giữ nguyên trạng thái nghiệm thu. Ký gửi/unlinked/RMA chưa bật; recovery bền vững sau restart
chờ B19, lệnh chưa rõ kết quả hiện giữ trong RAM theo scope. Không push hoặc triển khai DB vận hành.
