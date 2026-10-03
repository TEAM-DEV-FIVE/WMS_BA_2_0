"""Rebuild the import ZIP and checksums after reviewing intentional changes."""

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repository_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, capture_output=True,
    )
    return sorted({Path(name.decode("utf-8")) for name in result.stdout.split(b"\0") if name})


def main():
    files = repository_files()
    archive = ROOT / "06_Nhap_lieu/CSV_mau_va_vi_du.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for relative in files:
            if relative.parts[:2] != ("06_Nhap_lieu", "imports"):
                continue
            info = zipfile.ZipInfo(relative.relative_to("06_Nhap_lieu").as_posix())
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            output.writestr(info, (ROOT / relative).read_bytes())
    lines = []
    for relative in files:
        if relative.as_posix() == "SHA256SUMS.txt":
            continue
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative.as_posix()}\n")
    (ROOT / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"Updated import ZIP and {len(lines)} SHA-256 entries.")


if __name__ == "__main__":
    main()
