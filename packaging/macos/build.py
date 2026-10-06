"""Build, ad-hoc sign, verify and smoke a native macOS arm64 lab .app."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*args, **options):
    return subprocess.run([str(arg) for arg in args], check=True, **options)


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("Native macOS arm64 required")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise SystemExit("Clean committed checkout required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = ROOT / "dist" / ("macos-" + commit[:12])
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="wms-mac-build-") as directory:
        work = Path(directory)
        run(sys.executable, "-m", "venv", work / "venv")
        python = work / "venv/bin/python"
        run(python, "-m", "pip", "install", "--require-hashes", "--only-binary=:all:",
            "-r", ROOT / "packaging/macos/requirements-build-lock.txt")
        run(python, "-m", "pip", "check")
        run(python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", work / "frozen",
            "--workpath", work / "pyinstaller", ROOT / "packaging/macos/WMS.spec", cwd=ROOT)
        app = work / "frozen/WMS.app"
        meta = dict(version="0.1.0", commit=commit, platform="macos-arm64", signing="adhoc-test-only",
                    notarized=False, public_release=False, python=sys.version, os=platform.platform())
        resource = app / "Contents/Resources/release.json"
        resource.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        # Adding metadata changes the bundle resource seal, so sign the outer bundle again.
        run("/usr/bin/codesign", "--force", "--sign", "-", app)
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app)
        run("/usr/bin/codesign", "--display", "--verbose=4", app)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory(prefix="WMS cài thử ") as installed:
            target = Path(installed) / "WMS.app"
            run("/usr/bin/ditto", app, target)
            run(target / "Contents/MacOS/WMS", "--self-test", "--report", output / "installed-smoke.json",
                cwd=installed, env=env, timeout=120)
            run("/usr/bin/codesign", "--verify", "--deep", "--strict", target)
        archive = output / "WMS-macos-arm64-TEST-ONLY.zip"
        run("/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive)
        (output / "release.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        (output / "SHA256SUMS.txt").write_text(
            "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                    for p in sorted(output.iterdir()) if p.is_file()), encoding="utf-8")
    print(f"Built {output}; ad-hoc lab signing, not Developer ID or notarization.")


if __name__ == "__main__":
    main()
