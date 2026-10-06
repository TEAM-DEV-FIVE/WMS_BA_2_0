"""Release manifest integrity, shared by the Windows build and installed helper."""

import hashlib
import json
import re
import struct
from pathlib import PurePosixPath

from packages.contracts.compatibility import API_PROTOCOL, CACHE_READ_MAX, CLIENT_VERSION, RECOVERY_PROTOCOL


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def safe_relative(name):
    p = PurePosixPath(name)
    if (
        not name
        or p.is_absolute()
        or str(p) != name
        or ".." in p.parts
        or any(c in name for c in "\\:\x00")
        or any(part.endswith((".", " ")) for part in p.parts)
    ):
        raise ValueError("Invalid release path")
    return p


def pe_x64(path):
    with path.open("rb") as f:
        if f.read(2) != b"MZ":
            return False
        f.seek(60)
        offset = struct.unpack("<I", f.read(4))[0]
        f.seek(offset)
        return f.read(6) == b"PE\0\0\x64\x86"


def write_manifest(directory, *, commit, lock_hash, signing):
    if not re.fullmatch("[0-9a-f]{40}", commit) or signing not in {"unsigned", "authenticode"}:
        raise ValueError("Invalid build provenance")
    inventory = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Release cannot contain links")
        if not path.is_file() or path.name == "manifest.json":
            continue
        relative = path.relative_to(directory).as_posix()
        safe_relative(relative)
        parts = relative.lower().split("/")
        if any(
            p in {".git", ".env", ".reports", "tests", "migrations", "server"} for p in parts
        ) or path.suffix.lower() in {".pfx", ".p12", ".key", ".sqlite3", ".backup"}:
            raise ValueError("Forbidden client release content")
        inventory[relative] = {"sha256": sha256(path), "size": path.stat().st_size}
    for name in ("WMS.exe", "WMSHelper.exe"):
        if name not in inventory or not pe_x64(directory / name):
            raise ValueError("Windows x64 executable required")
    data = dict(
        schema=1,
        product="wms-desktop",
        version=CLIENT_VERSION,
        commit=commit,
        python="3.12",
        platform="windows-x64",
        api_protocol=API_PROTOCOL,
        recovery_protocol=RECOVERY_PROTOCOL,
        cache_read_max=CACHE_READ_MAX,
        lock_sha256=lock_hash,
        signing=signing,
        files=inventory,
    )
    (directory / "manifest.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return data


def verify_manifest(directory):
    path = directory / "manifest.json"
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Release manifest too large")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != 1
        or manifest.get("product") != "wms-desktop"
        or manifest.get("version") != CLIENT_VERSION
        or manifest.get("platform") != "windows-x64"
        or manifest.get("cache_read_max") != CACHE_READ_MAX
        or manifest.get("api_protocol") != API_PROTOCOL
        or manifest.get("recovery_protocol") != RECOVERY_PROTOCOL
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ValueError("Incompatible release manifest")
    for name, info in manifest["files"].items():
        p = directory.joinpath(*safe_relative(name).parts)
        if p.is_symlink() or not p.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Release file escaped package")
        if p.stat().st_size != info["size"] or sha256(p) != info["sha256"]:
            raise ValueError("Release file checksum mismatch")
    if not {"WMS.exe", "WMSHelper.exe"} <= manifest["files"].keys():
        raise ValueError("Release executable missing")
    return manifest
