# WMS — InternTechLead — Bàn giao phần mềm

Mã ứng dụng: 97d4c510dab8370643b7d55e85d6788443b5e209.
Source/tài liệu trong archive: 158f9dacc06fa76ca50a2d0a0193a55ecf78d54b.
Ứng dụng 0.1.0, PostgreSQL 001–024, SQLite 001–003.

1. Thư mục `wms-handover-97d4c51/clients/windows` chứa bộ cài EXE và portable ZIP.
   Bản Windows x64 ký TEST ONLY, đã cài/chạy thử trên Windows Server 2022 VM.
2. `clients/macos` chứa WMS.app trong ZIP, ARM64, đã ký ad-hoc/chạy thử trên macOS 15 VM.
   Hai bản là gói lab; chưa có chứng thư phát hành công khai/Apple notarization.
3. `server` chứa wheel WMS, 58 dependency wheel, config/script LAN và backup.
   Máy server cần chuẩn bị Ubuntu 24.04 x64, PostgreSQL 16, Python 3.12/venv/Tk và Nginx
   theo runbook. Gói wheel offline không chứa bộ cài hệ điều hành/PostgreSQL/Nginx.
4. Giải nén `source-158f9dacc06f.tar.gz` trong thư mục riêng. Đọc `01_Tai_lieu/HANDOVER.md`,
   `USER_GUIDE.md`, `OPERATIONS_RUNBOOK.md`, `LAN_DEPLOYMENT.md`, `BACKUP_RESTORE.md`.
   Kết quả chi tiết tại `07_Kiem_tra/release/FINAL_HANDOVER.md`; evidence local/CI nằm cùng source.

Kiểm tra sau chuyển gói, dùng verifier trong source đã giải nén:

```
python3 07_Kiem_tra/release/verify_delivery.py <đường-dẫn>/wms-handover-97d4c51 --manifest-sha256 4b80057cb0f693966e847bc44d0ec94de7d0dd2663fe74104925bfb82d0c0d7c
```

Server manifest SHA256: 6ab87d732ef36e128d2a984b0465bedbd224327f6841ad4baec43ba37a87d093.
Đối chiếu hash qua kênh bàn giao tin cậy. Hash trong cùng gói chỉ giúp phát hiện thay đổi.
`DELIVERY.json` là biên nhận được tạo sau ghép/nén, lưu trong repo bàn giao hiện hành;
source archive giữ nguyên snapshot trước khi ghép và không chứa biên nhận này.
Không ghi đè prefix đang phục vụ. Làm đúng runbook để bootstrap cấu hình/DB/quyền/HTTPS/worker,
chuyển giao bí mật riêng và diễn tập rollback trước triển khai kho thật.

Kiểm chứng: local 1.320 test + 10 subtest; CI PostgreSQL 15/16 mỗi bản 1.266 test + 10 subtest;
Windows 586 unit + 10 subtest và 14 GUI. Không lỗi hoặc skip. Cài offline sạch: 209 module,
189 API path, 24 migration PG, SQLite và PDF đạt. Các input đã cài khớp gói cuối từng byte.

Đã hoàn thiện phần mềm, gồm sửa #14 bố cục và #19 lịch sử import/export.
Nghiệm thu người dùng/thiết bị tại kho, DR độc lập, tải dữ liệu đích, chứng thư công khai và đào tạo
cần môi trường/người phụ trách thực tế. T01–T28 giữ PLANNED, không có chữ ký nghiệm thu tự điền.
Đơn vị: InternTechLead; MST 0869233973; điện thoại 0329511628; Trần Trung Kiên.
