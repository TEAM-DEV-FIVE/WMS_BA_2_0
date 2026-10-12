"""Verified channels, durable encrypted notifications and explicit Google linking."""

import hmac
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text

from apps.server.application.identity import audit, row
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.credentials import hash_password, new_token, token_hash
from apps.server.infrastructure.google_oidc import exchange

GENERIC = 'Nếu thông tin khớp tài khoản đã xác minh, bạn sẽ nhận được hướng dẫn. Mã có hiệu lực 15 phút.'


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='WMS_AUTH_', extra='ignore', hide_input_in_errors=True)
    smtp_host: str = ''
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_user: str = ''
    smtp_password: SecretStr | None = None
    smtp_from: str = ''
    smtp_starttls: bool = False
    twilio_account_sid: str = ''
    twilio_auth_token: SecretStr | None = None
    twilio_from: str = ''
    google_client_id: str = ''
    google_client_secret: SecretStr | None = None
    @field_validator('twilio_account_sid')
    @classmethod
    def valid_sid(cls, value):
        if value and not re.fullmatch(r'AC[0-9a-fA-F]{32}', value):
            raise ValueError('Invalid Twilio account SID')
        return value

    @field_validator('google_client_id')
    @classmethod
    def valid_google_id(cls, value):
        if value and not re.fullmatch(r'[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com', value):
            raise ValueError('Invalid Google desktop client ID')
        return value

    def capabilities(self):
        return dict(email=bool(self.smtp_host and self.smtp_from and self.smtp_user and self.smtp_password),
                    sms=bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from),
                    google=bool(self.google_client_id))


def contact_value(kind, value):
    value = value.strip().lower()
    if kind == 'email' and re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+', value) and len(value) <= 254:
        return value
    if kind == 'sms':
        value = re.sub(r'[ ()-]', '', value)
        if re.fullmatch(r'0[0-9]{9}', value):
            value = '+84' + value[1:]
        if re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
            return value
    raise DomainError('INVALID_CONTACT', 'Nhập email hợp lệ hoặc số điện thoại quốc tế (ví dụ +84…).')


class ModernIdentity:
    def __init__(self, identity, settings=None):
        self.identity = identity
        self.settings = settings or AuthSettings()

    def require_channel(self, kind):
        if not self.settings.capabilities().get(kind):
            raise DomainError('AUTH_PROVIDER_UNAVAILABLE', 'Dịch vụ này chưa được quản trị viên cấu hình. Dùng tài khoản/mật khẩu hoặc liên hệ quản trị.')

    def queue(self, c, user, kind, value, body, now, **binding):
        message = dict(kind=kind, to=value, body=body, **binding)
        ciphertext = self.identity.cipher().encrypt(json.dumps(message).encode()).decode()
        c.execute(text('''INSERT INTO wms.auth_delivery(id,user_id,auth_version,ciphertext,expires_at)
            VALUES(:id,:user,:version,:cipher,:expires)'''), dict(id=uuid4(), user=user['id'],
            version=user['auth_version'], cipher=ciphertext, expires=now + timedelta(minutes=15)))

    def contacts(self, token):
        with self.identity.engine.begin() as c:
            actor = self.identity.authenticate(c, token)
            return [dict(r) for r in c.execute(text('SELECT kind,value FROM wms.auth_contact WHERE user_id=:id ORDER BY kind'), dict(id=actor.user_id)).mappings()]

    def contact_start(self, token, payload, request_id):
        self.require_channel(payload.kind)
        value = contact_value(payload.kind, payload.value)
        now, result = self.identity.clock(), None
        with self.identity.engine.begin() as c:
            actor, user = self.identity.lock_actor(c, token, now)
            if self.identity.reauthenticate(c, actor, user, payload.password.get_secret_value(),
                    payload.code.get_secret_value() if payload.code else None, request_id, now, mfa=True):
                key = self.identity.throttle(c, 'CONTACT_SEND', user['id'], now)
                self.identity.failed_attempt(c, key, now)
                c.execute(text('UPDATE wms.auth_contact_challenge SET consumed_at=:now WHERE user_id=:id AND kind=:kind AND consumed_at IS NULL'), dict(now=now, id=user['id'], kind=payload.kind))
                challenge, code = uuid4(), f'{secrets.randbelow(1000000):06d}'
                c.execute(text('''INSERT INTO wms.auth_contact_challenge(id,user_id,kind,value,code_hash,auth_version,expires_at)
                    VALUES(:id,:user,:kind,:value,:hash,:version,:expires)'''), dict(id=challenge, user=user['id'],
                    kind=payload.kind, value=value, hash=token_hash(str(challenge) + ':' + code), version=user['auth_version'], expires=now + timedelta(minutes=15)))
                self.queue(c, user, payload.kind, value, 'WMS: Ma xac minh lien he cua ban: ' + code + '. Het han sau 15 phut.', now, challenge=str(challenge))
                audit(c, user['id'], 'auth.contact.requested', user['id'], request_id, now)
                result = dict(challenge_id=str(challenge), message='Đã yêu cầu gửi mã. Nhập mã 6 số để xác minh liên hệ.')
        if result is None:
            raise DomainError('MFA_INVALID', 'Cần mật khẩu và mã MFA mới để thay liên hệ.')
        return result

    def contact_confirm(self, token, challenge_id, code, request_id):
        now, success = self.identity.clock(), False
        with self.identity.engine.begin() as c:
            actor, user = self.identity.lock_actor(c, token, now)
            key = self.identity.throttle(c, 'CONTACT_VERIFY', user['id'], now)
            self.identity.failed_attempt(c, key, now)
            challenge = row(c, 'SELECT * FROM wms.auth_contact_challenge WHERE id=:id AND user_id=:user FOR UPDATE', id=challenge_id, user=user['id'])
            if (challenge and challenge['consumed_at'] is None and challenge['expires_at'] > now
                    and challenge['auth_version'] == user['auth_version']
                    and hmac.compare_digest(challenge['code_hash'], token_hash(str(challenge_id) + ':' + code))):
                conflict = row(c, 'SELECT user_id FROM wms.auth_contact WHERE kind=:kind AND value=:value', kind=challenge['kind'], value=challenge['value'])
                if conflict and conflict['user_id'] != user['id']:
                    raise DomainError('INVALID_CONTACT', 'Liên hệ này không thể gắn vào tài khoản.')
                c.execute(text('''INSERT INTO wms.auth_contact(user_id,kind,value,verified_at) VALUES(:user,:kind,:value,:now)
                    ON CONFLICT(user_id,kind) DO UPDATE SET value=excluded.value,verified_at=excluded.verified_at'''),
                    dict(user=user['id'], kind=challenge['kind'], value=challenge['value'], now=now))
                c.execute(text('UPDATE wms.auth_contact_challenge SET consumed_at=:now WHERE id=:id'), dict(now=now, id=challenge_id))
                c.execute(text('UPDATE wms.auth_self_reset SET consumed_at=:now WHERE user_id=:user AND kind=:kind AND consumed_at IS NULL'), dict(now=now, user=user['id'], kind=challenge['kind']))
                audit(c, user['id'], 'auth.contact.verified', user['id'], request_id, now)
                success = True
        if not success:
            raise DomainError('MFA_INVALID', 'Mã liên hệ sai, đã dùng hoặc đã hết hạn.')
        return dict(message='Đã xác minh liên hệ. Bạn có thể dùng để khôi phục tài khoản.')

    def forgot(self, payload, peer, request_id):
        self.require_channel(payload.kind)
        value, now = contact_value(payload.kind, payload.value), self.identity.clock()
        with self.identity.engine.begin() as c:
            for category, identity in [('FORGOT_PEER', peer), ('FORGOT_CONTACT', payload.kind + ':' + value)]:
                key = self.identity.throttle(c, category, identity, now)
                self.identity.failed_attempt(c, key, now)
            user = row(c, '''SELECT u.* FROM wms.app_user u JOIN wms.auth_contact t ON t.user_id=u.id
                WHERE t.kind=:kind AND t.value=:value AND u.is_active FOR UPDATE OF u''', kind=payload.kind, value=value)
            reset = new_token()  # Same cryptographic work even for unknown contacts.
            self.identity.cipher().encrypt(reset.encode())
            if user:
                binding = dict(contact_kind=payload.kind, contact_value=value)
                if payload.purpose == 'account':
                    body = 'WMS: Tai khoan cua ban la ' + user['username'] + '. Khong chia se mat khau hoac ma MFA.'
                else:
                    c.execute(text('UPDATE wms.auth_self_reset SET consumed_at=:now WHERE user_id=:id AND consumed_at IS NULL'), dict(now=now, id=user['id']))
                    c.execute(text('''INSERT INTO wms.auth_self_reset(token_hash,user_id,kind,contact_value,auth_version,expires_at)
                        VALUES(:hash,:user,:kind,:value,:version,:expires)'''), dict(hash=token_hash(reset), user=user['id'], kind=payload.kind, value=value,
                        version=user['auth_version'], expires=now + timedelta(minutes=15)))
                    binding['reset_hash'] = token_hash(reset)
                    body = f'WMS: Tai khoan {user["username"]}. Ma dat lai mat khau: {reset}. Het han sau 15 phut. MFA van duoc giu nguyen.'
                self.queue(c, user, payload.kind, value, body, now, **binding)
                audit(c, user['id'], 'auth.recovery.requested', user['id'], request_id, now)
        return dict(message=GENERIC)

    def reset(self, username, reset_token, password, request_id):
        now, success = self.identity.clock(), False
        with self.identity.engine.begin() as c:
            user = row(c, 'SELECT * FROM wms.app_user WHERE username=:name FOR UPDATE', name=username)
            key = self.identity.throttle(c, 'PASSWORD_RESET', username, now)
            self.identity.failed_attempt(c, key, now)
            reset = row(c, 'SELECT * FROM wms.auth_self_reset WHERE token_hash=:hash FOR UPDATE', hash=token_hash(reset_token))
            contact = row(c, 'SELECT value FROM wms.auth_contact WHERE user_id=:id AND kind=:kind', id=user['id'], kind=reset['kind']) if user and reset else None
            if (user and user['is_active'] and reset and reset['user_id'] == user['id'] and contact
                    and contact['value'] == reset['contact_value'] and reset['auth_version'] == user['auth_version']
                    and reset['consumed_at'] is None and reset['expires_at'] > now):
                c.execute(text('UPDATE wms.app_user SET password_hash=:hash WHERE id=:id'), dict(id=user['id'], hash=hash_password(password)))
                self.identity.invalidate(c, user['id'], now)
                c.execute(text('UPDATE wms.auth_self_reset SET consumed_at=:now WHERE user_id=:id AND consumed_at IS NULL'), dict(now=now, id=user['id']))
                audit(c, user['id'], 'auth.password.self_reset', user['id'], request_id, now)
                success = True
        if not success:
            raise DomainError('MFA_INVALID', 'Mã đặt lại không hợp lệ, đã dùng hoặc đã hết hạn.')

    def google_start(self, payload, token, request_id):
        self.require_channel('google')
        state, nonce, verifier = new_token(), new_token(), new_token()
        now, result = self.identity.clock(), None
        with self.identity.engine.begin() as c:
            user_id = session_id = version = None
            if payload.link:
                actor, user = self.identity.lock_actor(c, token, now)
                if not self.identity.reauthenticate(c, actor, user,
                        payload.password.get_secret_value() if payload.password else '',
                        payload.code.get_secret_value() if payload.code else None, request_id, now, mfa=True):
                    return_after_commit = True
                else:
                    user_id, session_id, version = user['id'], actor.session_id, user['auth_version']
                    return_after_commit = False
            else:
                return_after_commit = False
            if not return_after_commit:
                key = self.identity.throttle(c, 'GOOGLE_START', payload.device_id, now)
                self.identity.failed_attempt(c, key, now)
                redirect = f'http://127.0.0.1:{payload.port}/wms-google'
                c.execute(text('''INSERT INTO wms.auth_google_flow(state_hash,nonce_hash,verifier_ciphertext,redirect_uri,device_id,user_id,session_id,auth_version,expires_at)
                    VALUES(:state,:nonce,:cipher,:redirect,:device,:user,:session,:version,:expiry)'''),
                    dict(state=token_hash(state), nonce=token_hash(nonce), cipher=self.identity.cipher().encrypt(verifier.encode()).decode(),
                         redirect=redirect, device=payload.device_id, user=user_id, session=session_id, version=version, expiry=now + timedelta(minutes=5)))
                import base64
                import hashlib
                pkce = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(dict(client_id=self.settings.google_client_id,
                    redirect_uri=redirect, response_type='code', scope='openid email', state=state, nonce=nonce,
                    code_challenge=pkce, code_challenge_method='S256', prompt='select_account'))
                result = dict(url=url, state=state)
        if result is None:
            raise DomainError('MFA_INVALID', 'Cần mật khẩu và mã MFA mới để liên kết Google.')
        return result

    def google_complete(self, state, code, token, request_id):
        self.require_channel('google')
        now = self.identity.clock()
        # Consume before exchange: authorization codes are never retried after a lost response.
        with self.identity.engine.begin() as c:
            flow = row(c, 'SELECT * FROM wms.auth_google_flow WHERE state_hash=:hash FOR UPDATE', hash=token_hash(state))
            if not flow or flow['expires_at'] <= now or flow['consumed_at'] is not None:
                raise DomainError('UNAUTHENTICATED', 'Yêu cầu Google đã hết hạn hoặc đã dùng. Đăng nhập lại.')
            if flow['user_id']:
                actor = self.identity.authenticate(c, token)
                if actor.user_id != flow['user_id'] or actor.session_id != flow['session_id']:
                    raise DomainError('UNAUTHENTICATED', 'Phiên liên kết đã thay đổi.')
            verifier = self.identity.cipher().decrypt(flow['verifier_ciphertext'].encode()).decode()
            c.execute(text('UPDATE wms.auth_google_flow SET consumed_at=:now,verifier_ciphertext=NULL WHERE state_hash=:hash'), dict(now=now, hash=token_hash(state)))
        claims = exchange(self.settings, code, verifier, flow['redirect_uri'], flow['nonce_hash'], now)
        with self.identity.engine.begin() as c:
            if flow['user_id']:
                actor, user = self.identity.lock_actor(c, token, now)
                if actor.user_id != flow['user_id'] or actor.session_id != flow['session_id'] or user['auth_version'] != flow['auth_version']:
                    raise DomainError('UNAUTHENTICATED', 'Phiên liên kết đã thay đổi.')
                existing = row(c, 'SELECT user_id FROM wms.auth_google_identity WHERE subject=:sub OR user_id=:id LIMIT 1', sub=claims['sub'], id=user['id'])
                if existing:
                    raise DomainError('INVALID_STATE', 'Google hoặc tài khoản WMS đã có liên kết. Liên hệ quản trị để đối chiếu.')
                c.execute(text('INSERT INTO wms.auth_google_identity(subject,user_id,linked_at) VALUES(:sub,:user,:now)'), dict(sub=claims['sub'], user=user['id'], now=now))
                audit(c, user['id'], 'auth.google.linked', user['id'], request_id, now)
                return dict(message='Đã liên kết Google. Lần sau bạn có thể dùng Google và MFA của WMS.')
            user = row(c, '''SELECT u.* FROM wms.app_user u JOIN wms.auth_google_identity g ON g.user_id=u.id
                WHERE g.subject=:sub FOR UPDATE OF u''', sub=claims['sub'])
            if not user or not user['is_active']:
                raise DomainError('UNAUTHENTICATED', 'Google chưa được liên kết với tài khoản WMS đang hoạt động. Đăng nhập bằng mật khẩu và liên kết trong Bảo mật.')
            return self.identity.login_verified(c, user, flow['device_id'], request_id, now)
