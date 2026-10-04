"""Small, secret-free evidence helpers shared by local and hosted checks."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def evidence(path: Path, **details):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "lock_sha256": hashlib.sha256((ROOT / "requirements-app-lock.txt").read_bytes()).hexdigest(),
        "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions())),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        **details,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def logged_run(args, log: Path, **kwargs):
    """Keep the console and artifact identical; callers never pass secrets in argv."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        with subprocess.Popen(
            [str(arg) for arg in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **kwargs,
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                stream.write(line)
            return process.wait()


def main():
    parser = argparse.ArgumentParser(description="Run a CI command and save log/environment without secrets")
    parser.add_argument("--name", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Expected a command after --")
    if Path(args.name).name != args.name:
        parser.error("Name must be a filename stem")
    status = logged_run(command, ROOT / ".reports" / (args.name + ".log"), cwd=ROOT)
    evidence(ROOT / ".reports" / (args.name + ".environment.json"), check=args.name, result=status)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
