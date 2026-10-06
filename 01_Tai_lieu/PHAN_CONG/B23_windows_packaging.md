# B23 — Bộ cài Windows và nâng cấp an toàn

**Kích hoạt 06/10: READY trên nền B01–B20 đã tích hợp và kiểm thử.** Xem integration_log.json. Bảo toàn SQLite003, backup v1/v2, device identity và journal commands/receipts. Server hỗ trợ X-WMS-Recovery trước client; không downgrade cache. Theo dõi lỗi hosted Windows O_NOFOLLOW (#21), không bỏ/skip test để build xanh.

- Nhánh: `agent/b23-windows-packaging`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b23-windows-packaging`
- Trạng thái ban đầu: **WAITING_DEPENDENCIES**, ưu tiên **P1**.
- Phụ thuộc: [B08](./B08_ci_contracts.md), [B19](./B19_recovery_all.md)
- Issues liên quan: [#37](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/37), [#12](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/12) (đối chiếu snapshot local).
- Yêu cầu: FR28, TR02, NFR06, NFR07, NFR08.
- Bằng chứng liên quan: T08, T11, T22, T23; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B23.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Build artifact client Windows 10/11 x64 từ lock, manifest/checksum/version, tài nguyên Tk/font/cert và API compatibility handshake.
2. Cài mới/nâng cấp/khởi động lại, bảo toàn device identity/drafts/pending SQLite ngoài thư mục cài; xử lý cache migration failure và API không tương thích.
3. Runbook cập nhật/khôi phục app version tương thích, không downgrade cache phá dữ liệu; không bundle DB credential/dev secrets.
4. Kiểm tra login/MFA/scanner/printing/vietnamese scaling trên target; chứng thư ký code nếu được cung cấp, ghi rõ unsigned nếu chưa có.

## Phạm vi sửa chính

- `packaging/windows/ và workflow build Windows (mới)`
- `manifest version/API compatibility và scripts upgrade`
- `tests smoke cài đặt/nâng cấp trên Windows`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Máy Windows sạch cài artifact và chạy API thật; upgrade từ baseline có nháp/SENDING/UNKNOWN không mất hoặc double-post.
- Windows 10 và 11 x64: paths Unicode, quyền user thường, display scale, missing network/cert và restart.
- Verify installed package/resource/version/checksum; Linux cross-build không thay bằng chứng Windows.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Cần Windows 10/11 x64 VM hoặc máy thật và thiết bị liên quan; chứng thư ký code là đầu vào riêng nếu yêu cầu phát hành có ký.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b23-windows-packaging, nhánh agent/b23-windows-packaging. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B23_windows_packaging.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B23.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
