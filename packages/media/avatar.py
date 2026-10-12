"""Bounded avatar decoding shared by the desktop upload and server validation."""
import base64
import binascii
import os
import stat
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ENCODED = 350000


def normalize_avatar(raw: bytes) -> str:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Chọn ảnh PNG, JPG hoặc WebP không quá 5 MB")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Chọn ảnh tĩnh PNG, JPG hoặc WebP")
            if source.width * source.height > 20000000:
                raise ValueError("Chọn ảnh không quá 20 triệu điểm ảnh")
            source.load()
            oriented = ImageOps.exif_transpose(source)
            thumbnail = ImageOps.fit(oriented.convert("RGBA"), (256, 256), method=Image.Resampling.LANCZOS)
            # A new image discards EXIF, GPS, comments and other source metadata.
            clean = Image.new("RGBA", thumbnail.size)
            clean.paste(thumbnail)
            output = BytesIO()
            clean.save(output, format="PNG")
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
            if len(encoded) > MAX_ENCODED:
                raise ValueError("Ảnh quá lớn sau xử lý; hãy chọn ảnh khác")
            return encoded
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Không đọc được ảnh; hãy chọn ảnh PNG, JPG hoặc WebP khác") from exc


def validate_avatar(encoded: str) -> str:
    if len(encoded) > MAX_ENCODED:
        raise ValueError("Ảnh vượt dung lượng cho phép")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Dữ liệu ảnh không hợp lệ") from exc
    return normalize_avatar(raw)


def load_avatar_file(path: str) -> str:
    if not Path(path).is_file():
        raise ValueError("Chọn một tệp ảnh trên máy")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Chọn một tệp ảnh trên máy")
        return normalize_avatar(source.read(MAX_FILE_BYTES + 1))
