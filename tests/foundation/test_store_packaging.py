"""MSIX input integrity tests; Windows SDK/Store certification are separate gates."""

import struct
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from apps.desktop.bundle import sha256, write_manifest
from scripts.store_package import NS, TEST_IDENTITY, manifest, stage, validate_identity


@pytest.fixture
def store_input(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    pe = b"MZ" + b"\0" * 58 + struct.pack("<I", 64) + b"PE\0\0\x64\x86"
    for name in ("WMS.exe", "WMSHelper.exe"):
        (bundle / name).write_bytes(pe)
    (bundle / "payload.txt").write_text("Dữ liệu tiếng Việt", encoding="utf-8")
    write_manifest(bundle, commit="a" * 40, lock_hash="b" * 64, signing="unsigned")
    return bundle


def test_stage_preserves_payload_and_declares_external_cache(store_input, tmp_path):
    before = {p.name: sha256(p) for p in store_input.iterdir()}
    output = tmp_path / "staged"
    report = stage(store_input, output, TEST_IDENTITY, "1.0.0.0", test_only=True)
    assert report["status"] == "TEST_PACKAGE_ONLY"
    assert report["store_signed"] is report["store_certified"] is False
    assert {p.name: sha256(p) for p in (output / "App").iterdir()} == before
    root = ET.parse(output / "AppxManifest.xml").getroot()
    assert root.find(f"{{{NS['']}}}Properties/{{{NS['desktop6']}}}FileSystemWriteVirtualization").text == "disabled"
    caps = root.find(f"{{{NS['']}}}Capabilities")
    assert {p.attrib["Name"] for p in caps} == {"runFullTrust", "unvirtualizedResources"}
    for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
        with Image.open(output / "Assets" / (name + ".png")) as image:
            assert image.size == (size, size) and image.mode == "RGBA"


def test_stage_rejects_tampered_payload_before_creating_output(store_input, tmp_path):
    (store_input / "WMS.exe").write_bytes(b"tampered")
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match="checksum"):
        stage(store_input, output, TEST_IDENTITY, "1.0.0.0", test_only=True)
    assert not output.exists()


def test_stage_rejects_unmanifested_sensitive_file(store_input, tmp_path):
    (store_input / "secret.pfx").write_bytes(b"not a real key")
    with pytest.raises(ValueError, match="unmanifested"):
        stage(store_input, tmp_path / "staged", TEST_IDENTITY, "1.0.0.0", test_only=True)


def test_stage_does_not_overwrite_existing_directory(store_input, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(ValueError, match="new staging"):
        stage(store_input, output, TEST_IDENTITY, "1.0.0.0", test_only=True)
    assert marker.read_text() == "preserve"


def test_real_identity_roundtrips_xml_special_characters():
    identity = dict(name="12345.WMS", publisher="CN=Owner & Publisher", publisher_display_name="Kho & Thiết bị")
    validate_identity(identity, "1.0.0.0")
    root = ET.fromstring(manifest(identity, "1.0.0.0"))
    assert root.find(f"{{{NS['']}}}Identity").attrib["Publisher"] == identity["publisher"]
    assert root.find(f"{{{NS['']}}}Properties/{{{NS['']}}}PublisherDisplayName").text == identity["publisher_display_name"]


@pytest.mark.parametrize("version", ["0.1.0.0", "1.0.0", "1.0.0.1", "65536.0.0.0", "1.-1.0.0"])
def test_invalid_store_version_is_rejected(version):
    with pytest.raises(ValueError, match="version"):
        validate_identity(TEST_IDENTITY, version, test_only=True)


def test_test_identity_cannot_silently_become_submission():
    with pytest.raises(ValueError, match="Placeholder/test"):
        validate_identity(TEST_IDENTITY, "1.0.0.0")


@pytest.mark.parametrize("name", ["../escape", "bad/name", "ab", "x" * 51])
def test_invalid_identity_name_is_rejected(name):
    with pytest.raises(ValueError, match="identity name"):
        validate_identity(dict(TEST_IDENTITY, name=name), "1.0.0.0", test_only=True)
