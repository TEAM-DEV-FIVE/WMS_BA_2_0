"""Import HTTP adapter and bounded local file preflight; no server/DB imports."""

import csv
import hashlib
import io
import json
import os
import posixpath
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode
from uuid import UUID
from xml.etree import ElementTree as ET

from apps.desktop.api.client import ApiError
from packages.contracts.imports import FileView, ImportAck, ImportCapabilities, ImportRows, ImportView

STATES = {"QUEUED", "VALIDATING", "VALIDATED", "INVALID", "FAILED", "CANCELLED", "COMMITTED"}
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def validated(model, data):
    try:
        return model.model_validate(data).model_dump(mode="json")
    except (ValueError, TypeError):
        raise ApiError("INVALID_RESPONSE", "Phản hồi import không đúng định dạng; cần tra lại trạng thái.") from None


def identifier(value):
    return str(UUID(str(value)))


def checked_ack(command, data):
    result = validated(ImportAck, data)
    body = json.loads(command.body_json)
    try:
        if (result["status"] not in STATES or result["version"] < 1
                or (command.job_id and result["id"] != command.job_id)
                or (command.operation == "commit" and result["status"] != "COMMITTED")
                or ("expected_version" in body and result["version"] != body["expected_version"] + 1)):
            raise ValueError
        for target in result["targets"]:
            identifier(target["id"])
            if type(target["row_no"]) is not int or target["row_no"] < 1:
                raise ValueError
        if result["status"] == "COMMITTED" and not result["targets"]:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ApiError("INVALID_RESPONSE", "ACK không khớp yêu cầu import đang gửi.") from None
    return result


@dataclass(frozen=True)
class SourceFile:
    path: str
    name: str
    sha256: str
    row_count: int
    data: bytes = field(repr=False)


def source_file(path, kind, limit, row_limit):
    """Count only, not a dry-run. Server remains the authoritative validator."""
    path = Path(path)
    if path.suffix.lower() not in {".csv", ".xlsx"}:
        raise ApiError("INVALID_FILE", "Chọn CSV UTF-8 hoặc XLSX theo mẫu.")
    try:
        with path.open("rb") as stream:
            data = stream.read(min(limit, 20 * 1024 * 1024) + 1)
        if not data or len(data) > min(limit, 20 * 1024 * 1024):
            raise ApiError("FILE_LIMIT", "Tệp trống hoặc vượt hạn mức upload máy chủ.")
        if path.suffix.lower() == ".csv":
            count = 0
            for row in csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True):
                if any(cell.strip() for cell in row):
                    count += 1
                if count > row_limit + 1:
                    break
            count = max(0, count - 1)
        else:
            count = xlsx_count(data, kind)
        if count > row_limit:
            raise ApiError("ROW_LIMIT", f"Tối đa {row_limit} dòng cho mẫu này; không chia tệp để vượt giới hạn khởi tạo tồn.")
        return SourceFile(str(path.resolve()), path.name, hashlib.sha256(data).hexdigest(), count, data)
    except ApiError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error,
            zipfile.BadZipFile, ET.ParseError, NotImplementedError, RuntimeError):
        raise ApiError("INVALID_FILE", "Không đọc được CSV UTF-8/XLSX; kiểm tra định dạng và quyền đọc.") from None


def xlsx_count(data, kind):
    def xml(raw):
        if b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Unsupported XML")
        return ET.fromstring(raw)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (len(entries) > 128 or len({e.filename for e in entries}) != len(entries)
                or sum(e.file_size for e in entries) > 20 * 1024 * 1024
                or any(e.file_size > 8 * 1024 * 1024 or e.flag_bits & 1 for e in entries)):
            raise ApiError("FILE_LIMIT", "XLSX vượt hạn mức giải nén hoặc bị mã hóa.")
        book = xml(archive.read("xl/workbook.xml"))
        sheets = book.find(NS + "sheets")
        selected = [s for s in sheets if s.attrib["name"] == kind or len(sheets) == 1]
        if len(selected) != 1:
            raise ValueError("Missing sheet")
        relations = {r.attrib["Id"]: r.attrib["Target"]
                     for r in xml(archive.read("xl/_rels/workbook.xml.rels"))}
        target = relations[selected[0].attrib[REL]]
        path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        if not path.startswith("xl/worksheets/"):
            raise ValueError("Invalid sheet path")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(s.itertext()) for s in xml(archive.read("xl/sharedStrings.xml")).findall(NS + "si")]

        def populated(cell):
            if cell.find(NS + "f") is not None:
                return True
            if cell.attrib.get("t") == "inlineStr":
                inline = cell.find(NS + "is")
                return inline is not None and bool("".join(inline.itertext()).strip())
            value = cell.findtext(NS + "v", "")
            if cell.attrib.get("t") == "s":
                index = int(value)
                if not 0 <= index < len(strings):
                    raise ValueError("Invalid string reference")
                value = strings[index]
            return bool(value.strip())

        rows = xml(archive.read(path)).findall(".//" + NS + "sheetData/" + NS + "row")
        return max(0, sum(any(populated(c) for c in row) for row in rows) - 1)


def check_source(source):
    try:
        with Path(source.path).open("rb") as stream:
            data = stream.read(len(source.data) + 1)
    except OSError:
        raise ApiError("SOURCE_CHANGED", "Không còn đọc được tệp nguồn. Chọn lại tệp trước khi xác nhận.") from None
    if data != source.data:
        raise ApiError("SOURCE_CHANGED", "Tệp đã đổi sau khi chọn/dry-run. Chọn lại, upload và kiểm tra lại.")


def save_bytes(path, data, current=lambda: True):
    """Atomic local save in worker; stale downloads never replace the user's file."""
    temporary = None
    try:
        destination = Path(path)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".wms-import-", delete=False) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not current():
            raise ApiError("STALE_SESSION", "Phiên/kho đã đổi; tệp tải về chưa được lưu.")
        os.replace(temporary, destination)
        temporary = None
        return str(destination)
    except OSError:
        raise ApiError("LOCAL_STORAGE_ERROR", "Không lưu được tệp. Kiểm tra đường dẫn và quyền ghi.") from None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


class ImportApi:
    def __init__(self, client):
        self.client = client

    def capabilities(self):
        return validated(ImportCapabilities, self.client.get("import-templates"))

    def metadata(self, file_id):
        return validated(FileView, self.client.get("files/" + identifier(file_id)))

    def read(self, job_id, kind, warehouse):
        result = validated(ImportView, self.client.get("imports/" + identifier(job_id)))
        if (result["id"] != identifier(job_id) or result["status"] not in STATES
                or result["kind"] != kind or result["warehouse_id"] != warehouse):
            raise ApiError("INVALID_SCOPE", "Job không thuộc loại import/kho đang chọn.")
        if result["token_expires_at"]:
            if datetime.fromisoformat(result["token_expires_at"].replace("Z", "+00:00")).tzinfo is None:
                raise ApiError("INVALID_RESPONSE", "Thời hạn dry-run thiếu múi giờ; cần đọc lại job.")
        return result

    def rows(self, job_id, after=0):
        return validated(ImportRows, self.client.get(f"imports/{identifier(job_id)}/rows?after={int(after)}&limit=50"))

    def execute(self, command):
        if command.operation == "upload":
            source = command.source
            response = self.client.file_request("POST", command.path, content=source.data, headers={
                "Idempotency-Key": command.key, "X-File-Name": quote(source.name, safe=""),
                "X-File-Name-Encoding": "percent-utf8", "Content-Type": "application/octet-stream"})
            result = validated(FileView, response)
            if (result["sha256"] != source.sha256 or result["size_bytes"] != len(source.data)
                    or result["kind"] != command.kind or result["warehouse_id"] != command.warehouse
                    or not result["ready"]):
                raise ApiError("INVALID_RESPONSE", "Metadata upload không khớp tệp/kho đã gửi.")
        else:
            result = checked_ack(command, self.client.command("POST", command.path,
                                                              json.loads(command.body_json), command.key))
        return result

    def download(self, job, errors=False):
        route = f"imports/{job['id']}/errors" if errors else f"files/{job['file_id']}/download"
        response = self.client.file_request("GET", route, binary=True)
        expected = "text/csv" if errors else "application/octet-stream"
        if response.headers.get("content-type", "").split(";")[0] != expected:
            raise ApiError("INVALID_RESPONSE", "Máy chủ chưa trả tệp đúng định dạng.")
        if not errors and hashlib.sha256(response.content).hexdigest() != job["file_hash"]:
            raise ApiError("FILE_HASH_MISMATCH", "Hash tệp tải về không khớp job.")
        return response.content


def upload_path(kind, warehouse):
    params = {"kind": kind}
    if warehouse:
        params["warehouse_id"] = warehouse
    return "files?" + urlencode(params)
