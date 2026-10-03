"""Bounded, dependency-free tabular CSV/XLSX reader. Never evaluate formulas."""

import csv
import io
import posixpath
import re
import zipfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from apps.server.application.import_templates import TEMPLATES
from apps.server.domain.errors import DomainError

MAX_ROWS = 500
MAX_CELL = 4000
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def issue(row, column, code, message):
    return dict(
        row_no=row,
        column=column,
        code=code,
        message=message,
        suggested_fix="Sửa dữ liệu nguồn rồi tải lại và chạy dry-run.",
    )


def xml(data):
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise DomainError("INVALID_FILE", "Không cho phép DTD/entity trong XLSX.")
    return ET.fromstring(data)


def xlsx_rows(data, kind):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 128
            or len({x.filename for x in entries}) != len(entries)
            or sum(x.file_size for x in entries) > 20 * 1024 * 1024
            or any(x.file_size > 8 * 1024 * 1024 or x.flag_bits & 1 for x in entries)
        ):
            raise DomainError("FILE_LIMIT", "XLSX vượt giới hạn giải nén hoặc bị mã hóa.")
        for item in entries:
            if (
                item.filename.startswith("/")
                or ".." in item.filename.split("/")
                or "\\" in item.filename
                or any(x in item.filename.lower() for x in ["vbaproject", "externallinks", "embeddings/"])
            ):
                raise DomainError("INVALID_FILE", "XLSX có đường dẫn/macro/liên kết ngoài không hỗ trợ.")
            if item.filename.endswith(".rels"):
                for rel in xml(archive.read(item)).iter():
                    if rel.attrib.get("TargetMode") == "External":
                        raise DomainError("INVALID_FILE", "Không cho phép liên kết ngoài trong XLSX.")
        book = xml(archive.read("xl/workbook.xml"))
        props = book.find(NS + "workbookPr")
        epoch1904 = props is not None and props.attrib.get("date1904") in {"1", "true"}
        relations = {
            r.attrib["Id"]: r.attrib["Target"] for r in xml(archive.read("xl/_rels/workbook.xml.rels"))
        }
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(s.itertext()) for s in xml(archive.read("xl/sharedStrings.xml")).findall(NS + "si")
            ]
            if len(strings) > 50000 or any(len(s) > MAX_CELL for s in strings):
                raise DomainError("FILE_LIMIT", "Bảng chuỗi XLSX vượt giới hạn.")
        sheets = book.find(NS + "sheets")
        selected = None
        for sheet in sheets:
            target = relations[sheet.attrib[REL]]
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/worksheets/") or ".." in path.split("/"):
                raise DomainError("INVALID_FILE", "Tham chiếu worksheet không hợp lệ.")
            tree = xml(archive.read(path))
            cells = tree.findall(".//" + NS + "c")
            if sheet.attrib["name"] != kind and len(sheets) > 1:
                if any(
                    int(re.search(r"\d+$", c.attrib["r"])[0]) > 1
                    and (
                        c.find(NS + "v") is not None
                        or c.find(NS + "is") is not None
                        or c.find(NS + "f") is not None
                    )
                    for c in cells
                ):
                    raise DomainError("MULTIPLE_SHEETS", "Mỗi job chỉ nhập một mẫu; để trống các sheet khác.")
                continue
            if selected is not None:
                raise DomainError("INVALID_FILE", "Chỉ chọn một sheet nhập liệu.")
            selected = []
            seen_rows = set()
            for row in tree.findall(".//" + NS + "sheetData/" + NS + "row"):
                number = int(row.attrib["r"])
                if number in seen_rows or number < 1 or number > 10000:
                    raise DomainError("FILE_LIMIT", "Số dòng XLSX không hợp lệ.")
                seen_rows.add(number)
                values = {}
                for cell in row.findall(NS + "c"):
                    ref = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", cell.attrib["r"])
                    if not ref or int(ref[2]) != number:
                        raise DomainError("INVALID_FILE", "Địa chỉ ô không hợp lệ.")
                    column = 0
                    for letter in ref[1]:
                        column = column * 26 + ord(letter) - 64
                    if column > 40 or column in values:
                        raise DomainError("FILE_LIMIT", "Số cột XLSX không hợp lệ.")
                    typ = cell.attrib.get("t", "n")
                    value = cell.findtext(NS + "v", "")
                    if cell.find(NS + "f") is not None:
                        typ, value = "formula", "Công thức không được hỗ trợ"
                    elif typ == "s":
                        index = int(value)
                        if not 0 <= index < len(strings):
                            raise DomainError("INVALID_FILE", "Tham chiếu chuỗi không hợp lệ.")
                        value = strings[index]
                    elif typ == "inlineStr":
                        value = "".join(cell.find(NS + "is").itertext())
                    values[column] = (value, typ)
                if values:
                    selected.append((number, [values.get(i, ("", "str")) for i in range(1, max(values) + 1)]))
        if selected is None:
            raise DomainError("INVALID_FILE", "Không tìm thấy sheet của loại import.")
        return sorted(selected), epoch1904


def parse(data, filename, kind):
    errors, rows = [], []
    try:
        if filename.lower().endswith(".xlsx"):
            raw_rows, epoch1904 = xlsx_rows(data, kind)
        else:
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
            raw_rows, epoch1904 = [], False
            for row in reader:
                if row and any(v.strip() for v in row):
                    raw_rows.append((reader.line_num, [(v, "str") for v in row]))
                if len(raw_rows) > MAX_ROWS + 1:
                    raise DomainError("ROW_LIMIT", "Mỗi tệp tối đa 500 dòng; chứng từ tối đa 200 dòng.")
        expected = TEMPLATES[kind]
        # v1 opening was explicitly COMPANY-only. Preserve that published contract,
        # while v2 requires an explicit owner and never infers owner from agreement.
        legacy_opening = kind == "11_opening" and raw_rows and [v[0] for v in raw_rows[0][1]] == [c[0] for c in expected[:-2]]
        if legacy_opening:
            raw_rows = [(n, cells + [("owner_code", "str"), ("consignment_code", "str")]
                         if index == 0 else cells + [("COMPANY", "str"), ("", "str")])
                        for index, (n, cells) in enumerate(raw_rows)]
        if not raw_rows or [v[0] for v in raw_rows[0][1]] != [c[0] for c in expected]:
            return [], [issue(1, "header", "HEADER", "Header/thứ tự cột phải đúng mẫu.")]
        raw_rows = [(n, r) for n, r in raw_rows[1:] if any(v[0].strip() for v in r)]
        if not raw_rows or len(raw_rows) > MAX_ROWS:
            return [], [issue(0, "file", "ROW_LIMIT", "Cần 1–500 dòng; mỗi chứng từ tối đa 200 dòng.")]
        for number, cells in raw_rows:
            if len(cells) > len(expected):
                errors.append(issue(number, "row", "COLUMNS", "Thừa cột dữ liệu."))
                continue
            cells += [("", "str")] * (len(expected) - len(cells))
            values = {}
            for (column, typ, required), (raw, cell_type) in zip(expected, cells):
                value = raw.strip()
                code = None
                if (
                    cell_type == "formula"
                    or value.startswith(("=", "+", "@"))
                    or value.startswith("-")
                    and typ == "text"
                ):
                    code = "FORMULA"
                elif len(value) > MAX_CELL:
                    code = "CELL_LIMIT"
                elif not value:
                    if required:
                        code = "REQUIRED"
                    value = None
                else:
                    try:
                        if typ == "text" and cell_type not in {"str", "s", "inlineStr"}:
                            code = "TEXT_REQUIRED"
                        elif typ == "integer":
                            if Decimal(value) != Decimal(value).to_integral_value():
                                raise ValueError
                            value = int(value)
                        elif typ == "boolean":
                            if cell_type == "b":
                                value = {"0": "FALSE", "1": "TRUE"}[value]
                            if value.upper() not in {"TRUE", "FALSE"}:
                                raise ValueError
                            value = value.upper() == "TRUE"
                        elif typ == "decimal":
                            number_value = Decimal(value)
                            if (
                                not number_value.is_finite()
                                or abs(number_value) >= Decimal("1e20")
                                or number_value.as_tuple().exponent < -8
                            ):
                                raise ValueError
                            value = format(number_value, "f")
                            if len(value) > 50:
                                raise ValueError
                        elif typ == "date":
                            if cell_type == "n":
                                serial = Decimal(value)
                                if serial != serial.to_integral_value() or serial == 60 and not epoch1904:
                                    raise ValueError
                                epoch = date(1904, 1, 1) if epoch1904 else date(1899, 12, 30)
                                value = (
                                    epoch
                                    + timedelta(
                                        days=int(serial) + (1 if not epoch1904 and serial < 60 else 0)
                                    )
                                ).isoformat()
                            if date.fromisoformat(value).isoformat() != value:
                                raise ValueError
                    except (ValueError, KeyError, InvalidOperation, OverflowError):
                        code = "INVALID_TYPE"
                if code:
                    errors.append(
                        issue(
                            number,
                            column,
                            code,
                            "Giá trị không hợp lệ; mã/serial cần ô text, không công thức.",
                        )
                    )
                values[column] = value
            rows.append(dict(row_no=number, payload=values))
    except (
        DomainError,
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
        TypeError,
        UnicodeError,
        csv.Error,
        zipfile.BadZipFile,
        NotImplementedError,
        RuntimeError,
        ET.ParseError,
        OverflowError,
    ) as error:
        return [], [
            issue(
                0,
                "file",
                error.code if isinstance(error, DomainError) else "INVALID_FILE",
                error.message if isinstance(error, DomainError) else "Không đọc được CSV UTF-8/XLSX hợp lệ.",
            )
        ]
    return rows, errors


def error_csv(errors):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    fields = ["row_no", "column", "code", "message", "suggested_fix"]
    writer.writerow(fields)
    for error in errors:
        values = []
        for field in fields:
            value = str(error.get(field, ""))
            if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return stream.getvalue().encode("utf-8-sig")
