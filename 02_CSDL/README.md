# Mô hình dữ liệu WMS

Bản hiện hành ngày 13/10/2026 ở [`current/schema.json`](current/schema.json), [`current/dictionary.csv`](current/dictionary.csv) và [`current/wms.dbml`](current/wms.dbml): **108 bảng, 736 cột, 219 FK** trong schema `wms`.

Snapshot được trích từ catalog PostgreSQL sau khi thực thi migration 001–026 trên cluster tạm. JSON giữ đầy đủ constraint và index; DBML/từ điển phục vụ tra cứu cột và quan hệ. Chạy `python scripts/export_report_schema.py --check` để đối chiếu lại từ SQL. Công cụ không kết nối DB vận hành.

`model.json` là thiết kế cơ sở 56 bảng, các `*_extension_model.json` ghi các phần bổ sung; không dùng riêng model cơ sở để đếm schema hiện tại. `avatar_extension*` bổ sung bảng `user_avatar` theo migration 026. Lịch sử migration đã phát hành được giữ bất biến.

[ERD hiện hành](../03_So_do/Hien_hanh/index.md) · [Quyền seed hiện hành](../04_Phan_quyen/current_permissions.json) · [Căn cứ báo cáo](../01_Tai_lieu/HIEN_TRANG_BAO_CAO.md).
