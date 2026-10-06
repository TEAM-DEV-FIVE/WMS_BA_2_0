"""Explicit target-component suite: requires WMS_TEST_NGINX_BINARY or installed nginx.

Run with check_application.py --test-path deploy/lan/tests; never silently skip.
"""

import ipaddress
import os
import shutil
import signal
import socket
import ssl
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import text

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from scripts.lan_probe import probe

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def certificate(path, name, *, ca=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    issuer, signing = (ca[0].subject, ca[1]) if ca else (subject, key)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(datetime.now(UTC)-timedelta(minutes=1))
               .not_valid_after(datetime.now(UTC)+timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=ca is None, path_length=None), critical=True))
    if ca:
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
    cert = builder.sign(signing, hashes.SHA256())
    cert_path, key_path = path / (name + ".pem"), path / (name + ".key")
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_path.chmod(0o600)
    return cert, key, cert_path, key_path


@pytest.fixture
def proxy(iam, tmp_path):
    binary = os.environ.get("WMS_TEST_NGINX_BINARY") or shutil.which("nginx")
    assert binary, "Install nginx or set WMS_TEST_NGINX_BINARY; this explicit suite cannot skip it"
    ca = certificate(tmp_path, "ca")
    server_cert = certificate(tmp_path, "server", ca=ca)
    wrong_ca = certificate(tmp_path, "untrusted-ca")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    api_port = sock.getsockname()[1]
    with socket.socket() as pick:
        pick.bind(("127.0.0.1", 0))
        port = pick.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    process = None
    log = (tmp_path / "nginx-process.log").open("w+")
    maintenance = tmp_path / "maintenance"
    template = (ROOT / "deploy/lan/nginx/wms.conf.example").read_text()
    template = (template.replace("listen 443 ssl", f"listen 127.0.0.1:{port} ssl")
                .replace("    listen [::]:443 ssl default_server;", "")
                .replace("wms.example.internal", "localhost")
                .replace("/etc/wms/tls/server-chain.pem", str(server_cert[2]))
                .replace("/etc/wms/tls/server-key.pem", str(server_cert[3]))
                .replace("/var/log/nginx/wms-access.log", str(tmp_path / "access.log"))
                .replace("127.0.0.1:8000", f"127.0.0.1:{api_port}")
                .replace("/etc/wms/maintenance.on", str(maintenance)))
    config = tmp_path / "nginx.conf"
    config.write_text(f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/startup.log;\n"
                      f"events {{}}\nhttp {{ client_body_temp_path {tmp_path}/body;\n"
                      f"proxy_temp_path {tmp_path}/proxy; fastcgi_temp_path {tmp_path}/fastcgi;\n"
                      f"uwsgi_temp_path {tmp_path}/uwsgi; scgi_temp_path {tmp_path}/scgi;\n{template}\n}}\n")
    try:
        subprocess.run([binary, "-t", "-p", str(tmp_path), "-c", str(config)], check=True,
                       stdout=log, stderr=log)
        process = subprocess.Popen([binary, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"],
                                   stdout=log, stderr=log)
        url = f"https://localhost:{port}/api/v1"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if server.started and probe(url, str(ca[2]))["schema"] == "ready":
                    break
            except Exception:
                time.sleep(0.05)
        else:
            raise AssertionError("TLS proxy/API failed to start")
        yield dict(iam=iam, url=url, ca=ca[2], wrong_ca=wrong_ca[2], path=tmp_path,
                   maintenance=maintenance, server=server)
    finally:
        if process:
            process.send_signal(signal.SIGQUIT)
            process.wait(timeout=15)
        log.close()
        server.should_exit = True
        thread.join(15)
        sock.close()
        assert not thread.is_alive()


def test_tls_trust_hostname_maintenance_and_upstream_failure(proxy):
    p = proxy
    assert probe(p["url"], str(p["ca"]))["tls"] == "verified"
    with pytest.raises(Exception):
        probe(p["url"], str(p["wrong_ca"]))
    context = ssl.create_default_context(cafile=str(p["ca"]))
    port = int(p["url"].split(":")[2].split("/")[0])
    with socket.create_connection(("127.0.0.1", port)) as sock, pytest.raises(ssl.SSLCertVerificationError):
        context.wrap_socket(sock, server_hostname="wrong-host.invalid")
    with httpx.Client(verify=context, trust_env=False) as client:
        p["maintenance"].touch()
        assert client.get(p["url"] + "/health").status_code == 503
        p["maintenance"].unlink()
        assert client.get(p["url"] + "/health").status_code == 200
        p["server"].should_exit = True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if client.get(p["url"] + "/ready").status_code == 503:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Upstream failure must become 503")


def test_real_desktop_recovery_permissions_and_no_proxy_secret_logs(proxy):
    p, key = proxy, uuid4()
    iam = p["iam"]
    user, _ = iam.user("lan-operator")
    grant = iam.grant(user, "MASTER_DATA")
    api = IdentityClient(DesktopSettings(api_url=p["url"], ca_file=p["ca"],
                                         local_data_dir=p["path"] / "client"))
    body = {"code": "LAN", "name": "Cái", "decimal_places": 0, "reason": "LAN probe"}
    try:
        api.enable_recovery()
        tokens = api.login("lan-operator", "Test-only-password-2026!")
        api.me()
        result = api.command("POST", "master/uoms", body, key)
        assert result["code"] == "LAN"
        assert api.command("POST", "master/uoms", body, key) == result
        with iam.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.uom WHERE code='LAN'")).scalar_one() == 1
        with iam.engine.begin() as c:
            c.execute(text("DELETE FROM wms.user_role_grant WHERE id=:id"), {"id": grant})
        from apps.desktop.api.client import ApiError

        with pytest.raises(ApiError):
            api.command("POST", "master/uoms", body, key)
        context = ssl.create_default_context(cafile=str(p["ca"]))
        with httpx.Client(verify=context, trust_env=False) as client:
            assert client.get(p["url"] + "/health?token=proxy-secret-sentinel",
                              headers={"Authorization": "Bearer header-secret-sentinel"}).status_code == 200
        logs = "\n".join(f.read_text() for f in p["path"].glob("*.log"))
        for secret in ("proxy-secret-sentinel", "header-secret-sentinel", "Test-only-password-2026!"):
            assert secret not in logs
        assert tokens is not None
    finally:
        api.close()
