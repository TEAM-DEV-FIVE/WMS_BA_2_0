"""Persistent device identity; call from the session worker, never the Tk thread."""

import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4


def default_data_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "wms-lan"


def private_file(path: Path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    if os.name != "nt":
        path.chmod(0o600)


def device_identity(directory: Path) -> UUID:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "device.sqlite3"
    private_file(path)
    connection = sqlite3.connect(path, timeout=2)
    try:
        connection.execute("PRAGMA synchronous=FULL")
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS device(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
            )
            connection.execute("INSERT OR IGNORE INTO device(id,value) VALUES (1,?)", (str(uuid4()),))
            return UUID(connection.execute("SELECT value FROM device WHERE id=1").fetchone()[0])
    finally:
        connection.close()


class PartitionLock:
    """OS lock released on process death. Never delete the lock file while holding it."""

    def __init__(self, path: Path):
        self.file = open(path, "a+b")
        try:
            if path.stat().st_size == 0:
                self.file.write(b"\0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise OSError("Dữ liệu phục hồi đang được một cửa sổ WMS khác sử dụng.") from None

    def close(self):
        if self.file.closed:
            return
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
