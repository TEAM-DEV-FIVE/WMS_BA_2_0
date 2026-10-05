# Toàn bộ phần còn lại và nhánh phân công

**Cập nhật 05/10 sau B07/B17:** B01–B17 đã tích hợp (17/26 nhánh). B18 đủ dependency, cần đồng bộ trước khi giao triển khai.
B19/B20 còn chờ B18; B18–B26 chưa có code riêng. Xem [báo cáo mới](../../07_Kiem_tra/B07_B17_INTEGRATION_2026_10_05.md) và [sổ tích hợp](integration_log.json).

Ngày 03/10/2026 · Mốc mã đã tích hợp: `06041b7bc0c6e6515cb396d2ab5a29fae772df19`.
Nhánh điều phối: `feat/application-foundation`. Các nhánh mới lấy **cùng commit kế hoạch chứa tài liệu này**,
không lấy các nhánh agent cũ làm nền. [Quy trình agent](QUY_TRINH_AGENT.md) ·
[Catalog JSON](backlog.json) · [Sổ tích hợp](integration_log.json) · [Đợt trước](DOT_1_DA_TICH_HOP.md).

## Lịch sử hệ thống và phần còn lại tại mốc chia việc 03/10

Đã có nền FastAPI/Tkinter/PostgreSQL; đăng nhập/phiên/MFA, phân quyền kho và duyệt cấp quyền; danh mục,
PO/SO và phê duyệt; nhận hàng từng phần; truy vấn owner và bảo hành serial; backend tồn đầu kỳ COMPANY;
journal phục hồi receipt.post; engine outbox và desktop quản trị. Ba nhánh opening/outbox/admin-ui đã ghép.
Mốc này đạt **301 tests + 10 subtests local**, 0 failed/skip; runtime có 65 API paths và 10 migration PG.

Chưa đầy đủ: import/tệp và UI tồn đầu kỳ; xuất/giữ hàng, kiểm định/cất hàng, picking/packing; chuyển/trả/đảo;
kiểm kê và kỳ; ký gửi xuyên nghiệp vụ; IAM/danh mục/chứng từ UI nâng cao; custom fields; báo cáo/in;
recovery ngoài receipt.post; consumer thực tế và vận hành worker; CI được chạy trên target; triển khai LAN,
backup/restore, bộ cài Windows, tải/an toàn, tài liệu và UAT. Bảng dưới giao hết các phần này.

T01–T28 vẫn PLANNED đến khi đủ bằng chứng. Đây là audit mã và hồ sơ local, **không phải lần đọc lại trạng thái
GitHub trực tiếp**. Nhiều issue OPEN đã có một phần code; agent tiếp tục phần thiếu, không viết lại từ đầu.
Không quy đổi số test hoặc số nhánh thành phần trăm hoàn thành hay cam kết ngày xong.

## Lịch giao việc ban đầu — 03/10/2026

**8 nhánh READY:** B01, B02, B03, B04, B05, B06, B08, B15. Chỉ mở số agent phù hợp tài nguyên máy.
Nếu có 4 agent, ưu tiên B01 (import), B02 (xuất), B03 (quality/move), B08 (CI/contract); khi trống chỗ
giao B04/B05/B06/B15. Mỗi agent một worktree; không dùng chung DB tạm/server/cache/port.

**18 nhánh chờ phụ thuộc:** có thể đọc brief trước, bắt đầu triển khai khi các nhánh ghi ở cột phụ thuộc
đã tích hợp và worktree được đồng bộ lên mốc đó. B07 là P3 nhưng vẫn thuộc phạm vi; không tự bỏ khỏi MVP.
Không mở cả 26 agent lập trình ngay từ checkout ban đầu.

| ID / brief | Phần còn thiếu | Nhánh | Bắt đầu sau | Ưu tiên |
| --- | --- | --- | --- | --- |
| [B01](B01_import_files.md) | Tệp và import có kiểm tra trước khi ghi | `agent/b01-import-files` | **Giao ngay** | P1 |
| [B02](B02_issue_reservation.md) | Giữ hàng, xuất kho và đóng phần còn lại | `agent/b02-issue-reservation` | **Giao ngay** | P1 |
| [B03](B03_move_quality.md) | Kiểm định, cất hàng và di chuyển nội bộ | `agent/b03-move-quality` | **Giao ngay** | P1 |
| [B04](B04_iam_lifecycle.md) | Hoàn thiện mật khẩu, MFA và quản trị phiên | `agent/b04-iam-lifecycle` | **Giao ngay** | P1 |
| [B05](B05_master_traceability_ui.md) | Danh mục nâng cao, chủ hàng và bảo hành serial | `agent/b05-master-traceability-ui` | **Giao ngay** | P1 |
| [B06](B06_opening_ui.md) | Giao diện tồn đầu kỳ thủ công | `agent/b06-opening-ui` | **Giao ngay** | P1 |
| [B07](B07_custom_fields.md) | Trường mở rộng có kiểu và phiên bản | `agent/b07-custom-fields` | B14 | P3 |
| [B08](B08_ci_contracts.md) | CI, hợp đồng API và nền kiểm thử | `agent/b08-ci-contracts` | **Giao ngay** | P1 |
| [B09](B09_consignment.md) | Hoàn thiện nghiệp vụ hàng ký gửi và phân loại dữ liệu cũ | `agent/b09-consignment` | B01, B02, B03, B05, B06 | P1 |
| [B10](B10_fulfillment.md) | Soạn hàng và đóng kiện | `agent/b10-fulfillment` | B02, B03, B09 | P1 |
| [B11](B11_transfer.md) | Chuyển kho và nhận hàng đang vận chuyển | `agent/b11-transfer` | B02, B03, B09 | P1 |
| [B12](B12_returns.md) | Khách trả hàng và trả nhà cung cấp | `agent/b12-returns` | B02, B03, B09 | P1 |
| [B13](B13_count_period.md) | Kiểm kê, điều chỉnh và khóa kỳ | `agent/b13-count-period` | B02, B03, B09, B11, B12 | P1 |
| [B14](B14_reversal.md) | Đảo giao dịch và bảo toàn lịch sử | `agent/b14-reversal` | B02, B03, B09, B11, B12, B13 | P1 |
| [B15](B15_documents_ui.md) | Hoàn thiện PO/SO, phân công và màn hình duyệt | `agent/b15-documents-ui` | **Giao ngay** | P1 |
| [B16](B16_import_ui.md) | Giao diện import và theo dõi xử lý tệp | `agent/b16-import-ui` | B01, B06, B09, B15 | P1 |
| [B17](B17_reports_export.md) | Tám báo cáo và xuất dữ liệu có phân quyền | `agent/b17-reports-export` | B01, B02, B03, B09, B10, B11, B12, B13, B14 | P1 |
| [B18](B18_printing_scanner.md) | In chứng từ, tem và máy quét HID | `agent/b18-printing-scanner` | B05, B15, B16, B17 | P1 |
| [B19](B19_recovery_all.md) | Nháp và phục hồi mất LAN cho mọi luồng ghi | `agent/b19-recovery-all` | B01, B02, B03, B04, B05, B06, B07, B09, B10, B11, B12, B13, B14, B15, B16, B18 | P1 |
| [B20](B20_outbox_operations.md) | Consumer thực tế và vận hành worker | `agent/b20-outbox-operations` | B01, B08, B17, B18 | P1 |
| [B21](B21_lan_deployment.md) | Triển khai máy chủ và vận hành qua LAN | `agent/b21-lan-deployment` | B08, B20 | P1 |
| [B22](B22_backup_restore.md) | Sao lưu, PITR và diễn tập phục hồi | `agent/b22-backup-restore` | B21 | P1 |
| [B23](B23_windows_packaging.md) | Bộ cài Windows và nâng cấp an toàn | `agent/b23-windows-packaging` | B08, B19 | P1 |
| [B24](B24_concurrency_security.md) | Kiểm thử cạnh tranh, phân quyền và tải 15 CCU | `agent/b24-concurrency-security` | B04, B07, B08, B13, B14, B17, B19, B20, B21 | P1 |
| [B25](B25_docs_runbooks.md) | Tài liệu sử dụng, vận hành và hồ sơ bàn giao | `agent/b25-docs-runbooks` | B07, B15, B16, B17, B18, B19, B20, B21, B22, B23, B24 | P1 |
| [B26](B26_uat_release.md) | Nghiệm thu T01–T28 và chốt bản bàn giao | `agent/b26-uat-release` | B01, B02, B03, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, B14, B15, B16, B17, B18, B19, B20, B21, B22, B23, B24, B25 | P1 |

Các bước phụ thuộc chính: nhập/xuất/move → ký gửi → soạn/chuyển/trả → kiểm kê/đảo → báo cáo/in/recovery →
worker/LAN/backup/bộ cài/tải → hồ sơ/UAT. DAG trong JSON là danh sách phụ thuộc trực tiếp; B26 chờ tất cả B01–B25.
Phụ thuộc không buộc chờ đến nghiệm thu doanh nghiệp để lập trình: cần code/contract đã review và tích hợp;
các giới hạn môi trường vẫn được theo dõi đến B26. Việc thiếu một artifact/API bắt buộc thì vẫn chặn nhánh dùng nó.

## Thư mục và cách giao

Thư mục chung: `/home/kien/Đồ án KHMT2_2/worktrees/`. Mỗi thư mục mới dùng tên
`wms-bXX-<slug>` viết thường, giống phần sau `agent/` của nhánh. Ví dụ B02:
`/home/kien/Đồ án KHMT2_2/worktrees/wms-b02-issue-reservation`.
Đường dẫn đầy đủ và prompt từng agent nằm ngay đầu/cuối brief. Mở thư mục đó làm workspace của agent.

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b02-issue-reservation trên nhánh agent/b02-issue-reservation.
Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B02_issue_reservation.md và QUY_TRINH_AGENT.md cùng thư mục.
Kiểm tra dependency; triển khai đủ phạm vi và kiểm thử theo brief. Ghi báo cáo bàn giao đúng đường dẫn,
commit local rồi trả hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng.
```

Ba worktree `wms-opening`, `wms-outbox`, `wms-admin-ui` giữ nguyên làm hồ sơ đợt trước;
**không giao việc mới trên ba nhánh này** vì chúng chưa chứa đầy đủ bản ghép mới.

## Ranh giới tích hợp và migration

Mỗi brief có phạm vi file, đầu ra, test, handoff, phụ thuộc và đầu vào UAT. B01/B17/B18 bàn giao consumer
thực hiện enqueue DB, B20 ghép registry; file/network/print I/O chạy job executor riêng. B19 nối recovery sau
khi các command/form ổn định. Điều phối review các hook chung vào router/shell/orders/authorization/kernel.

Revision SQL của từng nhánh được dành tên riêng để dùng **DB test tạm**. Khi merge, điều phối chốt số tăng
tiếp theo và kiểm thử upgrade, vì runner chỉ nhận lịch sử là prefix của release. Không đổi revision đã tích hợp,
không lấy DB phát triển độc lập làm DB dùng chung; xem quy tắc chi tiết trước khi chạy migration.

## Các đầu vào vẫn cần để nghiệm thu

- Quy tắc/hợp đồng ký gửi và nguồn thời hạn bảo hành: B05/B09, không tự suy nghiệp vụ.
- Mẫu chứng từ được chọn, quyền giá/retention Q08; model/driver/khổ tem và scanner Q06: B18/B20/B25.
- Linux đích/LAN/TLS/storage, Windows 10/11 x64, backup storage/DR và workload đại diện: B21–B24.
- Người dùng nghiệp vụ/IT và người có quyền xác nhận kết quả/đào tạo: B25/B26.

Các điều kiện trên không ngăn viết code và test local độc lập. Chỉ đánh dấu NEEDS_ENVIRONMENT/NOT_RUN phần
chưa kiểm chứng; không tự ký biên bản hoặc báo đủ UAT. Không yêu cầu lại người dùng cấp quyền cho công việc
đã giao chỉ vì một brief có checklist review.

## Độ phủ issue trong hồ sơ local

37 issue OPEN đều có nhánh tiếp tục/kiểm chứng dưới đây. #1, #39, #41 đã CLOSED trong snapshot nên không
tạo nhánh riêng. Issue nền đã có implementation như #3 được giao xác minh/hoàn thiện, không coi là chưa viết.

| Issue | Công việc gốc | Nhánh chịu trách nhiệm phần còn lại |
| --- | --- | --- |
| [#2](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/2) | [BE01] Hoàn thiện hợp đồng API | [B08](B08_ci_contracts.md), [B25](B25_docs_runbooks.md) |
| [#3](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/3) | [TL02] Khởi tạo nền tảng ứng dụng | [B08](B08_ci_contracts.md) |
| [#4](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/4) | [BE02] Migration và hạ tầng PostgreSQL | [B01](B01_import_files.md), [B08](B08_ci_contracts.md), [B09](B09_consignment.md) |
| [#5](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/5) | [BE03] Đăng nhập, phiên và MFA | [B04](B04_iam_lifecycle.md) |
| [#6](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/6) | [BE04] Phân quyền theo kho | [B04](B04_iam_lifecycle.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md) |
| [#7](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/7) | [TL03] Command, version và idempotency | [B02](B02_issue_reservation.md), [B19](B19_recovery_all.md), [B24](B24_concurrency_security.md) |
| [#8](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/8) | [BE05] Danh mục hàng, kho và đối tác | [B05](B05_master_traceability_ui.md), [B09](B09_consignment.md) |
| [#9](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/9) | [BE06] Vòng đời chứng từ PO/SO | [B02](B02_issue_reservation.md), [B15](B15_documents_ui.md) |
| [#10](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/10) | [BE07] Phê duyệt và phân tách nhiệm vụ | [B02](B02_issue_reservation.md), [B13](B13_count_period.md), [B15](B15_documents_ui.md) |
| [#11](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/11) | [UI01] Thiết kế luồng màn hình | [B08](B08_ci_contracts.md), [B15](B15_documents_ui.md), [B25](B25_docs_runbooks.md) |
| [#12](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/12) | [UI02] Khung Tkinter và API client | [B15](B15_documents_ui.md), [B19](B19_recovery_all.md), [B23](B23_windows_packaging.md) |
| [#13](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/13) | [UI03] Giao diện đăng nhập và quản trị | [B04](B04_iam_lifecycle.md) |
| [#14](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/14) | [UI04] Giao diện danh mục | [B05](B05_master_traceability_ui.md) |
| [#15](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/15) | [UI05] Giao diện chứng từ và duyệt | [B15](B15_documents_ui.md) |
| [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) | [UI06] Màn hình vận hành kho | [B02](B02_issue_reservation.md), [B03](B03_move_quality.md), [B06](B06_opening_ui.md), [B10](B10_fulfillment.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B14](B14_reversal.md), [B18](B18_printing_scanner.md) |
| [#17](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/17) | [UI07] Giao diện kiểm kê | [B13](B13_count_period.md) |
| [#18](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/18) | [UI08] Nháp và phục hồi mất LAN | [B19](B19_recovery_all.md) |
| [#19](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/19) | [UI09] Giao diện import và báo cáo | [B16](B16_import_ui.md), [B17](B17_reports_export.md) |
| [#20](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/20) | [QA01] Kế hoạch nghiệm thu và fixtures | [B08](B08_ci_contracts.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| [#21](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/21) | [QA02] CI cho mã ứng dụng | [B08](B08_ci_contracts.md), [B21](B21_lan_deployment.md) |
| [#22](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/22) | [QA03] Audit, outbox và worker | [B20](B20_outbox_operations.md) |
| [#23](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/23) | [TL04] Ledger, balance và danh tính hàng | [B02](B02_issue_reservation.md), [B03](B03_move_quality.md), [B09](B09_consignment.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B13](B13_count_period.md), [B14](B14_reversal.md), [B24](B24_concurrency_security.md) |
| [#24](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/24) | [TL05] Nhận hàng và tồn đầu kỳ | [B01](B01_import_files.md), [B03](B03_move_quality.md), [B06](B06_opening_ui.md), [B09](B09_consignment.md), [B16](B16_import_ui.md) |
| [#25](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/25) | [TL06] Giữ hàng và xuất kho | [B02](B02_issue_reservation.md), [B09](B09_consignment.md) |
| [#26](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/26) | [TL07] Chuyển kho và di chuyển nội bộ | [B03](B03_move_quality.md), [B11](B11_transfer.md) |
| [#27](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/27) | [TL08] Trả hàng và đảo giao dịch | [B12](B12_returns.md), [B14](B14_reversal.md) |
| [#28](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/28) | [TL09] Kiểm kê và khóa kỳ | [B13](B13_count_period.md) |
| [#29](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/29) | [BE08] Soạn, đóng kiện và chất lượng | [B03](B03_move_quality.md), [B10](B10_fulfillment.md) |
| [#30](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/30) | [BE09] Định nghĩa trường mở rộng | [B07](B07_custom_fields.md) |
| [#31](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/31) | [QA04] Tệp và pipeline nhập dữ liệu | [B01](B01_import_files.md), [B09](B09_consignment.md), [B16](B16_import_ui.md) |
| [#32](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/32) | [QA05] Báo cáo và export | [B17](B17_reports_export.md) |
| [#33](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/33) | [QA06] In chứng từ, tem và barcode | [B18](B18_printing_scanner.md) |
| [#34](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/34) | [QA07] Triển khai máy chủ LAN | [B21](B21_lan_deployment.md) |
| [#35](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/35) | [QA08] Kiểm thử đồng thời và đối soát | [B24](B24_concurrency_security.md) |
| [#36](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/36) | [QA09] Diễn tập backup và restore | [B22](B22_backup_restore.md) |
| [#37](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/37) | [QA10] Đóng gói và nâng cấp desktop | [B23](B23_windows_packaging.md) |
| [#38](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/38) | [QA11] UAT, hiệu năng và bàn giao | [B25](B25_docs_runbooks.md), [B26](B26_uat_release.md) |

## Độ phủ 49 yêu cầu

GR/TR/NFR xuyên suốt và phần đã có vẫn phải được regression/kiểm chứng. B26 kiểm tra toàn bộ;
bảng ghi owner triển khai/kiểm chứng trước UAT, không tuyên bố tất cả các yêu cầu còn nguyên chưa làm.

| Yêu cầu | Nội dung | Nhánh triển khai/kiểm chứng |
| --- | --- | --- |
| GR01 | Quản lý truy vết nhận, xuất, chuyển và kiểm kê theo SKU/lô/serial. | [B02](B02_issue_reservation.md), [B03](B03_move_quality.md), [B09](B09_consignment.md), [B11](B11_transfer.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| GR02 | Phân quyền theo kho và phân tách người lập với người duyệt. | [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| GR03 | Bảo toàn lịch sử giao dịch tồn. | [B02](B02_issue_reservation.md), [B09](B09_consignment.md), [B14](B14_reversal.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| GR04 | Triển khai có nhập đầu kỳ, đào tạo và diễn tập phục hồi. | [B21](B21_lan_deployment.md), [B22](B22_backup_restore.md), [B25](B25_docs_runbooks.md) |
| TR01 | Hệ thống vận hành qua LAN. | [B21](B21_lan_deployment.md), [B25](B25_docs_runbooks.md) |
| TR02 | Target bàn giao: server Ubuntu/Debian x64 và client Windows 10/11 x64; không bao gồm Mac. Distro/version cụ thể do QA07 chốt trước nghiệm thu. | [B08](B08_ci_contracts.md), [B21](B21_lan_deployment.md), [B23](B23_windows_packaging.md), [B25](B25_docs_runbooks.md) |
| TR03 | Desktop Tkinter truy cập API; PostgreSQL tập trung là nguồn dữ liệu chính thức. | [B08](B08_ci_contracts.md), [B21](B21_lan_deployment.md), [B25](B25_docs_runbooks.md) |
| TR04 | Mở rộng theo mô-đun, API và migration có phiên bản. | [B07](B07_custom_fields.md), [B08](B08_ci_contracts.md), [B20](B20_outbox_operations.md), [B25](B25_docs_runbooks.md) |
| FR01 | Hệ thống phải hỗ trợ: Đăng nhập và MFA. | [B04](B04_iam_lifecycle.md) |
| FR02 | Hệ thống phải hỗ trợ: Cấp vai trò theo kho. | [B04](B04_iam_lifecycle.md) |
| FR03 | Hệ thống phải hỗ trợ: Nhập danh mục hàng và quy cách. | [B01](B01_import_files.md), [B05](B05_master_traceability_ui.md) |
| FR04 | Hệ thống phải hỗ trợ: Tạo kho và vị trí. | [B05](B05_master_traceability_ui.md) |
| FR05 | Hệ thống phải hỗ trợ: Lập và gửi yêu cầu mua. | [B15](B15_documents_ui.md) |
| FR06 | Hệ thống phải hỗ trợ: Nhận hàng từng phần. | [B03](B03_move_quality.md) |
| FR07 | Hệ thống phải hỗ trợ: Kiểm tra và cất hàng. | [B03](B03_move_quality.md) |
| FR08 | Hệ thống phải hỗ trợ: Lập yêu cầu bán và phiếu xuất. | [B02](B02_issue_reservation.md), [B15](B15_documents_ui.md) |
| FR09 | Hệ thống phải hỗ trợ: Giữ hàng theo lô/vị trí. | [B02](B02_issue_reservation.md) |
| FR10 | Hệ thống phải hỗ trợ: Soạn và đóng kiện. | [B10](B10_fulfillment.md) |
| FR11 | Hệ thống phải hỗ trợ: Xuất hàng từng phần. | [B02](B02_issue_reservation.md), [B10](B10_fulfillment.md) |
| FR12 | Hệ thống phải hỗ trợ: Xuất chuyển kho. | [B11](B11_transfer.md) |
| FR13 | Hệ thống phải hỗ trợ: Nhận chuyển thiếu hoặc từng phần. | [B11](B11_transfer.md) |
| FR14 | Hệ thống phải hỗ trợ: Khách trả hàng. | [B12](B12_returns.md) |
| FR15 | Hệ thống phải hỗ trợ: Trả nhà cung cấp. | [B12](B12_returns.md) |
| FR16 | Hệ thống phải hỗ trợ: Mở phiên kiểm kê. | [B13](B13_count_period.md) |
| FR17 | Hệ thống phải hỗ trợ: Đếm mù và đếm lại. | [B13](B13_count_period.md) |
| FR18 | Hệ thống phải hỗ trợ: Duyệt kiểm kê và điều chỉnh. | [B13](B13_count_period.md) |
| FR19 | Hệ thống phải hỗ trợ: Hủy hoặc đóng phần còn lại. | [B02](B02_issue_reservation.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B15](B15_documents_ui.md) |
| FR20 | Hệ thống phải hỗ trợ: Đảo lần ghi sổ sai. | [B14](B14_reversal.md) |
| FR21 | Hệ thống phải hỗ trợ: Khóa/mở kỳ. | [B13](B13_count_period.md) |
| FR22 | Hệ thống phải hỗ trợ: Import danh mục và đơn mở. | [B01](B01_import_files.md), [B16](B16_import_ui.md) |
| FR23 | Hệ thống phải hỗ trợ: Nạp tồn đầu kỳ. | [B01](B01_import_files.md), [B06](B06_opening_ui.md), [B16](B16_import_ui.md) |
| FR24 | Hệ thống phải hỗ trợ: Tra cứu và xuất báo cáo. | [B05](B05_master_traceability_ui.md), [B17](B17_reports_export.md) |
| FR25 | Hệ thống phải hỗ trợ: Nháp và phục hồi sau mất LAN. | [B19](B19_recovery_all.md) |
| FR26 | Hệ thống phải hỗ trợ: In tem và in lại chứng từ. | [B18](B18_printing_scanner.md) |
| FR27 | Hệ thống phải hỗ trợ: Sao lưu và khôi phục. | [B22](B22_backup_restore.md) |
| FR28 | Hệ thống phải hỗ trợ: Cập nhật app đa hệ điều hành. | [B19](B19_recovery_all.md), [B23](B23_windows_packaging.md) |
| FR29 | Hệ thống phải hỗ trợ: Xác thực yếu tố thứ hai. | [B04](B04_iam_lifecycle.md) |
| FR30 | Hệ thống phải hỗ trợ: Duyệt chứng từ. | [B02](B02_issue_reservation.md), [B06](B06_opening_ui.md), [B07](B07_custom_fields.md), [B13](B13_count_period.md), [B15](B15_documents_ui.md) |
| FR31 | Hệ thống phải hỗ trợ: Kiểm tra file nhập. | [B01](B01_import_files.md), [B16](B16_import_ui.md) |
| NFR01 | Phân quyền server phải chặn toàn bộ truy cập ngoài kho và tải file sau thu hồi quyền. | [B01](B01_import_files.md), [B04](B04_iam_lifecycle.md), [B17](B17_reports_export.md), [B18](B18_printing_scanner.md), [B21](B21_lan_deployment.md), [B24](B24_concurrency_security.md) |
| NFR02 | Thử lại sau mất phản hồi không tạo giao dịch tồn trùng. | [B01](B01_import_files.md), [B02](B02_issue_reservation.md), [B19](B19_recovery_all.md), [B20](B20_outbox_operations.md), [B24](B24_concurrency_security.md) |
| NFR03 | Thông báo phân biệt DRAFT, SYNCED, UNKNOWN và POSTED. | [B06](B06_opening_ui.md), [B15](B15_documents_ui.md), [B16](B16_import_ui.md), [B19](B19_recovery_all.md) |
| NFR04 | Mục tiêu phục hồi giao dịch RPO <1 giờ, RTO <4 giờ theo Q07. | [B22](B22_backup_restore.md) |
| NFR05 | Tải đại diện theo Q05: 1 kho trung tâm/3 phân khu, tối đa 15 CCU, khoảng 20 GB dữ liệu trong 3 năm. | [B17](B17_reports_export.md), [B21](B21_lan_deployment.md), [B24](B24_concurrency_security.md) |
| NFR06 | Máy trạm phải giữ nháp và mã thao tác khi nâng cấp hoặc khởi động lại. | [B19](B19_recovery_all.md), [B23](B23_windows_packaging.md) |
| NFR07 | Thao tác nhập chính hỗ trợ bàn phím và máy quét; chữ tiếng Việt rõ ở mức hiển thị OS đã chốt. | [B05](B05_master_traceability_ui.md), [B15](B15_documents_ui.md), [B16](B16_import_ui.md), [B18](B18_printing_scanner.md), [B23](B23_windows_packaging.md) |
| NFR08 | Mọi thay đổi mô hình phải giữ truy vết yêu cầu và tương thích dữ liệu đã phát sinh. | [B07](B07_custom_fields.md), [B08](B08_ci_contracts.md), [B20](B20_outbox_operations.md), [B21](B21_lan_deployment.md), [B22](B22_backup_restore.md), [B23](B23_windows_packaging.md), [B25](B25_docs_runbooks.md) |
| FR32 | Hàng ký gửi nằm trong kho nhưng chưa thuộc sở hữu doanh nghiệp; số lượng và truy vết phải tách theo chủ sở hữu trong mọi luồng tồn. | [B03](B03_move_quality.md), [B05](B05_master_traceability_ui.md), [B09](B09_consignment.md), [B10](B10_fulfillment.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B13](B13_count_period.md), [B14](B14_reversal.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md) |
| FR33 | Tra serial của thiết bị để biết NCC, receipt, ngày nhập và tình trạng bảo hành dựa trên dữ liệu thời hạn có nguồn. | [B05](B05_master_traceability_ui.md), [B09](B09_consignment.md), [B12](B12_returns.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md) |

## Độ phủ 28 kịch bản nghiệm thu

B26 chịu nghiệm thu cuối cho mọi T01–T28. Các nhánh dưới cung cấp test thành phần/tích hợp và evidence;
phải đọc kịch bản đầy đủ trong acceptance_tests.csv, không coi số Txx trên brief là bằng chứng đã chạy.

| Test | Kịch bản | Nhánh cung cấp bằng chứng trước B26 |
| --- | --- | --- |
| T01 | Nhận 80/100 và chuyển cách ly 5 | [B03](B03_move_quality.md), [B09](B09_consignment.md), [B25](B25_docs_runbooks.md) |
| T02 | Timeout sau COMMIT và kiểm soát Idempotency | [B02](B02_issue_reservation.md), [B06](B06_opening_ui.md), [B08](B08_ci_contracts.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B14](B14_reversal.md), [B19](B19_recovery_all.md), [B20](B20_outbox_operations.md), [B24](B24_concurrency_security.md) |
| T03 | Hai phiên PostgreSQL cùng xuất 7 từ tồn 10 | [B02](B02_issue_reservation.md), [B10](B10_fulfillment.md), [B24](B24_concurrency_security.md) |
| T04 | Chuyển kho 20 qua vị trí trung chuyển nhưng chỉ nhận 18 | [B11](B11_transfer.md), [B24](B24_concurrency_security.md) |
| T05 | Kiểm kê phát hiện 100 thành 98 với quy trình phê duyệt 2 bước | [B13](B13_count_period.md), [B24](B24_concurrency_security.md) |
| T06 | Cạnh tranh nhập cùng một mã Serial vào hai vị trí khác nhau | [B03](B03_move_quality.md), [B09](B09_consignment.md), [B12](B12_returns.md), [B24](B24_concurrency_security.md) |
| T07 | Người dùng phân quyền Kho A cố thao tác trên dữ liệu Kho B | [B01](B01_import_files.md), [B04](B04_iam_lifecycle.md), [B05](B05_master_traceability_ui.md), [B06](B06_opening_ui.md), [B08](B08_ci_contracts.md), [B13](B13_count_period.md), [B15](B15_documents_ui.md), [B16](B16_import_ui.md), [B17](B17_reports_export.md), [B18](B18_printing_scanner.md), [B21](B21_lan_deployment.md), [B24](B24_concurrency_security.md) |
| T08 | Quản lý bản nháp SQLite offline và xử lý crash khi đang ở trạng thái SENDING | [B19](B19_recovery_all.md), [B23](B23_windows_packaging.md) |
| T09 | Khôi phục thảm họa từ Base Backup và WAL, đo lường RPO và RTO | [B22](B22_backup_restore.md), [B25](B25_docs_runbooks.md) |
| T10 | Kiểm soát nghiệp vụ xuất trả nhà cung cấp và đảo giao dịch (Reversal) | [B12](B12_returns.md), [B14](B14_reversal.md), [B24](B24_concurrency_security.md) |
| T11 | Thu hồi phiên đăng nhập, xác thực MFA và bảo mật Token | [B04](B04_iam_lifecycle.md), [B08](B08_ci_contracts.md), [B19](B19_recovery_all.md), [B21](B21_lan_deployment.md), [B23](B23_windows_packaging.md), [B24](B24_concurrency_security.md) |
| T12 | Nhập liệu Master Data từ CSV/Excel với kiểm tra Dry-run và toàn vẹn mã băm | [B01](B01_import_files.md), [B05](B05_master_traceability_ui.md), [B16](B16_import_ui.md) |
| T13 | Phát hiện và ngăn chặn cấu trúc cây vị trí vòng lặp hoặc sai kho cha | [B03](B03_move_quality.md), [B05](B05_master_traceability_ui.md) |
| T14 | Đồng thời sửa đổi và phê duyệt chứng từ (Optimistic Lock & Stale State) | [B02](B02_issue_reservation.md), [B06](B06_opening_ui.md), [B07](B07_custom_fields.md), [B08](B08_ci_contracts.md), [B15](B15_documents_ui.md), [B24](B24_concurrency_security.md) |
| T15 | Hoàn thành soạn hàng (Picking) không làm thay đổi tồn vật lý trước khi xuất | [B10](B10_fulfillment.md), [B24](B24_concurrency_security.md) |
| T16 | Cạnh tranh giữa lệnh khóa kiểm kê (Freeze Location) và giao dịch xuất nhập kho | [B13](B13_count_period.md), [B24](B24_concurrency_security.md) |
| T17 | Hủy đơn hàng khi đang có giao dịch ghi sổ hoặc đã xuất kho một phần | [B02](B02_issue_reservation.md), [B10](B10_fulfillment.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B15](B15_documents_ui.md), [B24](B24_concurrency_security.md) |
| T18 | Cạnh tranh giữa hai yêu cầu đảo giao dịch (Reversal Concurrency) | [B14](B14_reversal.md), [B24](B24_concurrency_security.md) |
| T19 | Đóng kỳ kiểm kê và ngăn chặn ghi lùi ngày vào kỳ đã khóa (Period Close & Backdate) | [B13](B13_count_period.md), [B14](B14_reversal.md), [B24](B24_concurrency_security.md) |
| T20 | Nhập số dư đầu kỳ lặp lại và kiểm soát trùng lặp Serial | [B01](B01_import_files.md), [B06](B06_opening_ui.md), [B09](B09_consignment.md), [B16](B16_import_ui.md) |
| T21 | Kiểm tra ranh giới báo cáo Nhập-Xuất-Tồn (R02) và phân quyền che giá | [B11](B11_transfer.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md) |
| T22 | Kiểm thử máy quét mã vạch và in ấn nhãn tem, phiếu khổ chuẩn | [B18](B18_printing_scanner.md), [B23](B23_windows_packaging.md), [B25](B25_docs_runbooks.md) |
| T23 | Kiểm thử cài đặt và nâng cấp Client trên Windows x64 với tính tương thích ngược | [B19](B19_recovery_all.md), [B23](B23_windows_packaging.md), [B25](B25_docs_runbooks.md) |
| T24 | Kiểm tra các ràng buộc toàn vẹn cơ sở dữ liệu và Rollback giao dịch nguyên tử | [B01](B01_import_files.md), [B03](B03_move_quality.md), [B07](B07_custom_fields.md), [B08](B08_ci_contracts.md), [B09](B09_consignment.md), [B13](B13_count_period.md), [B14](B14_reversal.md), [B20](B20_outbox_operations.md), [B21](B21_lan_deployment.md), [B22](B22_backup_restore.md), [B24](B24_concurrency_security.md) |
| T25 | Ngăn chặn xuất kho hàng thuộc Lô hết hạn và giải phóng giữ chỗ an toàn | [B02](B02_issue_reservation.md), [B10](B10_fulfillment.md), [B24](B24_concurrency_security.md) |
| T26 | Kiểm thử tải đại diện 15 CCU trên mô hình 1 kho trung tâm/3 phân khu | [B17](B17_reports_export.md), [B20](B20_outbox_operations.md), [B21](B21_lan_deployment.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| T27 | Phân tách và quản lý tồn kho hàng ký gửi độc lập với hàng thuộc sở hữu doanh nghiệp | [B02](B02_issue_reservation.md), [B03](B03_move_quality.md), [B05](B05_master_traceability_ui.md), [B09](B09_consignment.md), [B10](B10_fulfillment.md), [B11](B11_transfer.md), [B12](B12_returns.md), [B13](B13_count_period.md), [B14](B14_reversal.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
| T28 | Tra cứu nguồn gốc phiếu nhập và thời hạn bảo hành theo số Serial | [B05](B05_master_traceability_ui.md), [B09](B09_consignment.md), [B12](B12_returns.md), [B17](B17_reports_export.md), [B24](B24_concurrency_security.md), [B25](B25_docs_runbooks.md) |
