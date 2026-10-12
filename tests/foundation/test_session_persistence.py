import json
from uuid import uuid4

import httpx
import pyotp
import pytest
from sqlalchemy import text

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.local_store.session_vault import SessionVault
from apps.desktop.presenters.session import SessionPresenter


class MemoryVault:
    token = None

    def save(self, token):
        self.token = token

    def forget(self):
        self.token = None

    def take(self):
        token, self.token = self.token, None
        return token


@pytest.mark.integration
@pytest.mark.parametrize('ending', ['logout', 'expire', 'revoke', 'password_version'])
def test_close_restore_mfa_refresh_rotation_and_revocation(iam, tmp_path, ending):
    user, secret = iam.user('remembered', mfa=True)
    store = MemoryVault()
    settings = DesktopSettings(local_data_dir=tmp_path)

    def client():
        def respond(request):
            return iam.client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                      headers=dict(request.headers))
        return IdentityClient(settings, transport=httpx.MockTransport(respond), session_store=store)

    first = client()
    presenter = SessionPresenter(None, first)
    try:
        assert first.login('remembered', 'Test-only-password-2026!', True) == 'MFA_REQUIRED'
        assert store.token is None
        first.mfa(pyotp.TOTP(secret).at(iam.now))
        assert presenter.snapshot()['user'].mfa_verified
        original = store.token
        assert original
    finally:
        presenter.close()
        presenter.finish()
    assert store.token == original
    second = client()
    try:
        assert second.restore_session()
        assert second.me().id == user and second.me().mfa_verified
        assert store.token and store.token != original
        restored = store.token
        iam.advance(901)
        assert second.me().mfa_verified
        assert store.token and store.token != restored
        if ending == 'logout':
            second.logout()
        elif ending == 'expire':
            iam.advance(28801)
        else:
            with iam.engine.begin() as c:
                if ending == 'revoke':
                    c.execute(text('UPDATE wms.auth_session SET revoked_at=now() WHERE user_id=:id'), {'id': user})
                else:
                    c.execute(text('UPDATE wms.app_user SET auth_version=auth_version+1 WHERE id=:id'), {'id': user})
    finally:
        second.close()
    third = client()
    try:
        if ending == 'logout':
            assert not third.restore_session()
        else:
            with pytest.raises(ApiError):
                third.restore_session()
        assert store.token is None and third._tokens is None
    finally:
        third.close()
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert original.encode() not in path.read_bytes()


def test_lost_refresh_is_consumed_and_never_replayed(tmp_path):
    store = MemoryVault()
    store.save('x' * 50)
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout('lost response')

    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(respond), session_store=store)
    try:
        with pytest.raises(ApiError):
            api.restore_session()
        assert store.token is None
        assert not api.restore_session() and len(calls) == 1
    finally:
        api.close()


def test_vault_binding_disabled_marker_and_no_plaintext_fallback(tmp_path, monkeypatch):
    settings = DesktopSettings(local_data_dir=tmp_path)
    device = uuid4()
    vault = SessionVault(settings, device)

    class Backend:
        value = None
        locked = False

        def get_password(self, *args):
            if self.locked:
                raise RuntimeError('locked')
            return self.value

        def set_password(self, service, account, value):
            self.value = value

        def delete_password(self, *args):
            if self.locked:
                raise RuntimeError('locked')
            self.value = None

    backend = Backend()
    monkeypatch.setattr(vault, 'backend', lambda: backend)
    vault.save('private-test-token')
    assert json.loads(vault.marker.read_text()) == {'enabled': True}
    assert 'private-test-token' not in vault.marker.read_text()
    assert SessionVault(settings, uuid4()).account != vault.account
    assert SessionVault(settings.model_copy(update={'api_url': 'https://another.example/api/v1'}), device).account != vault.account
    backend.locked = True
    with pytest.raises(RuntimeError):
        vault.forget()
    assert not vault.take()
    backend.locked = False
    vault.save('rotated')
    assert vault.take() == 'rotated' and vault.take() is None


def test_opt_out_never_saves_credentials(tmp_path):
    from packages.contracts.identity import SessionTokens
    store = MemoryVault()
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), session_store=store)
    try:
        api._tokens = SessionTokens(access_token='a', refresh_token='b', expires_in=900)
        api.persist_allowed = True
        api.persist_session()
        assert store.token is None
    finally:
        api.close()
