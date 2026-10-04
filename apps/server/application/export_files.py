"""Deterministic CSV/OOXML serialization, called only outside DB transactions."""

import csv
import io
import re
import zipfile
from xml.sax.saxutils import escape

from apps.server.application.reports import serialized
from apps.server.domain.errors import DomainError


def cell(value):
    value = "" if value is None else serialized(value) if isinstance(value, (dict, list)) else str(value)
    # Treat leading whitespace/control characters as untrusted too.
    if re.sub(r"^[\s\ufeff]*", "", value).startswith(("=", "+", "-", "@")) or value.startswith(
        ("\t", "\r", "\n")
    ):
        value = "'" + value
    if len(value) > 32767:
        raise DomainError("EXPORT_CELL_LIMIT", "Một ô vượt 32.767 ký tự; thu hẹp bộ lọc.")
    return value


def render(snapshot, rows, format, max_bytes=20 * 1024 * 1024):
    columns = snapshot["columns"]
    metadata = [
        str(snapshot["id"]),
        str(snapshot["created_at"]),
        serialized(snapshot["criteria"]),
        snapshot["sha256"],
    ]
    header = ["snapshot_id", "snapshot_created_at", "criteria", "snapshot_sha256", *columns]
    values = [header] + [[*metadata, *(r.get(k) for k in columns)] for r in rows]
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        for row in values:
            writer.writerow([cell(v) for v in row])
            if output.tell() > max_bytes:
                raise DomainError("FILE_LIMIT", "Export vượt hạn mức tệp; thu hẹp bộ lọc.")
        data = output.getvalue().encode("utf-8-sig")
        if len(data) > max_bytes:
            raise DomainError("FILE_LIMIT", "Export vượt hạn mức tệp; thu hẹp bộ lọc.")
        return data
    if format != "xlsx":
        raise ValueError("Unsupported export format")
    sheet = [
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    ]
    xml_bytes = 0
    for number, row in enumerate(values, 1):
        sheet.append(f'<row r="{number}">')
        for value in row:
            text = cell(value)
            # XML 1.0 cannot represent these controls. Fail rather than silently lose data.
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", text):
                raise DomainError("EXPORT_INVALID_TEXT", "Dữ liệu chứa ký tự không hợp lệ cho XLSX.")
            sheet.append('<c t="inlineStr"><is><t xml:space="preserve">' + escape(text) + "</t></is></c>")
            xml_bytes += len(sheet[-1].encode())
            if xml_bytes > 64 * 1024 * 1024:
                raise DomainError("FILE_LIMIT", "XLSX vượt hạn mức XML 64 MiB; thu hẹp bộ lọc.")
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    files = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": "".join(sheet),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value.encode())
    data = output.getvalue()
    if len(data) > max_bytes:
        raise DomainError("FILE_LIMIT", "Export vượt hạn mức tệp; thu hẹp bộ lọc.")
    return data
