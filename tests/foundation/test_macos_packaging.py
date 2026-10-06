import json
import subprocess
import sys

import pytest

from apps.desktop import macos_bundle
from apps.desktop.startup import settings_for_startup


def app(tmp_path, monkeypatch):
    bundle = tmp_path / "WMS.app"
    executable = bundle / "Contents/MacOS/WMS"
    executable.parent.mkdir(parents=True)
    executable.touch()
    resources = bundle / "Contents/Resources"
    resources.mkdir()
    (resources / "release.json").write_text(json.dumps(
        dict(version="0.1.0", platform="macos-arm64", signing="adhoc-test-only")))
    monkeypatch.setattr(sys, "executable", str(executable))
    return bundle


def test_macos_signature_failure_blocks_bundle(tmp_path, monkeypatch):
    app(tmp_path, monkeypatch)

    def reject(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "codesign")

    monkeypatch.setattr(macos_bundle.subprocess, "run", reject)
    with pytest.raises(subprocess.CalledProcessError):
        macos_bundle.verify_bundle()


def test_macos_cache_forbidden_in_resources_not_only_executable_directory(tmp_path, monkeypatch):
    bundle = app(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("WMS_LOCAL_DATA_DIR", str(bundle / "Contents/Resources/data"))
    with pytest.raises(ValueError, match="ngoài thư mục cài đặt"):
        settings_for_startup()


def test_macos_rejects_non_bundle_path():
    with pytest.raises(ValueError, match="bundle"):
        macos_bundle.bundle_root("/tmp/unpacked/WMS")
