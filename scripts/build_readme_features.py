"""Keep README feature coverage aligned with the desktop navigation and real captures."""

import ast
import hashlib
import json
from pathlib import Path

from readme_content import OPERATIONS, SYSTEM, introduction

ROOT = Path(__file__).resolve().parents[1]
DETAILS = {
    'session_view': ('Chọn kho làm việc, xem quyền, quản lý phiên, đổi mật khẩu, thiết lập MFA và đăng xuất. '
                     'Menu tài khoản hiển thị tên/ảnh đại diện, mở chỉnh sửa hồ sơ và đổi ảnh.', 'apps/desktop/views/session.py'),
    'master_container': ('Quản lý sản phẩm, đơn vị tính, nhóm hàng, kho, vị trí và đối tác; tìm kiếm và phân trang. '
                         'Các tab riêng quản lý quy đổi đơn vị, barcode, giá tham chiếu, chủ hàng, hợp đồng ký gửi và tồn theo chủ sở hữu. '
                         'Có hồ sơ ảnh và mô tả sản phẩm.', 'apps/desktop/views/master_data.py'),
    'serial_view': ('Duyệt hoặc tra chính xác serial, xem lịch sử truy vết và chứng cứ bảo hành theo quyền hiện tại. '
                    'Thông tin nguồn, ngày nhập và mốc bảo hành được lấy từ dữ liệu đã lưu.', 'apps/desktop/views/serial_lookup.py'),
    'custom_fields_view': ('Định nghĩa bộ trường có kiểu, xuất bản phiên bản và nhập giá trị bổ sung cho đối tượng. '
                           'Xem lịch sử giá trị; chuyển phiên bản khi lưu theo kiểm tra của máy chủ.', 'apps/desktop/views/custom_fields.py'),
    'order_view': ('Lập và sửa đơn mua PO/đơn bán SO; thêm dòng hàng, giao người xử lý, gửi duyệt, sửa lại hoặc hủy theo trạng thái. '
                   'Danh sách, chi tiết và lịch sử được tách để theo dõi từng chứng từ.', 'apps/desktop/views/orders.py'),
    'approval_view': ('Xem phiếu chờ phê duyệt theo loại và kho, đọc nội dung/snapshot, duyệt hoặc từ chối kèm lý do. '
                      'Máy chủ kiểm tra quyền, phiên bản và phân tách nhiệm vụ; không cho tự duyệt trái quy định.', 'apps/desktop/views/approvals.py'),
    'receipt_view': ('Lập phiếu nhận từ PO, chọn vị trí nhận và định danh hàng; duyệt rồi ghi sổ theo lượng thực nhận. '
                     'Hỗ trợ nhận từng phần, tra kết quả ghi sổ và nhập mã bằng máy quét HID.', 'apps/desktop/views/receipts.py'),
    'opening_view': ('Lập tồn đầu kỳ theo kho, sản phẩm, vị trí, lô/serial và chủ sở hữu. '
                     'Có biên bản nguồn, gửi duyệt và ghi sổ; điều kiện khởi tạo được kiểm tra ở máy chủ.', 'apps/desktop/views/openings.py'),
    'consignment_view': ('Tiếp nhận hàng ký gửi gắn với chủ hàng và hợp đồng; lập dòng, gửi duyệt và ghi sổ nhận. '
                         'Hàng ký gửi giữ định danh sở hữu riêng trong tồn kho.', 'apps/server/application/consignments.py'),
    'issue_view': ('Lập phiếu xuất từ SO, đề xuất nguồn giữ hàng theo khả dụng/FEFO, giữ hoặc giải phóng lượng giữ. '
                   'Xuất một phần hoặc toàn bộ theo chứng từ được duyệt, có kiểm tra phiên bản và truy vết kết quả.', 'apps/desktop/views/issues.py'),
    'fulfillment_view': ('Phân công và xử lý tác vụ soạn hàng, quét mã, ghi lượng thực soạn, đóng kiện và quản lý nội dung kiện. '
                         'Kiểm tra nguồn giữ hàng, quyền người thao tác và trạng thái phiếu xuất.', 'apps/desktop/views/fulfillment.py'),
    'quality_view': ('Xem hàng cần kiểm định, ghi quyết định chất lượng và lượng được chấp nhận hoặc cách ly. '
                     'Quyết định chất lượng làm căn cứ cho thao tác cất và di chuyển tiếp theo.', 'apps/desktop/views/quality.py'),
    'move_view': ('Chọn nguồn tồn và vị trí đích để cất hoặc di chuyển hàng trong kho. '
                  'Liên kết quyết định kiểm định khi cần; có lập nháp, phê duyệt và ghi sổ.', 'apps/desktop/views/moves.py'),
    'transfer_view': ('Lập chuyển kho, theo dõi lượng đã gửi, đã nhận và còn đang vận chuyển. '
                      'Có lịch sử giao nhận, xử lý thiếu/hỏng và chứng cứ chênh lệch; kiểm tra phạm vi quyền tại các kho liên quan.', 'apps/desktop/views/transfers.py'),
    'customer_return_view': ('Lập phiếu khách trả hàng tham chiếu chứng từ xuất; kiểm tra hàng và lượng có thể trả, '
                             'phê duyệt rồi ghi nhận về vị trí được phép.', 'apps/desktop/views/returns.py'),
    'supplier_return_view': ('Lập phiếu trả nhà cung cấp có tham chiếu nguồn nhận; chọn nguồn tồn, kiểm tra số lượng, '
                             'gửi duyệt và ghi sổ trả.', 'apps/server/application/returns.py'),
    'report_view': ('Tra cứu R01 tồn theo vị trí; R02 nhập/xuất qua ranh giới; R03 thẻ kho; R04 giữ hàng/nhu cầu mở; '
                    'R05 chuyển kho/transit; R06 hạn dùng/tồn lâu; R07 kiểm kê; R08 hoạt động/giá tham chiếu. '
                    'Lọc, phân trang, xuất CSV/XLSX, theo dõi job và lịch sử export. Giá tham chiếu cần quyền giá, không phải giá vốn kế toán.', 'apps/desktop/views/reports.py'),
    'count_view': ('Tạo phiên kiểm kê, chọn và đóng băng phạm vi, chụp snapshot tồn, ghi các lần đếm hoặc xác nhận vị trí trống. '
                   'Nộp, xét duyệt chênh lệch và ghi điều chỉnh theo quy trình.', 'apps/desktop/views/counting.py'),
    'period_view': ('Xem và mở kỳ kho, khóa kỳ/đối soát, xác nhận và thực hiện mở lại kỳ theo vai trò và MFA. '
                    'Thông tin kỳ và quy định hiển thị khi cần; có tra ACK cho thao tác ghi.', 'apps/desktop/views/periods.py'),
    'reversal_view': ('Lập phiếu đảo có tham chiếu giao dịch gốc, lý do, phê duyệt và ghi bút toán bù. '
                      'Không sửa trực tiếp giao dịch tồn đã ghi sổ.', 'apps/desktop/views/reversals.py'),
    'import_view': ('Tải mẫu CSV/XLSX, chọn và upload tệp, tạo job/dry run, xem lỗi từng dòng, xác nhận commit và xem lịch sử nhập. '
                    'Tồn đầu kỳ/đơn hàng nhập từ tệp tạo chứng từ để tiếp tục nghiệp vụ. '
                    'Kiểm tra lại, hủy và khôi phục yêu cầu nằm trong menu Thao tác khác.', 'apps/desktop/views/imports.py'),
    'print_view': ('Chọn chứng từ hoặc hàng, mẫu và khổ giấy; tạo PDF tiếng Việt, xem trước khi mở thao tác in, lưu PDF hoặc gửi máy in. '
                   'Có phiếu nhận, xuất, chuyển, kiểm kê và tem sản phẩm/vị trí; theo dõi trạng thái, in lại và kiểm tra yêu cầu.', 'apps/desktop/printing/view.py'),
    'admin_view': ('Quản lý tài khoản, trạng thái hoạt động, vai trò và quyền theo kho/thời hạn; xử lý yêu cầu cấp quyền, '
                   'thu hồi phiên và các thao tác bảo mật theo quyền hiện tại.', 'apps/desktop/views/admin.py'),
    'recovery_view': ('Xem nhật ký nháp và lệnh theo thiết bị/tài khoản/máy chủ; tra ACK, xem nội dung, sửa hoặc bỏ nháp chưa gửi. '
                      'Gửi lại dùng đúng key và nội dung. Danh sách và chi tiết nằm ở hai tab riêng.', 'apps/desktop/views/recovery.py'),
    'receipt_recovery_view': ('Tra các lần ghi sổ nhận hàng bị gián đoạn, kiểm tra kết quả máy chủ và tiếp tục với đúng yêu cầu cũ. '
                              'Không tự ghi nhận thành công khi chưa có xác nhận.', 'apps/desktop/views/receipt_recovery.py'),
    'connection_view': ('Kiểm tra kết nối API và trạng thái sẵn sàng của máy chủ/cơ sở dữ liệu. '
                        'Hiển thị địa chỉ API được cấu hình và kết quả kiểm tra.', 'apps/desktop/views/shell.py'),
}


def main():
    module=ast.parse((ROOT/'apps/desktop/views/admin_workspace.py').read_text())
    sections=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=='SECTIONS' for t in n.targets))
    captures=json.loads((ROOT/'assets/readme/screenshots.json').read_text())
    images={c['feature']:c for c in captures}
    for key in ['login',*[s[1] for s in sections]]:
        row=images[key]
        if hashlib.sha256((ROOT/row['file']).read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Screenshot hash differs: '+key)
    schema=json.loads((ROOT/'02_CSDL/current/schema.json').read_text())
    api=json.loads((ROOT/'05_API/openapi_runtime.json').read_text())
    ops=sum(m in {'get','post','put','patch','delete','head','options'} for p in api['paths'].values() for m in p)
    counts=schema['counts']
    text=[introduction().strip(), '', SYSTEM.strip(), '',
          '## Quy mô mã nguồn hiện tại', '',
          '| Thành phần | Số liệu đối chiếu |', '|---|---|',
          f'| Cơ sở dữ liệu PostgreSQL | {counts["tables"]} bảng, {counts["columns"]} cột, {counts["foreign_keys"]} khóa ngoại trong schema `wms` |',
          '| Migration | PostgreSQL 001–026; SQLite 001–003 |',
          f'| API | {len(api["paths"])} đường dẫn, {ops} thao tác HTTP trong OpenAPI runtime |',
          f'| Quyền được seed | {counts["roles"]} vai trò, {counts["permissions"]} quyền |',
          f'| Giao diện | {len(sections)} mục trên menu chức năng; thêm màn đăng nhập và các hộp thoại/tabs bên trong |',
          '| Phiên bản ứng dụng | `0.1.0`; bản cài phát hành được định danh riêng theo commit |', '',
          'Số liệu schema được đọc từ PostgreSQL tạm sau khi chạy toàn bộ migration. '
          '[Catalog hiện hành](02_CSDL/current/schema.json) lưu cột, ràng buộc và index; '
          '[DBML hợp nhất](02_CSDL/current/wms.dbml) và [từ điển dữ liệu](02_CSDL/current/dictionary.csv) dùng cho báo cáo. '
          'Số liệu mô tả cấu trúc schema và hợp đồng API.', '',
          '<a id="chuc-nang"></a>', '',
          '## Chức năng và ảnh giao diện', '',
          'Dưới đây là đủ 26 mục chức năng trong menu hiện tại và màn hình đăng nhập. '
          'Ảnh chụp trực tiếp từ ứng dụng ngày 13/10/2026 trên dữ liệu thực hành; '
          'chức năng/màn hình được mở theo quyền tài khoản. '
          '[Nguồn ảnh và SHA-256](assets/readme/screenshots.json) · '
          '[Thuyết minh báo cáo](01_Tai_lieu/HIEN_TRANG_BAO_CAO.md) · '
          '[PDF sơ đồ](03_So_do/Hien_hanh/WMS_Hien_hanh.pdf) · '
          '[draw.io](03_So_do/Hien_hanh/WMS_Hien_hanh.drawio).', '',
          '## Đăng nhập và giao diện chung', '',
          'Đăng nhập tài khoản, MFA, nhớ phiên qua kho bí mật hệ điều hành, đổi mật khẩu và khôi phục tài khoản. '
          'Mã nguồn có luồng email/SMS và Google; khả năng sử dụng phụ thuộc cấu hình máy chủ và dịch vụ ngoài. '
          'Hồ sơ cho phép đổi tên hiển thị và ảnh đại diện. Thanh trên có tìm chức năng, hỗ trợ, menu tài khoản, '
          'chế độ sáng/tối và **Tải lại**. Khi đóng hoặc tải lại, ứng dụng hỏi xác nhận và chờ tác vụ nền kết thúc.', '',
          '![Màn đăng nhập thực tế](assets/readme/login.png)', '',
          'Nguồn: [giao diện tài khoản](apps/desktop/views/session.py), '
          '[xác thực mở rộng](apps/server/api/modern_identity.py), [vòng đời desktop](apps/desktop/lifecycle.py).', '']
    previous=None
    features=[]
    for group,key,title,_ in sections:
        desc,source=DETAILS[key]
        if group!=previous:
            text+=['## '+group,'']
            previous=group
        text+=['### '+title,'',desc,'',f'![{title}]({images[key]["file"]})','',f'[Mã nguồn chức năng]({source})','']
        features.append(dict(group=group,key=key,title=title,description=desc,source=source,image=images[key]['file']))
    text += [OPERATIONS.strip(), '', '<a id="chay-tu-ma-nguon"></a>', '',
             '## Chạy từ mã nguồn','',
             'Yêu cầu phát triển: Python 3.12, Tkinter và PostgreSQL 15/16. '
             'Cài dependency theo [requirements-app-lock.txt](requirements-app-lock.txt), cấu hình API/cơ sở dữ liệu theo '
             '[hướng dẫn triển khai](01_Tai_lieu/LAN_DEPLOYMENT.md). PostgreSQL cần có database và tài khoản '
             'được chuẩn bị trước; Tkinter/Tcl-Tk phải có trên máy chạy desktop.', '',
             '| Cấu hình | Dùng ở đâu | Ý nghĩa |', '|---|---|---|',
             '| `WMS_DATABASE_URL` | Server / migration | DSN PostgreSQL dùng driver `postgresql+psycopg`; desktop không cần biến này |',
             '| `WMS_API_URL` | Desktop | URL API kết thúc bằng `/api/v1`; LAN dùng HTTPS, local development cho phép HTTP loopback |',
             '| `WMS_CA_FILE` | Desktop | Đường dẫn CA nội bộ khi triển khai TLS với CA riêng |',
             '| `WMS_MFA_ENCRYPTION_KEY` | Server | Khóa Fernet do quản trị tạo và giữ riêng, cần cho đăng ký/sử dụng MFA |',
             '| `WMS_LOCAL_DATA_DIR` | Desktop | Thư mục nháp/journal trên đĩa cục bộ; giữ qua các lần nâng cấp |', '',
             'Xem [.env.example](.env.example) để biết các biến. File này là mẫu; server không tự đọc `.env`, '
             'cần xuất biến môi trường hoặc cấu hình service. Sau khi cấu hình, chạy ở thư mục gốc repository:', '',
             '```bash\npython -m apps.server.infrastructure.migrations\npython -m apps.server\n# Terminal khác\npython -m apps.desktop\n```','',
             'Migration chỉ chạy khi người quản trị yêu cầu; API không tự nâng schema khi khởi động. '
             'Khởi tạo/cấp tài khoản theo [hướng dẫn IAM](01_Tai_lieu/IDENTITY.md); không có mật khẩu mặc định trong README. '
             'Client kết nối LAN sử dụng HTTPS với CA tin cậy. Các tác vụ import/export/in cần worker tương ứng '
             'được bật theo runbook.', '',
             '<a id="kiem-chung"></a>', '',
             '## Tài liệu và kiểm chứng','',
             '| Tài liệu | Nội dung |', '|---|---|',
             '| [Sơ đồ hệ thống](03_So_do/README.md) | Use case, BPMN, UML lớp, trạng thái, kiến trúc, quyền và ERD; PDF/SVG/draw.io |',
             '| [Ký pháp theo giáo trình BA](03_So_do/NOTATION_GUIDE.md) | Đối chiếu chương/trang, quy ước và nguồn dữ liệu từng loại sơ đồ |',
             '| [Hiện trạng hệ thống](01_Tai_lieu/HIEN_TRANG_BAO_CAO.md) | Chức năng, schema, API và phạm vi bằng chứng |',
             '| [Kiểm tra tài liệu](07_Kiem_tra/current_report/README.md) | Kết quả kiểm tra sơ đồ, schema, ảnh và liên kết |',
             '| [Bàn giao 0.1.0](07_Kiem_tra/release/FINAL_HANDOVER.md) | Bằng chứng kiểm thử gắn với commit `97d4c51` và các cổng nghiệm thu |',
             '| [Bảo trì tài liệu](01_Tai_lieu/DOCUMENTATION.md) | Lệnh xuất schema/API, dựng sơ đồ, chụp ảnh và kiểm định artifact |', '',
             '[Tải ứng dụng](#tai-ung-dung) · [Mục lục](#muc-luc)', '']
    (ROOT/'README.md').write_text('\n'.join(text))
    (ROOT/'01_Tai_lieu/current_features.json').write_text(json.dumps(features,ensure_ascii=False,indent=2)+'\n')
    print(f'README: logo, {len(sections)} menu features, {len(captures)} verified screenshots')


if __name__=='__main__':
    main()
