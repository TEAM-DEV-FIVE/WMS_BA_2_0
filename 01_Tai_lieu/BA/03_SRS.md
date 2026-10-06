# SRS - Yêu cầu hệ thống WMS
## 1. Phạm vi và nguồn
Áp dụng mô hình yêu cầu Ch7 PDF 6-21 và Ch8 PDF 5-33. Ranh giới WMS gồm desktop, API, dịch vụ nền và dữ liệu do ứng dụng quản lý. Con người và hệ thống ngoài là actor; DB và API bên trong ranh giới không vẽ như actor. Vai trò ngoài đời và grant quyền ứng dụng là hai khái niệm khác nhau.

requirements.json là danh mục có mã ổn định: 4 GR, 4 TR, 33 FR, 8 NFR; FR32–FR33 là phạm vi bổ sung từ Q02 ngày 02/10/2026, chưa có schema/API hiện thực. Mỗi yêu cầu có nguồn, owner, priority, trạng thái, tiêu chí nghiệm thu, UC và phiên bản. Chủ nghiệp vụ hiện được định danh theo vai trò vì chưa có danh tính người phụ trách. Các mục tiêu hiệu năng/đo lợi ích là PROPOSED, chưa benchmark hay được ký.

## 2. Ưu tiên và trạng thái
MoSCoW: Must - thiếu thì không hoàn thành mục tiêu cơ sở; Should - quan trọng nhưng có phương án tạm được chủ nghiệp vụ chấp nhận; Could - cải thiện tùy nguồn lực; Won't this release - ngoài đợt. Danh mục cơ sở đang ghi Must theo hồ sơ đã xây; workshop phải kiểm tra có thực sự cần trong đợt pilot. Không coi tất cả chức năng tương lai là Must. Danh mục ngoài phạm vi trong BRD là Won't ở đợt cơ sở.

Trạng thái quản lý: Draft -> Reviewed -> Validated -> Baselined -> Implemented -> Verified; Rejected/Deferred lưu lý do. Reviewed chỉ kiểm tra chất lượng đặc tả; Validated cần chủ nghiệp vụ xác nhận đúng nhu cầu. Hiện mọi yêu cầu ở Draft; việc kiểm tra file/mô hình không thay thế xác nhận stakeholder hoặc kiểm thử ứng dụng.

## 3. Mô hình chức năng
use_cases.json và USE_CASES.md chứa tên, actor, mô tả, ưu tiên, trạng thái, trigger, tiền/hậu điều kiện, luồng chính đánh số, nhánh và ngoại lệ, rule, NFR và kiểm thử. UC29 xác thực MFA mở rộng UC01 tại điểm sau kiểm tra mật khẩu nếu policy yêu cầu. UC22 include UC31 vì kiểm tra file là bắt buộc trước commit. UC30 duyệt là tác vụ độc lập có thời điểm/actor khác; không dùng include để diễn tả chờ duyệt bất đồng bộ. Đăng nhập hợp lệ thường là tiền điều kiện của nghiệp vụ, không vẽ include đăng nhập vào mọi UC.

Các use case cấp cao có nhiều vai trò giữ mã cũ để truy vết; bước thực hiện ghi rõ vai trò. Một role tham gia UC không đồng nghĩa có mọi quyền trong UC đó; quyền cụ thể tra ma trận và điều kiện server. Nhánh thay thế mô tả điều kiện và kết quả hoặc điểm quay lại; ngoại lệ timeout dùng UNKNOWN, không giả định chưa commit.

## 4. Dữ liệu và giao diện
ERD khái niệm sử dụng thuật ngữ nghiệp vụ, tên quan hệ là động từ và cardinality. ERD vật lý dùng tên bảng/cột thật, PK/FK, nullable và cardinality; tên bảng xuất hiện một lần trong mỗi trang. Các view là lát cắt mô hình, có mục lục toàn bộ; tập FK 105 quan hệ được đối chiếu schema. Bảng đích chỉ hiện cột liên quan và chỉ dẫn sang trang đầy đủ, không tạo thực thể alias lặp.

DBML/SQL/từ điển dữ liệu kế thừa cơ sở 1.1, không đổi dữ liệu chỉ để khớp hình. Partial index, composite unique và rule liên bảng tra SQL/INVARIANTS; crow's foot không thể hiện mọi invariant. Class có conceptual/domain và implementation views; visibility '-'/'+' và ngăn thuộc tính/phương thức là quy ước mô hình, không tuyên bố Python cưỡng chế private.

API OpenAPI lõi nằm 05_API; chưa bao phủ đủ mọi UC và chưa có server chạy. Ma trận truy vết ghi API của UC nào còn thiếu để bổ sung khi triển khai. Không được đánh dấu FR Verified chỉ vì tồn tại một path API.

## 5. Bảo mật, mở rộng và nghiệm thu
Áp dụng BR01-BR12; kiểm soát phải ở server và cùng transaction khi liên quan tồn. RACI không thay RBAC. Một người có vai trò quản lý ở kho A và nhận hàng ở kho B không được mang quyền duyệt sang B. Các mục tiêu kỹ thuật NFR01-NFR08 có cách đo; không ghi 'nhanh', 'an toàn', 'dễ mở rộng' mà không có tiêu chí.

Mở rộng theo chuỗi: nhu cầu mới -> GR/FR/NFR -> UC/BPMN -> policy -> class/API -> migration -> dữ liệu mẫu -> acceptance. Loại phiếu mới cần validator/state machine/posting strategy/report mapping; không ghi số dư trực tiếp. Thêm trường mô tả theo định nghĩa có kiểu; trường lõi dùng schema rõ. Multi-company/3PL cần thiết kế isolation riêng và chưa nằm trong bản này.

## 6. Quản lý thay đổi và xác nhận
Mỗi CR ghi lý do, người yêu cầu, ngày, yêu cầu bị ảnh hưởng, tác động quy trình/quyền/dữ liệu/API/test/chi phí/lịch, quyết định và người duyệt. Chỉ baseline sau workshop và ký; không tái sử dụng mã đã bỏ. Mẫu change_requests.json có dòng trống, không tạo quyết định duyệt giả. Checklist thẩm định: rõ nghĩa, đơn nhất ở mức acceptance, nguồn có thật, không mâu thuẫn, khả thi, đo được, truy vết hai chiều và đủ nhánh lỗi.

## 7. Các điều kiện còn phải xác minh
Q01–Q08 đã được tech lead trả lời trong bảng quyết định; trạng thái nguồn và follow-up được lưu trong open_questions.json. [Baseline TL01](../SCOPE_BASELINE.md) là căn cứ triển khai hiện hành. As-Is được vẽ như giả thuyết để phỏng vấn, To-Be là đề xuất. Schema, quyền và policy là thiết kế; acceptance_tests.csv là đặc tả test chứ chưa phải kết quả chạy PostgreSQL hoặc app. Bộ kiểm tra BA chỉ xác nhận tính nhất quán của hồ sơ và ký pháp đã dựng.

## 8. Bổ sung Q02 trong TL01

FR32/UC32 quản lý hàng ký gửi theo chủ sở hữu, FR33/UC33 tra cứu bảo hành theo serial. T27/T28 là đặc tả chưa chạy. Baseline 56 bảng/53 quyền chưa bao phủ hai UC này. Migration 006/007 và API/desktop mới có bằng chứng thành phần tại [TRACEABILITY.md](../TRACEABILITY.md); luồng posting/policy ký gửi và nghiệm thu T27/T28 còn thiếu, tham chiếu CR-TL01-Q02-20261002.
