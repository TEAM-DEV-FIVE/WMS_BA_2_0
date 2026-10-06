import os
import subprocess
from contextlib import closing

import pypdfium2 as pdfium
import pytest
import zxingcpp
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID

from apps.server.application.print_render import render
from apps.server.application.printing import PrintSettings
from scripts.create_test_certificates import create
from scripts.preview_print_templates import ISSUER, preview, samples


@pytest.mark.parametrize("name,snapshot", list(samples()))
def test_branded_production_pdf_and_readable_barcodes(name, snapshot):
    data = render(snapshot)
    assert data == render(snapshot)
    with pdfium.PdfDocument(data) as document:
        assert len(document) == 1
        with closing(document[0]) as page:
            with closing(page.get_textpage()) as textpage:
                text = textpage.get_text_range()
            assert ISSUER["name"] in text and ISSUER["address"] in text
            assert "MAU-" in text
            assert ISSUER["phone"] in text
            if not snapshot["template"].endswith("LABEL"):
                assert ISSUER["tax_code"] in text and ISSUER["signer"] in text
            if snapshot["template"].endswith("LABEL"):
                bitmap = page.render(scale=300 / 72)
                try:
                    assert [code.text for code in zxingcpp.read_barcodes(bitmap.to_pil())] == [
                        snapshot["header"]["barcode"]
                    ]
                finally:
                    bitmap.close()
            if snapshot["template"] == "COUNT":
                assert "Số đếm" in text and "SL yêu cầu" not in text and "Đã ghi sổ" not in text
            assert "Giá tham chiếu" not in text


def test_catalog_preserves_native_paper_sizes(tmp_path):
    path = tmp_path / "catalog.pdf"
    manifest = preview(path, tmp_path / "native")
    assert len(manifest) == 12
    with pdfium.PdfDocument(path) as document:
        assert len(document) == 13
        with closing(document[len(document) - 1]) as page:
            assert page.get_size() == pytest.approx((80 * 72 / 25.4, 40 * 72 / 25.4), abs=0.01)


@pytest.mark.parametrize("value", ["Bad\nHeader", "x" * 81])
def test_reject_unsafe_or_unbounded_issuer(value):
    with pytest.raises(ValueError):
        PrintSettings(issuer_name=value)


def test_test_pki_crypto_permissions_and_openssl_trust(tmp_path):
    path = tmp_path / "private"
    if os.name != "posix":
        with pytest.raises(ValueError, match="Generate on Linux"):
            create(path)
        assert not path.exists()
        return
    manifest = create(path)
    assert path.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in path.iterdir())
    assert not (path / "ca.key").exists()
    password = (path / "pfx-password.txt").read_bytes().strip()
    data = (path / "windows-test-signing.pfx").read_bytes()
    signing_key, signer, chain = pkcs12.load_key_and_certificates(data, password)
    assert signing_key.public_key() == signer.public_key() and not chain
    assert signer.fingerprint(hashes.SHA1()).hex().upper() == manifest["windows_thumbprint_sha1"]
    assert list(signer.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == [
        ExtendedKeyUsageOID.CODE_SIGNING
    ]
    assert not signer.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    with pytest.raises(ValueError):
        pkcs12.load_key_and_certificates(data, b"wrong-password")
    for option, host, expected in (("-verify_hostname", "wms.test", 0),
                                   ("-verify_ip", "127.0.0.1", 0),
                                   ("-verify_hostname", "wrong.example", 2)):
        result = subprocess.run(["openssl", "verify", "-CAfile", str(path / "tls-ca.pem"),
                                 "-purpose", "sslserver", option, host, str(path / "tls-server.pem")],
                                capture_output=True)
        assert result.returncode == expected, result.stderr.decode()
    result = subprocess.run(["openssl", "verify", "-CAfile", str(path / "tls-ca.pem"),
                             "-purpose", "sslclient", str(path / "tls-server.pem")], capture_output=True)
    assert result.returncode != 0
    with pytest.raises(FileExistsError):
        create(path)


def test_pki_rejects_symlink_and_invalid_scope(tmp_path):
    if os.name != "posix":
        with pytest.raises(ValueError, match="Generate on Linux"):
            create(tmp_path / "new")
        return
    target = tmp_path / "other"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        create(link)
    for values in ({"dns_names": ["*.example.com"]}, {"days": 365}, {"ips": ["not-an-ip"]}):
        with pytest.raises(ValueError):
            create(tmp_path / "new", **values)
        assert not (tmp_path / "new").exists()
    assert not list(target.iterdir())
