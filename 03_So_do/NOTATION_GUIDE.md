# Ký pháp sơ đồ theo giáo trình Business Analysis

Nguồn gồm tám chương PDF, tổng cộng 358 trang. [Manifest giáo trình](reference_sources.json) lưu tên tệp, số trang và SHA-256. Số trang dưới đây tính từ trang đầu PDF, không theo số slide ở chân trang. Bản vẽ dùng dữ liệu WMS; không sao chép mô hình ví dụ trong giáo trình thành nghiệp vụ của dự án.

## Đối chiếu chương

| Chương | Trang PDF | Nội dung và cách áp dụng |
|---|---|---|
| 1 — Business Analysis Overview | 10–11, 22–32, 35–36 | Phân biệt nhu cầu, giải pháp và phạm vi; kiến trúc mô tả hệ thống hiện có |
| 2 — Business Context | 9–27 | Bối cảnh và mục tiêu; không suy ngân sách, KPI hoặc kết quả kinh doanh từ mã nguồn |
| 3 — BA Process Model | 6–9, 12–15, 20–35, 40–44 | Phân biệt khảo sát, phân tích và triển khai; nguồn của mô hình hiện hành là mã/schema |
| 4 — Investigation Techniques | 4–35, 37–47 | Phân biệt tài liệu, quan sát, phỏng vấn và workshop; không tạo biên bản khảo sát khi chưa có |
| 5 — Stakeholder Management | 8–24, 28–40 | Actor nghiệp vụ và stakeholder khác vai trò/quyền seed; không gán power/interest hay RACI khi thiếu xác nhận |
| 6 — Modelling Business Processes | 9–14, 15–23, 24–37 | BPMN: pool/lane, sự kiện, task, gateway và sequence flow |
| 7 — Managing Requirements | 6–21 | Truy vết yêu cầu/chức năng sang nguồn và bằng chứng; giữ riêng trạng thái nghiệm thu |
| 8 — Modelling Requirements | 5–23; 35–61; 64–71 | UML use case, ERD và UML class theo từng mức mô hình |

## UML use case

Sáu hình chia theo nhóm chức năng: actor hình người đứng ngoài **ranh giới WMS**, use case hình ellipse ở bên trong, association là đường liền không mũi tên. Tên use case thể hiện mục tiêu sử dụng, không thể hiện thứ tự màn hình.

Actor “Người dùng có quyền tương ứng” là vai trò tương tác ở mức tổng quát. Mỗi association có điều kiện cấp quyền tương ứng; không suy ra actor được làm mọi nghiệp vụ bằng một tài khoản. Quyền cụ thể xem mười hình `ROLE_*` và [catalog quyền](../04_Phan_quyen/current_permissions.json). Đăng nhập là tiền điều kiện của chức năng bảo vệ; không gán `include` cho mọi use case. Không thêm `extend` hoặc generalization chỉ để có đủ ký hiệu.

Ví dụ: [Use case vận hành kho](Hien_hanh/svg/UC_CURRENT_04.svg). Mẫu ký pháp: Ch8 PDF 7, 10, 14–15, 19, 21, 23.

## BPMN

Mỗi hình có một pool quy trình WMS, các lane chia trách nhiệm. Vòng tròn nét mảnh là start event; vòng tròn nét đậm là end event; chữ nhật bo góc là task; hình thoi có dấu **×** là exclusive gateway. Nhánh rẽ ghi điều kiện, đường liền có mũi tên là sequence flow. Màu hỗ trợ đọc, ý nghĩa nằm ở hình dạng và nét.

Lane là trách nhiệm thực hiện, không mặc nhiên là bảng phân công nhân sự. Tác vụ phê duyệt gộp các bước nội bộ đã có trong service. Một lần xử lý kết thúc không đồng nghĩa toàn bộ chứng từ đã hoàn tất: nhận/xuất/chuyển có thể thực hiện từng phần. Cột “Phạm vi / điều kiện” trong [mục lục](Hien_hanh/index.md) xác định tiền điều kiện và nhánh được mô tả. Bản vẽ chỉ hiển thị tiêu đề, đối tượng và quan hệ; chú giải ký pháp và nguồn được giữ trong tài liệu riêng. Các lỗi quyền, version, kỳ kho và giao dịch vẫn theo service được dẫn nguồn.

Ví dụ: [Nhận hàng](Hien_hanh/svg/FLOW_RECEIPT.svg), [Kiểm kê](Hien_hanh/svg/FLOW_COUNT.svg), [Nhập tệp](Hien_hanh/svg/FLOW_IMPORT.svg). Mẫu ký pháp: Ch6 PDF 9–14, 15–23, 24–37.

## ERD vật lý

Chọn **physical model** vì nguồn là catalog PostgreSQL đã thực thi. Mỗi bảng có tên, cột và kiểu; `PK`, `FK`, `?` biểu thị khóa chính, khóa ngoại, nullable. Quan hệ dùng Crow’s Foot kèm số ở hai đầu: `1`, `0..1`, `0..*`.

- Đầu bảng được tham chiếu là `1` nếu các cột FK bắt buộc, `0..1` nếu FK có cột nullable (MATCH SIMPLE).
- Đầu bảng chứa FK là `0..1` khi tập cột FK chứa một khóa UNIQUE/PK; nếu không là `0..*`. FK không ép bảng cha phải có bảng con nên cận dưới là 0.
- UNIQUE index có điều kiện chỉ được xét khi điều kiện là `IS NOT NULL` trên cột khóa; không suy lực lượng toàn cục từ index lọc theo trạng thái.
- Nét liền là quan hệ định danh khi toàn bộ FK thuộc PK của bảng con; nét đứt là quan hệ không định danh.
- FK ghép giữ nguyên tập cột và thứ tự; nhiều FK cùng trỏ một bảng vẫn là các quan hệ riêng, bảng đích không bị nhân bản.

Ví dụ: [document](Hien_hanh/svg/ERD_document.svg), [user_avatar](Hien_hanh/svg/ERD_user_avatar.svg). Mẫu ký pháp: Ch8 PDF 48–52. Các CHECK hoặc quy tắc theo loại chứng từ có thể thu hẹp điều kiện nghiệp vụ; hình thể hiện lực lượng cấu trúc theo khóa/nullable, catalog và service là nguồn đầy đủ.

## UML lớp

Implementation view với ba ngăn: tên lớp; thuộc tính; phương thức. Thành viên lấy từ AST mã đang có, lược chọn để hình dễ đọc; `…` trong ngoặc lược danh sách tham số. `+` là công khai, `−` là nội bộ theo quy ước tên Python; kiểu chỉ hiển thị khi có annotation.

Kế thừa dùng đường liền với tam giác rỗng hướng về lớp cha. Hiện thực `UnitOfWork` dùng đường đứt với tam giác rỗng; đây là structural protocol của Python. Dependency dùng đường đứt với mũi tên mở. Không tạo association, composition hoặc lớp domain chỉ dựa vào việc có bảng cùng tên.

Ví dụ: [Lớp desktop](Hien_hanh/svg/CLASS_DESKTOP.svg), [Lớp server](Hien_hanh/svg/CLASS_SERVER.svg), [DTO](Hien_hanh/svg/CLASS_CONTRACTS.svg). Mẫu ký pháp: Ch8 PDF 66–71.

## Sơ đồ bổ trợ và truy vết

Kiến trúc, trạng thái chứng từ, hoạt động phục hồi lệnh và vai trò/quyền được ghi đúng loại; không gọi chung là BPMN. Mỗi hình liên kết nguồn trong [diagram_sources.json](Hien_hanh/diagram_sources.json). Bộ thiết kế cơ sở vẫn lưu riêng để truy vết thay đổi; các giả thiết khảo sát trong bộ cũ không được chuyển thành dữ kiện của hiện trạng.
