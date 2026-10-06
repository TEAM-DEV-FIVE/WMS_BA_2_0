import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

root = Path.cwd()
source = root / "dist/hosted-37471976127"
target = Path("/home/kien/Đồ án KHMT2_2/WMS_BA_2_0/dist/native-97d4c510dab8")
evidence = {"commit": "97d4c510dab8370643b7d55e85d6788443b5e209", "artifacts": []}
for sums in sorted(source.rglob("SHA256SUMS.txt")):
    directory = sums.parent
    kind = "windows" if directory.name.startswith("windows-") else "macos"
    for line in sums.read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        path = directory / name
        assert path.resolve().is_relative_to(directory.resolve()) and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    if kind == "windows":
        manifest = json.loads((directory / "manifest.json").read_text())
        signature = json.loads((directory / "lab-signature.json").read_text(encoding="utf-8-sig"))
        assert signature["signature"] == "Valid" and signature["timestamped"] and signature["test_only"]
        assert manifest["commit"] == evidence["commit"] == signature["commit"]
        with ZipFile(next(directory.glob("WMS-0.1*.zip"))) as archive:
            names = {n.replace("\\", "/"): n for n in archive.namelist()}
            assert len(names) == len(archive.namelist())
            for name, info in manifest["files"].items():
                data = archive.read(names["WMS/" + name])
                assert len(data) == info["size"] and hashlib.sha256(data).hexdigest() == info["sha256"], name
            assert not any(n.lower().endswith((".pfx", ".p12", ".key")) for n in names)
        print(f"Windows bundle: {len(manifest['files'])} hashes verified; signed installer hash verified")
    else:
        meta = json.loads((directory / "release.json").read_text())
        assert meta["commit"] == evidence["commit"] and meta["signing"] == "adhoc-test-only"
        assert json.loads((directory / "installed-smoke.json").read_text())["status"] == "PASS"
        with ZipFile(next(directory.glob("*.zip"))) as archive:
            assert "WMS.app/Contents/MacOS/WMS" in archive.namelist()
            assert not any(n.lower().endswith((".pfx", ".p12", ".key")) for n in archive.namelist())
        print("macOS archive: checksum and installed smoke verified")
    shutil.copytree(directory, target / kind)
    for path in sorted((target / kind).iterdir()):
        if path.is_file():
            evidence["artifacts"].append(dict(platform=kind, name=path.name, size=path.stat().st_size,
                                               sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
assert len(evidence["artifacts"]) == 13
(root / ".reports/native-final.artifacts.json").write_text(
    json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
print(f"Verified and copied delivery to {target}")
