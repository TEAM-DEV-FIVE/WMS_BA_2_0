"""Inventory for separate server bundle; never changes the client-only manifest policy."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

from apps.local_launcher.product import PRODUCT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise SystemExit("Clean committed checkout required")
    notices = args.directory / "licenses"
    notices.mkdir(exist_ok=True)
    distributions = []
    for d in importlib.metadata.distributions():
        name = d.metadata["Name"]
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
        json.dumps(sorted(distributions, key=lambda d: d["name"]), indent=2), encoding="utf-8"
    )
    inventory = {}
    for p in sorted(args.directory.rglob("*")):
        if p.is_symlink():
            raise ValueError("Links are not allowed")
        if not p.is_file() or p.name == "local-manifest.json":
            continue
        if p.suffix.lower() in {".pfx", ".p12", ".key", ".sqlite3", ".backup"} or p.name in {
            "runtime.json",
            ".env",
        }:
            raise ValueError("User data or secret material cannot ship")
        inventory[p.relative_to(args.directory).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    (args.directory / "local-manifest.json").write_text(
        json.dumps(
            {
                "product": PRODUCT,
                "kind": "local-server",
                "signing": "unsigned",
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "files": inventory,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
