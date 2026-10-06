"""Verify all candidate bytes against a separately trusted manifest hash; does not grant acceptance."""

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, trusted_hash):
    manifest = root / "delivery-manifest.json"
    if root.is_symlink() or not re.fullmatch(r"[0-9a-f]{64}", trusted_hash) or digest(manifest) != trusted_hash:
        raise ValueError("MANIFEST_HASH_MISMATCH")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_MANIFEST_KEY")
            result[key] = value
        return result
    record = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if record["status"] != "CANDIDATE_NOT_ACCEPTED":
        raise ValueError("UNEXPECTED_RELEASE_STATUS")
    for relative, expected in record["files"].items():
        path = PurePosixPath(relative)
        if (path.is_absolute() or ".." in path.parts or str(path) != relative or "\\" in relative
                or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise ValueError("INVALID_MANIFEST_ENTRY")
        target = root / relative
        if not target.is_file() or digest(target) != expected:
            raise ValueError(f"ARTIFACT_MISMATCH: {relative}")
    paths = list(root.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("SYMLINK_IN_DELIVERY")
    actual = {p.relative_to(root).as_posix() for p in paths if p.is_file() and p != manifest}
    if actual != set(record["files"]):
        raise ValueError("UNMANIFESTED_CONTENT")
    return len(actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    count = verify(args.directory.absolute(), args.manifest_sha256)
    print(json.dumps({"result": "PASS", "verified_files": count, "acceptance": "NOT_ACCEPTED"}))


if __name__ == "__main__":
    main()
