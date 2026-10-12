> Tài liệu lịch sử. Thông tin triển khai hiện hành nằm trong README.md và 01_Tai_lieu/HIEN_TRANG_BAO_CAO.md tại gốc dự án.

# Thiết kế kỹ thuật WMS desktop

WMS-DD-003 • Phiên bản 1.0 • 26/09/2026 • Bản thiết kế cơ sở để phát triển và thẩm định nghiệp vụ

**Đầu vào hiện hành:** [baseline TL01 ngày 02/10/2026](SCOPE_BASELINE.md). Số liệu ngân sách/tải/RPO ở dưới đã được đồng bộ; target bàn giao được chốt là server Ubuntu/Debian x64 và client Windows 10/11 x64; bỏ Mac. Các phương án Windows server/macOS dưới đây là tham khảo lịch sử, không phải cam kết hỗ trợ trong đợt này.

## 1. Các điều chỉnh đã tiếp nhận

UI Tkinter/ttk; giao tiếp qua LAN; máy chủ có phương án Linux, Windows và macOS. Một PostgreSQL trung tâm là nguồn chính thức. Không đặt file SQLite hay thư mục dữ liệu PostgreSQL lên SMB/NFS để nhiều desktop cùng mở. Không thiết kế ba server độc lập cùng ghi rồi tự đồng bộ số tồn.

Q01 đã xác nhận 200 triệu chưa gồm dự phòng 50 triệu, tổng số học 250 triệu. Phân bổ và phê duyệt chi thực tế cần bằng chứng sponsor; không tự tăng phạm vi ERP từ dự phòng.

Phạm vi vận hành Q05: một doanh nghiệp, một kho trung tâm/ba phân khu, tối đa 15 người đồng thời, khoảng 20 GB trong ba năm. Bộ dữ liệu cũ 5 kho/100 tài khoản/30 đồng thời/50.000 SKU/1 triệu dòng sổ/200 dòng mỗi phiếu chỉ là bộ thử sức tải riêng, chưa phải quy mô thực tế hoặc kết quả benchmark. Giữ 8 báo cáo, 4 mẫu in, 2 tem. Multi-company/3PL, giá vốn kế toán, RFID, PDA/native mobile và ghi sổ offline độc lập là hướng mở rộng riêng.

## 2. Kiến trúc triển khai qua LAN

Desktop Tkinter -> HTTPS nội bộ -> reverse proxy -> FastAPI application -> PostgreSQL. Worker dùng cùng application services cho outbox/export/import. Storage adapter lưu ảnh/tệp ngoài DB, metadata trong stored_file. PostgreSQL chỉ mở cho server/worker, desktop không có DB credential. DNS hoặc địa chỉ tĩnh cho API; chứng chỉ TLS do CA nội bộ cấp và được các máy tin cậy, không tắt verify_tls vì dùng LAN.

Server Linux: có thể chạy service hệ thống hoặc container theo runbook đã chốt. Server Windows: triển khai native service hoặc máy ảo Linux do IT quản lý; chọn một phương thức, không coi Docker Desktop là mặc định server production. Server macOS: phương án native service/launchd, phải kiểm thử restart, sleep, quyền đĩa và backup; tắt sleep trên máy vận hành. Cả ba dùng cùng code/API/schema nhưng script service và đường dẫn khác nhau. Đây là các phương án hỗ trợ cần nghiệm thu từng OS/version/architecture, không phải kết quả đã chạy thực tế.

Chọn một máy chủ active để pilot. Nếu cần dự phòng máy chủ thì dùng PostgreSQL standby/backup theo ADR sau, không dùng multi-master tự phát. LAN khác địa điểm cần kết nối mạng riêng do IT thiết kế, không giả định các kho xa tự cùng LAN. Sự cố switch/nguồn/server vẫn làm dừng post; UPS, backup ngoài máy và khôi phục có kiểm thử là hạng mục vận hành.

## 3. Ranh giới mô-đun

iam sở hữu user/role/permission/session; master sở hữu hàng/đơn vị/đối tác/vị trí; documents sở hữu phiếu và dòng; inventory sở hữu ledger/balance/item; fulfillment sở hữu giữ chỗ/soạn/kiện/chất lượng; approval sở hữu policy/request/step; counting sở hữu snapshot/đếm/khóa; operations sở hữu audit/outbox/import/export/file; extension sở hữu định nghĩa trường và phát hành client.

Domain không import tkinter, HTTPX hay SQLAlchemy. Application service điều phối authorization, transaction và domain rules. Repository/UoW là interfaces, infrastructure triển khai PostgreSQL/SQLAlchemy. Tkinter view gọi Presenter, Presenter gọi API client, không truy cập repository server. Các class diagram là mô hình thiết kế, không ánh xạ một class cho mỗi bảng.

Cấu trúc repo đề xuất: apps/desktop/{views,presenters,api,local_store,platform}; apps/server/{api,application,domain,infrastructure}; packages/contracts; migrations; tests/{domain,integration,contract,desktop}; deploy/{linux,windows,macos}; 01_Tai_lieu/adr. Shared contracts chỉ DTO/error codes, không chia sẻ ORM hoặc secret.

## 4. Desktop không đơ và không ghi thành công giả

Main thread sở hữu mọi widget. Executor/worker thực hiện HTTP và I/O; kết quả vào Queue; root.after poll trên UI thread. Request có sequence để bỏ kết quả cũ sau khi đổi phiếu; nút post khóa trong lúc gửi, nhưng server vẫn bắt buộc idempotency. Danh sách phân trang khoảng 100 dòng, debounce tìm kiếm, quét exact barcode. Không tải toàn bộ SKU vào Treeview.

SQLite cục bộ tách server/user/device. Draft có thể sync lại; operation key/payload được lưu trước khi gửi. SENDING sau crash thành UNKNOWN; tra operation, gửi lại cùng key khi cần. Chỉ server commit mới là POSTED. Không tự gửi lệnh xuất từ phiên quét offline khi kết nối trở lại. Token giữ trong RAM hoặc kho bí mật OS; nếu không có vault thì đăng nhập lại, không ghi token vào SQLite.

## 5. Mở rộng có kiểm soát

Thêm màn hình bằng view/presenter và hợp đồng API; thêm báo cáo qua query read-only, vẫn áp dụng scope/price permissions. Thêm loại chứng từ phải đăng ký validator, state machine, approval permissions, posting strategy, tests và report mapping. Không nhúng Python/SQL tùy ý vào cấu hình doanh nghiệp.

Trường bổ sung lưu JSONB theo định nghĩa có kiểu, có phiên bản; trường lõi vẫn là cột có FK/CHECK. Cần truy vấn nhiều thì migrate thành cột/index. Tích hợp tương lai đọc outbox event versioned và gọi API bằng tài khoản dịch vụ scope hẹp. Không tích hợp bằng ghi trực tiếp balance.

Migration theo expand -> deploy tương thích -> backfill có checkpoint -> chuyển client -> contract ở bản sau. Chỉ một migration runner; backend worker không tự migrate khi khởi động. API major version, schema version và client version độc lập. N/N-1 chỉ hỗ trợ sau khi contract tests đạt. Giữ nháp khi nâng cấp; build gói riêng theo OS và kiến trúc.

## 6. Định nghĩa báo cáo

R01 tồn theo vị trí: physical, eligible, reserved, available theo SKU/base UOM; transit riêng. R02 nhập-xuất-tồn: phát sinh đi qua ranh giới tập vị trí kho mới tính nhập/xuất, nội bộ không cộng đôi. R03 thẻ kho: thứ tự posted_at,id; ngày nghiệp vụ lọc riêng. R04 giữ chỗ: remaining = quantity-consumed-released và nhu cầu còn mở. R05 transit: phiếu chuyển, đã gửi, đã nhận, còn transit và biên bản mất/hỏng. R06 hạn dùng/tồn lâu: ngày hết hạn và ngày phát sinh cuối, không giả làm tuổi tồn theo lớp nhập. R07 kiểm kê: snapshot, từng lần đếm, số duyệt, delta, người duyệt. R08 hoạt động/giá trị: giá tham chiếu đúng effective_on, có nhãn giá quản trị, quyền giá riêng.

## 7. Triển khai và kiểm thử

Chọn chính xác OS/version/arch server và client trước khi khóa lịch. Cùng một server được thử với client Windows/Linux/macOS nếu doanh nghiệp cần cả ba. Server mỗi OS được chạy bộ integration, service restart, backup/restore, đường dẫn Unicode, TLS/firewall và file permissions. Không chỉ thử app mở cửa sổ.

Mục tiêu Q07: RPO giao dịch <1 giờ, RTO <4 giờ. Tệp đính kèm RPO 24 giờ và chu kỳ backup 30 ngày vẫn là giả định cần xác nhận riêng. Q08 yêu cầu giữ hồ sơ nghiệp vụ tối thiểu năm năm; chu kỳ backup không thay thế yêu cầu lưu hồ sơ. Base backup + WAL/PITR cần diễn tập trên môi trường khác. Không tuyên bố SLA hay HA từ một máy chủ. Tuần 24/240 ngày công không tự giữ nguyên khi thêm build/test ba OS; dùng dự phòng sau khi ước lượng hạng mục thực tế.

## 8. Cách dùng bộ file

02_CSDL/wms.dbml: nhập vào dbdiagram hoặc công cụ hỗ trợ DBML để xem toàn ERD. 02_CSDL/001_schema.sql: DDL nền PostgreSQL 15+ trên database trống; 02_CSDL/002_seed_permissions.sql: role/permission, không có user thật. 02_CSDL/data_dictionary.csv: từ điển toàn bộ cột. PostgreSQL-specific partial indexes, NULLS NOT DISTINCT và triggers nằm trong SQL, không coi export SQL từ DBML là bản đầy đủ tương đương.

03_So_do/00_Tong_hop/WMS_Design.drawio: mở và sửa offline bằng diagrams.net Desktop, mỗi bảng một trang ERD chi tiết, cùng các trang class/usecase đã tách đường nối. SVG dùng xem trong trình duyệt. PlantUML .puml là nguồn class/usecase/state/sequence có thể sửa. 03_So_do/00_Tong_hop/Diagram_Atlas.pdf chứa các sơ đồ vector, có thể zoom. Tài liệu chính và USE_CASES/RBAC/INVARIANTS bổ sung ngữ nghĩa mà ERD không thể biểu diễn.

Mau_nhap_lieu_WMS.xlsx và CSV templates dùng nhập dữ liệu. CSV examples chỉ minh họa. File API có thể import vào công cụ OpenAPI nhưng chưa đại diện server đang chạy. Bộ QA là acceptance specification, không phải báo cáo test ứng dụng đã pass.

## 9. Khoảng trống mô hình theo Q02 ngày 02/10/2026

Thiết bị điện tử/IT/văn phòng dùng serial hoặc lot theo SKU; thêm tra cứu bảo hành serial và hàng ký gửi theo FR32/FR33. Mô hình 56 bảng hiện tại chưa có chiều chủ sở hữu tồn kho; không thể phân biệt an toàn hàng doanh nghiệp và hàng ký gửi chỉ bằng ghi chú/JSONB. BE02/TL04 phải thiết kế migration, khóa và truy vấn theo chủ sở hữu, đảm bảo tất cả luồng reservation/post/count/import/report dùng cùng chiều. Contract quyền xuất và chuyển quyền ký gửi cần policy được chốt trước bật luồng. T27/T28 hiện là đặc tả chưa chạy. Không thay SQL trong TL01 để giả vờ đã hiện thực phần mới.
