import json
from uuid import uuid4

import pytest

from scripts.wms_backup import BackupError, Repository, copy_verified, main, publish


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    identity = uuid4().hex
    (root / ".repository-id").write_text(identity)
    return Repository(root, identity, require_mount=False)


def test_archive_is_durable_idempotent_and_rejects_overwrite(repo, tmp_path):
    source = tmp_path / "segment"
    source.write_bytes(b"original WAL fixture")
    name = "000000010000000000000001"
    repo.archive(source, name)
    repo.archive(source, name)
    assert repo.wal_path(name).read_bytes() == source.read_bytes()
    assert repo.wal_path(name).stat().st_mode & 0o077 == 0
    source.write_bytes(b"changed WAL")
    with pytest.raises(BackupError, match="IMMUTABLE_COLLISION"):
        repo.archive(source, name)
    assert repo.wal_path(name).read_bytes() == b"original WAL fixture"


@pytest.mark.parametrize("name", ["../bad", "/tmp/bad", "0000;rm", "x.history", "000000010000000000000001.partial"])
def test_archive_refuses_invalid_names(repo, tmp_path, name):
    with pytest.raises(BackupError):
        repo.archive(tmp_path / "absent", name)


@pytest.mark.parametrize("fault", ["missing", "corrupt", "symlink"])
def test_wal_corruption_never_returned_as_success(repo, tmp_path, fault):
    source = tmp_path / "segment"
    source.write_bytes(b"wal")
    name = "000000010000000000000001"
    repo.archive(source, name)
    wal = repo.wal / name
    if fault == "corrupt":
        wal.write_bytes(b"bad")
    else:
        wal.unlink()
        if fault == "symlink":
            wal.symlink_to(source)
    with pytest.raises((BackupError, OSError)):
        repo.wal_path(name)


def test_wrong_repository_mount_permissions_and_identity(tmp_path):
    path = tmp_path / "backup"
    path.mkdir(mode=0o700)
    (path / ".repository-id").write_text("expected")
    with pytest.raises(BackupError):
        Repository(path, "expected")  # Not a dedicated mount; no fallback to root filesystem.
    with pytest.raises(BackupError):
        Repository(path, "wrong", require_mount=False)
    path.chmod(0o755)
    with pytest.raises(BackupError):
        Repository(path, "expected", require_mount=False)


def test_quota_and_locks_fail_closed(repo, tmp_path):
    source = tmp_path / "large"
    source.write_bytes(b"x" * 100)
    repo.limit = 10
    with pytest.raises(BackupError, match="CAPACITY"):
        repo.object(source)
    with repo.lock(), pytest.raises(BlockingIOError), repo.lock():
        pass


def test_snapshot_deduplicates_and_refuses_symlinks(repo, tmp_path):
    root = tmp_path / "files"
    root.mkdir(mode=0o700)
    (root / "a").write_bytes(b"private content")
    (root / "b").write_bytes(b"private content")
    entries = repo.snapshot({"config": root})
    assert entries["config/a"]["sha256"] == entries["config/b"]["sha256"]
    assert len(list((repo.root / "objects").iterdir())) == 1
    (root / "link").symlink_to(root / "a")
    with pytest.raises(BackupError):
        repo.snapshot({"config": root})


def test_manifest_and_error_output_not_secret(repo, tmp_path, capsys):
    source = tmp_path / "s"
    source.write_text("never-log-mfa-secret")
    copy_verified(source, repo.root / "objects/test")
    rc = main(["archive", "--repository", str(repo.root), "--repository-id", "bad",
               "--source", str(source), "--name", "invalid", "--local"])
    assert rc == 1
    output = capsys.readouterr()
    assert "never-log" not in output.out + output.err


def test_publish_collision_cannot_change_catalog(tmp_path):
    path = tmp_path / "catalog"
    publish(path, b"old")
    with pytest.raises(BackupError):
        publish(path, b"new")
    assert path.read_bytes() == b"old"


def test_retention_has_no_delete_path(repo, capsys):
    identity = (repo.root / ".repository-id").read_text()
    before = sorted(str(p) for p in repo.root.rglob("*"))
    assert main(["retention-plan", "--repository", str(repo.root), "--repository-id", identity, "--local"]) == 0
    assert json.loads(capsys.readouterr().out)["automatic_delete"] is False
    assert sorted(str(p) for p in repo.root.rglob("*")) == before


def test_copy_does_not_follow_destination_symlink(tmp_path):
    source, other, link = [tmp_path / n for n in ("source", "other", "link")]
    source.write_bytes(b"same")
    other.write_bytes(b"same")
    link.symlink_to(other)
    with pytest.raises(BackupError):
        copy_verified(source, link)
    assert other.read_bytes() == b"same"
