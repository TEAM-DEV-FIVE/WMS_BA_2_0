"""Linux-only, short-lived TLS and Windows code-signing certificates for an isolated lab.

Never installs trust, signs a release, or uses the production certificate store.
Private output must not be uploaded to CI artifacts, Git, chat or issue attachments.
"""

import argparse
import ipaddress
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def name(common_name):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def certificate(subject, public_key, issuer, signing_key, now, days, *, ca=False, eku=None, sans=None):
    builder = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(public_key)
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=not ca, content_commitment=False,
                                    key_encipherment=eku == ExtendedKeyUsageOID.SERVER_AUTH,
                                    data_encipherment=False, key_agreement=False, key_cert_sign=ca,
                                    crl_sign=ca, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_key.public_key()), critical=False)
    )
    if eku:
        builder = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return builder.sign(signing_key, hashes.SHA256())


def create(output: Path, dns_names=("localhost", "wms.test"), ips=("127.0.0.1",), days=30):
    if os.name != "posix":
        raise ValueError("Generate on Linux; Windows ACL handling is not implemented by this tool.")
    if not 1 <= days <= 30:
        raise ValueError("Test certificates must expire within 1..30 days.")
    sans = []
    for dns in dict.fromkeys(dns_names):
        if len(dns) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                                for part in dns.split(".")):
            raise ValueError("Use explicit ASCII DNS names (no URLs or wildcards).")
        sans.append(x509.DNSName(dns))
    sans.extend(x509.IPAddress(ipaddress.ip_address(ip)) for ip in dict.fromkeys(ips))
    if not sans:
        raise ValueError("At least one DNS name or IP is required.")
    # mkdir(exist_ok=False) rejects an existing directory and symlinks. The caller's
    # private directory protects every file from creation, independently of umask.
    output.mkdir(mode=0o700)
    now = datetime.now(UTC)
    ca_key, tls_key, signing_key = key(), key(), key()
    ca_name, signer_name = name("WMS LAB TEST CA - NOT FOR PRODUCTION"), name("InternTechLead TEST ONLY")
    ca = certificate(ca_name, ca_key.public_key(), ca_name, ca_key, now, days, ca=True)
    tls = certificate(name("WMS LAB HTTPS"), tls_key.public_key(), ca_name, ca_key, now, days,
                      eku=ExtendedKeyUsageOID.SERVER_AUTH, sans=sans)
    signer = certificate(signer_name, signing_key.public_key(), signer_name, signing_key, now, days,
                         eku=ExtendedKeyUsageOID.CODE_SIGNING)
    password = secrets.token_urlsafe(32).encode("ascii")
    pem = serialization.Encoding.PEM
    contents = {
        "tls-ca.pem": ca.public_bytes(pem),
        "tls-server.pem": tls.public_bytes(pem),
        "tls-server.key": tls_key.private_bytes(pem, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()),
        "windows-test-signing.cer": signer.public_bytes(serialization.Encoding.DER),
        "windows-test-signing.pfx": pkcs12.serialize_key_and_certificates(
            b"InternTechLead TEST ONLY", signing_key, signer, None,
            serialization.BestAvailableEncryption(password)),
        "pfx-password.txt": password + b"\n",
    }
    # Discard the CA private key: this one-shot lab CA cannot be used to issue more certificates.
    manifest = {
        "test_only": True, "expires_utc": signer.not_valid_after_utc.isoformat(),
        "dns": list(dict.fromkeys(dns_names)), "ips": list(dict.fromkeys(ips)),
        "windows_thumbprint_sha1": signer.fingerprint(hashes.SHA1()).hex().upper(),
        "certificate_sha256": {label: cert.fingerprint(hashes.SHA256()).hex()
                               for label, cert in (("tls_ca", ca), ("tls_server", tls), ("windows_signer", signer))},
        "native_authenticode": "NOT_RUN", "macos_developer_id": "NOT_CREATED",
    }
    contents["public-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    for filename, data in contents.items():
        with (output / filename).open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local-test-pki"))
    parser.add_argument("--dns", action="append", help="Repeat for each exact test hostname.")
    parser.add_argument("--ip", action="append", help="Repeat for each test server IP.")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    manifest = create(args.output, args.dns or ("localhost", "wms.test"), args.ip or ("127.0.0.1",), args.days)
    print(f"Created private TEST ONLY bundle in {args.output}; expires {manifest['expires_utc']}.")
    print("No trust store changed. Native Authenticode and macOS signing remain NOT_RUN.")


if __name__ == "__main__":
    main()
