"""Release safety tests; native Windows installation remains a separate target gate."""
import json
import sqlite3
import struct
import sys
from uuid import uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import text
from test_recovery_all import BODY, live_recovery  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.bundle import safe_relative, sha256, verify_manifest, write_manifest
from apps.desktop.local_store.commands import CommandStore
from apps.desktop.local_store.device import device_identity
from apps.desktop.printing.spool import windows_command
from apps.desktop.startup import preflight_cache, settings_for_startup
from packages.contracts.compatibility import server_headers


@pytest.mark.parametrize('headers', [{}, {'X-WMS-API-Protocol': '2'}, {'X-WMS-API-Protocol': '1', 'X-WMS-Recovery-Protocol': 'lookup-v1'}])
def test_incompatible_server_never_receives_password(tmp_path, headers):
    requests = []
    def serve(request):
        requests.append(request)
        return httpx.Response(200, json={'status': 'ok', 'service': 'wms-api', 'version': '0.1.0'}, headers=headers)
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path, require_compatibility=True), transport=httpx.MockTransport(serve))
    try:
        with pytest.raises(ApiError) as error:
            api.login('user', 'never-transmit-password')
        assert error.value.code == 'INCOMPATIBLE_SERVER'
        assert [(r.method, r.url.path) for r in requests] == [('GET', '/api/v1/health')]
        assert all(b'never-transmit-password' not in p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    finally:
        api.close()


@pytest.mark.integration
def test_real_api_mfa_handshake_and_downgrade_preserve_pending(request, monkeypatch):
    f = request.getfixturevalue("live_recovery")
    user, secret = f.user('signed-client', mfa=True)
    f.grant(user, 'MASTER_DATA')
    settings = f.desktop_settings.model_copy(update={'require_compatibility': True})
    api = IdentityClient(settings)
    api.enable_recovery()
    key = uuid4()
    try:
        assert api.health().status == 'ok'
        assert api.health(readiness=True).status == 'ready'
        assert api.login('signed-client', 'Test-only-password-2026!') == 'MFA_REQUIRED'
        assert api.mfa(pyotp.TOTP(secret).at(f.now)) == 'AUTHENTICATED'
        api.me()
        api.draft_only = True
        with pytest.raises(ApiError) as error:
            api.command('POST', 'master/uoms', BODY, key)
        assert error.value.code == 'DRAFT_SAVED'
        api.draft_only = False
        # Real HTTP server now advertises a pre-B23 deployment during this session.
        monkeypatch.setattr('apps.server.api.app.server_headers', lambda: {})
        with pytest.raises(ApiError) as error:
            api.recover(key, retry=True)
        assert error.value.code == 'INCOMPATIBLE_SERVER'
        assert api._journal_call('checked', key)['envelope']['body'] == BODY
        with f.engine.connect() as c:
            assert c.execute(text('SELECT count(*) FROM wms.uom')).scalar_one() == 0
        monkeypatch.setattr('apps.server.api.app.server_headers', server_headers)
        result = api.recover(key, retry=True)
        assert api.recover(key) == result
        with f.engine.connect() as c:
            assert c.execute(text('SELECT count(*) FROM wms.uom')).scalar_one() == 1
        assert api._journal_call('checked', key)['state'] == 'COMMITTED'
    finally:
        api.close()


def test_startup_config_unicode_env_and_frozen_directory(tmp_path, monkeypatch):
    data = tmp_path / 'Dữ liệu'
    data.mkdir()
    monkeypatch.setenv('WMS_LOCAL_DATA_DIR', str(data))
    (data/'client.json').write_text(json.dumps({'api_url': 'https://wms.example/api/v1', 'ca_file': 'ca.pem'}))
    settings = settings_for_startup()
    assert settings.api_url == 'https://wms.example/api/v1'
    assert settings.ca_file == data/'ca.pem' and settings.require_compatibility
    monkeypatch.setenv('WMS_API_URL', 'https://other.example/api/v1')
    monkeypatch.setenv('WMS_REQUIRE_COMPATIBILITY', 'false')
    assert settings_for_startup().api_url == 'https://other.example/api/v1'
    assert settings_for_startup().require_compatibility
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(data/'WMS.exe'))
    with pytest.raises(ValueError, match='ngoài'):
        settings_for_startup()


@pytest.mark.parametrize('value', [{'password': 'secret'}, [], {'database_url': 'forbidden'}])
def test_startup_rejects_non_client_configuration(tmp_path, monkeypatch, value):
    monkeypatch.setenv('WMS_LOCAL_DATA_DIR', str(tmp_path))
    (tmp_path/'client.json').write_text(json.dumps(value))
    with pytest.raises(ValueError):
        settings_for_startup()


def test_preflight_preserves_sending_draft_device_then_restart_recovers(tmp_path):
    device = device_identity(tmp_path)
    args = dict(server_id='https://wms.example/api/v1', user_id=uuid4(), device_id=device)
    store = CommandStore(tmp_path/'commands', **args)
    key = uuid4()
    draft = store.save_draft('RECEIPT', {'name': 'Nháp tiếng Việt'})
    store.prepare_command('POST', 'master/uoms', BODY, key)
    store.command_transition(key, 'SENDING')
    path = store.path
    store.close()
    before = {p: sha256(p) for p in tmp_path.rglob('*.sqlite3')}
    preflight_cache(tmp_path)
    assert {p: sha256(p) for p in tmp_path.rglob('*.sqlite3')} == before
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT state FROM recovery_command').fetchone()[0] == 'SENDING'
    store = CommandStore(tmp_path/'commands', **args)
    try:
        assert store.checked(key)['state'] == 'UNKNOWN'
        assert 'Nháp tiếng Việt' in store.get_draft(draft)['payload']
        assert device_identity(tmp_path) == device
    finally:
        store.close()


@pytest.mark.parametrize('broken', [False, True])
def test_preflight_future_or_corrupt_cache_preserves_bytes(tmp_path, broken):
    path = tmp_path/'pending.sqlite3'
    if broken:
        path.write_bytes(b'corrupt but preserve me')
    else:
        with sqlite3.connect(path) as c:
            c.execute('PRAGMA user_version=4')
    before = path.read_bytes()
    with pytest.raises((ValueError, sqlite3.Error)):
        preflight_cache(tmp_path)
    assert path.read_bytes() == before


@pytest.fixture
def bundle(tmp_path):
    # A PE header fixture checks manifest validation; this is NOT a Windows build.
    data = b'MZ' + b'\0'*58 + struct.pack('<I',64) + b'PE\0\0\x64\x86'
    for name in ('WMS.exe', 'WMSHelper.exe'):
        (tmp_path/name).write_bytes(data)
    write_manifest(tmp_path, commit='a'*40, lock_hash='b'*64, signing='unsigned')
    return tmp_path


def test_manifest_tampering_is_rejected(bundle):
    assert verify_manifest(bundle)['signing'] == 'unsigned'
    (bundle/'WMS.exe').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        verify_manifest(bundle)


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'C:/foo', 'a\\b', 'a/../b', 'a//b', 'file.', 'dir /file'])
def test_manifest_rejects_windows_escape_paths(name):
    with pytest.raises(ValueError):
        safe_relative(name)


@pytest.mark.parametrize('name', ['secret.pfx', '.env', 'device.sqlite3', 'server/config.py'])
def test_manifest_excludes_secrets_and_server(bundle, name):
    path = bundle/name
    path.parent.mkdir(exist_ok=True)
    path.write_text('forbidden')
    with pytest.raises(ValueError, match='Forbidden'):
        write_manifest(bundle, commit='a'*40, lock_hash='b'*64, signing='unsigned')


def test_frozen_spool_calls_console_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path/'WMS.exe'))
    assert windows_command('Máy in', 'A4', 2) == [str(tmp_path/'WMSHelper.exe'), '--spool', 'Máy in', 'A4', '2']


@pytest.mark.gui
def test_source_release_resource_probe():
    from apps.desktop.windows_entry import installed_self_test
    result = installed_self_test()
    assert result['status'] == 'PASS' and result['frozen'] is False
