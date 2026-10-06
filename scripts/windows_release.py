"""Build provenance and inventory from a real frozen Windows bundle."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

from apps.desktop.bundle import sha256, verify_manifest, write_manifest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--signing", choices=["unsigned", "authenticode"], default="unsigned")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_manifest(args.directory)
        print("PASS release checksums")
        return
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise SystemExit("Build requires a clean committed checkout")
    notices = args.directory / "licenses"
    notices.mkdir(exist_ok=True)
    distributions = []
    for d in importlib.metadata.distributions():
        name = d.metadata["Name"]
        # Record exact build environment; copy shipped dependency licenses with source filenames.
        distributions.append(
            dict(
                name=name,
                version=d.version,
                license=d.metadata.get("License-Expression") or d.metadata.get("License", ""),
            )
        )
        for f in d.files or []:
            if (
                any(k in f.name.lower() for k in ("license", "copying", "notice"))
                and d.locate_file(f).is_file()
            ):
                destination = (
                    notices / name / (hashlib.sha256(str(f).encode()).hexdigest()[:8] + "-" + f.name)
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(d.locate_file(f), destination)
    (args.directory / "dependencies.json").write_text(
        json.dumps(sorted(distributions, key=lambda d: d["name"]), indent=2) + "\n", encoding="utf-8"
    )
    shutil.copyfile(ROOT / "packaging/windows/client.example.json", args.directory / "client.example.json")
    manifest = write_manifest(
        args.directory,
        commit=commit,
        lock_hash=sha256(ROOT / "packaging/windows/requirements-build-lock.txt"),
        signing=args.signing,
    )
    verify_manifest(args.directory)
    print(f"PASS manifest: {len(manifest['files'])} files; {args.signing}")


if __name__ == "__main__":
    main()
