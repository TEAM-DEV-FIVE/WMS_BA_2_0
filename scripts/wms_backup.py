"""PostgreSQL16 backup repository and application-consistent PITR checkpoints.

Repository contents are sensitive. No destructive retention or in-place restore.
CLI configuration is root-owned on target; local tests use disposable clusters.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

WAL = re.compile(r"(?:[0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)")
UNITS = ["wms-api.service", *[f"wms-worker@{k}.service" for k in
         ("outbox", "import", "export", "print", "export-cleanup", "print-cleanup")],
         "wms-monitor.service", "wms-monitor.timer"]


class BackupError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(path, data):
    """Durable, immutable name publication. Never acknowledge different existing bytes."""
    path = Path(path)
    temporary = path.with_name("." + uuid4().hex + ".partial")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise BackupError("IMMUTABLE_COLLISION") from None
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path, value):
    publish(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def regular_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or root.resolve() != root.absolute():
        raise BackupError("UNSAFE_ROOT")
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise BackupError("UNSAFE_TREE_ENTRY")
        if path.is_file():
            yield path


def copy_verified(source, target, expected=None):
    source, target = Path(source), Path(target)
    if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
        raise BackupError("UNSAFE_FILE")
    expected = expected or digest(source)
    temporary = target.with_name("." + uuid4().hex + ".partial")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            os.chmod(temporary, 0o600)
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if digest(temporary) != expected:
            raise BackupError("COPY_HASH_MISMATCH")
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or digest(target) != expected:
                raise BackupError("IMMUTABLE_COLLISION") from None
        sync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return expected


class Repository:
    def __init__(self, path, identity, *, max_bytes=2 * 1024**3, require_mount=True, wal_repository=None):
        self.root = Path(path).absolute()
        if (self.root.is_symlink() or self.root.resolve() != self.root or not self.root.is_dir()
                or self.root.stat().st_mode & 0o077 or (require_mount and not self.root.parent.is_mount())):
            raise BackupError("REPOSITORY_MOUNT_OR_PERMISSIONS")
        marker = self.root / ".repository-id"
        if marker.is_symlink() or marker.read_text().strip() != identity:
            raise BackupError("REPOSITORY_ID_MISMATCH")
        self.limit = max_bytes
        for name in ("wal", "bases", "objects", "checkpoints"):
            p = self.root / name
            p.mkdir(mode=0o700, exist_ok=True)
            if p.is_symlink() or p.stat().st_mode & 0o077:
                raise BackupError("UNSAFE_REPOSITORY_DIRECTORY")
        self.wal = self.root / "wal"
        if wal_repository is not None:
            other = Path(wal_repository).absolute()
            if (other.is_symlink() or other.resolve() != other or other.stat().st_mode & 0o077
                    or other.parent != self.root.parent
                    or (other / '.repository-id').read_text().strip() != identity):
                raise BackupError("WAL_REPOSITORY_MISMATCH")
            self.wal = other / "wal"
            if self.wal.is_symlink() or not self.wal.is_dir():
                raise BackupError("WAL_REPOSITORY_MISSING")

    def capacity(self, extra=0):
        used = sum(p.stat().st_size for p in regular_files(self.root))
        if used + extra > self.limit or shutil.disk_usage(self.root).free < extra + 64 * 1024**2:
            raise BackupError("REPOSITORY_CAPACITY")

    @contextmanager
    def lock(self, kind="catalog"):
        fd = os.open(self.root / ("." + kind + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def archive(self, source, name):
        if not WAL.fullmatch(name):
            raise BackupError("INVALID_WAL_NAME")
        with self.lock("wal"):
            target = self.wal / name
            self.capacity(0 if target.exists() else Path(source).stat().st_size)
            sha = copy_verified(source, target)
            publish(target.with_name(name + ".sha256"), (sha + "\n").encode())

    def wal_path(self, name):
        if not WAL.fullmatch(name):
            raise BackupError("INVALID_WAL_NAME")
        path = self.wal / name
        sha = path.with_name(name + ".sha256")
        if path.is_symlink() or sha.is_symlink() or digest(path) != sha.read_text().strip():
            raise BackupError("WAL_MISSING_OR_CORRUPT")
        return path

    def object(self, source):
        sha = digest(source)
        destination = self.root / "objects" / sha
        if not destination.exists():
            self.capacity(Path(source).stat().st_size)
        copy_verified(source, destination, sha)
        return sha

    def snapshot(self, roots):
        entries = {}
        for name, root in roots.items():
            if not re.fullmatch(r"[a-z_]+", name):
                raise BackupError("INVALID_ROOT_LABEL")
            for p in regular_files(root):
                relative = name + "/" + str(p.relative_to(root))
                entries[relative] = {"sha256": self.object(p), "size": p.stat().st_size}
        return entries

    def verify_checkpoint(self, checkpoint):
        if not re.fullmatch(r"[0-9a-f]{32}", checkpoint):
            raise BackupError("INVALID_CHECKPOINT")
        path = self.root / "checkpoints" / (checkpoint + ".json")
        expected = path.with_suffix(".sha256").read_text().strip()
        if path.is_symlink() or digest(path) != expected:
            raise BackupError("CHECKPOINT_CORRUPT")
        record = json.loads(path.read_text())
        if record["id"] != checkpoint or not re.fullmatch(r"[0-9a-f]{32}", record["base"]):
            raise BackupError("INVALID_BASE_REFERENCE")
        base = self.root / "bases" / record["base"]
        if base.is_symlink() or (base / "base.json").is_symlink():
            raise BackupError("UNSAFE_BASE_REFERENCE")
        metadata = json.loads((base / "base.json").read_text())
        if (any(metadata[k] != record[k] for k in ("system_id", "timeline", "major", "release", "revisions"))
                or (base / "pg/backup_manifest").is_symlink()
                or digest(base / "pg/backup_manifest") != metadata["manifest_sha256"]):
            raise BackupError("BASE_METADATA_MISMATCH")
        for name, item in record["files"].items():
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise BackupError("INVALID_MANIFEST_PATH")
            obj = self.root / "objects" / item["sha256"]
            if obj.is_symlink() or obj.stat().st_size != item["size"] or digest(obj) != item["sha256"]:
                raise BackupError("OBJECT_MISSING_OR_CORRUPT")
        for name, sha in record["wal"].items():
            if digest(self.wal_path(name)) != sha:
                raise BackupError("WAL_MISSING_OR_CORRUPT")
        return record


class Postgres:
    def __init__(self, bindir, socket, port, database, user, *, os_user=None):
        self.bindir = Path(bindir)
        self.socket, self.port, self.database, self.user = str(socket), str(port), database, user
        self.prefix = ["runuser", "-u", os_user, "--"] if os_user else []

    def run(self, binary, *args, timeout=300):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "WMS_"))}
        env["PGAPPNAME"] = "wms-backup"
        if binary == "psql":
            # Row JSON contains timestamptz. Canonical UTC is independent of source/DR host defaults.
            env["PGOPTIONS"] = "-c timezone=UTC"
        prefix = self.prefix if binary in {"psql", "pg_basebackup"} else []
        result = subprocess.run([*prefix, str(self.bindir / binary), *map(str, args)],
                                capture_output=True, env=env, timeout=timeout)
        if result.returncode:
            raise BackupError("POSTGRES_TOOL_FAILED")
        return result.stdout.decode()

    def sql(self, query):
        return self.run("psql", "-XAt", "--no-password", "-v", "ON_ERROR_STOP=1", "-h", self.socket,
                        "-p", self.port, "-U", self.user, "-d", self.database, "-c", query).strip()

    def info(self):
        value = json.loads(self.sql("""SELECT json_build_object('major',current_setting('server_version_num')::int/10000,
            'system_id',system_identifier::text,'timeline',(pg_control_checkpoint()).timeline_id,
            'recovery',pg_is_in_recovery()) FROM pg_control_system()"""))
        if value["major"] != 16 or value["recovery"]:
            raise BackupError("PRIMARY_PG16_REQUIRED")
        return value

    def revisions(self):
        return json.loads(self.sql("SELECT json_object_agg(version,sha256) FROM public.wms_schema_migration"))

    def fingerprints(self):
        tables = json.loads(self.sql("""SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables
            WHERE schemaname='wms'"""))
        result = {}
        for table in tables:
            if not re.fullmatch(r"[a-z_]+", table):
                raise BackupError("UNEXPECTED_TABLE")
            # Per-row SHA256, sorted, then a table SHA256; never return business values to logs.
            result[table] = json.loads(self.sql(f"""SELECT json_build_object('count',count(*),'sha256',
                encode(sha256(convert_to(COALESCE(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex'))
                FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') h
                FROM wms.{table} t) s"""))
        return result


def reconcile(pg):
    """Read-only invariant checks; no cache rebuilding or ledger mutation."""
    sql = """WITH physical AS (
      SELECT id FROM wms.location WHERE kind IN ('STORAGE','RECEIVING','QUARANTINE','SHIPPING','TRANSIT')
    ), flow AS (
      SELECT stock_item_id,destination_location_id location_id,quantity_base q FROM wms.stock_move
      UNION ALL SELECT stock_item_id,source_location_id,-quantity_base FROM wms.stock_move
    ), ledger AS (
      SELECT stock_item_id,location_id,sum(q) q FROM flow JOIN physical p ON p.id=location_id
      GROUP BY stock_item_id,location_id
    ), reserves AS (
      SELECT stock_item_id,location_id,sum(quantity-consumed-released) q FROM wms.reservation
      GROUP BY stock_item_id,location_id
    ) SELECT json_build_object(
      'ledger_balance', (SELECT count(*) FROM ledger l FULL JOIN wms.stock_balance b
        USING(stock_item_id,location_id) WHERE coalesce(l.q,0)<>coalesce(b.on_hand,0)),
      'reservation_balance', (SELECT count(*) FROM reserves r FULL JOIN wms.stock_balance b
        USING(stock_item_id,location_id) WHERE coalesce(r.q,0)<>coalesce(b.reserved,0)),
      'serial_balance', (SELECT count(*) FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
        LEFT JOIN wms.serial_position s ON s.serial_id=i.serial_id
        WHERE i.serial_id IS NOT NULL AND b.on_hand>0 AND (b.on_hand<>1 OR s.location_id IS DISTINCT FROM b.location_id)),
      'serial_position', (SELECT count(*) FROM wms.serial_position s JOIN physical p ON p.id=s.location_id
        WHERE NOT EXISTS (SELECT 1 FROM wms.stock_balance b JOIN wms.stock_item i ON i.id=b.stock_item_id
          WHERE i.serial_id=s.serial_id AND b.location_id=s.location_id AND b.on_hand=1)))"""
    result = json.loads(pg.sql(sql))
    if any(result.values()):
        raise BackupError("RECONCILIATION_FAILED")
    return result


def base_backup(repo, pg, staging, release):
    with repo.lock():
        info = pg.info()
        if pg.sql("SELECT count(*) FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global')") != "0":
            raise BackupError("TABLESPACES_REQUIRE_SEPARATE_PROFILE")
        size = int(pg.sql("SELECT sum(pg_database_size(oid)) FROM pg_database"))
        repo.capacity(size * 2 + 64 * 1024**2)
        name = uuid4().hex
        work = Path(staging) / name
        work.mkdir(mode=0o700)
        if pg.prefix:
            import pwd
            owner = pwd.getpwnam(pg.prefix[2])
            os.chown(work, owner.pw_uid, owner.pw_gid)
        pg.run("pg_basebackup", "-h", pg.socket, "-p", pg.port, "-U", pg.user, "-D", work / "pg",
               "--no-password", "--format=plain", "--wal-method=stream", "--checkpoint=fast",
               "--manifest-checksums=SHA256", timeout=3600)
        pg.run("pg_verifybackup", work / "pg", timeout=3600)
        destination = repo.root / "bases" / name
        destination.mkdir(mode=0o700)
        shutil.copytree(work / "pg", destination / "pg")
        for p in regular_files(destination / "pg"):
            with p.open("rb") as f:
                os.fsync(f.fileno())
        for directory in sorted((p for p in destination.rglob("*") if p.is_dir()), reverse=True):
            sync_dir(directory)
        manifest = json.loads((destination / "pg/backup_manifest").read_text())
        first_lsn = manifest["WAL-Ranges"][0]["Start-LSN"]
        if not re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", first_lsn):
            raise BackupError("INVALID_BASE_WAL_RANGE")
        record = info | {"id": name, "release": release, "revisions": pg.revisions(),
                         "created_at": datetime.now(UTC).isoformat(),
                         "start_wal": pg.sql(f"SELECT pg_walfile_name('{first_lsn}'::pg_lsn)"),
                         "wal_segment_bytes": int(pg.sql("SELECT pg_size_bytes(current_setting('wal_segment_size'))")),
                         "manifest_sha256": digest(destination / "pg/backup_manifest")}
        save_json(destination / "base.json", record)
        sync_dir(destination)
        sync_dir(destination.parent)
        # Staging retained intentionally; no automatic deletion of database-like trees.
        return record


def checkpoint(repo, pg, base_id, roots, release, *, timeout=60):
    """Call only after producers/ALL workers stopped, including cleanup; no live file snapshot."""
    with repo.lock():
        if not re.fullmatch(r"[0-9a-f]{32}", base_id):
            raise BackupError("INVALID_BASE")
        base = json.loads((repo.root / "bases" / base_id / "base.json").read_text())
        info = pg.info()
        if any(base[k] != info[k] for k in ("system_id", "timeline", "major")):
            raise BackupError("BASE_PRIMARY_MISMATCH")
        if base["release"] != release or base["revisions"] != pg.revisions():
            raise BackupError("RELEASE_MISMATCH")
        if pg.sql("""SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
            AND pid<>pg_backend_pid() AND backend_type='client backend'""") != "0":
            raise BackupError("OTHER_DATABASE_CLIENTS")
        before = pg.fingerprints()
        invariant = reconcile(pg)
        files = repo.snapshot(roots)
        if pg.fingerprints() != before:
            raise BackupError("DATABASE_CHANGED_DURING_CHECKPOINT")
        verify_files(pg, roots)
        target = pg.sql("SELECT clock_timestamp()::text")
        # Force a COMMIT strictly after target so recovery_target_time can stop definitively.
        pg.sql("SELECT pg_logical_emit_message(true,'wms-backup','checkpoint-boundary')")
        name = pg.sql("SELECT pg_walfile_name(pg_switch_wal())")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                repo.wal_path(name)
                break
            except (OSError, BackupError):
                time.sleep(0.1)
        else:
            raise BackupError("ARCHIVE_TIMEOUT")
        # Pin every segment in this base→checkpoint chain; never omit a gap or require old unrelated chains.
        per_log = 2**32 // base["wal_segment_bytes"]
        def index(value):
            return int(value[8:16], 16) * per_log + int(value[16:], 16)
        first, last = index(base["start_wal"]), index(name)
        if first > last or name[:8] != base["start_wal"][:8]:
            raise BackupError("INVALID_WAL_CHAIN")
        names = [f"{info['timeline']:08X}{i // per_log:08X}{i % per_log:08X}" for i in range(first, last + 1)]
        names += [p.name for p in repo.wal.glob("*.history")]
        wal = {n: digest(repo.wal_path(n)) for n in names}
        record = info | {"id": uuid4().hex, "base": base_id, "release": release, "target_time": target,
                         "created_at": datetime.now(UTC).isoformat(), "files": files, "wal": wal,
                         "fingerprints": before, "invariants": invariant, "revisions": pg.revisions()}
        path = repo.root / "checkpoints" / (record["id"] + ".json")
        save_json(path, record)
        publish(path.with_suffix(".sha256"), (digest(path) + "\n").encode())
        return record


def verify_files(pg, roots):
    rows = json.loads(pg.sql("""SELECT coalesce(json_agg(json_build_object('key',f.storage_key,
        'sha256',f.sha256,'size',f.size_bytes,'root', CASE
          WHEN EXISTS (SELECT 1 FROM wms.print_job p WHERE p.file_id=f.id) THEN 'print'
          WHEN EXISTS (SELECT 1 FROM wms.export_job e WHERE e.file_id=f.id) THEN 'export'
          ELSE 'import' END)), '[]') FROM wms.stored_file f
        LEFT JOIN wms.import_file i ON i.file_id=f.id WHERE coalesce(i.ready,true)"""))
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{64}", row["key"]):
            raise BackupError("INVALID_STORAGE_KEY")
        matches = [Path(roots[row["root"]]) / row["key"]]
        if not any(p.is_file() and not p.is_symlink() and p.stat().st_size == row["size"]
                   and digest(p) == row["sha256"] for p in matches):
            raise BackupError("REFERENCED_FILE_MISSING_OR_CORRUPT")
    return len(rows)


def restore_prepare(repo, checkpoint_id, destination, pg, *, target_time):
    """Materialize an isolated NEW tree; never start/promote or replace a live cluster."""
    record = repo.verify_checkpoint(checkpoint_id)
    if target_time != record["target_time"]:
        raise BackupError("TARGET_NOT_APP_CONSISTENT_CHECKPOINT")
    destination = Path(destination).absolute()
    if (destination.exists() or destination.is_symlink() or destination.parent.resolve() != destination.parent
            or destination.is_relative_to(repo.root) or repo.root.is_relative_to(destination)):
        raise BackupError("RESTORE_REQUIRES_NEW_ISOLATED_DIRECTORY")
    base = repo.root / "bases" / record["base"]
    metadata = json.loads((base / "base.json").read_text())
    if (metadata["system_id"] != record["system_id"] or metadata["timeline"] != record["timeline"]
            or metadata["release"] != record["release"]
            or digest(base / "pg/backup_manifest") != metadata["manifest_sha256"]):
        raise BackupError("BASE_METADATA_MISMATCH")
    # Verify before making a runnable directory. Missing/corrupt files must fail closed.
    pg.run("pg_verifybackup", base / "pg", timeout=3600)
    size = (sum(p.stat().st_size for p in regular_files(base / "pg"))
            + sum(v["size"] for v in record["files"].values())
            + sum(repo.wal_path(n).stat().st_size for n in record["wal"]))
    if shutil.disk_usage(destination.parent).free < size + 64 * 1024**2 or size > repo.limit:
        raise BackupError("RESTORE_CAPACITY")
    destination.mkdir(mode=0o700)
    shutil.copytree(base / "pg", destination / "pg")
    for relative, item in record["files"].items():
        path = destination / "files" / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        copy_verified(repo.root / "objects" / item["sha256"], path, item["sha256"])
    for root in ("import", "export", "print", "config", "release"):
        (destination / "files" / root).mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = destination / "archive"
    archive.mkdir(mode=0o700)
    identity = uuid4().hex
    publish(archive / ".repository-id", (identity + "\n").encode())
    local_repo = Repository(archive, identity, require_mount=False, max_bytes=repo.limit)
    for name, sha in record["wal"].items():
        copy_verified(repo.wal_path(name), archive / "wal" / name, sha)
        publish(archive / "wal" / (name + ".sha256"), (sha + "\n").encode())
    # Never copy an upstream auto.conf, restore_command, archive_command or preloaded code into execution.
    (destination / "pg/postgresql.auto.conf").write_text("")
    (destination / "pg/standby.signal").unlink(missing_ok=True)
    # Archive segment retrieval verifies content on each request. No credentials in argv.
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), "fetch-wal", "--repository",
                          str(local_repo.root), "--repository-id", identity,
                          "--name", "%f", "--destination", "%p", "--local"])
    config = "\n".join([
        "listen_addresses = ''", "archive_mode = off", "shared_preload_libraries = ''",
        "session_preload_libraries = ''", "local_preload_libraries = ''", "external_pid_file = ''",
        "hba_file = '" + str(destination / "pg_hba.conf").replace("'", "''") + "'",
        "ident_file = '" + str(destination / "pg_ident.conf").replace("'", "''") + "'",
        "ssl = off", "hot_standby = on", "restore_command = '" + command.replace("'", "''") + "'",
        "recovery_target_time = '" + target_time.replace("'", "''") + "'",
        "recovery_target_inclusive = true", "recovery_target_action = 'pause'",
        f"recovery_target_timeline = '{record['timeline']}'", "unix_socket_permissions = 0700", "",
    ])
    (destination / "postgresql.conf").write_text(config)
    (destination / "pg_hba.conf").write_text("local all all trust\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n")
    (destination / "pg_ident.conf").write_text("")
    (destination / "pg/recovery.signal").touch(mode=0o600)
    save_json(destination / "checkpoint.json", record)
    return record


def restore_check(pg, restored):
    record = json.loads((Path(restored) / "checkpoint.json").read_text())
    if pg.sql("SELECT pg_is_in_recovery() AND pg_is_wal_replay_paused()") != "t":
        raise BackupError("PITR_NOT_PAUSED_AT_TARGET")
    if pg.revisions() != record["revisions"] or pg.fingerprints() != record["fingerprints"]:
        raise BackupError("RESTORE_DATABASE_MISMATCH")
    reconcile(pg)
    roots = {k: Path(restored) / "files" / k for k in ("import", "export", "print")}
    return {"files": verify_files(pg, roots), "tables": len(record["fingerprints"]), "ready_for_review": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("archive", "fetch-wal", "verify", "retention-plan"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--wal-repository", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--checkpoint")
    parser.add_argument("--local", action="store_true", help="Disposable local directory, not target acceptance")
    parser.add_argument("--max-bytes", type=int, default=2 * 1024**3)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        repo = Repository(args.repository, args.repository_id, max_bytes=args.max_bytes,
                          require_mount=not args.local, wal_repository=args.wal_repository)
        if args.action == "archive":
            repo.archive(args.source, args.name)
        elif args.action == "fetch-wal":
            # PostgreSQL owns the destination, including a possibly preallocated temporary file.
            source = repo.wal_path(args.name)
            if args.destination.is_symlink():
                raise BackupError("UNSAFE_WAL_DESTINATION")
            with source.open("rb") as src, args.destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
        elif args.action == "verify":
            repo.verify_checkpoint(args.checkpoint)
        else:
            # No deletion: every published checkpoint pins its base, WAL and file objects.
            points = [repo.verify_checkpoint(p.stem) for p in (repo.root / "checkpoints").glob("*.json")]
            print(json.dumps({"checkpoints": len(points), "automatic_delete": False,
                              "pinned_bases": sorted({r["base"] for r in points})}))
        return 0
    except Exception:
        print('{"event":"backup_failed","code":"BACKUP_CHECK_FAILED"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
