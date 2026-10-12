"""Render source-backed WMS diagrams, with editable draw.io and Graphviz sources."""

import ast
import html
import json
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '03_So_do/Hien_hanh'


def node(name, lines=()):
    return {'name': name, 'lines': list(lines)}


def graph(code, title, nodes, edges, sources, direction='LR'):
    return dict(code=code, title=title, nodes=nodes, edges=edges, sources=sources, direction=direction)


def actual_class(file, name):
    tree = ast.parse((ROOT / file).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    methods = [n.name + '()' for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')]
    fields = [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
    return node(name, [file, *fields[:5], *methods[:7]])


def main_graphs():
    result = [graph('ARCHITECTURE', 'Kiến trúc ứng dụng hiện tại', {
        'desktop': node('Desktop Tkinter', ['views / presenters / API client', 'Luồng UI và executor I/O']),
        'local': node('SQLite cục bộ', ['Nháp và nhật ký lệnh', 'Tách máy chủ / tài khoản / thiết bị']),
        'proxy': node('Reverse proxy Nginx', ['Cấu hình triển khai LAN', 'HTTPS; chuyển header phục hồi']),
        'api': node('FastAPI', ['create_app()', 'Xác thực và dịch vụ nghiệp vụ']),
        'db': node('PostgreSQL', ['Schema wms', '108 bảng qua migration 001–026']),
        'workers': node('Worker nền', ['Outbox · import · export · print', 'Export cleanup · print cleanup', 'Auth delivery']),
        'files': node('Kho tệp riêng', ['Import / export / PDF', 'Truy cập qua API kiểm quyền']),
        'vault': node('Kho bí mật hệ điều hành', ['SessionVault', 'Nhớ phiên khi người dùng bật']),
        'print': node('Hệ thống in của máy', ['Spooler Windows / CUPS', 'Máy quét HID nhập bàn phím']),
    }, [('desktop','proxy','HTTPS'),('proxy','api','HTTP nội bộ'),('api','db','SQLAlchemy / psycopg'),
        ('desktop','local','Nháp / key'),('desktop','vault','Refresh token'),('workers','db','Job / lease / ACK'),
        ('workers','files','Tác vụ tệp'),('api','files','Kiểm soát tải tệp'),('desktop','print','In / nhập mã')],
        ['apps/desktop/views/shell.py','apps/server/api/app.py','deploy/lan','apps/desktop/local_store/session_vault.py'])]
    specs = [
        ('CLASS_DESKTOP','Các lớp desktop đang triển khai', [
            ('apps/desktop/views/shell.py','DesktopShell'), ('apps/desktop/views/orders.py','OrderView'),
            ('apps/desktop/presenters/orders.py','OrderPresenter'), ('apps/desktop/api/identity.py','IdentityClient'),
            ('apps/desktop/local_store/recovery.py','RecoveryJournal'),
            ('apps/desktop/local_store/commands.py','CommandStore')],
            [('DesktopShell','OrderView','Khởi tạo / điều phối'),('OrderView','OrderPresenter','Sự kiện UI'),
             ('OrderPresenter','IdentityClient','Gọi API qua executor'),('IdentityClient','RecoveryJournal','Nhật ký phục hồi'),
             ('RecoveryJournal','CommandStore','Lưu lệnh cục bộ')]),
        ('CLASS_SERVER','Các lớp xử lý lệnh trên máy chủ', [
            ('apps/server/application/orders.py','OrderService'),('apps/server/application/receipts.py','ReceiptService'),
            ('apps/server/application/commands.py','CommandBus'),('apps/server/infrastructure/database.py','PostgresUnitOfWork'),
            ('apps/server/infrastructure/database.py','PostgresCommandRepository'),('apps/server/application/ports.py','UnitOfWork')],
            [('ReceiptService','OrderService','Dùng orders / identity / bus'),('OrderService','CommandBus','execute()'),
             ('CommandBus','UnitOfWork','Giao diện transaction'),('PostgresUnitOfWork','UnitOfWork','Hiện thực giao thức'),
             ('PostgresUnitOfWork','PostgresCommandRepository','commands')]),
        ('CLASS_CONTRACTS','Các hợp đồng dữ liệu và lỗi đang triển khai', [
            ('packages/contracts/orders.py','OrderAction'),('packages/contracts/receipts.py','ReceiptPost'),
            ('packages/contracts/orders.py','OrderView'),('packages/contracts/receipts.py','ReceiptView'),
            ('apps/server/application/commands.py','CommandResult'),('apps/server/domain/errors.py','DomainError')],
            [('ReceiptPost','OrderAction','Kế thừa'),('ReceiptView','OrderView','Kế thừa'),
             ('ReceiptPost','CommandResult','Xử lý qua ReceiptService')]),
    ]
    for code,title,classes,edges in specs:
        result.append(graph(code,title,{name:actual_class(file,name) for file,name in classes},edges,[f for f,_ in classes],
                            'TB' if code == 'CLASS_DESKTOP' else 'LR'))
    result.append(graph('STATE_DOCUMENT','Trạng thái chứng từ và điều kiện chuyển', {
        name:node(name) for name in ['DRAFT','SUBMITTED','APPROVED','REJECTED','PARTIAL','COMPLETED','CANCELLED']
    }, [('DRAFT','SUBMITTED','submit; kiểm tra dữ liệu'),('REJECTED','DRAFT','Sửa nháp'),
        ('REJECTED','SUBMITTED','Gửi lại hợp lệ'),('SUBMITTED','APPROVED','Đủ các bước duyệt'),
        ('SUBMITTED','REJECTED','Từ chối'),('APPROVED','DRAFT','revise; hủy hiệu lực duyệt'),
        ('APPROVED','PARTIAL','Thực hiện một phần theo loại phiếu'),('APPROVED','COMPLETED','Thực hiện đủ'),
        ('PARTIAL','COMPLETED','Thực hiện đủ / đóng phần còn lại hợp lệ'),
        *[(s,'CANCELLED','cancel trước thực hiện') for s in ['DRAFT','SUBMITTED','REJECTED','APPROVED']]],
        ['apps/server/application/orders.py','apps/server/application/receipts.py','apps/server/application/issues.py'], 'TB'))
    result.append(graph('COMMAND_RECOVERY','Luồng xử lý lệnh và phục hồi ACK', {
        'input':node('Người dùng xác nhận thao tác'),
        'store':node('IdentityClient / RecoveryJournal', ['Lưu nội dung và idempotency key', 'Đánh dấu lệnh SENDING']),
        'api':node('API nhận lệnh', ['Kiểm tra DTO / phiên / quyền']),
        'lock':node('CommandBus', ['Khóa key; authorize trong UoW', 'Đối chiếu request hash']),
        'old':node('Đã có kết quả cùng key', ['Trả lại kết quả đã lưu']),
        'handle':node('Handler nghiệp vụ', ['Kiểm tra phiên bản / trạng thái', 'Khóa dữ liệu; cập nhật nghiệp vụ']),
        'commit':node('Transaction commit', ['Lưu kết quả idempotency', 'Dữ liệu / audit / outbox theo handler']),
        'ack':node('Nhận ACK và kết quả', ['Đánh dấu COMMITTED cục bộ']),
        'unknown':node('Mất phản hồi', ['Giữ lệnh UNKNOWN']),
        'lookup':node('Tra ACK bằng yêu cầu gốc', ['X-WMS-Recovery: lookup-v1', 'Không thực thi lệnh còn thiếu']),
        'retry':node('Người dùng quyết định gửi lại', ['Cùng key và cùng nội dung']),
    }, [('input','store',''),('store','api','send-v1'),('api','lock',''),('lock','old','Key tồn tại, hash khớp'),
        ('lock','handle','Chưa có, gửi lệnh thật'),('handle','commit','Hợp lệ'),('commit','ack','Phản hồi nhận được'),
        ('old','ack',''),('commit','unknown','Phản hồi bị mất'),('unknown','lookup','Theo yêu cầu người dùng'),
        ('lookup','ack','Tìm thấy kết quả'),('lookup','retry','OPERATION_UNCONFIRMED'),('retry','api','send-v1')],
        ['apps/desktop/local_store/recovery.py','apps/server/api/recovery.py','apps/server/application/commands.py'], 'TB'))
    workflows = [
        ('FLOW_RECEIPT','Luồng nhận hàng trong phần mềm',['PO đã được duyệt','Lập phiếu nhận và dòng kế hoạch','Gửi duyệt phiếu nhận','Người có thẩm quyền duyệt','Ghi sổ nhận hàng','Ledger / số dư / kết quả thực hiện'],
         ['apps/server/application/receipts.py','apps/server/application/orders.py']),
        ('FLOW_ISSUE','Luồng giữ hàng và xuất kho',['SO đã được duyệt','Lập, gửi duyệt và duyệt phiếu xuất','Giữ số lượng khả dụng','Soạn hàng và đóng kiện theo tác vụ','Ghi sổ xuất theo dòng hợp lệ'],
         ['apps/server/application/issues.py','apps/server/application/reservations.py','apps/server/application/picking.py']),
        ('FLOW_COUNT','Luồng kiểm kê trong phần mềm',['Chọn phạm vi và tạo phiên','Đóng băng phạm vi và snapshot','Ghi các lần đếm','Nộp kết quả kiểm kê','Ra quyết định đối soát','Ghi điều chỉnh theo kết quả được duyệt'],
         ['apps/server/application/counting.py']),
        ('FLOW_TRANSFER','Luồng chuyển kho trong phần mềm',['Lập phiếu chuyển','Gửi duyệt và duyệt','Ghi xuất vào transit','Ghi nhận tại kho đích','Xử lý chênh lệch nếu có','Hoàn tất hoặc tiếp tục phần còn lại'],
         ['apps/server/application/transfers.py','apps/server/application/transfer_stock.py']),
        ('FLOW_IMPORT','Luồng nhập dữ liệu từ tệp',['Chọn mẫu và tệp','Kiểm tra và tải tệp lên','Tạo job và dry run','Xem lỗi hoặc kết quả kiểm tra','Xác nhận commit với token hợp lệ','Xem chứng từ đã tạo hoặc lịch sử'],
         ['apps/desktop/views/imports.py','apps/server/application/imports.py','apps/server/application/import_jobs.py']),
        ('FLOW_LIFECYCLE','Tải lại giao diện và đóng ứng dụng',['Bấm Tải lại hoặc đóng cửa sổ','Xác nhận và nhắc phần chưa lưu','Ngừng nhận việc mới','Chờ executor và đóng journal','Giải phóng Tk và API client','Nhả khóa ứng dụng','Khởi động lại nếu đã chọn Tải lại'],
         ['apps/desktop/views/shell.py','apps/desktop/lifecycle.py','apps/desktop/__main__.py']),
    ]
    for code,title,steps,sources in workflows:
        result.append(graph(code,title,{f'n{i}':node(s) for i,s in enumerate(steps)},
                            [(f'n{i}',f'n{i+1}','') for i in range(len(steps)-1)], sources, 'TB'))
    return result


def table_graphs(schema):
    tables = {t['name']:t for t in schema['tables']}
    result = []
    for name, table in tables.items():
        keys = {x for c in table['constraints'] if c['kind']=='p' for x in c['columns']}
        nodes = {name: node(name, [('PK ' if c['name'] in keys else '') + c['name'] + ' : ' + c['type']
                                 + (' ?' if c['nullable'] else '') for c in table['columns']])}
        edges = []
        for fk in table['constraints']:
            if fk['kind'] != 'f':
                continue
            target = fk['target']
            if target not in nodes:
                nodes[target] = node(target, ['Bảng đích — các cột được tham chiếu'])
            if target != name:
                for col in fk['target_columns']:
                    dtype = next(c['type'] for c in tables[target]['columns'] if c['name']==col)
                    label = col + ' : ' + dtype
                    if label not in nodes[target]['lines']:
                        nodes[target]['lines'].append(label)
            edges.append((name,target,', '.join(fk['columns']) + ' → ' + ', '.join(fk['target_columns'])))
        result.append(graph('ERD_' + name,'ERD hiện hành · ' + name,nodes,edges,
                            ['02_CSDL/current/schema.json','migrations/001_schema.sql … 026_user_avatar.sql']))
    return result


def role_graphs(schema):
    result=[]
    permissions={p['code']:p for p in schema['permissions']}
    for role in schema['roles']:
        grants=[r['permission'] for r in schema['role_permissions'] if r['role']==role['code']]
        nodes={'role':node(role['name'],[role['code']])}
        edges=[]
        for start in range(0,len(grants),7):
            lines=[]
            for code in grants[start:start+7]:
                permission=permissions[code]
                lines += [code + ' [' + permission['scope_kind'] + ']',
                          *textwrap.wrap(permission['description'],40), '']
            key=f'group{start//7}'
            nodes[key]=node(f'Quyền {start+1}–{min(start+7,len(grants))}',lines)
            edges.append(('role',key,''))
        result.append(graph('ROLE_'+role['code'],'Vai trò và quyền seed · '+role['name'],nodes,edges,
                            ['04_Phan_quyen/current_permissions.json','migrations/*.sql'], 'TB'))
    return result


def dot_source(g):
    lines=['digraph WMS {', 'graph [rankdir='+g['direction']+', bgcolor="white", nodesep=.32, ranksep=.6, pad=.28];',
           'node [shape=plain, fontname="DejaVu Sans", fontsize=12];',
           'edge [fontname="DejaVu Sans", fontsize=10, color="#567086", fontcolor="#334155", arrowsize=.7];',
           'label='+json.dumps(g['title'],ensure_ascii=False)+'; labelloc=t; fontname="DejaVu Sans"; fontsize=20;']
    for key,n in g['nodes'].items():
        rows=['<TR><TD BGCOLOR="#005b9e"><FONT COLOR="white"><B>'+html.escape(n['name'])+'</B></FONT></TD></TR>']
        for line in n['lines']:
            for part in textwrap.wrap(line,78) or ['']:
                rows.append('<TR><TD ALIGN="LEFT">'+html.escape(part)+'</TD></TR>')
        label='<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="7" COLOR="#b7c9da">'+''.join(rows)+'</TABLE>'
        lines.append(json.dumps(key)+' [label=<'+label+'>];')
    if g['code'] == 'CLASS_DESKTOP':
        lines += ['{rank=same; "DesktopShell"; "OrderView"; "OrderPresenter";}',
                  '{rank=same; "IdentityClient"; "RecoveryJournal"; "CommandStore";}']
    for source,target,label in g['edges']:
        lines.append(f'{json.dumps(source)} -> {json.dumps(target)} [label={json.dumps(label,ensure_ascii=False)}];')
    return '\n'.join(lines+['}'])


def drawio_page(root,g,layout):
    width,height=map(float,layout['bb'].split(',')[2:])
    diagram=ET.SubElement(root,'diagram',id=g['code'],name=g['title'])
    model=ET.SubElement(diagram,'mxGraphModel',page='1',pageScale='1',pageWidth=str(int(width+80)),pageHeight=str(int(height+100)))
    cells=ET.SubElement(model,'root')
    ET.SubElement(cells,'mxCell',id='0')
    ET.SubElement(cells,'mxCell',id='1',parent='0')
    for obj in layout['objects']:
        if obj['name'] not in g['nodes']:
            continue
        key=obj['name']
        x,y=map(float,obj['pos'].split(','))
        w,h=float(obj['width'])*72,float(obj['height'])*72
        n=g['nodes'][key]
        value='<b>'+html.escape(n['name'])+'</b>' + ''.join('<br/>'+html.escape(s) for s in n['lines'])
        cell=ET.SubElement(cells,'mxCell',id=key,value=value,vertex='1',parent='1',
            style='rounded=0;whiteSpace=wrap;html=1;fillColor=#edf4fb;strokeColor=#567086;fontSize=12;align=left;verticalAlign=top;spacing=8;')
        ET.SubElement(cell,'mxGeometry',x=str(x-w/2+40),y=str(height-y-h/2+60),width=str(w),height=str(h),attrib={'as':'geometry'})
    for i,(source,target,label) in enumerate(g['edges']):
        cell=ET.SubElement(cells,'mxCell',id='edge'+str(i),value=label,edge='1',parent='1',source=source,target=target,
                           style='edgeStyle=orthogonalEdgeStyle;html=1;endArrow=block;strokeColor=#567086;fontSize=10;')
        ET.SubElement(cell,'mxGeometry',relative='1',attrib={'as':'geometry'})


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    for folder in ['svg','dot']:
        (DEST/folder).mkdir(exist_ok=True)
    temporary = ROOT / '.reports/current-diagrams'
    temporary.mkdir(parents=True, exist_ok=True)
    schema=json.loads((ROOT/'02_CSDL/current/schema.json').read_text())
    graphs=main_graphs()+role_graphs(schema)+table_graphs(schema)
    drawio=ET.Element('mxfile',host='app.diagrams.net',type='device')
    pdfs=[]
    index=['# Sơ đồ hiện hành của WMS','',
           'Sinh từ mã nguồn và schema PostgreSQL dựng bằng migration 001–026. '
           'Các luồng mô tả xử lý trong phần mềm; không đại diện cho khảo sát quy trình doanh nghiệp.', '',
           'ERD: dấu ? là nullable; mũi tên biểu diễn FK từ cột nguồn sang cột đích. '
           'PK ghép, CHECK, UNIQUE và index đầy đủ trong `02_CSDL/current/schema.json`.', '',
           '| Sơ đồ | Nguồn đối chiếu |','|---|---|']
    for g in graphs:
        for source in g['sources']:
            if '*' not in source and '…' not in source and not (ROOT/source).exists():
                raise ValueError('Missing source '+source)
        source=DEST/'dot'/f"{g['code']}.dot"
        source.write_text(dot_source(g))
        for fmt in ['svg','pdf']:
            output = (DEST/'svg' if fmt == 'svg' else temporary)/f"{g['code']}.{fmt}"
            subprocess.run(['dot','-T'+fmt,str(source),'-o',str(output)],check=True,capture_output=True)
        layout=json.loads(subprocess.check_output(['dot','-Tjson',str(source)]))
        drawio_page(drawio,g,layout)
        pdfs.append(str(temporary/f"{g['code']}.pdf"))
        index.append(f"| [{g['title']}](svg/{g['code']}.svg) | "+'; '.join('`'+s+'`' for s in g['sources'])+' |')
    pdfmetrics.registerFont(TTFont('WMS', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    contents = temporary/'contents.pdf'
    pdf = canvas.Canvas(str(contents), pagesize=(595,842))
    pdf.setTitle('Sơ đồ hiện hành WMS')
    per_page = 30
    toc_pages = (len(graphs)+per_page-1)//per_page
    for start in range(0,len(graphs),per_page):
        pdf.setFont('WMS',18)
        pdf.drawString(40,795,'Sơ đồ hiện hành WMS')
        pdf.setFont('WMS',9)
        pdf.drawString(40,773,'Mã nguồn và migration 001–026 · 13/10/2026')
        pdf.drawString(40,754,'Mục lục — số trang tính từ đầu tệp PDF')
        for offset,g in enumerate(graphs[start:start+per_page]):
            y = 724 - offset*22
            pdf.drawString(40,y,g['title'])
            pdf.drawRightString(554,y,str(toc_pages+start+offset+1))
        pdf.showPage()
    pdf.save()
    subprocess.run(['pdfunite',str(contents),*pdfs,str(DEST/'WMS_Hien_hanh.pdf')],check=True)
    ET.indent(drawio)
    ET.ElementTree(drawio).write(DEST/'WMS_Hien_hanh.drawio',encoding='utf-8',xml_declaration=True)
    (DEST/'index.md').write_text('\n'.join(index)+'\n')
    (DEST/'diagram_sources.json').write_text(json.dumps(graphs,ensure_ascii=False,indent=2)+'\n')
    print(f"Rendered {len(graphs)} diagrams including {len(schema['tables'])} tables and {schema['counts']['foreign_keys']} FKs")


if __name__=='__main__':
    main()
