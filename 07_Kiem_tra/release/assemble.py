"""Assemble a local candidate from committed sources and previously verified artifacts; never publish."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def committed(commit, name):
    return git("show", f"{commit}:{name}")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-commit", required=True)
    parser.add_argument("--docs-commit", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--dependency-bundle", type=Path, required=True)
    parser.add_argument("--dependency-manifest-sha256", required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    runtime = git("rev-parse", "--verify", f"{args.runtime_commit}^{{commit}}").decode().strip()
    docs = git("rev-parse", "--verify", f"{args.docs_commit}^{{commit}}").decode().strip()
    assert re.fullmatch(r"[0-9a-f]{40}", runtime) and re.fullmatch(r"[0-9a-f]{40}", docs)
    subprocess.run(["git", "merge-base", "--is-ancestor", runtime, docs], cwd=ROOT, check=True)
    code_paths = ["apps", "packages", "migrations", "requirements-app-lock.txt", "pyproject.toml"]
    assert not git("diff", runtime, docs, "--", *code_paths), "Docs commit changed runtime"
    native = json.loads(committed(docs, "07_Kiem_tra/NATIVE_VM_2026_10_06.artifacts.json"))
    assert not git("diff", native["commit"], runtime, "--", *code_paths), "Rebuild native clients for changed code"
    # Validate the installed Python package bytes against the named runtime, not a wheel filename.
    source_files = git("ls-tree", "-r", "--name-only", runtime, "--", "apps", "packages", "migrations").decode().splitlines()
    with zipfile.ZipFile(args.wheel) as wheel:
        for name in source_files:
            if Path(name).suffix in {".py", ".sql", ".ttf", ".txt"}:
                assert wheel.read(name) == committed(runtime, name), f"Wheel source mismatch: {name}"
    deps = args.dependency_bundle.resolve()
    assert sha(deps / "manifest.json") == args.dependency_manifest_sha256, "Untrusted dependency manifest"
    prior = json.loads((deps / "manifest.json").read_text())
    assert (deps / "requirements-app-lock.txt").read_bytes() == committed(runtime, "requirements-app-lock.txt")
    for name, digest in prior.items():
        if name.startswith("wheels/"):
            path = deps / name
            assert path.parent == deps / "wheels" and path.suffix == ".whl" and not path.is_symlink()
            assert sha(path) == digest, f"Dependency hash mismatch: {name}"
    destination = args.destination.absolute()
    destination.mkdir(parents=False, exist_ok=False)
    server = destination / "server"
    server.mkdir()
    shutil.copyfile(args.wheel, server / args.wheel.name)
    (server / "wheels").mkdir()
    for name in prior:
        if name.startswith("wheels/"):
            shutil.copyfile(deps / name, server / name)
    files = git("ls-tree", "-r", "--name-only", docs, "--", "deploy/lan", "deploy/backup").decode().splitlines()
    for name in files:
        target = server / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(committed(docs, name))
    for name in ["lan_runtime.py", "lan_stage.py", "lan_probe.py", "wms_backup.py", "backup_admin.py"]:
        (server / name).write_bytes(committed(docs, f"scripts/{name}"))
    (server / "requirements-app-lock.txt").write_bytes(committed(runtime, "requirements-app-lock.txt"))
    for name in ["LAN_DEPLOYMENT", "BACKUP_RESTORE", "OPERATIONS_RUNBOOK"]:
        (server / f"{name}.md").write_bytes(committed(docs, f"01_Tai_lieu/{name}.md"))
    write_json(server / "release.json", {"runtime_commit": runtime, "source_commit": docs,
                                        "status": "CANDIDATE_NOT_ACCEPTED"})
    write_json(server / "manifest.json", inventory(server))
    for entry in native["artifacts"]:
        source = args.native_root / entry["platform"] / entry["name"]
        assert source.is_file() and not source.is_symlink() and sha(source) == entry["sha256"]
        assert source.stat().st_size == entry["size"]
        target = destination / "clients" / entry["platform"] / entry["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    archive = destination / f"source-{docs[:12]}.tar.gz"
    with archive.open("wb") as stream:
        subprocess.run(["git", "archive", "--format=tar.gz", f"--prefix=wms-{docs[:12]}/", docs],
                       cwd=ROOT, stdout=stream, check=True)
    manifest = {"schema_version": 1, "status": "CANDIDATE_NOT_ACCEPTED", "runtime_commit": runtime,
                "source_commit": docs, "native_commit": native["commit"],
                "native_code_matches_runtime": True, "windows_signing": "TEST_ONLY",
                "macos_signing": "AD_HOC_NOT_NOTARIZED", "postgres_revisions": "001-024",
                "sqlite_revisions": "001-003", "client_protocol": 1,
                "server_manifest_sha256": sha(server / "manifest.json"), "files": inventory(destination)}
    write_json(destination / "delivery-manifest.json", manifest)
    print(json.dumps({"destination": str(destination), "files": len(manifest["files"]),
                      "manifest_sha256": sha(destination / "delivery-manifest.json"),
                      "server_manifest_sha256": manifest["server_manifest_sha256"]}))


if __name__ == "__main__":
    main()
