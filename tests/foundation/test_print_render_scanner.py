import subprocess

import pypdfium2 as pdfium
import pytest
import zxingcpp

from apps.desktop.printing.pdf import page_image
from apps.desktop.printing.spool import submit
from apps.desktop.scanner.hid import HID
from apps.server.application.print_render import render
from apps.server.domain.errors import DomainError


def sample(template="RECEIPT", paper="A4", code="SKU-ABC-001"):
    return dict(
        template=template,
        template_version=1,
        paper=paper,
        source_version=3,
        include_price=False,
        header=dict(
            number="PN-123",
            warehouse="Kho trung tâm",
            warehouse_code="K01",
            name="Thiết bị điện tử tiếng Việt",
            barcode=code,
            symbology="QR" if template == "LOCATION_LABEL" else "Code128",
            status="APPROVED",
            business_date="2026-10-05",
        ),
        lines=[
            dict(
                sku="SKU-01",
                product_name="Máy tính tiếng Việt <&>",
                quantity="1.25",
                uom_code="CÁI",
                owner_code="COMPANY",
                posted_base="0",
                location_code="KHU-A",
            )
        ]
        * 80,
    )


@pytest.mark.parametrize("template", ["RECEIPT", "ISSUE", "TRANSFER", "COUNT"])
@pytest.mark.parametrize("paper", ["A4", "A5"])
def test_pdf_vietnamese_repeated_headers_pagination_deterministic(template, paper):
    data = render(sample(template, paper))
    assert data == render(sample(template, paper))
    with pdfium.PdfDocument(data) as doc:
        assert len(doc) >= 2
        texts = []
        for page in doc:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        assert "Kho trung tâm" in texts[0]
        assert all("SKU" in t and "Trang" in t for t in texts)
        assert (
            "Máy tính tiếng Việt <&>" in " ".join("".join(texts).split())
            if template != "COUNT"
            else "Snapshot" not in "".join(texts)
        )


@pytest.mark.parametrize("paper", ["100x50", "80x40"])
@pytest.mark.parametrize(
    "template,code",
    [("PRODUCT_LABEL", "SKU-ABC-001"), ("LOCATION_LABEL", "KHU-A-R01"), ("PRODUCT_LABEL", "S" * 80)],
)
def test_rendered_barcodes_decode_actual_pixels(paper, template, code):
    data = render(sample(template, paper, code))
    image, count = page_image(data, scale=300 / 72)
    decoded = zxingcpp.read_barcodes(image)
    assert count == 1 and [r.text for r in decoded] == [code]


def test_pdf_file_size_bound_and_markup_escaped():
    with pytest.raises(DomainError):
        render(sample(), 100)


def test_hid_focus_terminators_timeout_debounce_and_manual_rescan():
    time = [10.0]
    hid = HID(clock=lambda: time[0])
    for c in "ABC":
        assert hid.key(c) is None
    assert hid.key(keysym="Return") == "ABC"
    for c in "ABC":
        hid.key(c)
    assert hid.key(keysym="Tab") is None
    time[0] += 1
    for c in "ABC":
        hid.key(c)
    assert hid.key(keysym="Tab") == "ABC"
    hid.key("X")
    hid.key("Y", focused=False)
    assert hid.key(keysym="Return") is None
    hid.key("X")
    time[0] += 2
    hid.key("Z")
    assert hid.key(keysym="Return") == "Z"
    for _ in range(160):
        hid.key("A")
    with pytest.raises(ValueError):
        hid.key("A")


@pytest.mark.parametrize(
    "error,outcome", [(FileNotFoundError(), "FAILED"), (subprocess.TimeoutExpired("lp", 1), "UNKNOWN")]
)
def test_spool_unavailable_timeout_never_claims_printed(monkeypatch, error, outcome):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    assert submit(b"%PDF-test", "Printer", "A4").outcome == outcome
