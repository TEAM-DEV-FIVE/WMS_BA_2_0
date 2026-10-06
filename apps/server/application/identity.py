"""IAM transactions and live session validation. Credentials never enter audit payloads."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, text

from apps.server.application.authorization import Authorization, Principal
from apps.server.domain.errors import DomainError
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.credentials import hash_password, new_token, token_hash, verify_password
from packages.contracts.identity import (
    Enrollment,
    MfaChallenge,
    PasswordResetToken,
    RecoveryCodes,
    SessionTokens,
)


def row(connection, sql, **params):
    return connection.execute(text(sql), params).mappings().one_or_none()


def audit(connection, actor, action, entity, request_id, now, reason=None):
    connection.execute(text("""
        INSERT INTO wms.audit_event(id,actor_id,action,entity_type,entity_id,request_id,occurred_at,reason)
        VALUES (:id,:actor,:action,'identity',:entity,:request,:now,:reason)
    """), {"id": uuid4(), "actor": actor, "action": action, "entity": entity, "request": request_id, "now": now, "reason": reason})


class IdentityService:
    def __init__(self, engine: Engine, settings: Settings, *, clock=None):
        self.engine = engine
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))

    def cipher(self) -> Fernet:
        if self.settings.mfa_encryption_key is None:
            raise DomainError("MFA_UNAVAILABLE", "Máy chủ chưa được cấu hình khóa MFA.")
        return Fernet(self.settings.mfa_encryption_key.get_secret_value().encode())

    def throttle(self, connection, category, identity, now):
        key = token_hash(category + ":" + str(identity))
        lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        connection.execute(text("""
            INSERT INTO wms.auth_throttle(key,failures,window_started_at) VALUES (:key,0,:now)
            ON CONFLICT DO NOTHING
        """), {"key": key, "now": now})
        state = row(connection, "SELECT * FROM wms.auth_throttle WHERE key=:key FOR UPDATE", key=key)
        if state["blocked_until"] and state["blocked_until"] > now:
            raise DomainError("RATE_LIMITED", "Thử lại sau vài phút.", retryable=True)
        if state["window_started_at"] + timedelta(seconds=self.settings.auth_lock_seconds) <= now:
            connection.execute(text("UPDATE wms.auth_throttle SET failures=0,blocked_until=NULL,window_started_at=:now WHERE key=:key"), {"key": key, "now": now})
        return key

    def failed_attempt(self, connection, key, now):
        connection.execute(text("""
            UPDATE wms.auth_throttle SET failures=failures+1,
              blocked_until=CASE WHEN failures+1>=:limit THEN :until ELSE blocked_until END
            WHERE key=:key
        """), {"key": key, "limit": self.settings.auth_failure_limit,
               "until": now + timedelta(seconds=self.settings.auth_lock_seconds)})

    def clear_attempts(self, connection, key):
        connection.execute(text("UPDATE wms.auth_throttle SET failures=0,blocked_until=NULL WHERE key=:key"), {"key": key})

    def tokens(self, connection, session, now) -> SessionTokens:
        access, refresh = new_token(), new_token()
        expiry = min(session["expires_at"], now + timedelta(seconds=self.settings.access_ttl_seconds))
        for token, kind, until in [(access, "ACCESS", expiry), (refresh, "REFRESH", session["expires_at"])]:
            connection.execute(text("""
                INSERT INTO wms.auth_token(token_hash,session_id,kind,created_at,expires_at)
                VALUES (:hash,:session,:kind,:now,:expiry)
            """), {"hash": token_hash(token), "session": session["id"], "kind": kind, "now": now, "expiry": until})
        connection.execute(text("UPDATE wms.auth_session SET refresh_hash=:hash WHERE id=:id"),
                           {"hash": token_hash(refresh), "id": session["id"]})
        return SessionTokens(access_token=access, refresh_token=refresh, expires_in=int((expiry-now).total_seconds()))

    def new_session(self, connection, user, device_id, now, *, mfa=False):
        session = {"id": uuid4(), "expires_at": now + timedelta(seconds=self.settings.session_ttl_seconds)}
        connection.execute(text("""
            INSERT INTO wms.auth_session(id,user_id,refresh_hash,device_id,auth_version,expires_at,mfa_verified_at)
            VALUES (:id,:user,:placeholder,:device,:version,:expires,:mfa)
        """), {"id": session["id"], "user": user["id"], "placeholder": token_hash(new_token()),
               "device": device_id, "version": user["auth_version"], "expires": session["expires_at"],
               "mfa": now if mfa else None})
        return self.tokens(connection, session, now)

    def login(self, username, password, device_id, request_id):
        now = self.clock()
        result = None
        with self.engine.begin() as connection:
            key = self.throttle(connection, "LOGIN", username, now)
            user = row(connection, "SELECT * FROM wms.app_user WHERE username=:name FOR UPDATE", name=username)
            verified = verify_password(user["password_hash"] if user else None, password)
            if not user or not user["is_active"] or not verified:
                self.failed_attempt(connection, key, now)
                audit(connection, user["id"] if user else None, "auth.login.failed", None, request_id, now)
            else:
                self.clear_attempts(connection, key)
                factor = row(connection, """SELECT id FROM wms.mfa_factor WHERE user_id=:user
                    AND kind='TOTP' AND verified_at IS NOT NULL AND revoked_at IS NULL""", user=user["id"])
                if factor:
                    self.cipher()  # Refuse, rather than bypass MFA, if encryption key is missing.
                    challenge = new_token()
                    connection.execute(text("""INSERT INTO wms.auth_challenge
                        (token_hash,user_id,device_id,auth_version,expires_at) VALUES (:hash,:user,:device,:version,:expiry)
                    """), {"hash": token_hash(challenge), "user": user["id"], "device": device_id,
                           "version": user["auth_version"], "expiry": now+timedelta(minutes=5)})
                    result = MfaChallenge(challenge_token=challenge)
                else:
                    result = self.new_session(connection, user, device_id, now)
                    audit(connection, user["id"], "auth.login.succeeded", user["id"], request_id, now)
        if result is None:
            raise DomainError("UNAUTHENTICATED", "Thông tin đăng nhập không hợp lệ.")
        return result

    def verify_totp(self, connection, factor, code, now):
        try:
            secret = self.cipher().decrypt(factor["credential_ciphertext"].encode()).decode()
        except InvalidToken:
            raise DomainError("MFA_UNAVAILABLE", "Không đọc được cấu hình MFA; liên hệ quản trị.") from None
        counter = int(now.timestamp()) // 30
        totp = pyotp.TOTP(secret)
        for candidate in (counter-1, counter, counter+1):
            if candidate > factor["last_counter"] and pyotp.utils.strings_equal(totp.at(candidate*30), code):
                connection.execute(text("UPDATE wms.mfa_factor SET last_counter=:counter WHERE id=:id"),
                                   {"counter": candidate, "id": factor["id"]})
                return True
        return False

    def complete_mfa(self, challenge_token, code, request_id):
        now = self.clock()
        result = None
        with self.engine.begin() as connection:
            challenge = row(connection, "SELECT * FROM wms.auth_challenge WHERE token_hash=:hash", hash=token_hash(challenge_token))
            if not challenge:
                raise DomainError("UNAUTHENTICATED", "Yêu cầu MFA không hợp lệ hoặc đã hết hạn.")
            user = row(connection, "SELECT * FROM wms.app_user WHERE id=:id FOR UPDATE", id=challenge["user_id"])
            key = self.throttle(connection, "MFA", challenge["user_id"], now)
            challenge = row(connection, "SELECT * FROM wms.auth_challenge WHERE token_hash=:hash FOR UPDATE", hash=token_hash(challenge_token))
            if (not user["is_active"] or user["auth_version"] != challenge["auth_version"]
                    or challenge["expires_at"] <= now or challenge["consumed_at"] is not None):
                raise DomainError("UNAUTHENTICATED", "Yêu cầu MFA không hợp lệ hoặc đã hết hạn.")
            factor = row(connection, """SELECT * FROM wms.mfa_factor WHERE user_id=:user AND kind='TOTP'
                AND verified_at IS NOT NULL AND revoked_at IS NULL FOR UPDATE""", user=user["id"])
            if factor and self.verify_totp(connection, factor, code, now):
                connection.execute(text("UPDATE wms.auth_challenge SET consumed_at=:now WHERE token_hash=:hash"),
                                   {"now": now, "hash": token_hash(challenge_token)})
                self.clear_attempts(connection, key)
                result = self.new_session(connection, user, challenge["device_id"], now, mfa=True)
                audit(connection, user["id"], "auth.mfa.succeeded", user["id"], request_id, now)
            else:
                self.failed_attempt(connection, key, now)
                audit(connection, user["id"], "auth.mfa.failed", user["id"], request_id, now)
        if result is None:
            raise DomainError("MFA_INVALID", "Mã MFA sai, đã dùng hoặc đã hết hạn.")
        return result

    def authenticate(self, connection, access_token: str) -> Principal:
        now = self.clock()
        identity = row(connection, """
            SELECT u.id,u.username,u.display_name,u.is_active,u.auth_version,s.id AS session_id,
              s.auth_version AS session_version,s.expires_at,s.revoked_at,s.mfa_verified_at,
              t.expires_at AS token_expires_at,t.used_at
            FROM wms.auth_token t JOIN wms.auth_session s ON s.id=t.session_id
            JOIN wms.app_user u ON u.id=s.user_id
            WHERE t.token_hash=:hash AND t.kind='ACCESS' FOR SHARE OF u,s,t
        """, hash=token_hash(access_token))
        if (not identity or not identity["is_active"] or identity["revoked_at"] is not None
                or identity["used_at"] is not None or identity["auth_version"] != identity["session_version"]
                or identity["expires_at"] <= now or identity["token_expires_at"] <= now):
            raise DomainError("UNAUTHENTICATED", "Phiên đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại.")
        return Principal(identity["id"], identity["session_id"], identity["username"],
                         identity["display_name"], identity["mfa_verified_at"])

    def authorization(self, connection, token):
        return Authorization(connection, self.authenticate(connection, token), self.clock())

    def refresh(self, refresh_token, device_id, request_id):
        now = self.clock()
        result = None
        with self.engine.begin() as connection:
            token = row(connection, """SELECT t.*,s.user_id FROM wms.auth_token t JOIN wms.auth_session s ON s.id=t.session_id
                WHERE t.token_hash=:hash AND t.kind='REFRESH'""", hash=token_hash(refresh_token))
            if not token:
                raise DomainError("UNAUTHENTICATED", "Refresh token không hợp lệ.")
            user = row(connection, "SELECT * FROM wms.app_user WHERE id=:id FOR UPDATE", id=token["user_id"])
            session = row(connection, "SELECT * FROM wms.auth_session WHERE id=:id FOR UPDATE", id=token["session_id"])
            token = row(connection, "SELECT * FROM wms.auth_token WHERE token_hash=:hash FOR UPDATE", hash=token_hash(refresh_token))
            if (not user["is_active"] or session["revoked_at"] is not None or session["expires_at"] <= now
                    or token["expires_at"] <= now or session["device_id"] != device_id
                    or session["auth_version"] != user["auth_version"]):
                raise DomainError("UNAUTHENTICATED", "Phiên đã hết hạn hoặc bị thu hồi.")
            if token["used_at"] is not None or session["refresh_hash"] != token_hash(refresh_token):
                connection.execute(text("UPDATE wms.auth_session SET revoked_at=:now WHERE id=:id"), {"id": session["id"], "now": now})
                audit(connection, user["id"], "auth.refresh.replay", session["id"], request_id, now)
            else:
                connection.execute(text("UPDATE wms.auth_token SET used_at=:now WHERE session_id=:id AND used_at IS NULL"),
                                   {"now": now, "id": session["id"]})
                result = self.tokens(connection, session, now)
                audit(connection, user["id"], "auth.refresh.succeeded", session["id"], request_id, now)
        # Raise AFTER commit: a replay must persist the family revocation.
        if result is None:
            raise DomainError("REFRESH_REPLAY", "Refresh token đã được dùng. Phiên đã bị thu hồi.")
        return result

    def logout(self, token, request_id):
        with self.engine.begin() as connection:
            actor = self.authenticate(connection, token)
            connection.execute(text("UPDATE wms.auth_session SET revoked_at=:now WHERE id=:id"),
                               {"now": self.clock(), "id": actor.session_id})
            audit(connection, actor.user_id, "auth.logout", actor.session_id, request_id, self.clock())

    def enroll(self, token, password, request_id):
        now = self.clock()
        cipher = self.cipher()
        result = None
        with self.engine.begin() as connection:
            # Resolve ID before taking the throttle/user locks used by MFA completion.
            actor, user = self.lock_actor(connection, token, now)
            key = self.throttle(connection, "ENROLL", actor.user_id, now)
            self.failed_attempt(connection, key, now)
            if not verify_password(user["password_hash"], password):
                audit(connection, actor.user_id, "auth.enroll.failed", actor.user_id, request_id, now)
            else:
                existing = row(connection, """SELECT id FROM wms.mfa_factor WHERE user_id=:id
                    AND verified_at IS NOT NULL AND revoked_at IS NULL""", id=actor.user_id)
                if existing:
                    raise DomainError("MFA_ALREADY_ENABLED", "MFA đã được bật; không được ghi đè yếu tố hiện tại.")
                connection.execute(text("UPDATE wms.mfa_factor SET revoked_at=:now WHERE user_id=:id AND verified_at IS NULL AND revoked_at IS NULL"),
                                   {"now": now, "id": actor.user_id})
                secret, factor_id = pyotp.random_base32(), uuid4()
                connection.execute(text("""INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext,enrollment_expires_at)
                    VALUES (:id,:user,'TOTP',:cipher,:expires)"""),
                                   {"id": factor_id, "user": actor.user_id, "cipher": cipher.encrypt(secret.encode()).decode(), "expires": now+timedelta(minutes=5)})
                audit(connection, actor.user_id, "auth.enroll.started", factor_id, request_id, now)
                result = Enrollment(factor_id=factor_id, secret=secret,
                                    provisioning_uri=pyotp.TOTP(secret).provisioning_uri(name=actor.username, issuer_name="WMS"))
        if result is None:
            raise DomainError("UNAUTHENTICATED", "Không xác nhận được mật khẩu.")
        return result

    def confirm_enrollment(self, token, factor_id, code, request_id):
        now = self.clock()
        success = False
        with self.engine.begin() as connection:
            actor, user = self.lock_actor(connection, token, now)
            key = self.throttle(connection, "MFA", actor.user_id, now)
            factor = row(connection, "SELECT * FROM wms.mfa_factor WHERE id=:id AND user_id=:user FOR UPDATE", id=factor_id, user=actor.user_id)
            if (not factor or factor["revoked_at"] is not None or factor["verified_at"] is not None
                    or not factor["enrollment_expires_at"] or factor["enrollment_expires_at"] <= now):
                raise DomainError("MFA_INVALID", "Yêu cầu đăng ký MFA đã hết hạn hoặc không hợp lệ.")
            if self.verify_totp(connection, factor, code, now):
                self.clear_attempts(connection, key)
                connection.execute(text("UPDATE wms.mfa_factor SET verified_at=:now WHERE id=:id"), {"id": factor_id, "now": now})
                connection.execute(text("UPDATE wms.app_user SET auth_version=auth_version+1 WHERE id=:id"), {"id": actor.user_id})
                connection.execute(text("UPDATE wms.auth_session SET mfa_verified_at=:now,auth_version=:version WHERE id=:id"),
                                   {"now": now, "version": user["auth_version"]+1, "id": actor.session_id})
                audit(connection, actor.user_id, "auth.enroll.confirmed", factor_id, request_id, now)
                success = True
            else:
                self.failed_attempt(connection, key, now)
                audit(connection, actor.user_id, "auth.enroll.code_failed", factor_id, request_id, now)
        if not success:
            raise DomainError("MFA_INVALID", "Mã MFA sai, đã dùng hoặc đã hết hạn.")

    def bootstrap(self, username, display_name, password):
        """Local operator only. At most two initial SYSADMINs; no default credentials."""
        self.cipher()
        password_hash = hash_password(password)
        with self.engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(871624920032)"))
            count = connection.execute(text("SELECT count(*) FROM wms.app_user")).scalar_one()
            admins = connection.execute(text("""SELECT count(DISTINCT u.id) FROM wms.app_user u
                JOIN wms.user_role_grant g ON g.user_id=u.id JOIN wms.role r ON r.id=g.role_id
                WHERE r.code='SYSADMIN' AND g.scope_kind='GLOBAL' AND g.revoked_at IS NULL""")).scalar_one()
            if count >= 2 or count != admins:
                raise DomainError("BOOTSTRAP_CLOSED", "Bootstrap đã đóng; dùng quản trị tài khoản có MFA.")
            if row(connection, "SELECT id FROM wms.app_user WHERE username=:name", name=username):
                raise DomainError("USER_EXISTS", "Tên tài khoản đã tồn tại.")
            user_id, now = uuid4(), self.clock()
            connection.execute(text("""INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
                VALUES (:id,:name,:display,:password,true,0,:now)"""),
                               {"id": user_id, "name": username, "display": display_name, "password": password_hash, "now": now})
            connection.execute(text("""INSERT INTO wms.user_role_grant(id,user_id,role_id,scope_kind,valid_from,granted_by)
                SELECT :id,:user,r.id,'GLOBAL',:now,:user FROM wms.role r WHERE r.code='SYSADMIN'"""),
                               {"id": uuid4(), "user": user_id, "now": now})
            audit(connection, user_id, "iam.bootstrap", user_id, uuid4(), now)
            return user_id

    def lock_actor(self, connection, token, now, target=None):
        # Resolve without SHARE first: two concurrent credential writes must not
        # deadlock upgrading authenticate's user/session locks. Refresh and login
        # also take user before session/factor. Multi-user operations sort UUIDs.
        found = row(connection, """SELECT s.user_id FROM wms.auth_token t
            JOIN wms.auth_session s ON s.id=t.session_id
            WHERE t.token_hash=:hash AND t.kind='ACCESS'""", hash=token_hash(token))
        if not found:
            raise DomainError("UNAUTHENTICATED", "Hãy đăng nhập lại.")
        users = sorted({found["user_id"], *([target] if target else [])}, key=str)
        for user_id in users:
            row(connection, "SELECT id FROM wms.app_user WHERE id=:id FOR UPDATE", id=user_id)
        actor = self.authenticate(connection, token)
        return actor, row(connection, "SELECT * FROM wms.app_user WHERE id=:id", id=actor.user_id)

    def reauthenticate(self, connection, actor, user, password, code, request_id, now, *, mfa=False):
        # Shared across all sensitive operations; successful calls also consume
        # budget, so repeatedly generating new secrets cannot bypass throttling.
        key = self.throttle(connection, "SENSITIVE", user["id"], now)
        self.failed_attempt(connection, key, now)
        factor = row(connection, """SELECT * FROM wms.mfa_factor WHERE user_id=:id
            AND kind='TOTP' AND verified_at IS NOT NULL AND revoked_at IS NULL FOR UPDATE""", id=user["id"])
        valid = verify_password(user["password_hash"], password)
        if factor:
            valid = valid and bool(code) and self.verify_totp(connection, factor, code, now)
        elif mfa:
            valid = False
        if not valid:
            audit(connection, actor.user_id, "auth.reauthentication.failed", user["id"], request_id, now)
        return valid

    def invalidate(self, connection, user_id, now, *, mfa=False):
        connection.execute(text("UPDATE wms.app_user SET auth_version=auth_version+1 WHERE id=:id"), {"id": user_id})
        connection.execute(text("UPDATE wms.auth_session SET revoked_at=COALESCE(revoked_at,:now) WHERE user_id=:id"),
                           {"id": user_id, "now": now})
        connection.execute(text("UPDATE wms.auth_challenge SET consumed_at=COALESCE(consumed_at,:now) WHERE user_id=:id"),
                           {"id": user_id, "now": now})
        connection.execute(text("UPDATE wms.auth_password_reset SET consumed_at=COALESCE(consumed_at,:now) WHERE user_id=:id"),
                           {"id": user_id, "now": now})
        if mfa:
            connection.execute(text("UPDATE wms.mfa_factor SET revoked_at=COALESCE(revoked_at,:now) WHERE user_id=:id"),
                               {"id": user_id, "now": now})
            connection.execute(text("UPDATE wms.auth_recovery_code SET revoked_at=COALESCE(revoked_at,:now) WHERE user_id=:id"),
                               {"id": user_id, "now": now})

    def change_password(self, token, password, code, new_password, request_id):
        now, success = self.clock(), False
        with self.engine.begin() as connection:
            actor, user = self.lock_actor(connection, token, now)
            if self.reauthenticate(connection, actor, user, password, code, request_id, now):
                password_hash = hash_password(new_password)
                connection.execute(text("UPDATE wms.app_user SET password_hash=:hash WHERE id=:id"),
                                   {"id": user["id"], "hash": password_hash})
                self.invalidate(connection, user["id"], now)
                audit(connection, actor.user_id, "auth.password.changed", user["id"], request_id, now)
                success = True
        if not success:
            raise DomainError("MFA_INVALID", "Không xác nhận được mật khẩu hoặc mã MFA mới.")

    def reset_mfa(self, token, password, code, request_id):
        now, success = self.clock(), False
        with self.engine.begin() as connection:
            actor, user = self.lock_actor(connection, token, now)
            if self.reauthenticate(connection, actor, user, password, code, request_id, now, mfa=True):
                self.invalidate(connection, user["id"], now, mfa=True)
                audit(connection, actor.user_id, "auth.mfa.reset", user["id"], request_id, now)
                success = True
        if not success:
            raise DomainError("MFA_INVALID", "Không xác nhận được mật khẩu hoặc mã MFA mới.")

    def recovery_codes(self, token, password, code, request_id):
        now, result = self.clock(), None
        with self.engine.begin() as connection:
            actor, user = self.lock_actor(connection, token, now)
            if self.reauthenticate(connection, actor, user, password, code, request_id, now, mfa=True):
                connection.execute(text("UPDATE wms.auth_recovery_code SET revoked_at=:now WHERE user_id=:id AND revoked_at IS NULL"),
                                   {"id": user["id"], "now": now})
                codes = [new_token() for _ in range(8)]
                connection.execute(text("""INSERT INTO wms.auth_recovery_code(code_hash,user_id,created_at)
                    VALUES (:hash,:user,:now)"""),
                                   [{"hash": token_hash(code), "user": user["id"], "now": now} for code in codes])
                audit(connection, actor.user_id, "auth.recovery_codes.rotated", user["id"], request_id, now)
                result = RecoveryCodes(codes=codes)
        if result is None:
            raise DomainError("MFA_INVALID", "Không xác nhận được mật khẩu hoặc mã MFA mới.")
        return result

    def recover_mfa(self, challenge_token, recovery_code, request_id):
        # Password has already been checked by login. Recovery never returns an
        # MFA-verified session: the user signs in and enrolls a new factor.
        now, success = self.clock(), False
        with self.engine.begin() as connection:
            challenge = row(connection, "SELECT * FROM wms.auth_challenge WHERE token_hash=:hash", hash=token_hash(challenge_token))
            if not challenge:
                raise DomainError("MFA_INVALID", "Yêu cầu khôi phục không hợp lệ.")
            user = row(connection, "SELECT * FROM wms.app_user WHERE id=:id FOR UPDATE", id=challenge["user_id"])
            key = self.throttle(connection, "RECOVERY", user["id"], now)
            challenge = row(connection, "SELECT * FROM wms.auth_challenge WHERE token_hash=:hash FOR UPDATE", hash=token_hash(challenge_token))
            self.failed_attempt(connection, key, now)
            recovery = row(connection, """SELECT code_hash FROM wms.auth_recovery_code
                WHERE code_hash=:hash AND user_id=:id AND consumed_at IS NULL AND revoked_at IS NULL FOR UPDATE""",
                           hash=token_hash(recovery_code), id=user["id"])
            if (recovery and user["is_active"] and user["auth_version"] == challenge["auth_version"]
                    and challenge["consumed_at"] is None and challenge["expires_at"] > now):
                connection.execute(text("UPDATE wms.auth_recovery_code SET consumed_at=:now WHERE code_hash=:hash"),
                                   {"now": now, "hash": recovery["code_hash"]})
                self.invalidate(connection, user["id"], now, mfa=True)
                audit(connection, user["id"], "auth.mfa.recovered", user["id"], request_id, now)
                success = True
            else:
                audit(connection, user["id"], "auth.recovery.failed", user["id"], request_id, now)
        if not success:
            raise DomainError("MFA_INVALID", "Mã khôi phục sai, đã dùng hoặc yêu cầu đã hết hạn.")

    def issue_password_reset(self, token, target, password, code, reason, request_id):
        now, result = self.clock(), None
        with self.engine.begin() as connection:
            actor, user = self.lock_actor(connection, token, now, target)
            auth = Authorization(connection, actor, now)
            auth.require("iam.manage")
            if target == actor.user_id:
                raise DomainError("SELF_MODIFICATION", "Dùng chức năng đổi mật khẩu cho chính mình.")
            target_user = row(connection, "SELECT * FROM wms.app_user WHERE id=:id AND is_active", id=target)
            if not target_user:
                raise DomainError("NOT_FOUND", "Không tìm thấy tài khoản đang hoạt động.")
            # Keep the authorizing grant alive until this transaction commits.
            for grant in sorted(auth.grants("iam.manage"), key=lambda g: str(g["id"])):
                row(connection, "SELECT id FROM wms.user_role_grant WHERE id=:id FOR SHARE", id=grant["id"])
            auth.require("iam.manage")
            if self.reauthenticate(connection, actor, user, password, code, request_id, now, mfa=True):
                self.invalidate(connection, target, now)
                reset = new_token()
                connection.execute(text("""INSERT INTO wms.auth_password_reset
                    (token_hash,user_id,issued_by,auth_version,created_at,expires_at)
                    VALUES (:hash,:user,:actor,:version,:now,:expiry)"""),
                                   {"hash": token_hash(reset), "user": target, "actor": actor.user_id,
                                    "version": target_user["auth_version"]+1, "now": now, "expiry": now+timedelta(minutes=15)})
                audit(connection, actor.user_id, "iam.password_reset.issued", target, request_id, now, reason)
                result = PasswordResetToken(reset_token=reset)
        if result is None:
            raise DomainError("MFA_INVALID", "Không xác nhận được mật khẩu hoặc mã MFA mới.")
        return result

    def complete_password_reset(self, username, reset_token, new_password, request_id):
        now, success = self.clock(), False
        with self.engine.begin() as connection:
            user = row(connection, "SELECT * FROM wms.app_user WHERE username=:name FOR UPDATE", name=username)
            key = self.throttle(connection, "PASSWORD_RESET", username, now)
            self.failed_attempt(connection, key, now)
            reset = row(connection, "SELECT * FROM wms.auth_password_reset WHERE token_hash=:hash FOR UPDATE", hash=token_hash(reset_token))
            if (user and user["is_active"] and reset and reset["user_id"] == user["id"]
                    and reset["auth_version"] == user["auth_version"] and reset["consumed_at"] is None and reset["expires_at"] > now):
                password_hash = hash_password(new_password)
                connection.execute(text("UPDATE wms.app_user SET password_hash=:hash WHERE id=:id"),
                                   {"id": user["id"], "hash": password_hash})
                self.invalidate(connection, user["id"], now)
                audit(connection, user["id"], "auth.password.reset", user["id"], request_id, now)
                success = True
            else:
                audit(connection, user["id"] if user else None, "auth.password_reset.failed", None, request_id, now)
        if not success:
            raise DomainError("MFA_INVALID", "Yêu cầu đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")
