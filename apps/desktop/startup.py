"""Per-user configuration and upgrade preflight, before opening any journal."""

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from apps.desktop.api.client import DesktopSettings
from apps.desktop.local_store.device import PartitionLock, default_data_directory
from packages.contracts.compatibility import CACHE_READ_MAX


def settings_for_startup():
    directory = Path(os.environ.get("WMS_LOCAL_DATA_DIR", default_data_directory())).absolute()
    if getattr(sys, "frozen", False):
        install = Path(sys.executable).resolve().parent
        if directory.resolve() == install or install in directory.resolve().parents:
            raise ValueError("Dữ liệu cá nhân phải nằm ngoài thư mục cài đặt.")
    config = directory / "client.json"
    values = {}
    if config.exists():
        if config.stat().st_size > 16384:
            raise ValueError("Cấu hình client quá lớn.")
        values = json.loads(config.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict) or set(values) - {"api_url", "ca_file", "http_timeout_seconds"}:
            raise ValueError("Cấu hình client chỉ chứa địa chỉ API, CA và timeout.")
        # Explicit environment overrides the user's persisted configuration.
        values = {k: v for k, v in values.items() if "WMS_" + k.upper() not in os.environ}
        if values.get("ca_file"):
            path = Path(values["ca_file"])
            values["ca_file"] = path if path.is_absolute() else directory / path
    return DesktopSettings(**values, local_data_dir=directory, require_compatibility=True)


def preflight_cache(directory: Path):
    """Inspect only. No migration, restore, SENDING transition or outbound HTTP here."""
    if not directory.exists():
        return
    for folder in (directory, directory / "commands", directory / "receipts"):
        if folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction()):
            raise ValueError("Thư mục cache không được là liên kết.")
        if not folder.exists():
            continue
        for path in folder.glob("*.sqlite3"):
            if ".backup." in path.name:
                continue
            if path.is_symlink():
                raise ValueError("Tệp cache không được là liên kết.")
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as c:
                version = c.execute("PRAGMA user_version").fetchone()[0]
                if version > CACHE_READ_MAX or version < 0:
                    raise ValueError("Cache mới hơn client; không hạ phiên bản hoặc xóa cache.")
                if (
                    c.execute("PRAGMA quick_check").fetchone()[0] != "ok"
                    or c.execute("PRAGMA foreign_key_check").fetchone() is not None
                ):
                    raise ValueError("Cache lỗi; giữ nguyên dữ liệu để phục hồi.")


def application_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return PartitionLock(directory / "application.lock")


def configure_display():
    if os.name == "nt":
        import ctypes

        # Match the manifest: per-monitor V2 where available. Must precede Tk creation.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
