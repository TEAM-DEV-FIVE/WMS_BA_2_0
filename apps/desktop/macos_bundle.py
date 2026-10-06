"""Native macOS bundle verification. Ad-hoc integrity is not publisher trust."""

import json
import subprocess
import sys
from pathlib import Path

from packages.contracts.compatibility import CLIENT_VERSION


def bundle_root(executable=None):
    executable = Path(executable or sys.executable).resolve()
    if executable.parent.name != "MacOS" or executable.parent.parent.name != "Contents":
        raise ValueError("Expected a macOS application bundle")
    root = executable.parents[2]
    if root.suffix != ".app":
        raise ValueError("Expected a .app directory")
    return root


def verify_bundle():
    root = bundle_root()
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(root)],
                   check=True, capture_output=True, timeout=60)
    data = json.loads((root / "Contents/Resources/release.json").read_text(encoding="utf-8"))
    if (data.get("version") != CLIENT_VERSION or data.get("platform") != "macos-arm64"
            or data.get("signing") != "adhoc-test-only"):
        raise ValueError("Incompatible macOS lab bundle")
    return data
