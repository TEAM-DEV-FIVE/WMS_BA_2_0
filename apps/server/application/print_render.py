"""Deterministic PDF template v1. Bundled fonts, escaped data and bounded pages."""

from importlib.resources import files
from io import BytesIO
from threading import RLock
from xml.sax.saxutils import escape

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.server.application.print_sources import TITLES
from apps.server.domain.errors import DomainError

PAPERS = {
    "A4": (210 * mm, 297 * mm),
    "A5": (148 * mm, 210 * mm),
    "100x50": (100 * mm, 50 * mm),
    "80x40": (80 * mm, 40 * mm),
}
LOCK = RLock()


def fonts():
    if "WMS" not in pdfmetrics.getRegisteredFontNames():
        root = files("apps.server.printing_assets")
        pdfmetrics.registerFont(TTFont("WMS", str(root / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("WMS-Bold", str(root / "DejaVuSans-Bold.ttf")))


def barcode(value, symbology="QR", width=28 * mm, height=28 * mm):
    if not value or len(value) > 160 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DomainError("INVALID_BARCODE", "Mã in chứa ký tự không hợp lệ.")
    if symbology == "Code128" and (len(value) > 24 or not value.isascii()):
        symbology = "QR"
    if symbology == "QR":
        return createBarcodeDrawing("QR", value=value, barLevel="M", width=width, height=height, barBorder=4)
    drawing = createBarcodeDrawing(
        "Code128", value=value, barWidth=0.25 * mm, barHeight=height, quiet=True, humanReadable=False
    )
    if drawing.width > width:
        raise DomainError("INVALID_BARCODE", "Mã vạch quá dài cho khổ tem; chọn QR.")
    return drawing


def render(snapshot, max_bytes=16 * 1024 * 1024):
    with LOCK:
        fonts()
        output = BytesIO()
        width, height = PAPERS[snapshot["paper"]]
        header = snapshot["header"]
        if snapshot["template"].endswith("LABEL"):
            canvas = Canvas(output, pagesize=(width, height), invariant=1, pageCompression=1)
            canvas.setTitle(TITLES[snapshot["template"]])
            code = header["barcode"]
            style = ParagraphStyle("label", fontName="WMS", fontSize=8, leading=10)
            canvas.setFont("WMS-Bold", 10)
            label = header["number"]
            while pdfmetrics.stringWidth(label, "WMS-Bold", 10) > width - 8 * mm:
                label = label[:-2] + "…"
            canvas.drawString(4 * mm, height - 6 * mm, label)

            def description(text, available_width, available_height):
                value = text
                while True:
                    paragraph = Paragraph(escape(value), style)
                    _, text_height = paragraph.wrap(available_width, available_height)
                    if text_height <= available_height:
                        return paragraph, text_height
                    value = value[:-2] + "…"

            name, name_height = description(header["name"], width - 8 * mm, 8 * mm)
            if header["symbology"] == "Code128" and len(code) <= 24 and code.isascii():
                name.drawOn(canvas, 4 * mm, height - 9 * mm - name_height)
                drawing = barcode(code, "Code128", width - 8 * mm, 10 * mm)
                drawing.drawOn(canvas, (width - drawing.width) / 2, 8 * mm)
            else:
                drawing = barcode(code, "QR", 22 * mm, 22 * mm)
                drawing.drawOn(canvas, width - 26 * mm, 4 * mm)
                name, h = description(header["name"], width - 34 * mm, height - 15 * mm)
                name.drawOn(canvas, 4 * mm, height - 9 * mm - h)
            canvas.setFont("WMS", 6)
            if pdfmetrics.stringWidth(code, "WMS", 6) <= width - 8 * mm:
                canvas.drawString(4 * mm, 3 * mm, code)
            canvas.showPage()
            canvas.save()
        else:
            small = snapshot["paper"] == "A5"
            style = ParagraphStyle(
                "cell", fontName="WMS", fontSize=7 if small else 8, leading=10 if small else 12
            )
            heading = ParagraphStyle("title", fontName="WMS-Bold", fontSize=16, leading=22, spaceAfter=10)

            def p(value):
                return Paragraph(escape(str(value if value is not None else "")), style)

            story = [
                Paragraph(TITLES[snapshot["template"]], heading),
                p("Số: " + str(header["number"])),
                p(f"Kho: {header['warehouse_code']} - {header['warehouse']}"),
                p(
                    f"Ngày: {header.get('business_date', '')} | Trạng thái nguồn: {header.get('status', '')} | Phiên bản: {snapshot['source_version']}"
                ),
            ]
            if header.get("destination"):
                story.append(p("Kho đích: " + header["destination"]))
            if header.get("partner_name"):
                story.append(p("Đối tác: " + header["partner_name"]))
            story += [
                Spacer(1, 8),
                p("Bản chụp dữ liệu; việc in không xác nhận giao hàng hay ghi sổ kho."),
                Spacer(1, 10),
            ]
            if snapshot["template"] == "COUNT":
                columns = [
                    ("sku", "SKU"),
                    ("owner_code", "Chủ hàng"),
                    ("trace", "Lô / serial"),
                    ("location_code", "Vị trí"),
                    ("counted", "Số đếm"),
                ]
            else:
                columns = [
                    ("sku", "SKU"),
                    ("product_name", "Tên hàng"),
                    ("owner_code", "Chủ hàng"),
                    ("quantity", "SL yêu cầu"),
                    ("uom_code", "ĐVT"),
                    ("posted_base", "Đã ghi sổ (cơ sở)"),
                ]
                if snapshot["include_price"]:
                    columns.append(("reference_unit_price", "Giá tham chiếu"))
            data = [[p(label) for _, label in columns]]
            for line in snapshot["lines"]:
                line = {
                    **line,
                    "trace": line.get("serial_code") or line.get("lot_code") or line.get("trace", ""),
                }
                if line.get("trace") or line.get("location"):
                    line["product_name"] = (
                        str(line.get("product_name", ""))
                        + " / "
                        + line.get("trace", "")
                        + " / "
                        + line.get("location", "")
                    )
                data.append([p(line.get(k, "")) for k, _ in columns])
            if len(data) == 1:
                data.append([p("Không có dòng")] + [p("") for _ in columns[1:]])
            table = Table(
                data, colWidths=[(width - 24 * mm) / len(columns)] * len(columns), repeatRows=1, hAlign="LEFT"
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#a4afba")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(table)

            def footer(canvas, doc):
                canvas.setFont("WMS", 7)
                canvas.drawString(
                    12 * mm, 15 * mm, "Người lập: ______________    Người giao/nhận/đếm: ______________"
                )
                canvas.drawString(12 * mm, 9 * mm, f"Mẫu v1 | {header['number']} | Trang {doc.page}")

            def stable(*args, **kwargs):
                return Canvas(*args, **dict(kwargs, invariant=1))

            SimpleDocTemplate(
                output,
                pagesize=(width, height),
                leftMargin=12 * mm,
                rightMargin=12 * mm,
                topMargin=12 * mm,
                bottomMargin=24 * mm,
                title=TITLES[snapshot["template"]],
            ).build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=stable)
        data = output.getvalue()
        if len(data) > max_bytes:
            raise DomainError("FILE_LIMIT", "PDF vượt giới hạn dung lượng.")
        return data
