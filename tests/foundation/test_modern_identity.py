import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pyotp
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import text

from apps.server.application.modern_identity import AuthSettings, ModernIdentity, contact_value
from apps.server.auth_delivery_worker import DeliveryWorker
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.credentials import token_hash
from apps.server.infrastructure.google_oidc import validate

PASSWORD = 'Test-only-password-2026!'


@pytest.fixture
def modern(iam):
    service = ModernIdentity(iam.service, AuthSettings(smtp_host='smtp.test.invalid', smtp_user='fixture',
        smtp_password='test-smtp-secret', smtp_from='wms@example.test', twilio_account_sid='AC' + 'a' * 32,
        twilio_auth_token='test-sms-secret', twilio_from='+84900000000', google_client_id='fixture.apps.googleusercontent.com'))
    iam.client.app.state.modern_identity.settings = service.settings
    return service


def add_contact(iam, user, value='operator@example.test', kind='email'):
    with iam.engine.begin() as c:
        c.execute(text('INSERT INTO wms.auth_contact(user_id,kind,value,verified_at) VALUES(:id,:kind,:value,:now)'),
                  dict(id=user, kind=kind, value=value, now=iam.now))


def message(iam):
    with iam.engine.connect() as c:
        encrypted = c.execute(text('SELECT ciphertext FROM wms.auth_delivery WHERE completed_at IS NULL ORDER BY expires_at DESC LIMIT 1')).scalar_one()
    return json.loads(iam.service.cipher().decrypt(encrypted.encode()))


@pytest.mark.integration
@pytest.mark.parametrize('kind,value', [('email', 'operator@example.test'), ('sms', '+84912345678')])
def test_verified_contact_proof_required_single_use_and_secret_encrypted(iam, modern, kind, value, caplog):
    user, secret = iam.user(mfa=True)
    tokens = iam.login(secret=secret)
    headers = iam.headers(tokens)
    iam.advance()
    r = iam.client.post('/api/v1/auth/contacts/start', headers=headers,
        json=dict(kind=kind, value=value, password=PASSWORD, code=pyotp.TOTP(secret).at(iam.now)))
    assert r.status_code == 200, r.text
    challenge = r.json()['challenge_id']
    sent = message(iam)
    code = sent['body'].split(': ')[-1].split('.')[0]
    assert len(code) == 6 and code.isdigit()
    assert iam.client.get('/api/v1/auth/contacts', headers=headers).json() == []
    payload = dict(challenge_id=challenge, code='xxxxxx')
    assert iam.client.post('/api/v1/auth/contacts/confirm', headers=headers, json=payload).status_code == 401
    payload['code'] = code
    assert iam.client.post('/api/v1/auth/contacts/confirm', headers=headers, json=payload).status_code == 200
    assert iam.client.post('/api/v1/auth/contacts/confirm', headers=headers, json=payload).status_code == 401
    assert iam.client.get('/api/v1/auth/contacts', headers=headers).json() == [dict(kind=kind, value=value)]
    with iam.engine.connect() as c:
        challenge_row = c.execute(text('SELECT code_hash FROM wms.auth_contact_challenge')).scalar_one()
        cipher = c.execute(text('SELECT ciphertext FROM wms.auth_delivery')).scalar_one()
        assert code not in cipher and value not in cipher
        assert challenge_row == token_hash(challenge + ':' + code)
    assert PASSWORD not in caplog.text and value not in caplog.text


@pytest.mark.integration
def test_email_login_only_verified_and_keeps_totp(iam, modern):
    user, _ = iam.user(mfa=True)
    payload = dict(username='operator@example.test', password=PASSWORD, device_id=str(iam.device))
    assert iam.client.post('/api/v1/auth/login', json=payload).status_code == 401
    add_contact(iam, user)
    payload['username'] = 'Operator@Example.Test'
    assert iam.client.post('/api/v1/auth/login', json=payload).json()['status'] == 'MFA_REQUIRED'


@pytest.mark.integration
@pytest.mark.parametrize('kind,value', [('email', 'operator@example.test'), ('sms', '+84912345678')])
def test_forgot_generic_reset_single_use_preserves_mfa_revokes_sessions(iam, modern, kind, value):
    user, secret = iam.user(mfa=True)
    old = iam.login(secret=secret)
    add_contact(iam, user, value, kind)
    payload = dict(kind=kind, value=value, purpose='password')
    result = iam.client.post('/api/v1/auth/forgot', json=payload)
    unknown = iam.client.post('/api/v1/auth/forgot', json={**payload, 'value': 'unknown@example.test' if kind == 'email' else '+84911111111'})
    assert result.status_code == unknown.status_code == 200 and result.json() == unknown.json()
    sent = message(iam)
    reset = sent['body'].split('mat khau: ')[1].split('.')[0]
    assert len(reset) == 43
    assert iam.client.get('/api/v1/auth/me', headers=iam.headers(old)).status_code == 200
    body = dict(username='operator', reset_token=reset, new_password='new-password-fixture-2026!')
    assert iam.client.post('/api/v1/auth/self-reset', json=body).status_code == 200
    assert iam.client.post('/api/v1/auth/self-reset', json=body).status_code == 401
    assert iam.client.get('/api/v1/auth/me', headers=iam.headers(old)).status_code == 401
    login = iam.client.post('/api/v1/auth/login', json=dict(username='operator', password=body['new_password'], device_id=str(iam.device)))
    assert login.json()['status'] == 'MFA_REQUIRED'


@pytest.mark.integration
def test_forgot_expiry_throttle_and_account_hint(iam, modern):
    user, _ = iam.user()
    add_contact(iam, user)
    body = dict(kind='email', value='operator@example.test', purpose='account')
    assert iam.client.post('/api/v1/auth/forgot', json=body).status_code == 200
    assert 'operator' in message(iam)['body']
    iam.advance(1)  # Latest-message ordering must not depend on tied expiry times.
    body['purpose'] = 'password'
    for _ in range(4):
        assert iam.client.post('/api/v1/auth/forgot', json=body).status_code == 200
    assert iam.client.post('/api/v1/auth/forgot', json=body).status_code == 429
    reset = message(iam)['body'].split('mat khau: ')[1].split('.')[0]
    iam.advance(901)
    assert iam.client.post('/api/v1/auth/self-reset', json=dict(username='operator', reset_token=reset, new_password=PASSWORD)).status_code == 401


@pytest.mark.integration
def test_concurrent_reset_consumes_only_once(iam, modern):
    from packages.contracts.modern_identity import ForgotInput
    user, _ = iam.user()
    add_contact(iam, user)
    modern.forgot(ForgotInput(kind='email', value='operator@example.test', purpose='password'), 'test-peer', uuid4())
    reset = message(iam)['body'].split('mat khau: ')[1].split('.')[0]
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        try:
            modern.reset('operator', reset, PASSWORD, uuid4())
            return True
        except DomainError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: run(), range(2))) == [False, True]


@pytest.mark.integration
def test_delivery_leases_cleanup_obsolete_and_redacts_transport_failure(iam, modern, caplog):
    user, _ = iam.user()
    add_contact(iam, user)
    body = dict(kind='email', value='operator@example.test', purpose='password')
    iam.client.post('/api/v1/auth/forgot', json=body)
    def fail(settings, msg):
        raise RuntimeError('provider-secret-and-email-' + msg['body'])
    worker = DeliveryWorker(iam.service, modern.settings, sender=fail)
    assert worker.run_one() == 'RETRY'
    assert worker.run_one() is None
    with iam.engine.begin() as c:
        c.execute(text('UPDATE wms.auth_delivery SET lease_until=NULL'))
        assert c.execute(text('SELECT last_error FROM wms.auth_delivery')).scalar_one() == 'DELIVERY_FAILED'
    sent = []
    worker.sender = lambda settings, msg: sent.append(dict(msg))
    assert worker.run_one() == 'SENT'
    assert worker.run_one() is None and len(sent) == 1
    with iam.engine.connect() as c:
        assert c.execute(text('SELECT ciphertext FROM wms.auth_delivery')).scalar_one() is None
    iam.client.post('/api/v1/auth/forgot', json=body)
    with iam.engine.begin() as c:
        c.execute(text('UPDATE wms.app_user SET is_active=false WHERE id=:id'), dict(id=user))
    assert worker.run_one() == 'OBSOLETE' and len(sent) == 1
    assert 'provider-secret' not in caplog.text


@pytest.mark.integration
def test_google_pkce_explicit_link_and_login_never_bypasses_mfa(iam, modern, monkeypatch):
    user, secret = iam.user(mfa=True)
    tokens = iam.login(secret=secret)
    iam.advance()
    body = dict(port=12345, device_id=str(iam.device), link=True, password=PASSWORD, code=pyotp.TOTP(secret).at(iam.now))
    started = iam.client.post('/api/v1/auth/google/start', headers=iam.headers(tokens), json=body)
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()['url']).query)
    assert query['code_challenge_method'] == ['S256'] and query['redirect_uri'] == ['http://127.0.0.1:12345/wms-google']
    def exchange(settings, code, verifier, redirect, nonce_hash, now):
        assert nonce_hash == token_hash(query['nonce'][0])
        assert len(verifier) >= 43
        return dict(sub='google-fixture-subject')
    monkeypatch.setattr('apps.server.application.modern_identity.exchange', exchange)
    complete = dict(state=started.json()['state'], code='fixture-oauth-code')
    assert iam.client.post('/api/v1/auth/google/complete', headers=iam.headers(tokens), json=complete).status_code == 200
    assert iam.client.post('/api/v1/auth/google/complete', headers=iam.headers(tokens), json=complete).status_code == 401
    started = iam.client.post('/api/v1/auth/google/start', json=dict(port=12345, device_id=str(iam.device)))
    query = parse_qs(urlsplit(started.json()['url']).query)
    result = iam.client.post('/api/v1/auth/google/complete', json=dict(state=started.json()['state'], code='fixture-code'))
    assert result.json()['status'] == 'MFA_REQUIRED' and 'access_token' not in result.json()
    with iam.engine.begin() as c:
        c.execute(text('DELETE FROM wms.auth_google_identity'))
    started = iam.client.post('/api/v1/auth/google/start', json=dict(port=12345, device_id=str(iam.device)))
    query = parse_qs(urlsplit(started.json()['url']).query)
    assert iam.client.post('/api/v1/auth/google/complete', json=dict(state=started.json()['state'], code='fixture-code')).status_code == 401


@pytest.mark.integration
def test_provider_disabled_and_link_requires_current_totp(iam, modern):
    iam.user()
    tokens = iam.login()
    response = iam.client.post('/api/v1/auth/google/start', headers=iam.headers(tokens),
        json=dict(port=12345, device_id=str(iam.device), link=True, password=PASSWORD, code='123456'))
    assert response.status_code == 401
    modern.settings.google_client_id = ''
    assert iam.client.get('/api/v1/auth/options').json()['google'] is False
    assert iam.client.post('/api/v1/auth/google/start', json=dict(port=12345, device_id=str(iam.device))).status_code == 503


@pytest.fixture(scope='module')
def signing():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    def b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip('=')
    public = private.public_key().public_numbers()
    keys = {'keys': [dict(kid='test-key', kty='RSA', e=b64(public.e.to_bytes(3, 'big')), n=b64(public.n.to_bytes(256, 'big')))]}
    def sign(claims, alg='RS256'):
        header = b64(json.dumps(dict(alg=alg, kid='test-key')).encode())
        body = b64(json.dumps(claims).encode())
        value = header + '.' + body
        return value + '.' + b64(private.sign(value.encode(), padding.PKCS1v15(), hashes.SHA256()))
    return keys, sign


@pytest.mark.parametrize('change', [{}, {'iss':'evil'}, {'aud':'wrong'}, {'exp':1}, {'nonce':'wrong'}, {'email_verified':False}, {'sub':''}, {'iat':9999999999}])
def test_signed_google_token_issuer_audience_expiry_nonce_verified_email(signing, change):
    keys, sign = signing
    now = datetime.now(UTC)
    claims = dict(iss='https://accounts.google.com', aud='fixture', exp=int(now.timestamp())+300,
                  iat=int(now.timestamp()), nonce='fixture-nonce', email_verified=True, sub='123') | change
    if change:
        with pytest.raises(ValueError):
            validate(sign(claims), keys, 'fixture', token_hash('fixture-nonce'), now)
    else:
        assert validate(sign(claims), keys, 'fixture', token_hash('fixture-nonce'), now)['sub'] == '123'
        with pytest.raises(ValueError):
            validate(sign(claims, alg='HS256'), keys, 'fixture', token_hash('fixture-nonce'), now)


@pytest.mark.parametrize('kind,value,expected', [('email','User@Example.com','user@example.com'), ('sms','0912 345 678','+84912345678')])
def test_contact_normalization(kind, value, expected):
    assert contact_value(kind, value) == expected


@pytest.mark.parametrize('kind,value', [('email','user\n@example.com'), ('email','not-email'), ('sms','abc'), ('sms','+123')])
def test_invalid_contact_rejected(kind, value):
    with pytest.raises(DomainError):
        contact_value(kind, value)
