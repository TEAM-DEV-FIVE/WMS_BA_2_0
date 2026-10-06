"""Render synthetic examples with the production renderer; no database or printer."""

import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from apps.server.application.print_render import fonts, render

ISSUER = {"name": "InternTechLead", "address": "Đông Thạnh, Hóc Môn, TP. Hồ Chí Minh",
          "tax_code": "0869233973", "phone": "0329511628", "signer": "Trần Trung Kiên"}


def samples(warehouse="Kho mẫu InternTechLead"):
    for template, prefix in (("RECEIPT", "PN"), ("ISSUE", "PX"), ("TRANSFER", "PC"), ("COUNT", "KK")):
        for paper in ("A4", "A5"):
            yield f"{template.lower()}-{paper}", dict(
                template=template, template_version=1, paper=paper, source_version=1, include_price=False,
                header=dict(issuer=dict(ISSUER), number=f"MAU-{prefix}-0001", warehouse=warehouse,
                            warehouse_code="MAU-K01",
                            business_date="2026-10-06", status="DRAFT",
                            partner_name="Đối tác mẫu" if template in {"RECEIPT", "ISSUE"} else "",
                            destination="MAU-K02 - Kho nhận mẫu" if template == "TRANSFER" else ""),
                lines=[dict(sku=f"MAU-SP-{i:03}", product_name=name, owner_code="COMPANY",
                            quantity=quantity, uom_code=unit, posted_base="0", lot_code=lot,
                            location="MAU-A-01", location_code="MAU-A-01", counted="")
                       for i, (name, quantity, unit, lot) in enumerate([
                           ("Máy quét mã vạch", "2", "CÁI", ""),
                           ("Giấy in tem tiếng Việt", "12.5", "MÉT", "MAU-LO-001"),
                           ("Thùng đóng gói", "24", "CÁI", ""),
                       ], 1)],
            )
    for template, code, name, symbology in (
        ("PRODUCT_LABEL", "MAU-SP-001", "MẪU - Máy quét mã vạch", "Code128"),
        ("LOCATION_LABEL", "MAU-K01-A-01", "MẪU - Kho / khu A / ô 01", "QR"),
    ):
        for paper in ("100x50", "80x40"):
            yield f"{template.lower()}-{paper}", dict(
                template=template, template_version=1, paper=paper, source_version=1,
                include_price=False, lines=[],
                header=dict(issuer=dict(ISSUER), number=code, name=name, barcode=code, symbology=symbology),
            )


def preview(output: Path, intermediate: Path, warehouse="Kho mẫu InternTechLead"):
    output.parent.mkdir(parents=True, exist_ok=True)
    intermediate.mkdir(parents=True, exist_ok=True)
    fonts()
    cover = BytesIO()
    canvas = Canvas(cover, pagesize=(210 * mm, 297 * mm), invariant=1)
    canvas.setTitle("WMS - Bộ mẫu phiếu và tem")
    canvas.setFont("WMS-Bold", 21)
    canvas.drawString(18 * mm, 268 * mm, "WMS | Phiếu và tem")
    canvas.setFont("WMS-Bold", 12)
    canvas.drawString(18 * mm, 250 * mm, "BẢN MẪU - DỮ LIỆU GIẢ LẬP")
    canvas.setFont("WMS", 10)
    for i, line in enumerate([
        "InternTechLead - Đông Thạnh, Hóc Môn, TP. Hồ Chí Minh",
        "Ngày lập mẫu: 06/10/2026. Chưa xác nhận mẫu nghiệp vụ hoặc thiết bị.",
        "Dùng đúng bộ dựng PDF của hệ thống, font tiếng Việt được nhúng.",
        "Phiếu nhập / xuất / chuyển / kiểm kê: mỗi loại có A4 và A5.",
        "Tem sản phẩm (Code128) / vị trí (QR): 100 x 50 và 80 x 40 mm.",
        "Phiếu kiểm kê đếm mù: không hiển thị tồn hệ thống hoặc chênh lệch.",
        "Mẫu không có giá; chỗ ký để trống. Đây không phải hóa đơn điện tử.",
        "Các trang sau giữ kích thước giấy thật, không phóng tem lên A4.",
        "Khi in thử chọn Actual size / 100%, tắt Fit to page.",
        "Đối chiếu máy in, khổ giấy và quét mã trên giấy trước nghiệm thu.",
    ]):
        canvas.drawString(18 * mm, (229 - i * 9) * mm, line)
    canvas.showPage()
    canvas.save()
    manifest = []
    with pdfium.PdfDocument.new() as combined:
        with pdfium.PdfDocument(cover.getvalue()) as document:
            combined.import_pages(document)
        for name, snapshot in samples(warehouse):
            data = render(snapshot)
            (intermediate / f"{name}.pdf").write_bytes(data)
            with pdfium.PdfDocument(data) as document:
                first_page = len(combined) + 1
                combined.import_pages(document)
                manifest.append(dict(name=name, paper=snapshot["paper"], pages=len(document),
                                     first_catalog_page=first_page, sha256=hashlib.sha256(data).hexdigest()))
        combined.save(str(output))
    (intermediate / "manifest.json").write_text(
        json.dumps(dict(synthetic=True, templates=manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/pdf/wms-phieu-tem-mau.pdf"))
    parser.add_argument("--intermediate", type=Path, default=Path("tmp/pdfs/native"))
    parser.add_argument("--warehouse", default="Kho mẫu InternTechLead")
    args = parser.parse_args()
    preview(args.output, args.intermediate, args.warehouse)
    print(f"Created {args.output} (12 synthetic templates plus cover; no spool submission).")


if __name__ == "__main__":
    main()
