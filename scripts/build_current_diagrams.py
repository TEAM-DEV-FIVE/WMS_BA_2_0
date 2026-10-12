"""Render source-backed WMS diagrams, with editable draw.io and Graphviz sources."""

import ast
import html
import json
import re
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from diagram_scenes import Scene, use_case_graphs, workflow_graphs
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
    def visibility(name):
        return '-' if name.startswith('_') else '+'

    def annotation(value):
        return ast.unparse(value) if value else ''

    fields = {}
    for item in cls.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            fields[item.target.id] = annotation(item.annotation)
    init = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__'), None)
    if init:
        arg_types = {a.arg: annotation(a.annotation) for a in init.args.args}
        for item in ast.walk(init):
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    for attr in ast.walk(target):
                        if isinstance(attr, ast.Attribute) and isinstance(attr.value, ast.Name) and attr.value.id == 'self':
                            dtype = annotation(item.annotation) if isinstance(item, ast.AnnAssign) else ''
                            if isinstance(item.value, ast.Name):
                                dtype = arg_types.get(item.value.id, dtype)
                            fields.setdefault(attr.attr, dtype)
    attributes = [visibility(key) + key + (': ' + value if value else '') for key, value in fields.items()][:6]
    methods = []
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith('_'):
            result = annotation(item.returns)
            arguments = [a for a in [*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs] if a.arg not in {'self','cls'}]
            signature = '(…)' if arguments or item.args.vararg or item.args.kwarg else '()'
            methods.append('+' + item.name + signature + (': ' + result if result else ''))
    n = node(name, [file, *attributes, *methods[:7]])
    n.update(kind='class', attributes=attributes, operations=methods[:7],
             bases=[ast.unparse(b) for b in cls.bases], partial=True)
    return n


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
            [('ReceiptPost','OrderAction','Kế thừa'),('ReceiptView','OrderView','Kế thừa')]),
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
    result.extend(workflow_graphs())
    for g in result:
        if g['code'].startswith('CLASS_'):
            g['notation'] = 'UML class'
            g['relations'] = []
            for source, target, label in g['edges']:
                kind = 'generalization' if target in g['nodes'][source]['bases'] else 'dependency'
                if source == 'PostgresUnitOfWork' and target == 'UnitOfWork':
                    kind = 'realization'
                g['relations'].append(dict(kind=kind))
        elif g['code'] == 'STATE_DOCUMENT':
            g['notation'] = 'UML state'
            for n in g['nodes'].values():
                n['kind'] = 'state'
            g['nodes']['initial'] = dict(name='', lines=[], kind='initial')
            g['edges'].insert(0, ('initial', 'DRAFT', 'create'))
        elif g['code'] == 'COMMAND_RECOVERY':
            g['notation'] = 'Activity overview'
            for n in g['nodes'].values():
                n['kind'] = 'task'
            g['nodes']['choice'] = dict(name='Có kết quả khớp key/hash?', lines=[], kind='decision')
            g['nodes']['response'] = dict(name='Nhận được phản hồi?', lines=[], kind='decision')
            g['nodes']['found'] = dict(name='Tìm thấy ACK?', lines=[], kind='decision')
            g['edges'] = [(a,b,label) for a,b,label in g['edges'] if a not in {'lock','commit','lookup'}]
            g['edges'] += [('lock','choice','Quyền và hash hợp lệ'), ('choice','old','Có'),
                           ('choice','handle','Chưa có; send-v1'), ('commit','response',''),
                           ('response','ack','Có'), ('response','unknown','Không'), ('lookup','found',''),
                           ('found','ack','Có'), ('found','retry','Không: OPERATION_UNCONFIRMED')]
    return result


def unique_keys(table):
    keys = [set(c['columns']) for c in table['constraints'] if c['kind'] in {'p','u'}]
    for sql in table['indexes']:
        match = re.search(r'CREATE UNIQUE INDEX .* USING btree \(([^()]+)\)(?: WHERE (.*))?$', sql)
        if not match:
            continue
        columns = [part.strip().strip('"') for part in match[1].split(',')]
        if not all(re.fullmatch(r'[a-z_][a-z_0-9]*', c) for c in columns):
            continue
        # A partial UNIQUE applies to referenced rows only when its predicate is
        # exactly IS NOT NULL on indexed columns (no business-state predicates).
        predicate = match[2]
        if predicate:
            normalized = predicate.replace('(', '').replace(')', '').replace('"', '')
            if any(term.strip() not in {c+' IS NOT NULL' for c in columns} for term in normalized.split(' AND ')):
                continue
        keys.append(set(columns))
    return keys


def foreign_key_relation(table, fk):
    columns = set(fk['columns'])
    optional = any(c['nullable'] for c in table['columns'] if c['name'] in columns)
    unique = any(key <= columns for key in unique_keys(table))
    primary = {c for constraint in table['constraints'] if constraint['kind'] == 'p' for c in constraint['columns']}
    return dict(kind='fk', source_columns=fk['columns'], target_columns=fk['target_columns'],
                constraint=fk['name'], source_cardinality='0..1' if unique else '0..*',
                target_cardinality='0..1' if optional else '1', identifying=columns <= primary)


def table_graphs(schema):
    tables = {t['name']:t for t in schema['tables']}
    result = []
    for name, table in tables.items():
        keys = {x for c in table['constraints'] if c['kind']=='p' for x in c['columns']}
        nodes = {name: node(name, [('PK ' if c['name'] in keys else '') + c['name'] + ' : ' + c['type']
                                 + (' ?' if c['nullable'] else '') for c in table['columns']])}
        foreign_columns = {col for c in table['constraints'] if c['kind'] == 'f' for col in c['columns']}
        for i, col in enumerate(table['columns']):
            if col['name'] in foreign_columns:
                nodes[name]['lines'][i] = 'FK ' + nodes[name]['lines'][i]
        edges = []
        relations = []
        for fk in table['constraints']:
            if fk['kind'] != 'f':
                continue
            relations.append(foreign_key_relation(table, fk))
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
        g = graph('ERD_' + name,'ERD · ' + name,nodes,edges,
                  ['02_CSDL/current/schema.json','migrations/001_schema.sql … 026_user_avatar.sql'])
        g.update(notation='Physical ERD', relations=relations)
        result.append(g)
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


def legend(g):
    if g['code'].startswith('ERD_'):
        return ('Ch8 PDF 48–52 · ERD vật lý / Crow’s Foot · PK: khóa chính; FK: khóa ngoại; ?: nullable\n'
                '1: đúng một; 0..1: tùy chọn; 0..*: nhiều · Nét liền: FK thuộc PK; nét đứt: FK không định danh')
    if g['code'].startswith('CLASS_'):
        return ('Ch8 PDF 66–71 · UML implementation view · + công khai; − nội bộ theo quy ước Python\n'
                'Lược chọn thành viên; kiểu chỉ ghi khi mã có annotation. Protocol được hiện thực theo cấu trúc.')
    if g['code'] == 'COMMAND_RECOVERY':
        return 'Luồng hoạt động rút gọn; lỗi quyền, hash khác và lỗi nghiệp vụ bị từ chối tại API/CommandBus.'
    if g['code'] == 'STATE_DOCUMENT':
        return 'UML state · Lát cắt trạng thái chung; nhánh thực hiện phụ thuộc loại chứng từ và quyền thao tác.'
    if g['code'].startswith('ROLE_'):
        return 'RBAC · Vai trò và quyền seed sau migration 001–026'
    return 'Kiến trúc triển khai · Desktop, API, lưu trữ và worker'


def dot_source(g):
    title_rows = ['<TR><TD><FONT POINT-SIZE="20">'+html.escape(g['title'])+'</FONT></TD></TR>']
    for line in legend(g).splitlines():
        for part in textwrap.wrap(line, 100):
            title_rows.append('<TR><TD><FONT POINT-SIZE="10">'+html.escape(part)+'</FONT></TD></TR>')
    title = '<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="3">'+''.join(title_rows)+'</TABLE>'
    lines=['digraph WMS {', 'graph [rankdir='+g['direction']+', bgcolor="white", nodesep=.5, ranksep=.9, pad=.3];',
           'node [shape=plain, fontname="DejaVu Sans", fontsize=12];',
           'edge [fontname="DejaVu Sans", fontsize=10, color="#334155", fontcolor="#334155", arrowsize=.8];',
           'label=<'+title+'>; labelloc=t; fontname="DejaVu Sans"; fontsize=16;']
    if g['code'] == 'COMMAND_RECOVERY':
        lines.append('graph [ranksep=.35];')
    for key,n in g['nodes'].items():
        kind=n.get('kind')
        if kind in {'state','task','decision','initial'}:
            shape={'state':'box','task':'box','decision':'diamond','initial':'circle'}[kind]
            style='rounded,filled' if kind in {'state','task'} else 'filled'
            label=n['name']+'\n'+'\n'.join(n['lines']) if n['lines'] else n['name']
            label='\n'.join(textwrap.wrap(label,18)) if kind=='decision' else label
            attrs=f'shape={shape}, style="{style}", fillcolor="#e3f1f8", label={json.dumps(label,ensure_ascii=False)}'
            if kind=='initial':
                attrs='shape=circle, width=.2, height=.2, fixedsize=true, style=filled, fillcolor="#17384d", label=""'
            lines.append(json.dumps(key)+' ['+attrs+'];')
            continue
        title=('«protocol»<BR/>' if 'Protocol' in n.get('bases',[]) else '')+html.escape(n['name'])
        rows=['<TR><TD BGCOLOR="#b7dff2"><B>'+title+'</B></TD></TR>']
        groups=[n['attributes'],n['operations']] if kind=='class' else [n['lines']]
        for group in groups:
            rendered=[]
            for line in group:
                rendered.extend(html.escape(part) for part in textwrap.wrap(line,68) or [''])
            rows.append('<TR><TD ALIGN="LEFT" BALIGN="LEFT">'+('<BR ALIGN="LEFT"/>'.join(rendered) or ' ')+'</TD></TR>')
        label='<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="7" COLOR="#526f83">'+''.join(rows)+'</TABLE>'
        lines.append(json.dumps(key)+' [label=<'+label+'>];')
    if g['code'] == 'CLASS_DESKTOP':
        lines += ['{rank=same; "DesktopShell"; "OrderView"; "OrderPresenter";}',
                  '{rank=same; "IdentityClient"; "RecoveryJournal"; "CommandStore";}']
    for i,(source,target,label) in enumerate(g['edges']):
        relation=g.get('relations',[{}]*len(g['edges']))[i]
        attrs={'label':label}
        kind=relation.get('kind')
        if kind=='fk':
            attrs.update(dir='both', arrowtail='teeodot' if relation['source_cardinality']=='0..1' else 'crowodot',
                         arrowhead='teeodot' if relation['target_cardinality']=='0..1' else 'teetee',
                         taillabel=relation['source_cardinality'], headlabel=relation['target_cardinality'],
                         labeldistance='2', style='solid' if relation['identifying'] else 'dashed')
        elif kind in {'generalization','realization'}:
            attrs.update(arrowhead='empty', style='dashed' if kind=='realization' else 'solid')
        elif kind=='dependency':
            attrs.update(arrowhead='vee',style='dashed')
        encoded=', '.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in attrs.items())
        lines.append(f'{json.dumps(source)} -> {json.dumps(target)} [{encoded}];')
    return '\n'.join(lines+['}'])


def drawio_page(root,g,layout):
    width,height=map(float,layout['bb'].split(',')[2:])
    diagram=ET.SubElement(root,'diagram',id=g['code'],name=g['title'])
    model=ET.SubElement(diagram,'mxGraphModel',page='1',pageScale='1',pageWidth=str(int(width+80)),pageHeight=str(int(height+100)))
    cells=ET.SubElement(model,'root')
    ET.SubElement(cells,'mxCell',id='0')
    ET.SubElement(cells,'mxCell',id='1',parent='0')
    title=ET.SubElement(cells,'mxCell',id='title',value=g['title']+'<br/>'+legend(g).replace('\n','<br/>'),vertex='1',parent='1',
                        style='text;html=1;align=center;fontSize=14;whiteSpace=wrap;')
    ET.SubElement(title,'mxGeometry',x='20',y='10',width=str(width+40),height='85',attrib={'as':'geometry'})
    for obj in layout['objects']:
        if obj['name'] not in g['nodes']:
            continue
        key=obj['name']
        x,y=map(float,obj['pos'].split(','))
        w,h=float(obj['width'])*72,float(obj['height'])*72
        n=g['nodes'][key]
        kind=n.get('kind')
        value='<b>'+html.escape(n['name'])+'</b>'
        if kind=='class':
            if 'Protocol' in n.get('bases',[]):
                value='«protocol»<br/>'+value
            value += '<hr/>'+'<br/>'.join(html.escape(s) for s in n['attributes'])
            value += '<hr/>'+'<br/>'.join(html.escape(s) for s in n['operations'])
        else:
            value += ''.join('<br/>'+html.escape(s) for s in n['lines'])
        shape={'decision':'rhombus;','initial':'ellipse;fillColor=#17384d;',
               'state':'rounded=1;','task':'rounded=1;'}.get(kind,'rounded=0;')
        cell=ET.SubElement(cells,'mxCell',id=key,value=value,vertex='1',parent='1',
            style='whiteSpace=wrap;html=1;fillColor=#e3f1f8;strokeColor=#526f83;fontSize=12;align=left;verticalAlign=middle;spacing=8;'+shape)
        ET.SubElement(cell,'mxGeometry',x=str(x-w/2+40),y=str(height-y-h/2+60),width=str(w),height=str(h),attrib={'as':'geometry'})
    for i,(source,target,label) in enumerate(g['edges']):
        relation=g.get('relations',[{}]*len(g['edges']))[i]
        kind=relation.get('kind')
        style='endArrow=block;'
        if kind=='fk':
            style='startArrow='+('ERzeroToOne' if relation['source_cardinality']=='0..1' else 'ERzeroToMany')+';'
            style+='endArrow='+('ERzeroToOne' if relation['target_cardinality']=='0..1' else 'ERmandOne')+';'
            style+='dashed='+('0' if relation['identifying'] else '1')+';'
            label += '<br/>'+relation['source_cardinality']+' → '+relation['target_cardinality']
        elif kind in {'generalization','realization'}:
            style='endArrow=block;endFill=0;dashed='+('1' if kind=='realization' else '0')+';'
        elif kind=='dependency':
            style='endArrow=open;dashed=1;'
        cell=ET.SubElement(cells,'mxCell',id='edge'+str(i),value=label,edge='1',parent='1',source=source,target=target,
                           style='edgeStyle=orthogonalEdgeStyle;html=1;strokeColor=#334155;fontSize=10;'+style)
        ET.SubElement(cell,'mxGeometry',relative='1',attrib={'as':'geometry'})


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    for folder in ['svg','dot']:
        (DEST/folder).mkdir(exist_ok=True)
    temporary = ROOT / '.reports/current-diagrams'
    temporary.mkdir(parents=True, exist_ok=True)
    schema=json.loads((ROOT/'02_CSDL/current/schema.json').read_text())
    features=json.loads((ROOT/'01_Tai_lieu/current_features.json').read_text())
    graphs=main_graphs()+use_case_graphs(features)+role_graphs(schema)+table_graphs(schema)
    pdfmetrics.registerFont(TTFont('WMS', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    drawio=ET.Element('mxfile',host='app.diagrams.net',type='device')
    pdfs=[]
    index=['# Sơ đồ hiện hành của WMS','',
           'Sinh từ mã nguồn và schema PostgreSQL dựng bằng migration 001–026. '
           'Các luồng mô tả xử lý trong phần mềm; không đại diện cho khảo sát quy trình doanh nghiệp.', '',
           '[Ký pháp và nguồn giáo trình](../NOTATION_GUIDE.md). Use case và BPMN dùng bố cục riêng; '
           'ERD dùng Crow’s Foot và lực lượng quan hệ suy từ schema. Lớp dùng các ngăn UML.', '',
           '| Sơ đồ | Nguồn đối chiếu |','|---|---|']
    for g in graphs:
        for source in g['sources']:
            if '*' not in source and '…' not in source and not (ROOT/source).exists():
                raise ValueError('Missing source '+source)
        if g.get('notation') in {'BPMN','UML use case'}:
            Scene(g,temporary/f"{g['code']}.pdf",drawio).render(DEST/'svg'/f"{g['code']}.svg")
            # Typed source is diagram_sources.json; remove superseded generic DOT.
            (DEST/'dot'/f"{g['code']}.dot").unlink(missing_ok=True)
        else:
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
