import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import backup_admin as admin
from scripts.wms_backup import BackupError, digest, verify_files


def test_file_reference_cannot_be_satisfied_by_wrong_storage_root(tmp_path):
    roots = {k: tmp_path / k for k in ("import", "export", "print")}
    for p in roots.values():
        p.mkdir()
    key = "a" * 64
    wrong = roots["export"] / key
    wrong.write_bytes(b"pdf")
    sha = digest(wrong)
    pg = SimpleNamespace(sql=lambda _: json.dumps([
        {"root": "print", "key": key, "size": 3, "sha256": sha}]))
    with pytest.raises(BackupError, match="REFERENCED_FILE"):
        verify_files(pg, roots)
    wrong.rename(roots["print"] / key)
    assert verify_files(pg, roots) == 1


@pytest.mark.parametrize("fault", ["none", "stale_checkpoint", "stale_base", "archive_failure", "wrong_primary"])
def test_monitor_rejects_stale_or_wrong_chain(tmp_path, fault):
    now = datetime.now(UTC)
    points, bases = tmp_path / "checkpoints", tmp_path / "bases/base"
    points.mkdir()
    bases.mkdir(parents=True)
    (points / "point.json").write_text("{}")
    identity = {"system_id": "test", "timeline": 1, "major": 16}
    point = identity | {"base": "base", "target_time": (now - timedelta(
        seconds=3000 if fault == "stale_checkpoint" else 60)).isoformat()}
    (bases / "base.json").write_text(json.dumps(identity | {"created_at": (now - timedelta(
        days=2 if fault == "stale_base" else 0)).isoformat()}))
    repo = SimpleNamespace(root=tmp_path, capacity=lambda: None, verify_checkpoint=lambda _: point)
    pg = SimpleNamespace(info=lambda: identity | ({"system_id": "other"} if fault == "wrong_primary" else {}),
                         sql=lambda _: "t" if fault == "archive_failure" else "f")
    if fault == "none":
        assert admin.monitor(repo, pg)["checkpoint_age_seconds"] >= 60
    else:
        with pytest.raises(admin.BackupError):
            admin.monitor(repo, pg)


@pytest.mark.parametrize("restart_ok", [True, False])
def test_failed_checkpoint_resumes_services_or_preserves_maintenance(tmp_path, monkeypatch, restart_ok):
    marker = tmp_path / "maintenance.on"
    monkeypatch.setattr(admin, "MAINTENANCE", marker)
    calls = []
    def systemctl(*args):
        calls.append(args)
        return SimpleNamespace(returncode=int(args == ("start", "wms.target") and not restart_ok), stdout="")
    monkeypatch.setattr(admin, "systemctl", systemctl)
    monkeypatch.setattr(admin, "assert_stopped", lambda: None)
    monkeypatch.setattr(admin, "newest_base", lambda _: "base")
    def fail(*args):
        assert marker.exists()
        raise admin.BackupError("CHECKPOINT_FAILED")
    monkeypatch.setattr(admin, "checkpoint", fail)
    with pytest.raises(admin.BackupError):
        admin.cycle(None, None, {"release": "test"}, {})
    assert ("stop", "wms.target") in calls
    assert ("start", "wms.target") in calls
    assert marker.exists() is not restart_ok


def test_existing_maintenance_is_never_removed(tmp_path, monkeypatch):
    marker = tmp_path / "maintenance.on"
    marker.touch()
    monkeypatch.setattr(admin, "MAINTENANCE", marker)
    def forbidden(*args):
        pytest.fail("Existing maintenance must not start or stop services")
    monkeypatch.setattr(admin, "systemctl", forbidden)
    with pytest.raises(admin.BackupError):
        admin.cycle(None, None, {}, {})
    assert marker.exists()
