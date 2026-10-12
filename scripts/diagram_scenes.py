"""Shared geometry for BPMN and UML use-case SVG/PDF/editable draw.io views."""

import html
import math
import xml.etree.ElementTree as ET
from collections import defaultdict

from reportlab.lib.colors import toColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

INK = "#17384d"
BLUE = "#dceef8"


def box(name, kind, x, y, w=174, h=72, lane=None):
    return dict(name=name, lines=[], kind=kind, x=x-w/2, y=y-h/2, w=w, h=h, lane=lane)


def workflow(code, title, lanes, specs, edges, sources, note):
    nodes = {}
    for key, label, kind, x, lane in specs:
        size = (38, 38) if kind in {"start", "end"} else (58, 58) if kind == "gateway" else (174, 72)
        nodes[key] = box(label, kind, x, 230+190*lane, *size, lane=lane)
    return dict(code=code, title=title, nodes=nodes, edges=edges, sources=sources,
                notation="BPMN", lanes=lanes, width=1850, height=820, note=note)


def workflow_graphs():
    service = "apps/server/application/"
    return [
        workflow("FLOW_RECEIPT", "Nhận hàng — phê duyệt và ghi sổ", ["Người nhận hàng", "Người phê duyệt", "Hệ thống WMS"], [
            ("start", "PO đã duyệt", "start", 190, 0),
            ("draft", "Lập phiếu nhận và kế hoạch dòng", "task", 350, 0),
            ("submit", "Gửi phiếu nhận để duyệt", "task", 550, 0),
            ("review", "Thực hiện các bước phê duyệt", "task", 750, 1),
            ("approved", "Được duyệt?", "gateway", 950, 1),
            ("rejected", "Phiếu bị từ chối", "end", 950, 2),
            ("post", "Yêu cầu ghi sổ lượng thực nhận", "task", 1150, 0),
            ("write", "Kiểm tra, ghi sổ và cập nhật tồn", "task", 1450, 2),
            ("end", "Đã ghi nhận", "end", 1730, 2),
        ], [("start","draft",""),("draft","submit",""),("submit","review",""),
            ("review","approved",""),("approved","rejected","Không"),("approved","post","Có"),
            ("post","write",""),("write","end","")], [service+"receipts.py",service+"orders.py"],
            "Tiền điều kiện: có quyền và PO còn lượng nhận. Một lần ghi sổ có thể nhận một phần hoặc đủ."),
        workflow("FLOW_ISSUE", "Xuất kho — duyệt, giữ hàng, soạn và ghi sổ", ["Người xử lý phiếu xuất", "Người phê duyệt", "Hệ thống WMS"], [
            ("start", "SO đã duyệt", "start", 190, 0),
            ("draft", "Lập và gửi duyệt phiếu xuất", "task", 350, 0),
            ("review", "Thực hiện các bước phê duyệt", "task", 550, 1),
            ("approved", "Được duyệt?", "gateway", 750, 1),
            ("rejected", "Phiếu bị từ chối", "end", 750, 2),
            ("reserve", "Giữ số lượng khả dụng", "task", 950, 0),
            ("pick", "Soạn hàng và đóng kiện", "task", 1150, 0),
            ("post", "Yêu cầu ghi sổ xuất", "task", 1350, 0),
            ("write", "Kiểm tra và ghi phát sinh xuất", "task", 1550, 2),
            ("end", "Đã ghi xuất", "end", 1760, 2),
        ], [("start","draft",""),("draft","review",""),("review","approved",""),
            ("approved","rejected","Không"),("approved","reserve","Có"),("reserve","pick",""),
            ("pick","post",""),("post","write",""),("write","end","")],
            [service+"issues.py",service+"reservations.py",service+"picking.py"],
            "Giữ hàng/soạn hàng thực hiện trên phiếu đã duyệt; nguồn giữ, số lượng và phiên bản được kiểm tra khi ghi sổ."),
        workflow("FLOW_COUNT", "Kiểm kê — từ phạm vi đếm đến điều chỉnh", ["Người thực hiện kiểm kê", "CONTROLLER / DIRECTOR", "Hệ thống WMS"], [
            ("start", "Bắt đầu", "start", 190, 0),
            ("create", "Tạo phiên và chọn phạm vi", "task", 350, 0),
            ("freeze", "Đóng băng phạm vi, chụp snapshot", "task", 550, 2),
            ("count", "Ghi các lượt đếm độc lập", "task", 750, 0),
            ("submit", "Nộp kết quả hợp lệ", "task", 950, 0),
            ("review", "CONTROLLER rồi DIRECTOR quyết định", "task", 1150, 1),
            ("approved", "Đủ hai duyệt?", "gateway", 1350, 1),
            ("rejected", "Từ chối: COUNTED", "end", 1350, 0),
            ("post", "Ghi điều chỉnh được yêu cầu", "task", 1550, 2),
            ("end", "Đã điều chỉnh", "end", 1760, 2),
        ], [("start","create",""),("create","freeze",""),("freeze","count",""),
            ("count","submit",""),("submit","review",""),("review","approved",""),
            ("approved","rejected","Bị từ chối"),("approved","post","Có"),("post","end","")],
            [service+"counting.py"],
            "Tác vụ quyết định chờ đủ bước duyệt hoặc bị từ chối. Ghi điều chỉnh cần adjustment.post và snapshot duyệt còn hiệu lực."),
        workflow("FLOW_TRANSFER", "Chuyển kho — xuất transit và nhận tại đích", ["Người thao tác kho nguồn", "Người duyệt / kho đích", "Hệ thống WMS"], [
            ("start", "Bắt đầu", "start", 190, 0),
            ("draft", "Lập và gửi duyệt phiếu chuyển", "task", 350, 0),
            ("review", "Phê duyệt phiếu chuyển", "task", 550, 1),
            ("ship", "Kiểm tra và ghi xuất vào transit", "task", 750, 2),
            ("receive", "Nhận hàng tại kho đích", "task", 950, 1),
            ("check", "Có thiếu / hỏng?", "gateway", 1150, 1),
            ("evidence", "Lập chứng cứ, xử lý chênh lệch", "task", 1350, 0),
            ("merge", "", "gateway", 1550, 1),
            ("end", "Kết thúc lần xử lý", "end", 1760, 1),
        ], [("start","draft",""),("draft","review",""),("review","ship","Đã duyệt"),
            ("ship","receive","Đã ghi xuất"),("receive","check",""),("check","evidence","Có"),
            ("check","merge","Không"),("evidence","merge",""),("merge","end","")],
            [service+"transfers.py",service+"transfer_stock.py"],
            "Lát cắt phiếu được duyệt. Xuất/nhận kiểm tra kỳ, quyền hai kho và số lượng; còn transit thì phiếu chưa hoàn tất."),
        workflow("FLOW_IMPORT", "Nhập tệp — kiểm tra trước khi commit", ["Người nhập dữ liệu", "API WMS", "Worker nhập tệp"], [
            ("start", "Có tệp nguồn", "start", 190, 0),
            ("upload", "Chọn mẫu, kiểm tra và tải tệp", "task", 350, 0),
            ("queue", "Tạo job và đưa vào hàng đợi", "task", 550, 1),
            ("validate", "Dry run và kiểm tra từng dòng", "task", 750, 2),
            ("valid", "Tệp hợp lệ?", "gateway", 950, 2),
            ("invalid", "INVALID: sửa tệp", "end", 950, 1),
            ("token", "Lưu VALIDATED và commit token", "task", 1150, 2),
            ("confirm", "Xem kết quả, xác nhận commit", "task", 1350, 0),
            ("commit", "Kiểm token, quyền và ghi dữ liệu", "task", 1550, 1),
            ("end", "COMMITTED", "end", 1760, 1),
        ], [("start","upload",""),("upload","queue",""),("queue","validate",""),
            ("validate","valid",""),("valid","invalid","Không"),("valid","token","Có"),
            ("token","confirm",""),("confirm","commit",""),("commit","end","")],
            ["apps/desktop/views/imports.py",service+"imports.py",service+"import_jobs.py"],
            "Sơ đồ kết thúc một lần nhập; lỗi tệp được sửa rồi tạo/kiểm tra lại. Chứng từ được tạo tiếp tục quy trình nghiệp vụ riêng."),
        workflow("FLOW_LIFECYCLE", "Tải lại hoặc đóng ứng dụng", ["Người dùng", "Desktop / main thread", "Worker và vòng đời tiến trình"], [
            ("start", "Đóng / Tải lại", "start", 190, 0),
            ("confirm", "Xác nhận và lưu ý phần chưa lưu", "task", 350, 0),
            ("yes", "Đồng ý?", "gateway", 550, 0),
            ("cancel", "Tiếp tục dùng", "end", 550, 1),
            ("stop", "Khóa thao tác, ngừng nhận việc mới", "task", 750, 1),
            ("wait", "Chờ worker và đóng journal", "task", 950, 2),
            ("release", "Đóng Tk, API và nhả khóa", "task", 1150, 1),
            ("reload", "Đã chọn Tải lại?", "gateway", 1350, 2),
            ("restart", "Khởi động lại bản đang cài", "task", 1550, 1),
            ("end", "Đã thoát", "end", 1550, 2),
            ("ready", "Phiên mới", "end", 1760, 1),
        ], [("start","confirm",""),("confirm","yes",""),("yes","cancel","Không"),
            ("yes","stop","Có"),("stop","wait",""),("wait","release",""),("release","reload",""),
            ("reload","restart","Có"),("reload","end","Không"),("restart","ready","")],
            ["apps/desktop/views/shell.py","apps/desktop/lifecycle.py","apps/desktop/__main__.py"],
            "Tải lại khởi động lại phần mềm đang cài sau khi giải phóng tài nguyên; không tải bộ cài từ Internet."),
    ]


GOALS = {
    "session_view": "Chọn kho và quản lý phiên làm việc",
    "master_container": "Quản lý danh mục kho và hàng hóa",
    "serial_view": "Tra cứu serial và chứng cứ bảo hành",
    "custom_fields_view": "Quản lý trường và giá trị mở rộng",
    "order_view": "Lập và theo dõi đơn mua / đơn bán",
    "approval_view": "Phê duyệt hoặc từ chối chứng từ",
    "receipt_view": "Tiếp nhận và ghi sổ hàng mua",
    "opening_view": "Khai báo và ghi sổ tồn đầu kỳ",
    "consignment_view": "Tiếp nhận hàng ký gửi",
    "issue_view": "Giữ hàng và ghi sổ xuất kho",
    "fulfillment_view": "Soạn hàng và đóng kiện",
    "quality_view": "Quyết định chất lượng hàng",
    "move_view": "Cất và di chuyển hàng trong kho",
    "transfer_view": "Chuyển hàng giữa hai kho",
    "customer_return_view": "Tiếp nhận hàng khách trả",
    "supplier_return_view": "Trả hàng nhà cung cấp",
    "report_view": "Tra cứu tồn và xuất báo cáo",
    "count_view": "Kiểm kê và điều chỉnh tồn",
    "period_view": "Mở, khóa và đối soát kỳ kho",
    "reversal_view": "Đảo giao dịch đã ghi sổ",
    "import_view": "Nhập dữ liệu từ tệp",
    "print_view": "Tạo PDF, in chứng từ và tem",
    "admin_view": "Quản lý tài khoản và phân quyền",
    "recovery_view": "Quản lý nháp và phục hồi lệnh",
    "receipt_recovery_view": "Phục hồi lần ghi nhận bị gián đoạn",
    "connection_view": "Kiểm tra kết nối máy chủ",
}


def use_case_graphs(features):
    groups = defaultdict(list)
    for f in features:
        groups[f["group"]].append(f)
    result = []
    for i, (group, rows) in enumerate(groups.items(), 1):
        height = max(520, 260+len(rows)*95)
        nodes = {"actor": box("Người dùng có quyền tương ứng", "actor", 160, height/2, 70, 105)}
        for j, f in enumerate(rows):
            nodes[f["key"]] = box(GOALS[f["key"]], "usecase", 650, 195+j*95, 390, 66)
        result.append(dict(code=f"UC_CURRENT_{i:02}", title="Use case — "+group, notation="UML use case",
                           nodes=nodes, edges=[("actor", f["key"], "") for f in rows],
                           sources=list(dict.fromkeys(["apps/desktop/views/admin_workspace.py", *[f["source"] for f in rows]])),
                           width=1100, height=height, group=group, feature_keys=[f["key"] for f in rows],
                           note="Actor chỉ tham gia use case khi được cấp quyền; scope kho, thời hạn và tách nhiệm vụ vẫn được kiểm tra."))
    return result


def wrapped(text, width, size=14):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = (line+" "+word).strip()
            if pdfmetrics.stringWidth(candidate, "WMS", size) > width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


class Scene:
    """Render one vector geometry to all formats; coordinates use top-left origin."""

    def __init__(self, graph, pdf_path, drawio):
        self.g = graph
        self.w, self.h = graph["width"], graph["height"]
        self.svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(self.w), height=str(self.h),
                              viewBox=f"0 0 {self.w} {self.h}")
        ET.SubElement(self.svg, "title").text = graph["title"]
        self.pdf = canvas.Canvas(str(pdf_path), pagesize=(self.w, self.h), invariant=1)
        self.pdf.setTitle(graph["title"])
        diagram = ET.SubElement(drawio,"diagram",id=graph["code"],name=graph["title"])
        model = ET.SubElement(diagram,"mxGraphModel",page="1",pageWidth=str(self.w),pageHeight=str(self.h))
        self.cells = ET.SubElement(model,"root")
        ET.SubElement(self.cells,"mxCell",id="0")
        ET.SubElement(self.cells,"mxCell",id="1",parent="0")
        self.serial = 0

    def cell(self, value, x, y, w, h, style, key=None):
        self.serial += 1
        key = key or "s"+str(self.serial)
        cell = ET.SubElement(self.cells,"mxCell",id=key,value=value,vertex="1",parent="1",
                             style=style+";html=1;whiteSpace=wrap;fontFamily=DejaVu Sans;fontColor="+INK)
        ET.SubElement(cell,"mxGeometry",x=str(x),y=str(y),width=str(w),height=str(h),attrib={"as":"geometry"})
        return cell

    def text(self, text, x, y, width, size=14, align="center", color=INK, key=None, export=True):
        lines = wrapped(text, width, size)
        line_height = size*1.35
        for i, line in enumerate(lines):
            yy = y+i*line_height
            anchor = "middle" if align == "center" else "start"
            ET.SubElement(self.svg,"text",x=str(x),y=str(yy),fill=color,
                          attrib={"font-family":"DejaVu Sans","font-size":str(size),"text-anchor":anchor}).text = line
            self.pdf.setFillColor(toColor(color))
            self.pdf.setFont("WMS",size)
            (self.pdf.drawCentredString if align == "center" else self.pdf.drawString)(x,self.h-yy,line)
        if export:
            self.cell(html.escape(text),x-width/2 if align=="center" else x,y-size,width,line_height*len(lines)+4,
                      f"text;strokeColor=none;fillColor=none;fontSize={size};align={align};verticalAlign=top;",key)

    def shape(self, kind, x, y, w, h, fill="white", stroke=INK, weight=1.4):
        attrs = dict(fill=fill,stroke=stroke,attrib={"stroke-width":str(weight)})
        self.pdf.setFillColor(toColor(fill))
        self.pdf.setStrokeColor(toColor(stroke))
        self.pdf.setLineWidth(weight)
        if kind in {"start", "end", "usecase", "ellipse"}:
            ET.SubElement(self.svg,"ellipse",cx=str(x+w/2),cy=str(y+h/2),rx=str(w/2),ry=str(h/2),**attrs)
            self.pdf.ellipse(x,self.h-y-h,x+w,self.h-y,fill=1,stroke=1)
        elif kind == "gateway":
            points = [(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)]
            ET.SubElement(self.svg,"polygon",points=" ".join(f"{a},{b}" for a,b in points),**attrs)
            p = self.pdf.beginPath()
            p.moveTo(points[0][0],self.h-points[0][1])
            for a,b in points[1:]:
                p.lineTo(a,self.h-b)
            p.close()
            self.pdf.drawPath(p,fill=1,stroke=1)
        else:
            radius = 12 if kind == "task" else 0
            ET.SubElement(self.svg,"rect",x=str(x),y=str(y),width=str(w),height=str(h),rx=str(radius),**attrs)
            self.pdf.roundRect(x,self.h-y-h,w,h,radius,fill=1,stroke=1)

    def line(self, points, arrow=False, weight=1.5):
        ET.SubElement(self.svg,"polyline",points=" ".join(f"{a},{b}" for a,b in points),fill="none",stroke=INK,
                      attrib={"stroke-width":str(weight)})
        self.pdf.setLineWidth(weight)
        self.pdf.setStrokeColor(toColor(INK))
        p=self.pdf.beginPath()
        p.moveTo(points[0][0], self.h-points[0][1])
        for a,b in points[1:]:
            p.lineTo(a,self.h-b)
        self.pdf.drawPath(p)
        if arrow:
            a,b=points[-1]
            prev=next(v for v in reversed(points[:-1]) if v != points[-1])
            angle=math.atan2(b-prev[1],a-prev[0])
            triangle=[(a,b), (a-10*math.cos(angle-.42),b-10*math.sin(angle-.42)),
                      (a-10*math.cos(angle+.42),b-10*math.sin(angle+.42))]
            ET.SubElement(self.svg,"polygon",points=" ".join(f"{u},{v}" for u,v in triangle),fill=INK)
            p=self.pdf.beginPath()
            p.moveTo(a,self.h-b)
            for u,v in triangle[1:]:
                p.lineTo(u,self.h-v)
            p.close()
            self.pdf.setFillColor(toColor(INK))
            self.pdf.drawPath(p,fill=1,stroke=0)

    def edge(self, source, target, label, index):
        a,b=self.g["nodes"][source],self.g["nodes"][target]
        ax,ay=a["x"]+a["w"]/2,a["y"]+a["h"]/2
        bx,by=b["x"]+b["w"]/2,b["y"]+b["h"]/2
        association=self.g["notation"]=="UML use case"
        if association:
            points=[(ax+35,ay-10),(b["x"],by)]
        elif ax==bx:
            sign=1 if by>ay else -1
            points=[(ax,ay+sign*a["h"]/2),(bx,by-sign*b["h"]/2)]
        else:
            points=[(ax+a["w"]/2,ay)]
            if ay!=by:
                mid=(points[0][0]+b["x"])/2
                points.extend([(mid,ay),(mid,by)])
            points.append((b["x"],by))
        if a['kind'] == 'gateway' and ay != by and ax != bx:
            same_row_branch = any(s == source and self.g['nodes'][t]['y'] + self.g['nodes'][t]['h']/2 == ay
                                  for s,t,_ in self.g['edges'])
            if same_row_branch:
                sign = 1 if by > ay else -1
                points = [(ax,ay+sign*a['h']/2),(ax,by),(b['x'],by)]
        if b['kind'] == 'gateway' and ay != by and ax != bx:
            same_row_incoming = any(t == target and self.g['nodes'][s]['y'] + self.g['nodes'][s]['h']/2 == by
                                    for s,t,_ in self.g['edges'])
            if same_row_incoming:
                sign = 1 if by > ay else -1
                points = [(ax+a['w']/2,ay),(bx,ay),(bx,by-sign*b['h']/2)]
        self.line(points,not association)
        if label:
            vertical = [(p,q) for p,q in zip(points, points[1:]) if p[0] == q[0] and p[1] != q[1]]
            if vertical:
                p,q = max(vertical, key=lambda pair: abs(pair[0][1]-pair[1][1]))
                label_y = (p[1]+q[1])/2
                # Keep connector text clear of lane borders and their headings.
                offset = (label_y-135) % 190
                if offset < 40:
                    label_y -= offset+16
                self.text(label,p[0]+16,label_y,150,13,align="left")
            else:
                self.text(label,(points[0][0]+points[-1][0])/2,ay-13,150,13)
        cell=ET.SubElement(self.cells,"mxCell",id=f"edge{index}",value="",edge="1",parent="1",source=source,target=target,
                           style="html=1;endArrow="+("none" if association else "block")+";endFill=1;strokeColor="+INK+";rounded=0;")
        geo=ET.SubElement(cell,"mxGeometry",relative="1",attrib={"as":"geometry"})
        arr=ET.SubElement(geo,"Array",attrib={"as":"points"})
        for x,y in points[1:-1]:
            ET.SubElement(arr,"mxPoint",x=str(x),y=str(y))

    def render(self, svg_path):
        g=self.g
        self.text(g["title"],40,45,self.w-80,26,align="left")
        if g["notation"]=="BPMN":
            self.shape("rect",30,110,self.w-60,595,BLUE)
            self.cell("",30,110,self.w-60,595,"rounded=0;fillColor="+BLUE+";strokeColor="+INK,key="pool")
            self.text("WMS",65,395,60,15)
            for i,lane in enumerate(g["lanes"]):
                y=135+i*190
                self.shape("rect",100,y,self.w-130,190,"white")
                self.cell("",100,y,self.w-130,190,"rounded=0;fillColor=white;strokeColor="+INK,key=f"lane{i}")
                self.text(lane,115,y+27,480,14,align="left")
        else:
            self.shape("rect",330,115,self.w-375,self.h-205,BLUE)
            self.cell("",330,115,self.w-375,self.h-205,"rounded=0;fillColor="+BLUE+";strokeColor="+INK,key="boundary")
            self.text("WMS · "+g["group"],355,144,self.w-425,17,align="left")
        for i,edge in enumerate(g["edges"]):
            self.edge(*edge,i)
        for key,n in g["nodes"].items():
            kind,x,y,w,h=n["kind"],n["x"],n["y"],n["w"],n["h"]
            cx,cy=x+w/2,y+h/2
            if kind=="actor":
                self.shape("ellipse",cx-12,y,24,24,BLUE)
                for pts in [[(cx,y+24),(cx,y+63)],[(cx-30,y+40),(cx+30,y+40)],
                            [(cx,y+63),(cx-28,y+97)],[(cx,y+63),(cx+28,y+97)]]:
                    self.line(pts)
                self.cell("",x,y,w,h,"shape=umlActor;fillColor="+BLUE+";strokeColor="+INK,key)
                self.text(n["name"],cx,y+h+24,230,15)
                continue
            fill={"start":"#cdeaca","end":"#edc5c6","gateway":"#ffe3b0","task":"#fff5cc","usecase":"#b7dff2"}[kind]
            self.shape(kind,x,y,w,h,fill,weight=3.5 if kind=="end" else 1.5)
            style={"start":"ellipse;","end":"ellipse;strokeWidth=3.5;","gateway":"rhombus;", "task":"rounded=1;arcSize=18;","usecase":"ellipse;"}[kind]
            value = html.escape(n['name']) if kind in {'task','usecase'} else ''
            self.cell(value,x,y,w,h,style+"fontSize=15;align=center;verticalAlign=middle;spacing=10;fillColor="+fill+";strokeColor="+INK,key)
            if kind in {"start","end","gateway"}:
                if kind=="gateway":
                    self.text("×",cx,cy+6,w,22)
                if n["name"]:
                    label_y = y+h+24
                    if kind == 'gateway' and any(s == key and self.g['nodes'][t]['x'] + self.g['nodes'][t]['w']/2 == cx
                                                 and self.g['nodes'][t]['y'] > y for s,t,_ in g['edges']):
                        label_y = y-18
                    if kind == 'end' and any(t == key and self.g['nodes'][s]['x'] + self.g['nodes'][s]['w']/2 == cx
                                             and self.g['nodes'][s]['y'] > y for s,t,_ in g['edges']):
                        label_y = y-18
                    self.text(n["name"],cx,label_y,min(190, 2*(self.w-40-cx)),14)
            else:
                lines=wrapped(n["name"],w-22,15)
                self.text(n["name"],cx,cy-(len(lines)-1)*10+5,w-22,15,export=False)
        self.pdf.showPage()
        self.pdf.save()
        ET.indent(self.svg)
        ET.ElementTree(self.svg).write(svg_path,encoding="utf-8",xml_declaration=True)
