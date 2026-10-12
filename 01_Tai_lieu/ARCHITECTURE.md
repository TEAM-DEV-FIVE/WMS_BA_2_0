# Kiến trúc WMS hiện hành

Đối chiếu mã nguồn ngày 13/10/2026. [Thiết kế cơ sở](ARCHITECTURE_BASELINE.md) được giữ riêng; số liệu ngân sách, sức tải và các phương án triển khai trong bản đó không phải kết quả đo của ứng dụng hiện tại.

![Kiến trúc hiện hành](../03_So_do/Hien_hanh/svg/ARCHITECTURE.svg)

## Các thành phần đang có

| Thành phần | Hiện thực và trách nhiệm |
|---|---|
| Desktop Tkinter/ttk | `apps/desktop`: view, presenter, API client, executor; UI chạy ở main thread |
| Nhật ký cục bộ | `apps/desktop/local_store`: SQLite chứa nháp/key/kết quả phục hồi theo máy chủ, người dùng và thiết bị |
| Phiên đăng nhập | `SessionVault` dùng kho bí mật hệ điều hành khi bật nhớ phiên; không lưu mật khẩu/refresh token vào journal |
| HTTP API | `apps/server/api/app.py` dựng FastAPI, route và middleware; hợp đồng DTO tại `packages/contracts` |
| Dịch vụ nghiệp vụ | `apps/server/application`: IAM, danh mục, chứng từ, phê duyệt, tồn, kiểm kê, báo cáo và các job |
| Transaction | `CommandBus`, giao thức `UnitOfWork`, `PostgresUnitOfWork` và `PostgresCommandRepository` |
| PostgreSQL | Nguồn dữ liệu chính thức: migration 001–026, schema `wms` gồm 108 bảng / 736 cột / 219 FK |
| Worker | Bảy loại: outbox, import, export, print, export cleanup, print cleanup, auth delivery |
| Tệp | Kho tệp riêng phục vụ import/export/PDF; tải qua API theo quyền |
| Triển khai LAN | Cấu hình Nginx và service trong `deploy`; TLS bên ngoài, API/DB phía máy chủ |
| Thiết bị | HID nhập mã như bàn phím; gửi lệnh in qua adapter hệ điều hành |

Nginx là thành phần của cấu hình triển khai LAN, không bắt buộc cho mọi lần chạy local. Sơ đồ không khẳng định máy người dùng đang chạy tất cả worker hoặc tích hợp ngoài.

## Lớp thực tế

Desktop: `DesktopShell` mở `OrderView`; sự kiện được điều phối bởi `OrderPresenter` và `IdentityClient`. `RecoveryJournal` dùng `CommandStore` để lưu lệnh cần khôi phục. Server: `OrderService` và `ReceiptService` phối hợp kernel lệnh, quyền và đơn vị công việc. Các DTO `OrderAction`, `ReceiptPost`, `OrderView`, `ReceiptView` nằm trong packages dùng chung.

Ba [sơ đồ lớp hiện hành](../03_So_do/Hien_hanh/index.md) sinh tên và thành viên từ AST Python. `apps/server/domain` hiện không phải hệ thống entity domain một lớp cho mỗi bảng; phần lớn xử lý nghiệp vụ nằm trong application services. Đây là mô tả cấu trúc mã hiện có.

## Lệnh và phục hồi

1. Desktop lưu nội dung/key trước khi gửi và thực hiện HTTP ở executor.
2. Dịch vụ server kiểm quyền, scope, trạng thái và version trong transaction; `CommandBus` tuần tự hóa key và kiểm hash.
3. Handler cập nhật dữ liệu và ghi kết quả chống trùng trong cùng đơn vị công việc; chỉ ACK hợp lệ mới được client coi là có kết quả xác nhận.
4. Mất phản hồi giữ UNKNOWN. Tra cứu chung dùng yêu cầu gốc cùng `X-WMS-Recovery: lookup-v1`; thiếu kết quả không làm thực thi nghiệp vụ. Người dùng có thể gửi lại đúng key/nội dung.

Chi tiết tại [commands.py](../apps/server/application/commands.py), [recovery.py](../apps/server/api/recovery.py), [bất biến](INVARIANTS.md). Không đánh đồng chống trùng giao dịch DB với bảo đảm máy in chỉ ra đúng một bản giấy.

## Vòng đời giao diện

Widget và hủy Tk ở main thread; I/O qua executor. Khi đóng hoặc bấm **Tải lại**, shell hỏi xác nhận, dừng nhận việc mới, chờ đóng tài nguyên nền rồi thoát. Nhánh tải lại khởi động lại ứng dụng sau khi nhả khóa phiên ứng dụng. Nút này nhận mã giao diện đã được cập nhật tại nơi chạy; không tải release từ mạng.

Nguồn: [shell](../apps/desktop/views/shell.py), [lifecycle](../apps/desktop/lifecycle.py), [entrypoint](../apps/desktop/__main__.py).

## Tài liệu đối chiếu

[Schema thực thi](../02_CSDL/current/schema.json), [OpenAPI runtime](../05_API/openapi_runtime.json), [26 mục chức năng có ảnh](../README.md), [nguồn và giới hạn bằng chứng](HIEN_TRANG_BAO_CAO.md), [runbook vận hành](OPERATIONS_RUNBOOK.md).
