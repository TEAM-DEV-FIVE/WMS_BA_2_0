"""Stage a verified offline wheel bundle into a NEW immutable release directory.

Manifest JSON: {relative_filename: sha256}. Pin its SHA256 from the trusted handoff.
Bundle contains application.whl, requirements-app-lock.txt, lan_runtime.py and wheels/.
Does not touch current, config, services or PostgreSQL. Failed stage stays for diagnosis.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath


def verify_bundle(bundle, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid manifest digest")
    manifest = bundle / "manifest.json"
    if manifest.is_symlink() or hashlib.sha256(manifest.read_bytes()).hexdigest() != expected:
        raise ValueError("Manifest mismatch")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate manifest entry")
            result[key] = value
        return result

    entries = json.loads(manifest.read_text(), object_pairs_hook=pairs)
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Invalid manifest")
    for name, digest in entries.items():
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid entry")
        source = bundle / name
        if (not source.is_file() or source.is_symlink()
                or any(p.is_symlink() for p in source.parents if p != bundle.parent)
                or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
            raise ValueError("Bundle mismatch")
    actual = {str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file() and p != manifest}
    if actual != set(entries) or any(p.is_symlink() for p in bundle.rglob("*")):
        raise ValueError("Unmanifested bundle content")
    wheels = [name for name in entries if "/" not in name and name.endswith(".whl")]
    if (len(wheels) != 1 or not wheels[0].startswith("wms_lan-")
            or not {"requirements-app-lock.txt", "lan_runtime.py"} <= entries.keys()):
        raise ValueError("Missing release inputs")
    # Offline dependency input is pins only; disallow pip options, URLs and includes.
    pins = (bundle / "requirements-app-lock.txt").read_text().splitlines()
    if not pins or any(not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", p) for p in pins):
        raise ValueError("Lock must contain exact pins only")
    if any(not name.endswith(".whl") for name in entries if name.startswith("wheels/")):
        raise ValueError("Use wheels only")
    return wheels[0]


def stage(bundle, destination, expected):
    wheel = verify_bundle(bundle, expected)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Release already exists")
    destination.mkdir(mode=0o755, parents=False)
    # Release is created at its final path; moving a venv afterwards breaks shebangs.
    snapshot = destination / "bundle"
    shutil.copytree(bundle, snapshot)
    verify_bundle(snapshot, expected)
    subprocess.run([sys.executable, "-I", "-m", "venv", str(destination / "venv")], check=True)
    python = destination / "venv/bin/python"
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("PIP_", "PYTHON", "WMS_"))}
    environment["PIP_CONFIG_FILE"] = os.devnull
    subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-index", "--no-cache-dir",
                    "--only-binary=:all:", "--find-links", str(snapshot / "wheels"),
                    "-r", str(snapshot / "requirements-app-lock.txt"), str(snapshot / wheel)],
                   check=True, env=environment)
    subprocess.run([str(python), "-I", "-m", "pip", "--no-cache-dir", "check"], check=True, env=environment)
    shutil.copyfile(snapshot / "lan_runtime.py", destination / "lan_runtime.py")
    # A root umask of 077 must not make the installed release unreadable to wms.
    # Inputs contain no secrets; retain executable bits, remove all group/other writes.
    for path in [destination, *destination.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    (destination / "VERIFIED_MANIFEST_SHA256").write_text(expected + "\n")
    (destination / "VERIFIED_MANIFEST_SHA256").chmod(0o644)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        bundle, destination = args.bundle.resolve(), args.destination.absolute()
        if args.verify_only:
            verify_bundle(bundle, args.manifest_sha256)
        else:
            stage(bundle, destination, args.manifest_sha256)
        print('{"event":"release_verified","ok":true}')
        return 0
    except Exception:
        print('{"event":"release_stage_failed","current_unchanged":true}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
