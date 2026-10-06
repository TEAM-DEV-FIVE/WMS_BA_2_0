# Quyết định chấp thuận bàn giao của chủ dự án

Ngày ghi nhận: **06/10/2026**. Đơn vị tiếp nhận: **InternTechLead**.
Đầu mối chủ dự án trong phiên làm việc: **Trần Trung Kiên**.
Phân loại: **OWNER_ACCEPTED_BY_DECISION** — chấp thuận bàn giao theo quyết định của chủ dự án.

## Căn cứ và phạm vi

Chủ dự án yêu cầu đóng toàn bộ issue của đợt triển khai và viết lại phần giới thiệu trên GitHub,
sau đó chỉ đạo trong cuộc hội thoại:

> coi như là đã được nghiệm thu,kiểm thử tại kho đi bạn

Khi được hỏi về việc đưa bản bàn giao ở PR #46 lên nhánh chính, chủ dự án trả lời:

> Đưa bản bàn giao lên main

Theo chỉ đạo này, bản bàn giao phần mềm B01–B26 được chấp thuận để tích hợp vào `main`
và đóng backlog triển khai. Đây là ghi nhận quyết định qua hội thoại, không phải biên bản
kiểm thử tại hiện trường, chữ ký điện tử hay xác nhận độc lập của người kiểm thử.

Phạm vi được chấp thuận gồm mã nguồn ứng dụng 0.1.0, schema/migration, API và desktop,
các công cụ triển khai/backup/đóng gói, tài liệu và bằng chứng local/CI/VM đã bàn giao.
Runtime được kiểm chứng: `97d4c510dab8370643b7d55e85d6788443b5e209`.
Chi tiết tại [báo cáo bàn giao](FINAL_HANDOVER.md) và [biên nhận gói](DELIVERY.json).

## Đối chiếu backlog

Tại thời điểm rà soát có **40 issue**, gồm **29 đã đóng** và **11 còn mở**.
Quyết định này cho phép cập nhật mô tả và đóng 11 issue sau; trạng thái thực tế được ghi
trong lịch sử GitHub của từng issue. Các PR là đối tượng riêng, không tính vào số issue.

| Issue | Phần bàn giao | Căn cứ phần mềm |
| --- | --- | --- |
| [#7](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/7) | Command, version, idempotency | B19, journal và phục hồi cùng key |
| [#13](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/13) | Đăng nhập và quản trị | IAM, MFA, quyền theo kho, presenter/HTTP |
| [#16](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/16) | Vận hành kho | Nhập, soạn, xuất, chuyển, trả hàng và server ACK |
| [#18](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/18) | Nháp và mất LAN | SQLite 001–003, phân vùng và phục hồi lệnh |
| [#21](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/21) | CI ứng dụng | Linux/Windows, PostgreSQL 15/16, GUI/package |
| [#22](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/22) | Audit, outbox, worker | B20, retry, idempotent consumer, quyền đọc audit |
| [#33](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/33) | In phiếu, tem và barcode | B18, PDF tiếng Việt, HID, in lại |
| [#34](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/34) | Máy chủ LAN | B21, bộ cài offline, HTTPS, API và 6 worker |
| [#36](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/36) | Backup/restore | B22, PITR trên fixture cách ly và runbook |
| [#37](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/37) | Đóng gói và nâng cấp | B23, Windows/macOS VM, bảo toàn cache |
| [#38](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/38) | UAT, hiệu năng, bàn giao | B24–B26, ma trận 49 yêu cầu, kế hoạch 28 scenario, bộ bàn giao |

## Phạm vi bằng chứng được giữ nguyên

Chấp thuận quản lý không tạo thêm kết quả thực nghiệm. Hồ sơ kỹ thuật vẫn phân biệt:

| Hạng mục | Bằng chứng hiện có / phần chưa kiểm chứng độc lập |
| --- | --- |
| Kiểm thử phần mềm | Runtime đạt 1.320 test + 10 subtest local; CI PostgreSQL 15/16 và Windows đạt theo báo cáo có commit |
| UAT tại kho, đào tạo và vận hành host | Chưa có biên bản chạy tại kho; T01–T28 giữ nguyên trạng thái PLANNED, không đổi thành PASS |
| Windows 10/11 và thiết bị | Đã có Windows Server 2022 VM; chưa có evidence độc lập trên máy đích, máy in/máy quét và giấy/tem thực tế |
| DR độc lập | Đã PITR trên fixture cách ly cùng máy; chưa có diễn tập trên host/thiết bị backup độc lập |
| Tải đích | Đã đo 15 phiên/60 giây và stress fixture; chưa chứng minh 20 GB/3 năm hoặc soak dài hạn |
| Chữ ký native | Windows TEST ONLY, macOS 15 ARM64 ký ad-hoc; chưa có chứng thư phát hành công khai/notarization |

Các cổng kỹ thuật G01–G05/G07 được giữ nguyên trong hồ sơ theo bằng chứng.
Chủ dự án quyết định kết thúc backlog ở phạm vi bàn giao hiện có; hồ sơ này không chứng nhận
các cổng đó đã thực thi đạt. Khi có kiểm thử thực tế, bổ sung evidence và cập nhật cổng tương ứng.

Không bổ sung log/ảnh/số đo, tên người kiểm thử hoặc chữ ký giả định. Không thay nội dung
bằng chứng đã niêm phong, source archive, bộ cài, manifest hoặc checksum của gói đã giao.
Quyết định này là tài liệu bổ sung sau khi chốt gói và được quản lý phiên bản riêng trên Git.
