"""Verify real PE icon resources against the multi-resolution application ICO."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


def ico_frames(path):
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    if reserved != 0 or kind != 1 or count == 0:
        raise ValueError("Invalid application ICO")
    frames = {}
    for index in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
        payload = data[offset:offset + length]
        if len(payload) != length:
            raise ValueError("Truncated ICO frame")
        frames[f"{width or 256}x{height or 256}"] = hashlib.sha256(payload).hexdigest()
    return frames


def check_pe(path, expected):
    import pefile

    with pefile.PE(str(path)) as pe:
        actual = set()
        for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if resource.id != pefile.RESOURCE_TYPE["RT_ICON"]:
                continue
            for icon in resource.directory.entries:
                for language in icon.directory.entries:
                    entry = language.data.struct
                    actual.add(hashlib.sha256(pe.get_data(entry.OffsetToData, entry.Size)).hexdigest())
    missing = sorted(size for size, digest in expected.items() if digest not in actual)
    if missing:
        raise ValueError(f"{path.name}: missing or stale application icon frames: {missing}")
    return {"file": path.name, "status": "PASS", "sizes": sorted(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ico", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("executables", nargs="+", type=Path)
    options = parser.parse_args()
    expected = ico_frames(options.ico)
    report = {"status": "PASS", "icon_sha256": hashlib.sha256(options.ico.read_bytes()).hexdigest(),
              "executables": [check_pe(path, expected) for path in options.executables]}
    options.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
