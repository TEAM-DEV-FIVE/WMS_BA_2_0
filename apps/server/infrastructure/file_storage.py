"""Private immutable content objects. No client name becomes a filesystem path."""

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.server.domain.errors import DomainError


class ImportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WMS_IMPORT_", extra="ignore")
    storage_root: Path = Path(".wms-import-files")
    max_file_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_user_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    max_user_files: int = Field(default=100, ge=1, le=10000)
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    max_attempts: int = Field(default=5, ge=1, le=20)


def safe_name(name):
    if (
        not name
        or len(name) > 240
        or name != name.strip()
        or name in {".", ".."}
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(c in name for c in "/\\:")
        or Path(name).suffix.lower() not in {".csv", ".xlsx"}
    ):
        raise DomainError("INVALID_FILENAME", "Tên tệp chỉ được là tên CSV/XLSX, không chứa đường dẫn.")
    return name


class FileStorage:
    def __init__(self, settings=None):
        self.settings = settings or ImportSettings()
        self.root = self.settings.storage_root.absolute()

    def path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise DomainError("FILE_UNAVAILABLE", "Tệp lưu trữ không hợp lệ.")
        if self.root.is_symlink():
            raise DomainError("FILE_UNAVAILABLE", "Storage phải là thư mục riêng của máy chủ.")
        return self.root / key

    def put(self, data, digest, key):
        if len(data) > self.settings.max_file_bytes or hashlib.sha256(data).hexdigest() != digest:
            raise DomainError("FILE_HASH_MISMATCH", "Nội dung tệp không khớp hash/kích thước.")
        target = self.path(key)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.root / (uuid4().hex + ".part")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                self.read(key, digest, len(data))
            directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, key, digest, size):
        try:
            fd = os.open(self.path(key), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                data = stream.read(self.settings.max_file_bytes + 1)
        except OSError:
            raise DomainError(
                "FILE_UNAVAILABLE", "Không đọc được tệp; thử lại sau khi kiểm tra storage.", retryable=True
            ) from None
        if (
            len(data) != size
            or len(data) > self.settings.max_file_bytes
            or hashlib.sha256(data).hexdigest() != digest
        ):
            raise DomainError("FILE_HASH_MISMATCH", "Tệp đã đổi hoặc hỏng; không dùng kết quả dry-run cũ.")
        return data
