# Kiến trúc hiện hành và cách đọc sơ đồ

Các sơ đồ thiết kế gốc giữ nguyên cho truy vết. Runtime B01–B24 tại `7b168c0` được đọc theo các thành phần:

| Thành phần | Trách nhiệm và biên tin cậy |
| --- | --- |
| Desktop Tkinter | HTTP/TLS tới API; GUI trên main thread; worker cho I/O; SQLite003 chứa nháp và key, không credential DB |
| Nginx | HTTPS443, guardHost, maintenance503, chuyển header ACK/recovery; không public private storage |
| API FastAPI | IAM live, scope kho/owner/SOD/version; command kernel transaction ledger/balance/audit/outbox/ACK |
| PostgreSQL16 | Nguồn chính thức; PG001–024,101bảng; owner migrate riêng runtime role; runtime không DDL/sửa ledger |
| Outbox +5job/cleanupworker | Consumer chỉ enqueue trong transaction, executor I/O ngoài transaction, lease/fencing/generation |
| Private files | Import/export/print tách root; tải qua API kiểm quyền hiện tại; không URL tĩnh |
| Backup B22 | Base+WAL+checkpoint DB/files/config/MFA/release; restore cách ly trước promote/cutover |
| Thiết bị | HID chỉ nhập; OSspool ngoài DB; UNKNOWN cần kiểm thực tế, không exactly-once giấy |

Contract sinh tại [runtime OpenAPI](../05_API/openapi_runtime.json); mô hình gốc trong
[model.json](../02_CSDL/model.json) và các extension cùng thư mục, SQL release trong `migrations/`.
Đối chiếu `scripts/export_runtime_contract.py --check` và
`scripts/check_artifacts.py`, không lấy số bảng ở PDF cũ để kết luận DB mới thiếu/thừa.
Tài liệu [kiến trúc](../01_Tai_lieu/ARCHITECTURE.md), [recovery](../01_Tai_lieu/RECOVERY_ALL.md),
[vận hành](../01_Tai_lieu/OPERATIONS_RUNBOOK.md) quy định luồng hiện hành.
