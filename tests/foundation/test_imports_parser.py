import csv
import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from apps.server.application.import_parser import error_csv, parse
from apps.server.application.import_templates import TEMPLATES
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.file_storage import FileStorage, ImportSettings, safe_name


def workbook(rows, *, kind="01_uom", date1904=False, extras=None):
    cells = []
    for n, row in enumerate(rows, 1):
        values = []
        for i, value in enumerate(row):
            typ, value = value if isinstance(value, tuple) else ("inlineStr", value)
            content = (
                "<f>1+1</f><v>2</v>"
                if typ == "formula"
                else "<is><t>" + escape(str(value)) + "</t></is>"
                if typ == "inlineStr"
                else "<v>" + escape(str(value)) + "</v>"
            )
            values.append(f'<c r="{chr(65 + i)}{n}" t="{typ}">{content}</c>')
        cells.append(f'<row r="{n}">' + "".join(values) + "</row>")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="{int(date1904)}"/><sheets><sheet name="{kind}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(cells)
            + "</sheetData></worksheet>",
        )
        for name, data in (extras or {}).items():
            z.writestr(name, data)
    return stream.getvalue()


def test_imports_parser_xlsx_csv_preserve_text_codes_and_exact_decimal():
    rows, errors = parse(
        workbook([["code", "name", "decimal_places"], ["000001", "Chiếc", ("n", "0")]]), "data.xlsx", "01_uom"
    )
    assert errors == [] and rows[0]["payload"] == dict(code="000001", name="Chiếc", decimal_places=0)
    rows, errors = parse(b"code,name,decimal_places\r\n000001,Unit,0\r\n", "data.csv", "01_uom")
    assert not errors and rows[0]["payload"]["code"] == "000001"
    headers = [c[0] for c in TEMPLATES["14_prices"]]
    rows, errors = parse(
        workbook([headers, ["SKU", ("n", "45932"), ("n", "123.1000"), "VND", "Quotation"]], kind="14_prices"),
        "data.xlsx",
        "14_prices",
    )
    assert not errors and rows[0]["payload"]["amount"] == "123.1000"
    assert rows[0]["payload"]["effective_on"] == "2025-10-02"


@pytest.mark.parametrize(
    "row,code",
    [
        ([("n", "123"), "Unit", 0], "TEXT_REQUIRED"),
        ([("formula", "2"), "Unit", 0], "FORMULA"),
        (['=HYPERLINK("http://bad")', "Unit", 0], "FORMULA"),
        (["+formula", "Unit", 0], "FORMULA"),
        (["@formula", "Unit", 0], "FORMULA"),
        (["CODE", "x" * 4001, 0], "CELL_LIMIT"),
        (["CODE", "Unit", ("n", "0.1")], "INVALID_TYPE"),
    ],
)
def test_imports_parser_rejects_dangerous_or_ambiguous_cells(row, code):
    _, errors = parse(workbook([["code", "name", "decimal_places"], row]), "file.xlsx", "01_uom")
    assert code in {e["code"] for e in errors}


@pytest.mark.parametrize(
    "extras",
    [
        {"../escape.xml": "x"},
        {"xl/vbaProject.bin": "x"},
        {"xl/externalLinks/link.xml": "x"},
        {
            "xl/_rels/sheet.xml.rels": '<Relationships><Relationship TargetMode="External" Target="https://bad"/></Relationships>'
        },
        {"xl/sharedStrings.xml": '<!DOCTYPE x [<!ENTITY x "expansion">]><x>&x;</x>'},
        {"xl/sharedStrings.xml": '<!DOCTYPE x [<!ENTITY x "expansion">]><x>&x;</x>'.encode("utf-16")},
        {"large.xml": "x" * (8 * 1024 * 1024 + 1)},
    ],
)
def test_imports_parser_rejects_unsafe_zip_xml_without_extracting(extras):
    rows, errors = parse(
        workbook([["code", "name", "decimal_places"], ["A", "Unit", 0]], extras=extras), "file.xlsx", "01_uom"
    )
    assert not rows and errors[0]["code"] in {"INVALID_FILE", "FILE_LIMIT"}


@pytest.mark.parametrize(
    "data", [b"not zip", b"\xff\xfe", b'code,name,decimal_places\n"broken', b"wrong,headers\nA,B"]
)
def test_imports_parser_bad_format_and_headers(data):
    rows, errors = parse(data, "file.csv", "01_uom")
    assert not rows and errors
    assert parse(data, "file.xlsx", "01_uom")[1]


def test_imports_parser_errors_csv_cannot_execute_formulas():
    errors = [dict(row_no=2, column="=1+1", code="@bad", message="\t=cmd", suggested_fix="-bad")]
    values = list(csv.reader(io.StringIO(error_csv(errors).decode("utf-8-sig"))))[1]
    assert values[0] == "2" and all(value.startswith("'") for value in values[1:])


def test_imports_storage_immutable_hash_symlink_and_private_mode(tmp_path):
    import hashlib

    data = b"private content"
    sha = hashlib.sha256(data).hexdigest()
    store = FileStorage(ImportSettings(storage_root=tmp_path / "files"))
    store.put(data, sha, "a" * 64)
    assert store.read("a" * 64, sha, len(data)) == data
    assert store.path("a" * 64).stat().st_mode & 0o777 == 0o600
    store.path("b" * 64).symlink_to(store.path("a" * 64))
    with pytest.raises(DomainError):
        store.read("b" * 64, sha, len(data))
    with pytest.raises(DomainError):
        store.put(b"changed", hashlib.sha256(b"changed").hexdigest(), "a" * 64)
    for value in ["../foo.csv", "foo\\bar.csv", "file.exe", "file.csv\n"]:
        with pytest.raises(DomainError):
            safe_name(value)


def test_imports_runtime_templates_match_published_manifest():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "06_Nhap_lieu/imports/template_manifest.json").read_text())
    assert set(TEMPLATES) == {s["name"] for s in manifest["templates"]} - {"13_grants"}
    for sheet in manifest["templates"]:
        if sheet["name"] in TEMPLATES:
            assert TEMPLATES[sheet["name"]] == [
                (c["name"], c["type"], c["required"]) for c in sheet["columns"]
            ]
