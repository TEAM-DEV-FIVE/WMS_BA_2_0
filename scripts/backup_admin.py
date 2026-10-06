"""Root-operated B22 orchestration; no in-place restore, no automatic promotion or purge."""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Installed beside this reviewed script; independent of an application source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lan_stage import verify_bundle  # noqa: E402
from wms_backup import (  # noqa: E402
    UNITS,
    BackupError,
    Postgres,
    Repository,
    base_backup,
    checkpoint,
    restore_check,
    restore_prepare,
)

MAINTENANCE = Path("/etc/wms/maintenance.on")

def settings(path):
    info = path.lstat()
    if os.geteuid() != 0 or info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise BackupError("ROOT_PRIVATE_CONFIG_REQUIRED")
    config = json.loads(path.read_text())
    if config["pg"]["os_user"] != "postgres" or config["pg"]["user"] != "postgres":
        raise BackupError("USE_LOCAL_POSTGRES_PEER_PROFILE")
    if config["pg"]["socket"] != "/var/run/postgresql" or config["pg"]["database"] != "wms":
        raise BackupError("USE_LOCAL_WMS_PROFILE")
    repo = Repository(config["repository"], config["repository_id"], max_bytes=config["max_bytes"],
                      wal_repository=config["wal_repository"])
    roots = {k: Path(v).resolve() for k, v in config["roots"].items()}
    if not {"import", "export", "print", "config", "pg_config", "release"} <= roots.keys():
        raise BackupError("MISSING_BACKUP_ROOT")
    if any(repo.root == p or repo.root in p.parents or p in repo.root.parents for p in roots.values()):
        raise BackupError("REPOSITORY_SOURCE_OVERLAP")
    dr_root = Path(config["dr_root"])
    if dr_root.resolve() != dr_root or any(dr_root == p or dr_root in p.parents or p in dr_root.parents
                                          for p in [repo.root, repo.wal.parent, *roots.values()]):
        raise BackupError("DR_ROOT_OVERLAP")
    return config, repo, Postgres(**config["pg"]), roots


def verify_release(config, roots):
    if not re.fullmatch(r"[0-9a-f]{40}", config["release"]):
        raise BackupError("VERIFIED_RELEASE_REQUIRED")
    verify_bundle(roots["release"], config["release_manifest_sha256"])



def systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=400)


def assert_stopped():
    for unit in UNITS:
        result = systemctl("show", "--property=ActiveState", "--value", unit)
        if result.returncode or result.stdout.strip() != "inactive":
            raise BackupError("WRITERS_NOT_STOPPED")
    if not MAINTENANCE.is_file():
        raise BackupError("MAINTENANCE_REQUIRED")


def newest_base(repo):
    records = [json.loads(p.read_text()) for p in (repo.root / "bases").glob("*/base.json")]
    if not records:
        raise BackupError("BASE_BACKUP_REQUIRED")
    return max(records, key=lambda r: r["created_at"])["id"]


def cycle(repo, pg, config, roots):
    """Brief write pause; preserve existing maintenance. Resume only after B21 readiness."""
    marker = MAINTENANCE
    if marker.exists() or any(systemctl("is-active", u).returncode for u in UNITS if u != "wms-monitor.service"):
        raise BackupError("NOT_AN_ACTIVE_DEPLOYMENT")
    marker.touch(mode=0o644, exist_ok=False)
    try:
        if systemctl("stop", "wms.target").returncode:
            raise BackupError("STOP_FAILED")
        assert_stopped()
        return checkpoint(repo, pg, newest_base(repo), roots, config["release"])
    finally:
        # Preserve maintenance if restart/readiness fails; never claim success from target active alone.
        resumed = systemctl("start", "wms.target").returncode == 0
        if resumed:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if systemctl("start", "wms-monitor.service").returncode == 0:
                    marker.unlink()
                    break
                time.sleep(2)
            else:
                raise BackupError("RESTART_READINESS_FAILED")
        else:
            raise BackupError("RESTART_FAILED")


def monitor(repo, pg):
    repo.capacity()
    points = sorted((repo.root / "checkpoints").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not points:
        raise BackupError("NO_RECOVERY_CHECKPOINT")
    record = repo.verify_checkpoint(points[-1].stem)
    age = (datetime.now(UTC) - datetime.fromisoformat(record["target_time"])).total_seconds()
    base = json.loads((repo.root / "bases" / record["base"] / "base.json").read_text())
    base_age = (datetime.now(UTC) - datetime.fromisoformat(base["created_at"])).total_seconds()
    info = pg.info()
    if any(record[k] != info[k] or base[k] != info[k] for k in ("system_id", "timeline", "major")):
        raise BackupError("BACKUP_PRIMARY_MISMATCH")
    failed = pg.sql("""SELECT coalesce(last_failed_time > last_archived_time OR
        (last_failed_time IS NOT NULL AND last_archived_time IS NULL),false) FROM pg_stat_archiver""")
    if age < 0 or age >= 2700 or base_age >= 129600 or failed == "t":
        raise BackupError("BACKUP_STALE_OR_ARCHIVE_FAILURE")
    return {"checkpoint_age_seconds": round(age, 3), "base_age_seconds": round(base_age, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("base", "checkpoint", "cycle", "monitor", "restore-prepare", "restore-check"))
    parser.add_argument("--config", type=Path, default=Path("/etc/wms-backup/config.json"))
    parser.add_argument("--checkpoint")
    parser.add_argument("--target-time")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--dr-socket", type=Path)
    parser.add_argument("--dr-port", type=int, default=55432)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config, repo, pg, roots = settings(args.config)
        if args.action in {"base", "checkpoint", "cycle"}:
            verify_release(config, roots)
        if args.action == "base":
            result = base_backup(repo, pg, config["staging"], config["release"])
        elif args.action == "checkpoint":
            assert_stopped()
            result = checkpoint(repo, pg, newest_base(repo), roots, config["release"])
        elif args.action == "cycle":
            result = cycle(repo, pg, config, roots)
        elif args.action == "monitor":
            result = monitor(repo, pg)
        elif args.action == "restore-prepare":
            # DBA prepares under a separate DR root, never in a production data/storage path.
            if args.destination is None or not args.destination.absolute().is_relative_to(Path(config["dr_root"])):
                raise BackupError("OUTSIDE_DR_ROOT")
            result = restore_prepare(repo, args.checkpoint, args.destination, pg, target_time=args.target_time)
        else:
            if args.destination is None or not args.destination.resolve().is_relative_to(Path(config["dr_root"])):
                raise BackupError("OUTSIDE_DR_ROOT")
            if not args.dr_socket or not args.dr_socket.resolve().is_relative_to(Path(config["dr_root"]).resolve()):
                raise BackupError("ISOLATED_DR_SOCKET_REQUIRED")
            dr = Postgres(config["pg"]["bindir"], args.dr_socket, args.dr_port, "wms", "postgres", os_user="postgres")
            result = restore_check(dr, args.destination)
        # Only operational metadata; no manifests, table hashes, file names or secrets in journald.
        print(json.dumps({"event": "backup_" + args.action, "ok": True,
                          **{k: v for k, v in result.items() if k in {"id", "target_time", "checkpoint_age_seconds"}}}))
        return 0
    except Exception:
        print(json.dumps({"event": "backup_" + args.action, "ok": False, "code": "BACKUP_CHECK_FAILED"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
