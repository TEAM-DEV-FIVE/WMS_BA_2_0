# Giao diện quản trị WMS

## Phong cách ERP tham chiếu ECOUNT

Giao diện nghiệp vụ được chỉnh theo ảnh ECOUNT người dùng cung cấp ngày 08/10/2026:
header trắng, thanh nhóm chức năng xanh đậm, menu cây bên trái, các tab công việc đầu vát,
biểu mẫu gọn, bảng dữ liệu nền sáng và nút hành động chính màu xanh.

Đã kiểm tra HTML và 8 stylesheet công khai được trang đăng nhập ECOUNT tham chiếu.
CSS có font Arial/Helvetica và màu `#005b9e`; đây là cơ sở đối chiếu cho giao diện WMS.
Link ERP được cung cấp chuyển về trang đăng nhập nên chưa quan sát được toàn bộ
các màn hình bên trong. Không lưu URL chứa mã phiên ECOUNT trong dự án.

WMS dùng Tkinter/ttk; bộ giao diện được hiện thực bằng thành phần desktop tương ứng.
Nguồn CSS công khai chỉ dùng để tham chiếu thiết kế. Phạm vi là các chức năng WMS
đang có; ảnh ECOUNT không bổ sung nghiệp vụ kế toán hay sản xuất vào hệ thống.

## Cách dùng

- Đóng rồi mở WMS từ launcher hiện có để nạp giao diện mới.
- Sau khi đăng nhập và xác minh MFA, mở trang **Tổng quan** với các lối tắt thực tế.
- Chọn nhóm trên thanh xanh đậm hoặc chức năng trong menu cây. Menu cây có thanh cuộn.
- Thanh tab giữ bốn màn gần mở; chuyển qua lại giữ nguyên nội dung đang nhập ở màn đó.
  Khi mở nhiều hơn bốn màn, màn cũ vẫn truy cập được từ menu, không bị xóa dữ liệu nháp.
- Dùng ô tìm chức năng trong header để tìm bằng tên màn.
- Ở cửa sổ nhỏ hơn 1250 px, menu trái thu lại; bộ chọn **Chức năng** vẫn cho phép mở
  toàn bộ các màn. Biểu mẫu danh mục cuộn được và tự cuộn đến ô được chọn bằng Tab.
- Nút mặt trời/mặt trăng đổi bảng, biểu mẫu, tab và cửa sổ chi tiết sang sáng/tối.
- Màn soạn/đóng kiện và chuyển kho có vùng thao tác cố định ở dưới;
  phần biểu mẫu trong tab cuộn được để dùng trên cửa sổ nhỏ.
- **Lưu nháp nghiệp vụ** giữ nguyên cơ chế lưu nháp cũ, không áp dụng cho IAM/tệp.
  Trạng thái này cũng được thể hiện trên trang Tổng quan.
- Đăng xuất thu lại điều hướng nghiệp vụ và xóa thông tin người dùng trên Tổng quan.

## Phạm vi kỹ thuật

`admin_theme.py` cung cấp màu, font, mật độ, trạng thái hover/focus/disabled,
ô nhập và nút bo nhẹ, bảng, tab và trường văn bản sáng/tối dùng chung.
`admin_workspace.py` định nghĩa điều hướng của 27 màn (26 màn hiện có và Tổng quan).
Icon dùng các tài sản Lucide chính thức đã có trong dự án, giữ thông tin giấy phép.

Các presenter, API, quyền kho, phê duyệt, version, idempotency và dữ liệu PostgreSQL
vẫn là nguồn xử lý nghiệp vụ. Tổng quan hiển thị số kho trong phiên hiện tại và chế độ
làm việc; không hiển thị số liệu tồn/doanh thu chưa được truy vấn từ máy chủ.

Tk widgets, ảnh theme và đối tượng Style được giải phóng trên UI thread khi đóng ứng dụng.
Trang đăng nhập/khôi phục vẫn giữ giao diện đã chốt trước đó.

Ảnh kiểm tra bố cục tại `.reports/admin-ui/`: sáng/tối, danh mục và cửa sổ 900×690.
Chỉ dùng dữ liệu DEMO cho ảnh kiểm tra. Bộ cài Windows/macOS đã phát hành trước
thay đổi này cần được build lại để chứa giao diện mới.

## Kiểm chứng lần triển khai ERP đầu ngày 08/10/2026

- 120 test riêng biệt trong 21 file desktop/điều hướng/dữ liệu mẫu đã được đối chiếu.
  Kết quả mới nhất của từng bài: **120 đạt, 0 lỗi, 0 bỏ qua**.
- Lượt đầu có 8 lỗi: các giả định kích thước mặc định, điều hướng sau đăng nhập,
  cách đọc khóa MFA cũ và nút cuối màn dài. Đã sửa và chạy lại đúng phạm vi bị ảnh hưởng.
  Báo cáo gốc được giữ nguyên; không thay đổi kết quả cũ thành PASS.
- Báo cáo: `.reports/erp-ui-regression.xml`, `.reports/erp-ui-followup.xml`,
  `.reports/erp-ui-final-workflows.xml`; tổng hợp kết quả mới nhất tại
  `.reports/erp-ui-summary.json`.
- Kiểm thử dùng PostgreSQL tạm và Xvfb trên Linux; không dùng DB mẫu của người dùng.
  Đây là kiểm thử giao diện/nghiệp vụ local, không thay thế kiểm thử native Windows/macOS.

## Bổ sung theo ảnh ECOUNT mới: danh mục và logo

- Bỏ khối xanh sau logo header. Logo navy nền alpha dùng ở chế độ sáng;
  logo trắng nền alpha dùng ở chế độ tối và trang đăng nhập.
- Dùng Arial 10 cho nội dung, hàng bảng 30 px, tiêu đề cột xanh, hàng xen kẽ
  sáng/tối theo theme. Menu nhóm dùng xanh đậm và đánh dấu nhóm hiện tại bằng xanh đậm hơn.
  Tab công việc nằm ngay dưới thanh nhóm, đầu vát nghiêng; tab đang mở xanh đậm/chữ trắng,
  tab còn lại nền sáng hoặc tối theo theme.
- Bấm **Danh mục sản phẩm** từ sidebar, Tổng quan, tìm chức năng hoặc bộ chọn
  sẽ mở đúng tab danh mục cơ sở, chọn Sản phẩm và tải trang đầu qua worker/API.
  Tài khoản thiếu quyền được thông báo; không bỏ kiểm tra MFA hoặc quyền máy chủ.
- Không tự chuyển danh mục khi có yêu cầu đang xử lý/chưa rõ kết quả, hoặc nội dung
  của danh mục khác chưa lưu. Quay lại cùng danh mục đã tải giữ nội dung đang nhập.
- Bảng sản phẩm có mã, tên, đơn vị, nhóm hàng, theo dõi lô/serial và trạng thái;
  có thanh cuộn ngang/dọc và phân trang. Dùng **Thông tin / chỉnh sửa**, nhấp đúp
  hoặc Enter trên hàng đã chọn để mở biểu mẫu; **Thêm mới** mở biểu mẫu trống.
- Chọn hàng rồi bấm **Ảnh & mô tả** để xem thông tin đầy đủ. Các nút thao tác
  tách khỏi hàng tìm kiếm để không bị cắt trên cửa sổ 900×690.

Logo được chỉnh bằng ImageGen tích hợp, lưu tại
`apps/desktop/assets/wms-logo-navy.png`; prompt lưu tại
`apps/desktop/assets/LOGO_NAVY_PROMPT.txt`. Không ghi đè logo trắng.

### Kiểm chứng bổ sung

- Bộ hồi quy 21 file: 122 test riêng biệt, kết quả mới nhất **122 đạt, 0 lỗi, 0 skip**.
  Lượt tổng đầu có 3 lỗi: fixture điều hướng chưa khởi tạo phiên đã xác thực,
  nút cuối màn di chuyển và khách trả hàng bị khuất với font lớn hơn.
  Kiểm tra thêm sau MFA phát hiện phần kiểm định cũng cần vùng cuộn.
  Đã sửa fixture đúng luồng xác thực và sửa layout thực tế, chạy lại các file
  bị ảnh hưởng. Lượt cuối 29 test điều hướng/danh mục/quản trị/di chuyển đều đạt.
- Biểu mẫu di chuyển/trả hàng/kiểm định cuộn bằng chuột hoặc Tab; nhóm nút cuối
  màn được giữ hiển thị. Màn quản trị ưu tiên chỗ cho biểu mẫu và nút hành động.
- Báo cáo gốc: `.reports/catalog-ui-regression.xml`; các lượt sau:
  `.reports/catalog-ui-layout-followup.xml`, `.reports/catalog-ui-returns-followup.xml`,
  `.reports/catalog-ui-move-layout.xml`, `.reports/catalog-ui-final.xml`.
  Tổng hợp theo từng test: `.reports/catalog-ui-summary.json`.
  Các kết quả lỗi ban đầu được giữ nguyên.
- Lint các file sửa và `git diff --check` đạt. Kiểm thử PostgreSQL tạm/Xvfb;
  dữ liệu vận hành của người dùng không bị thay đổi.

## Quy ước chữ hiển thị

Theo yêu cầu mới nhất ngày 08/10/2026, chỉ bỏ dấu chấm cuối câu, dấu chấm giữa
các nhãn và gạch ngang dùng làm dấu phân cách trong nội dung giao diện
Đường kẻ, viền ô, viền bảng và tab vẫn giữ nguyên

Mã hàng, tên sản phẩm từ cơ sở dữ liệu, email, URL, tên tệp, ngày ISO, số âm,
số thập phân và khoảng giá trị vẫn giữ nguyên định dạng
Thay đổi áp dụng cho nhãn và lời nhắc do desktop tạo, không sửa dữ liệu nghiệp vụ
hay nội dung thông báo trả về trực tiếp từ máy chủ


## Danh mục và dữ liệu thực hành kiểm định ngày 08/10/2026

Theo xác nhận của chủ dự án, mã sản phẩm `DEMO-0001` được trình bày thành
`ITL-0001` tại danh mục, biểu mẫu chi tiết, bộ chọn tham chiếu và màn kiểm định
Định danh, SKU gốc, mã vạch và sổ kho không đổi; sửa sản phẩm vẫn gửi SKU gốc
Tìm mã ITL chính xác có nhánh tìm mã DEMO tương ứng khi không có kết quả gốc

Đã bỏ dấu `·` trong tên 200 sản phẩm hiện có qua API với version và audit
Màn kiểm định tự tải khi mở hoặc đổi kho và chọn dòng đầu để hiển thị chi tiết
Các bảng vẫn giữ viền, thanh cuộn, phân trang và kiểm soát quyền của phiên

Dữ liệu thực hành được nạp vào `wms_demo_20261008`, mỗi kho có một đơn mua đã
phê duyệt và một phiếu nhận đã ghi sổ với 200 sản phẩm
Ba kho có tổng cộng 600 dòng nhận và 553 quyết định kiểm định (399 đạt, 154 lỗi)
Có cả hàng chưa kiểm định và hàng được kiểm định một phần để thực hành tiếp
Lý do chứng từ ghi rõ là dữ liệu thực hành, không phải biên bản kiểm tra thực tế
Các phiếu tồn đầu kỳ, ảnh, mô tả sản phẩm và thông tin đăng nhập được giữ nguyên
Đây là nhận hàng bổ sung nên tồn tại khu nhận tăng theo phiếu đã ghi sổ

Công cụ `scripts/prepare_training_quality.py` chỉ cho phép database demo/test
Tài khoản thực thi tạm được vô hiệu hóa và thu hồi phiên/quyền trong `finally`
Công cụ từ chối nạp lần hai hoặc chạy lại khi đã có chứng từ từ lượt trước
Đối soát ledger và ownership sau nạp đều đạt
Bản sao lưu trước thay đổi và báo cáo kết quả nằm trong thư mục riêng local
`~/.local/share/wms-local-server/backups/before-quality-20261008-224350`

Kiểm thử database tạm: `.reports/catalog-quality-data.xml` (3 đạt)
Kiểm thử danh mục, kiểm định và giao diện quản trị: `.reports/catalog-quality-ui.xml` (15 đạt)
Kiểm tra bổ sung mã hiển thị, sửa tên giữ SKU và tự tải kiểm định:
`.reports/catalog-quality-final.xml` và `.reports/catalog-quality-autoload.xml`
Lượt bổ sung đầu phát hiện fixture kiểm định chưa xác thực MFA nên bị shell chặn
Đã giữ nguyên guard MFA và chỉnh test gọi bộ tải của view trong phạm vi fixture
Lượt sau cả 8 test kiểm định đạt; tổng 18 test riêng biệt đạt theo kết quả mới nhất
Lint và kiểm tra artifact/checksum đều đạt


## Tự tải màn Tồn đầu kỳ

Màn Tồn đầu kỳ tự tải danh sách và đọc chi tiết phiếu đầu tiên khi người dùng
mở màn chưa tải hoặc đổi kho/bộ lọc
Quay lại màn đã tải không gửi yêu cầu mới và giữ nội dung đang soạn
Không tự tải khi chưa có phiên/kho, đang xử lý hoặc có yêu cầu chưa rõ kết quả
Bộ lọc không có kết quả hiển thị lời nhắc rõ ràng
Mã SKU trong bảng chi tiết dùng cùng quy ước hiển thị ITL

Kiểm tra database local xác nhận cả ba phiếu OPN đã hoàn tất, mỗi phiếu 200 dòng
Thay đổi lần này chỉ sửa giao diện tải dữ liệu, không tạo thêm tồn đầu kỳ
Bộ kiểm thử hồi quy tồn đầu kỳ/ký gửi: `.reports/opening-autoload.xml`


## Giữ phiên khi đóng và mở lại ứng dụng

Trang đăng nhập có lựa chọn “Giữ đăng nhập trên máy này”, có thể bỏ chọn trên máy dùng chung
Chỉ lưu refresh token sau khi máy chủ xác nhận MFA; mật khẩu, mã MFA và access token
không được ghi vào tệp hay SQLite
Refresh token được lưu bằng backend native của hệ điều hành qua python-keyring
(Linux Secret Service, Windows Credential Manager, macOS Keychain)
Không dùng backend plaintext thay thế; nếu vault không hoạt động, vẫn có thể đăng nhập
nhưng giao diện thông báo không giữ được phiên

Phiên được phân biệt theo địa chỉ API và mã thiết bị
Startup khôi phục qua worker HTTP, xoay refresh token rồi tải lại user/quyền/kho từ máy chủ
Không tự gửi lại lệnh nghiệp vụ trong journal khi phục hồi đăng nhập
Token đã lưu bị vô hiệu hóa cục bộ trước khi gọi refresh để không phát lại token cũ
nếu mất phản hồi hoặc tiến trình dừng giữa chừng
Marker bật/tắt trên đĩa chỉ là metadata, không chứa credential
Đăng xuất hoặc lỗi thu hồi xác thực xóa trạng thái lưu; đóng cửa sổ bình thường giữ phiên
Mất quyền, đổi mật khẩu/auth_version và hết hạn vẫn do máy chủ kiểm tra
Thời hạn phiên mặc định giữ nguyên 8 giờ kể từ lần đăng nhập, không kéo dài vô hạn

Thư viện tham khảo: https://keyring.readthedocs.io/en/stable/
Đã kiểm tra save/take/delete bằng vault thật đang mở khóa trên Linux, chỉ dùng giá trị thử
Các bài kiểm thử DB tạm kiểm tra khôi phục MFA, xoay token, hết hạn, đăng xuất,
thu hồi phiên, đổi auth_version, mất phản hồi và không ghi token vào tệp
Báo cáo: `.reports/session-persistence.xml`, `.reports/session-persistence-final.xml`
Phần phụ thuộc và cấu hình đóng gói Windows/macOS đã cập nhật; chưa build lại bộ cài native


## Dữ liệu các nhóm nghiệp vụ và menu ngang 08/10/2026

Thanh nhóm xanh dùng toàn bộ chiều rộng cửa sổ, phân bổ chiều rộng theo độ dài tên
Các màn dữ liệu tự tải khi mở lần đầu hoặc thay đổi kho/bộ lọc
Danh sách có kết quả chọn phiếu đầu tiên để đọc chi tiết
Giữ nội dung nháp, yêu cầu chưa rõ kết quả và dữ liệu đã tải trong cùng phạm vi
Serial có nút duyệt danh sách trong kho và trang tiếp
Trường mở rộng bắt đầu từ sản phẩm để hiển thị mô tả đã có
Mọi lần đọc vẫn dùng API và kiểm tra quyền của phiên hiện tại

Đã chạy `scripts/prepare_training_workflows.py` trên `wms_demo_20261008`
cho ba kho Bình Dương, Đông Thạnh và Thủ Đức
Đây là dữ liệu thực hành, không phải chứng từ giao dịch thực tế
Mỗi chứng từ mới ghi rõ điều này trong lý do và có audit
Script từ chối chạy lại khi đã có dấu mốc bắt đầu, kể cả lần trước chưa hoàn tất

Mỗi kho bổ sung hợp đồng/nhận ký gửi, cất hàng sau kiểm định, di chuyển nội bộ,
đảo một lần di chuyển, phiên kiểm kê hai người đếm đã duyệt/ghi sổ,
đơn mua nháp và chờ duyệt, đơn bán, xuất hàng đã soạn/đóng kiện/ghi sổ,
phiếu xuất còn giữ hàng và nhiệm vụ soạn giao cho tài khoản kien,
khách trả hàng, trả nhà cung cấp, chuyển kho đã nhận một phần và ba hồ sơ bảo hành
Các quyền duyệt/phân công được kiểm tra qua luồng nghiệp vụ bình thường
Không ghi trực tiếp ledger hay balance, không đổi mật khẩu/MFA của tài khoản người dùng
Tài khoản bảo trì tạm đã vô hiệu hóa và thu hồi phiên/quyền sau nạp

Sau nạp có 51 chứng từ thuộc 11 loại ở cả ba kho, gồm ba phiếu điều chỉnh kiểm kê
Có ba phiên kiểm kê POSTED và không còn khóa vị trí kiểm kê
Bốn đối soát ledger, ownership, fulfillment và transfer đều không có sai lệch
Bản sao lưu trước thay đổi và danh sách ID kết quả được lưu riêng tư tại
`~/.local/share/wms-local-server/backups/before-workflows-20261008-231432/`
Bộ cài native chưa được build lại; launcher Linux đang dùng source của repository


Kiểm chứng thay đổi này:
- `.reports/training-workflows-final.xml`: tạo chuỗi nghiệp vụ đủ ba kho, đối soát và chặn chạy lặp
- `.reports/training-workspace-verified3.xml`: 3 bài đạt; đăng nhập/MFA thật vào DB tạm,
  mở 19 màn và xác nhận có dòng dữ liệu, kiểm tra menu ở 1440px và 900px,
  hồi quy sửa/lưu/timeout/retry metadata và phản hồi muộn khi đăng xuất
- `.reports/workspace-loading.xml`: 7 bài giao diện quản trị/danh mục đạt
- `.reports/workspace-regression.xml`: 54 bài, ban đầu 1 lỗi fixture hình học không có HTTP session;
  đã tách fixture hình học khỏi tự tải mạng, chạy lại 8 bài move/quality đạt trong
  `.reports/training-workspace-final.xml` (lúc đó kiểm thử workspace mới vẫn còn lỗi đã sửa sau)
- Các báo cáo lỗi trung gian được giữ nguyên để truy vết, không thay trạng thái nghiệm thu T01–T28
- `.reports/admin-ui/wide-navbar.png`: đã xem trực quan menu trải hết chiều rộng 1440px


## Chuyển sang dữ liệu Mendeley và tăng chiều cao menu

Theo yêu cầu chủ dự án, nguồn chính mới là bộ dữ liệu kho sản xuất giày
của Rodrigo Furlan de Assis, phiên bản 1 ngày 24/12/2024
DOI: https://doi.org/10.17632/pf2w725pw3.1
Nguồn: https://data.mendeley.com/datasets/pf2w725pw3/1
Giấy phép dữ liệu CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
Bản công bố đã ẩn danh và có ngẫu nhiên hóa theo mô tả của tác giả
Không coi đây là bản sao nguyên trạng toàn bộ ERP hoặc kiểm kê thực tế của doanh nghiệp

ZIP đã kiểm SHA256 `0de6901d639cae782e661ee63d479360b6942b31072e53d07bbde8313cbe9880`
Bản gốc bất biến trong `~/.local/share/wms-datasets/mendeley-pf2w725pw3-v1/`
Liên kết thư mục cho chủ dự án: `../Du_lieu_kho_Mendeley/`
Không chạy Python/notebook đi kèm bộ dữ liệu

Nguồn có 208 mã sản phẩm, 2.292 vị trí, 122.370 dòng đơn thuộc 32.634 đơn,
588 mã khách hàng và 215.192 dòng soạn hàng
Các mã sản phẩm được thêm tiền tố SRC để phân biệt định danh trong WMS
Tên hiển thị mô tả mã ẩn danh, không suy đoán thương hiệu hoặc mẫu giày thật
Kích cỡ giữ nguyên mã chuỗi nguồn (không tự đổi 105 thành 10,5)
Đơn nguồn giữ ngày năm 2023 và khách hàng; lượng trong WMS tổng hợp theo mã tham chiếu
Chi tiết kích cỡ, operator và wave đầy đủ vẫn ở CSV gốc; không giả lập thành lịch sử quét đã thực thi
33 dòng số lượng bằng không được giữ trong nguồn, không tạo dòng nghiệp vụ lượng 0
Nếu toàn bộ một đơn bằng 0, ghi ngoại lệ vào crosswalk, không bịa lượng thay thế
Đơn nhập vào WMS ở trạng thái DRAFT, không khẳng định đã xuất kho hay hoàn tất lịch sử

Một số ô Random_Storage có phần sau dấu chấm phẩy là số lẻ như 7.5, giống cỡ giày,
trong khi README gọi đó là quantity; không dùng trường có nghĩa chưa rõ làm tồn thực tế
Tồn khởi tạo được bổ sung dựa trên tổng nhu cầu lịch sử mỗi mã chia cho ba kho, tối thiểu 20
Ba thiết bị quét mã quản lý serial, hai kho nhánh, toàn bộ phiếu kiểm định/di chuyển,
đóng kiện, ký gửi, trả hàng, kiểm kê và đảo giao dịch là phần cấu hình/nghiệp vụ bổ sung
Chúng không phải các giao dịch do tác giả dataset công bố
Hồ sơ nguồn/chuyển đổi lưu trong import-manifest.json và order-crosswalk.json
Giao diện không gắn nhãn “bổ sung để vận hành” theo lựa chọn chủ dự án

Database mới được dựng riêng qua 25 migrations; mọi sản phẩm và chứng từ ghi qua API
Giữ account kien, password hash, MFA, contact, Google identity và trạng thái mã khôi phục
Không sao chép phiên access/refresh đang mở sang database mới
Bộ demo cũ chỉ giữ riêng để phục hồi, không đổi tên hay sửa lịch sử thành dữ liệu thật
Menu xanh tăng padding dọc từ 9 lên 14, chiều cao kiểm tra thực tế 44px tại 1440px
Đã xem ảnh `.reports/admin-ui/taller-navbar.png`


Kết quả chuyển nguồn ngày 09/10/2026:
- Runtime đã chuyển sang `wms_dataset_mendeley_20261008`; readiness HTTP 200
- 208 mã giày nguồn + 3 thiết bị quét bổ sung, 3 kho, 2.292 vị trí nguồn
- 32.632 đơn lượng dương đã nhập, hai đơn `107393` và `100270` toàn lượng 0 được giữ ở crosswalk
- So sánh từng mã hàng trong từng đơn: PASS; tổng 228.195 đơn vị khớp nguồn
- Bốn đối soát inventory/ownership/fulfillment/transfers: PASS
- Tài khoản bảo trì đều vô hiệu hóa; không còn sản phẩm DEMO trong database đang sử dụng
- Mã kho bất biến được giữ nguyên; launcher đặt `WMS_PREFERRED_WAREHOUSE=SRC-QC`
  để IdentityClient đưa kho trung tâm lên đầu danh sách quyền đã được máy chủ cấp
- Backend thực tế đã kiểm tra 3 kho, 211 sản phẩm và 11 danh sách chứng từ/kỳ có dữ liệu
- Cả 9 dịch vụ WMS systemd đang active sau chuyển đổi
- Bản sao lưu có kiểm tra pg_restore và runtime.env riêng tư:
  `~/.local/share/wms-local-server/backups/before-source-20261008-235850/`
- Lần đổi ban đầu gặp cascade dừng PostgreSQL do target Requires các worker; đã khởi động
  PostgreSQL riêng để đồng bộ identity, sau đó start toàn bộ target đúng thứ tự
- Lần chuẩn bị bị dừng do lỗi nhánh >200 dòng được giữ trong DB riêng
  `wms_dataset_mendeley_incomplete_1`; chưa từng được nối vào runtime
- Báo cáo `.reports/warehouse-source-large.xml`: 2 bài kiểm tra nhập nguồn và chia phiếu >200 dòng đạt
- `.reports/source-workspace-final.xml`: cả hai bộ nguồn qua đăng nhập/MFA và 19 màn đạt
- `.reports/warehouse-source-final.xml`: 5 bài nguồn/giao diện quản trị đạt ở fixture nhỏ
- Serial tự bỏ qua các trang chỉ có hàng không serial, kiểm tra cursor tránh lặp vô hạn
- Phiên cũ không chuyển sang DB mới nên người dùng đăng nhập lại một lần; cơ chế giữ phiên vẫn hoạt động


## Hồ sơ trên header và giảm chữ trên màn hình 09/10/2026

Header sau khi xác thực MFA hiển thị avatar mặc định từ icon Lucide đã đóng gói và tên hiển thị
của phiên hiện tại. Menu có hai mục Chỉnh sửa hồ sơ và Đăng xuất. Hồ sơ sửa tên hiển thị qua
API, cập nhật header và lời chào ngay sau ACK. Tên đăng nhập chỉ đọc; nút Email và số điện thoại
mở quy trình xác minh liên hệ hiện có. Chưa có tải ảnh đại diện cá nhân.

Sidebar đổi Tài khoản & kho thành Kho làm việc. Quyền tại kho hiển thị số lượng quyền và nút
Xem quyền mở danh sách cuộn riêng. Nhập tệp chỉ hiện CSV/Excel và dung lượng tối đa; Yêu cầu tệp
chứa hướng dẫn chi tiết về số dòng, chủ hàng và điều kiện tồn đầu kỳ. Các giới hạn server không đổi.

API mới PATCH /auth/profile chỉ sửa display_name của chính phiên, bắt buộc MFA, kiểm tra
expected_display_name dưới khóa user trước khi ghi. Gửi lại tên đã lưu không tạo audit trùng;
hai cập nhật cạnh tranh trả STALE_VERSION cho bên còn lại. Không tăng auth_version, không đổi
mật khẩu, quyền kho hoặc liên hệ xác minh. Policy ONLINE, không ghi vào hàng đợi nghiệp vụ offline.
OpenAPI runtime và inventory được xuất lại từ ứng dụng.

Kiểm chứng: profile-api.xml có 18 test đạt, profile-ui-final.xml có 16 test đạt; profile-ui-review.xml
kiểm tra lại sửa tên và lời chào qua HTTP + Tk thật đạt. GUI chạy Xvfb ở 1280 và 900 pixel,
kiểm tra sáng tối, menu, lưu tên, quyền thu gọn và đăng xuất. Ảnh .reports/admin-ui/profile.png.
Bản wheel được cài vào máy chủ local; health/ready trả 200, endpoint profile yêu cầu bearer và
9 dịch vụ API/PostgreSQL/worker đang active. Desktop launcher chạy nguồn, mở lại app để lấy giao diện mới.


### Chọn avatar cá nhân 09/10/2026

Hồ sơ có ảnh xem trước, Chọn ảnh và Xóa ảnh. Chỉ Lưu thay đổi mới gửi ảnh lên server;
Hủy giữ ảnh cũ. Đọc tệp và chuẩn hóa chạy ở worker; Tk chỉ hiển thị kết quả thuộc phiên hiện tại.
Ảnh JPG/PNG/WebP tĩnh tối đa 5 MB và 20 triệu pixel được xoay theo EXIF, cắt giữa thành PNG
256×256 và bỏ metadata. Header dùng ảnh đã lưu trong vùng tròn 32 pixel; khi xóa dùng icon Lucide mặc định.

Migration 026_user_avatar tạo bảng riêng cho dữ liệu ảnh và version, không đổi bảng mật khẩu
hay quyền. API me trả ảnh của chính tài khoản; PATCH profile dùng expected_avatar_version,
khóa user và ghi tên/ảnh/audit cùng transaction. Bỏ qua avatar_base64 giữ ảnh; null xóa ảnh.
Ảnh không vào audit hoặc journal nghiệp vụ. Ảnh được tải lại qua me khi đăng nhập/khôi phục phiên.

Phiên Codex hiện tại không được mở Unix socket PostgreSQL hoặc kết nối màn hình X11, nên
chưa chạy integration/GUI và chưa cập nhật database/máy chủ vận hành. Bộ kiểm tra xử lý ảnh
được chạy độc lập; script scripts/apply_avatar_update.py chạy kiểm thử disposable PostgreSQL/Tk,
build wheel, dừng target, sao lưu pg_dump, áp migration, cấp quyền bảng ảnh và cài wheel rồi
khởi động target. Entry point bên cạnh repo: ../cap_nhat_avatar.sh. Script chưa thực thi trong phiên này.

Kiểm tra trong môi trường giới hạn: 7 kiểm thử xử lý ảnh/DTO/presenter đạt, 2 kiểm thử OpenAPI/inventory đạt, Ruff đạt và wheel build thành công
Không coi kết quả này là kiểm chứng integration hoặc GUI; các kiểm tra đó chạy trước cập nhật trong script bàn giao


### Hộp chọn ảnh hệ điều hành 09/10/2026

Linux dùng Zenity file chooser có sẵn trên máy, ưu tiên thư mục Pictures/Ảnh rồi Downloads
Windows/macOS tiếp tục dùng hộp chọn ảnh native qua Tk; Linux thiếu Zenity hoặc lỗi khởi chạy
mới dùng hộp Tk dự phòng. Zenity được gọi bằng argv, không shell; Tk thăm dò tiến trình qua after
để không đứng ứng dụng. Hủy chọn giữ nguyên ảnh; đóng hồ sơ/đăng xuất hủy tiến trình picker
Không thay server hoặc database trong lần chỉnh này; desktop launcher đọc trực tiếp source
Môi trường hạn chế X11 nên chỉ kiểm chứng chọn/hủy/đóng và đường dẫn qua mô phỏng tiến trình,
chưa quan sát hộp GTK thật từ phiên Codex này


### Phát hiện máy chủ chưa hỗ trợ avatar

Đối chiếu gói cài bằng python -I cho thấy máy chủ local vẫn có ProfileUpdate chỉ gồm tên
và migration mới nhất là 025 trong khi desktop source đã có avatar. API cũ từ chối hai trường
ảnh theo extra=forbid nên chỉ hiện Dữ liệu không hợp lệ. Desktop nay kiểm tra hai trường avatar
trong phản hồi me gốc trước PATCH, báo SERVER_UPDATE_REQUIRED nếu thiếu và không gửi ảnh
Đổi tên vẫn dùng được với API cũ; không bỏ ảnh khỏi payload rồi báo lưu thành công
Máy chủ cần chạy ../cap_nhat_avatar.sh ngoài môi trường hạn chế để áp dụng 026 và wheel mới


## Bảng nghiệp vụ thống nhất theo mẫu ERP 09/10/2026

DataTable dùng chung cho mọi bảng nghiệp vụ, cả bảng chi tiết, tra cứu, lịch sử và phân quyền;
sidebar tiếp tục dùng Nav.Treeview. Tiêu đề nền xám nhạt, chữ tối, viền ô mảnh; dòng xen kẽ nhẹ,
mã/số phiếu màu xanh, số lượng và giá trị căn phải, trạng thái/ngày căn giữa. Dòng 32 px, font Arial 9,
chữ mô tả tối đa hai dòng và dấu rút gọn khi vượt ô. Giá trị gốc vẫn nguyên để sửa/xử lý nghiệp vụ.

Tk 8.6 không tô màu từng ô hoặc xuống dòng trong Treeview, nên lớp Canvas trong thân bảng đảm nhiệm
hiển thị; item ID, giá trị, chọn dòng, cuộn, tiêu đề kéo giãn và sự kiện vẫn dựa trên Treeview gốc.
Cột cây/expander ở màn vị trí được giữ native. Không thêm cột hóa đơn, checkbox hay dữ liệu không
có trong nghiệp vụ. Thành phần đổi màu cùng theme sáng/tối và hủy callback khi đóng màn hình.

Kiểm tra định dạng/căn cột và bao phủ các bảng: 10 test unit đạt, Ruff và compileall đạt.
Có test GUI cho chọn dòng qua bề mặt, cuộn, đổi theme, cột cây và thay cấu trúc bảng; chưa chạy được
trong phiên hạn chế X11 (xvfb-run không kết nối được display). Không khẳng định đã kiểm chứng GUI.
Không cần cập nhật máy chủ cho thay đổi bảng; launcher desktop đang đọc mã nguồn.

## Tách trang danh sách và chi tiết nghiệp vụ 09/10/2026

DocumentPages mặc định mở Danh sách, chỉ hiện bảng phiếu và thanh tải/lọc/tạo mới.
Chọn phiếu rồi nhấn Chi tiết phiếu, Enter hoặc nhấp đúp để mở biểu mẫu; nút Danh sách
quay lại bảng phiếu. Tạo mới mở ngay biểu mẫu. Áp dụng đơn mua/bán, nhận hàng, tồn đầu kỳ,
ký gửi, xuất hàng, soạn/đóng kiện, kiểm định, di chuyển nội bộ, chuyển kho, trả hàng,
kiểm kê và đảo giao dịch. Liên kết mở phiếu từ duyệt/import mở trang chi tiết.

Thành phần chỉ ẩn/hiện geometry của widget sẵn có, không dựng lại form, gọi API hay xóa
nội dung nháp, selection, version hoặc lệnh đang chờ ACK. Reset phiên/kho quay về danh sách.
Tự tải/chọn dòng đầu vẫn đọc dữ liệu nhưng không tự chuyển người dùng sang trang chi tiết.

Các bảng phụ tiếp tục được chia tab: xuất hàng tách Dòng hàng/Giữ hàng, kiểm kê có Lịch sử đếm,
đảo giao dịch có Dòng đảo/Ảnh hưởng tồn/Lịch sử duyệt, đóng kiện tách Tạo kiện/Danh sách kiện.
Không thay dữ liệu vận hành, schema, API, presenter hay điều kiện cấp quyền ghi.

Kiểm chứng: 38 kiểm thử unit cho bảng, điều hướng và presenter giữ lệnh/phiên đạt
(.reports/document-pages-unit.xml). Bổ sung GUI test danh sách/chi tiết, giữ nháp và reset
cho toàn bộ màn áp dụng; cập nhật các test bố cục để mở đúng trang và tab mới.
GUI chưa chạy được: xvfb-run thất bại kết nối display :109 tại tk.Tk, trước khi khởi tạo app.
Ruff, compileall và kiểm tra artifact được chạy riêng. Đóng/mở lại desktop để nạp thay đổi;
không cần chạy lại script cập nhật máy chủ.

## Đánh dấu tính năng đang mở 10/10/2026

Menu trái hiển thị mục đang mở bằng nền xanh chuyển sắc, bo tròn hai đầu và chữ trắng đậm.
Lớp hiển thị bám item ID của màn đang mở; cây native giữ nguyên mở/đóng nhóm, bàn phím,
chọn dòng và cuộn. Mở từ header, tab hoặc lối tắt vẫn cập nhật qua AdminNavigation.select.
Nền bo tròn là hình học của control, không bổ sung icon tự vẽ. Tên quá dài rút gọn theo chiều rộng.
Callback vẽ và ảnh Tk được hủy trên main thread khi đóng sidebar.

Ruff, compileall và diff check đạt. Kiểm thử GUI điều hướng hiện dừng ngay tại tk.Tk với
lỗi không kết nối được display :109; chưa xác nhận hiển thị trực tiếp trong môi trường này.

### Hàng tiêu đề bảng màu xanh 10/10/2026

Toàn bộ Treeview.Heading dùng nền xanh #005b9e và chữ trắng đậm, cùng màu chủ đạo header.
Hover/nhấn vẫn giữ nền xanh và chữ trắng. Màu xen kẽ của dòng dữ liệu lấy từ Page.TFrame,
độc lập với tiêu đề để không tô xanh các dòng dữ liệu. Áp dụng cả chế độ sáng và tối.
Ruff và 10 kiểm thử unit bảng đạt; GUI vẫn chưa xác nhận do giới hạn display nêu trên.

## Bố trí nút và phân trang 10/10/2026

Thanh trên giữ bộ lọc, tìm kiếm và thao tác tạo mới; phân trang chuyển xuống dưới bảng.
PaginationBar hiển thị tổng bản ghi, Trước, Trang hiện tại / tổng trang và Sau. Nút điều hướng
vô hiệu khi đang tải hoặc ở đầu/cuối danh sách. Chỉ cập nhật trang sau khi tải thành công;
đổi bộ lọc, kho hoặc phiên đưa danh sách về trang đầu. Tìm kiếm, tạo mới và thao tác chính
dùng xanh dương; từ chối/hủy dùng chữ đỏ, thao tác phụ dùng nền trung tính.

Áp dụng cho danh mục và chi tiết mặt hàng, tra cứu, các danh sách chứng từ nhập/xuất,
tồn đầu kỳ, ký gửi, kiểm định, di chuyển, chuyển kho, trả hàng, soạn hàng, kiểm kê,
kỳ kho, đảo giao dịch, duyệt, quản trị quyền, báo cáo và lịch sử tác vụ.
Các nút tải tiếp dữ liệu tham chiếu trong biểu mẫu không thuộc thanh phân trang danh sách.

API bổ sung tổng số bản ghi cùng bộ lọc và quyền truy cập của danh sách. Endpoint IAM phân trang
giữ yêu cầu quyền và MFA, các endpoint cũ vẫn được giữ. Tổng của đảo giao dịch và lịch sử tác vụ
chỉ tính các bản ghi người dùng được phép đọc. Không thay đổi schema hay dữ liệu vận hành.

Kiểm chứng trên database tạm: nhóm API danh mục/chứng từ đạt 89 ca (1 deselected);
nhóm phân trang, đảo giao dịch và lịch sử đạt 49 ca. Nhóm GUI/presenter bổ sung đạt 10 ca
(4 deselected). Các nhóm có thể trùng phạm vi, không cộng thành tổng ca độc lập.
GUI đã chạy được qua Xvfb trong phiên này; đã xem ảnh bố cục danh mục và thanh phân trang.
Các kiểm thử GUI bảng, điều hướng và chia trang cũng đã chạy thành công, thay cho giới hạn
display được ghi ở các mục lịch sử phía trên. Ruff, compileall và diff check đạt.

Máy chủ local đã cài wheel mới, readiness trả 200 và OpenAPI có endpoint IAM cùng trường total.
Wheel phiên bản trước được giữ trong build/pagination-backups để phục hồi nếu cần.
Đóng rồi mở lại desktop để nạp giao diện và hợp đồng API mới.

## Thu gọn bố cục và tận dụng chiều cao 10/10/2026

Cụm Trước / số trang / Sau được căn giữa dưới bảng, độc lập với độ dài tổng bản ghi bên trái.
Nút thao tác dùng góc bo nhẹ khoảng 5 px; tab Notebook đang chọn có nền xanh #005b9e,
chữ trắng trong cả giao diện sáng và tối. Các tab công việc trên header vẫn giữ kiểu riêng.

ScrollPanel dùng khung có chiều cao tối thiểu bằng vùng nhìn: bảng ngắn giãn tới cuối trang,
biểu mẫu dài vẫn cuộn được. Khi thu gọn nội dung ở cuối trang, vùng cuộn được tính lại để
không để màn hình trống. WorkflowView dùng cùng thành phần thay cho khung chỉ giãn chiều ngang.

Trường mở rộng tách thành Thông tin mở rộng, Thiết lập trường và Lịch sử thay đổi.
ID và phiên bản nằm trong Tùy chọn nâng cao; bỏ hậu tố kiểu dữ liệu khỏi nhãn nhập liệu,
giữ nguyên validator, quyền và nội dung nháp. Lịch sử không còn chiếm chỗ dưới biểu mẫu.
Serial/bảo hành chuyển chi tiết sang nút Xem thông tin bảo hành và thu gọn phần cập nhật chứng cứ.
Các hướng dẫn tĩnh của điều hướng chứng từ, gửi lại yêu cầu, di chuyển, kiểm định, trả hàng,
chủ hàng và nhập tệp được đưa vào nút hướng dẫn/yêu cầu tệp. Lỗi và trạng thái cần xử lý vẫn hiển thị.

Kiểm chứng: 10 ca bố cục/điều hướng/phân trang đạt; 2 ca GUI Trường mở rộng đạt trên database tạm,
gồm biểu mẫu 50 trường, lưu, mất phản hồi/gửi lại và lịch sử; 4 ca danh mục/bảo hành GUI đạt
trên database tạm. Đã xem ảnh giao diện sáng/tối của tab, phân trang, Trường mở rộng và Serial.
Ruff và diff check đạt. Chỉ thay desktop, đóng/mở lại ứng dụng để nhận giao diện mới.

## Hoàn thiện các trang Nhập hàng và nút thao tác 10/10/2026

OpeningView (Tồn đầu kỳ và Nhận ký gửi) đã chuyển sang ScrollPanel dùng chung.
DocumentPages cho bảng danh sách giãn hai chiều, đặt trọng số hàng của khung chứa bảng;
bỏ chiều cao tối thiểu 12 dòng để phân trang vẫn nhìn thấy trên màn hình 900x690.
Kiểm tra trực tiếp cả Đơn mua/bán, Nhận hàng, Tồn đầu kỳ và Nhận ký gửi ở 1400x950 và 900x690.

Nút dùng font Arial 10, khoảng đệm 12x7; thao tác tạo mới/thêm dùng xanh lá, tải/tìm và lưu
dùng xanh dương theo kiểu nút chính, phụ giữ nền trung tính. Icon tải lại, thêm mới, lưu,
tìm kiếm và trợ giúp lấy từ Lucide chính thức tại commit ghi trong
apps/desktop/assets/lucide/ACTION_SOURCES.txt. Giữ nguyên đường nét SVG, chỉ đổi màu và
render PNG cho Tk; giấy phép và mã băm đi kèm. Công cụ render chỉ dùng lúc chuẩn bị asset,
không thêm dependency chạy ứng dụng.

Tab Notebook có cùng font, khoảng đệm và độ giãn ở trạng thái chọn/bỏ chọn. Chỉ đổi nền
và màu chữ; kiểm thử biên từng tab xác nhận kích thước không đổi ở cả sáng và tối.
HelpButton giải phóng tham chiếu StringVar trên UI thread khi đóng để tránh finalizer Tk
chạy trên worker. Helper kiểm thử phê duyệt chỉ chuyển trang chi tiết với màn có DocumentPages;
hộp thư duyệt vẫn giữ biểu mẫu quyết định trực tiếp.

12 kiểm thử bố cục/điều hướng/phân trang đạt; kiểm thử thu gom cửa sổ đã đóng trên worker đạt.
Chạy lại đầy đủ 11 kiểm thử GUI nhập hàng, tồn đầu kỳ, ký gửi và phê duyệt trên database tạm đạt
(.reports/inbound-layout.xml); số này đã bao gồm kiểm thử thu gom cửa sổ nêu trên.
Đã xem ảnh cửa sổ lớn và nhỏ, giao diện sáng/tối; Ruff, compileall và diff check đạt.

## Sắp xếp thanh thao tác và bỏ Tổng quan 10/10/2026

Bỏ Tổng quan khỏi menu, tìm kiếm và các tab. Sau đăng nhập mở Danh mục sản phẩm.
Nút tạo mới của danh mục và chứng từ được đặt bên phải thanh công cụ.
Combobox dùng một viền liền với mũi tên Lucide có sẵn, giữ hành vi chọn bằng chuột
và bàn phím của Tk. Không đổi kích thước tab khi chọn.

Các đoạn trạng thái dài trên màn nghiệp vụ chuyển thành nút Xem trạng thái.
Nội dung đầy đủ và phản hồi máy chủ vẫn được giữ; thông báo lỗi đổi nút sang màu đỏ
Cần kiểm tra và có thể mở để đọc. Hướng dẫn quét mã nằm trong nút hướng dẫn.
Bộ lọc, tùy chọn sắp xếp và giá quản trị của báo cáo được gom dưới
Xem bộ lọc và tùy chọn.

Thanh thao tác báo cáo và in dùng ActionGrid: các nút có màu riêng, chia đều theo
từng hàng và đổi số cột theo chiều rộng. Thanh thao tác luôn được dành chỗ trước
vùng bảng/xem trước để không mất nút trên cửa sổ nhỏ. Màn in chia thiết lập và
xem trước thành hai vùng; cửa sổ hẹp chuyển sang xếp dọc, phần thiết lập cuộn được.
Phân trang bản xem trước nằm giữa và hiển thị trang hiện tại khi đã tải PDF.

Kiểm chứng: 13 ca GUI bố cục/điều hướng/phân trang đạt, sau đó 5 ca bố cục đạt
với kiểm tra bổ sung mở Combobox ở hai theme, bộ lọc báo cáo khi thu nhỏ, và nút
không bị lớp khác che. Hai nhóm có ca trùng nhau. 10 ca tích hợp in PDF, báo cáo,
hồ sơ và chứng từ đạt trên database tạm (.reports/action-layout-api.xml).
Đã xem ảnh bố cục lớn/nhỏ, sáng/tối. Ruff, compileall và diff check đạt.
Chỉ thay giao diện desktop, đóng rồi mở lại ứng dụng để nạp thay đổi.

### Gộp trạng thái quét mã và chứng từ

Nhận hàng, xuất kho, soạn/đóng kiện, chuyển kho và kiểm kê dùng chung một nút
Xem trạng thái. Hộp thông tin gồm hai phần Nghiệp vụ và Quét mã, cập nhật độc lập;
lỗi ở phần nào cũng làm nút chuyển sang trạng thái cần kiểm tra. Không còn nút
trạng thái riêng trên thanh quét mã. Các trace được tháo khi đóng cửa sổ.

## Danh sách thao tác và xem trước theo yêu cầu

In chứng từ và Tồn kho/báo cáo chuyển các hàng nút màu sang menu danh sách dọc
Thao tác in và Thao tác báo cáo. Menu giữ nguyên các lệnh, có thể mở bằng chuột
hoặc bàn phím. Nút Tạo bản PDF và Tạo báo cáo dùng xanh dương.

Màn in mặc định chỉ hiện thiết lập, không dành chỗ cho bản xem trước trống.
Khi PDF sẵn sàng, chọn In / xem trước để mở cửa sổ xem trước có phân trang và
nút Gửi máy in. Đóng cửa sổ xem trước không mất thiết lập. Đổi kho, mẫu hoặc
phiên sẽ xóa và ẩn bản xem trước cũ.

Kỳ kho đưa thông tin phiên bản/xác nhận vào Xem thông tin kỳ, hướng dẫn ngày và
điều kiện khóa/mở kỳ vào Quy định kỳ kho. Giữ các bước kiểm tra quyền và MFA.
Ba ô Biên bản, Lý do và Mã job của Nhập dữ liệu từ tệp cùng chiều rộng, cùng mép;
Đọc / tiếp tục chuyển xuống hàng dưới, bên phải, dùng màu xanh dương khi được phép.

8 kiểm thử GUI bố cục và đóng cửa sổ đạt, gồm menu dọc, mở/ẩn xem trước theo yêu cầu,
căn ô nhập và thu gom tài nguyên Tk trên worker. Đã xem ảnh màn in, báo cáo,
kỳ kho và nhập tệp ở cửa sổ lớn/nhỏ. Chỉ thay desktop, mở lại ứng dụng để cập nhật.

21 ca tích hợp liên quan đã đạt qua các lượt chạy trên database tạm: báo cáo và
kỳ kho trong action-menu-api.xml, nhập tệp trong action-menu-api-followup.xml,
3 ca in/quét mã trong action-menu-print-final.xml. Các lượt đầu còn kiểm thử dùng
luồng xem trước/nơi đặt hướng dẫn cũ; đã cập nhật để kiểm tra thao tác mới.
Kiểm thử tải PDF muộn chờ worker hoàn tất thay vì chờ phần tử hàng đợi có thể đã
được UI lấy ra; vẫn xác nhận không ghi đè tệp và không giữ ảnh của phiên cũ.
Ruff, compileall và kiểm tra artifact đạt.

## Căn biểu mẫu in và thanh điều hướng chứng từ

Thiết lập in chia thành hai nhóm Chứng từ và Máy in, giãn hết vùng nội dung theo
chiều cao. Ô nhập và ô chọn có chiều rộng gọn; khổ giấy và số bản dùng ô ngắn hơn.
Màn rộng đặt hai nhóm cạnh nhau; dưới 1000 px vùng nội dung, các nhóm xếp dọc và
cuộn được. Tạo bản PDF, Xem trạng thái và Hướng dẫn nằm ở thanh cuối trang.
Bản xem trước vẫn chỉ mở khi được yêu cầu.

Kiểm định chất lượng và hai màn trả hàng đưa trạng thái lên cùng hàng Danh sách,
Chi tiết và Hướng dẫn. Các nút cùng chiều cao; mép thanh chọn kho/tải/tạo phiếu
căn theo vùng bảng bên dưới, có tính khoảng đệm và thanh cuộn. Giữ nguyên dữ liệu,
quyền, bản nháp và logic chuyển trang.

12 ca GUI bố cục, chuyển trang và đóng/thu gom cửa sổ đạt. Kiểm tra gồm nhóm in
giãn chiều cao, ô nhập ngắn, ô cuối vẫn tới được trên màn nhỏ, các nút cùng hàng
và mép trên/dưới thẳng nhau. Đã xem ảnh cửa sổ lớn/nhỏ; Ruff và compileall đạt.

### Căn ô nhập và phối màu Kỳ kho

Từ ngày, Đến ngày và Lý do dùng chung lưới nhãn/ô nhập, cùng mép và chiều rộng.
Bốn thao tác kỳ kho chia hai hàng, hai cột bằng nhau, khoảng cách 12 px theo cả
hai chiều: mở kỳ xanh dương, khóa kỳ vàng nâu, xác nhận xanh ngọc, mở lại tím.
Gửi lại/tra ACK có màu phụ riêng và được tách khỏi nhóm thao tác chính. Hai nút
thông tin/quy định đặt cùng hàng. Giữ nguyên trạng thái vô hiệu theo quyền và
trạng thái chứng từ; màu đầy đủ chỉ áp dụng khi nút được phép thao tác.
11 ca GUI liên quan đạt; kiểm tra trực tiếp căn ô, chiều cao nút và khoảng cách
ở 1700x1000 và 900x690 đạt. Không đổi xử lý nghiệp vụ hay API.

### Thu gọn thao tác nhập tệp và mở rộng icon Lucide

Nhóm xác nhận, tạo/kiểm tra/commit/hủy và khôi phục yêu cầu chuyển vào tab Tệp nhập,
ngay dưới tiến trình và nút tải tệp. Loại bỏ khoảng trống lớn ngăn biểu mẫu với
thanh thao tác ở đáy cửa sổ. Các nút cách nhau 12 px, có khoảng cách giữa các nhóm;
màu xanh dương cho tạo/chọn, xanh ngọc cho kiểm tra, xanh lá cho xác nhận, đỏ cho
hủy, tím/vàng nâu cho tra cứu/gửi lại. Tab Dòng dữ liệu / lỗi có nút quay về nhóm
Xác nhận / xử lý tệp. Logic cho phép/vô hiệu theo trạng thái job và quyền giữ nguyên.

Bổ sung 12 SVG từ kho lucide-icons/lucide chính thức, cùng commit đã ghi trong
apps/desktop/assets/lucide/ACTION_SOURCES.txt. Lưu URL, mã băm và giấy phép đi kèm;
không vẽ lại đường nét. Render 36 PNG cho màu xanh, trắng và trạng thái vô hiệu.
Icon thêm cho chọn/tải tệp, kiểm tra, xác nhận, hủy, thử lại, máy in và thông tin
trên các nút tương ứng. CairoSVG chỉ dùng trong môi trường tạm để tạo asset,
không thêm dependency cho ứng dụng.

12 ca GUI bố cục/đóng cửa sổ đạt. Đã kiểm tra khoảng cách, vị trí nhóm thao tác và
icon ở 1700x1000, 900x690 và giao diện tối; nhóm cuối vẫn cuộn tới được.
14 ca nhập tệp tích hợp đạt trên database tạm (.reports/import-actions-icons.xml),
gồm nhập tồn đầu kỳ, commit, hủy, thu hồi quyền, phản hồi muộn và gửi lại yêu cầu.
Nút quay từ dòng dữ liệu về nhóm xử lý đã kiểm tra trực tiếp. Ruff và artifact đạt.

### 13/10/2026 — Màu nút nhập tệp khi chưa được thao tác

Sáu nút tạo job, kiểm tra, xác nhận, hủy, tra yêu cầu và gửi lại dùng các style
Import riêng: xanh dương, xanh ngọc, xanh lá, đỏ, tím và vàng nâu. Khi disabled,
nút giữ nền nhạt theo màu tương ứng và chữ có màu, thay vì cùng chuyển xám;
giao diện tối dùng nền tối tương ứng. Giữ nguyên điều kiện enable và callback,
icon Lucide hiện có, kích thước và khoảng cách. Các nút khác không đổi.

Ruff, biên dịch Python và kiểm tra artifact đạt. Chưa kiểm tra trực quan lần này:
Xvfb không tạo được socket hiển thị trong môi trường thực thi hiện tại.

### 13/10/2026 — Tải lại giao diện và thoát có xác nhận

Thanh trên cùng có nút Tải lại giao diện với icon Lucide refresh-cw hiện có.
Nút này khởi động lại tiến trình để đọc mã giao diện mới, sau khi đóng tài nguyên
và nhả application lock. Dùng lại Python hiện tại hoặc executable của bản đóng gói.
Không truyền thông tin đăng nhập qua tham số tiến trình; giữ cơ chế nhớ phiên hiện có.

Đóng cửa sổ hoặc tải lại đều hỏi xác nhận, mặc định Hủy, nhắc phần đang nhập chưa
lưu sẽ mất. Khi đồng ý, hiển thị hộp tiến trình; ngừng nhận việc mới, chờ công việc
đang chạy và tác vụ đóng journal hoàn tất bằng thread riêng. Tk vẫn đáp ứng trong
lúc chờ; hủy widget/biến Tk vẫn ở main thread. Chặn yêu cầu thoát/tải lại lặp.
Các lệnh nghiệp vụ không tự gửi lại. Nếu không khởi động lại được, thông báo mở
WMS thủ công. Để nhận nút mới, bản đang chạy cần đóng/mở thủ công lần đầu.

17 kiểm thử không cần màn hình đạt (lifecycle và desktop), gồm chờ công việc +
journal, hủy thoát, giữ cửa sổ trong lúc chờ, thứ tự cleanup/nhả lock/restart và
đường khởi động source/frozen. Ruff và biên dịch Python đạt. Ca GUI đã thử chạy
nhưng bị chặn ngay tại tk.Tk(): Xvfb không tạo được socket hiển thị; chưa xác minh
trực quan hoặc chạy được ca GUI kiểm tra đóng cửa sổ trong môi trường này.

### 13/10/2026 — Nút nhập tệp dùng nền đậm theo ảnh tham chiếu

Theo phản hồi mới, thay nền nhạt/viền màu của sáu nút nhập tệp bằng nền màu đặc,
chữ và icon trắng, cùng kiểu nút Mở kỳ mới / Khóa kỳ. Áp dụng cả khi disabled
và trong hai giao diện sáng/tối. Giữ nguyên điều kiện khóa nút, callback và khoảng
cách; không đổi quyền hay điều kiện thực hiện nghiệp vụ.

### 13/10/2026 — Tách danh sách và chi tiết phục hồi

Màn Nháp và phục hồi lệnh chia hai tab Danh sách lệnh / Chi tiết lệnh, mỗi tab
chỉ hiển thị một bảng và dùng chiều cao còn lại. Bỏ đoạn ghi chú dưới tiêu đề.
Chọn lệnh rồi Xem nội dung (hoặc Enter) để tải qua kiểm tra quyền hiện tại;
chỉ mở tab chi tiết sau khi có kết quả. Nút Về danh sách giữ nội dung đang sửa,
còn đổi lệnh/kho/phiên sẽ xóa chi tiết cũ. Mỗi bảng có thanh cuộn ngang/dọc;
ô sửa và nút lưu đặt ở cuối tab chi tiết. Không đổi API hay xử lý gửi lại lệnh.
Ruff, biên dịch Python và artifact đạt; chưa xác minh trực quan do môi trường
hiện tại không mở được Xvfb.

### 13/10/2026 — Thu gọn nhóm xử lý nhập tệp

Chỉ giữ Tạo job / dry-run và Xác nhận commit trên thanh thao tác chính, cùng menu
Thao tác khác. Kiểm tra lại, Tra yêu cầu chưa rõ, Gửi lại đúng yêu cầu và Hủy job
chuyển vào danh sách dọc trong menu. Bỏ hàng nút phụ khỏi bố cục. Menu đồng bộ
trạng thái khóa theo enable() hiện có và gọi invoke() của control gốc, giữ nguyên
kiểm tra quyền/trạng thái cũng như điều kiện tra cứu trước khi gửi lại.
Ruff và biên dịch Python đạt; chưa kiểm tra trực quan do môi trường hiển thị.
