"""B04 credential lifecycle against isolated PostgreSQL and the runtime API."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy import text

from apps.server.domain.errors import DomainError
from apps.server.infrastructure.credentials import token_hash, verify_password

pytestmark = pytest.mark.integration
PASSWORD = "Test-only-password-2026!"
NEW_PASSWORD = "Changed-test-password-2026!"


def post(iam, path, body, tokens=None):
    return iam.client.post("/api/v1/" + path, json=body, headers=iam.headers(tokens) if tokens else {})


def proof(iam, secret=None, **extra):
    iam.advance()
    return {"password": PASSWORD, "code": pyotp.TOTP(secret).at(iam.now) if secret else None, **extra}


def setup_mfa(iam, name="operator", admin=False):
    user, secret = iam.user(name, mfa=True)
    if admin:
        iam.grant(user, "SYSADMIN")
    tokens = iam.login(name, secret)
    return user, secret, tokens


def issue_codes(iam, secret, tokens):
    result = post(iam, "auth/mfa/recovery-codes", proof(iam, secret), tokens)
    assert result.status_code == 200, result.text
    return result.json()["codes"]


def test_change_password_requires_fresh_totp_and_revokes_sessions_challenges(iam):
    user, secret, tokens = setup_mfa(iam)
    challenge = iam.login()
    payload = {"password": PASSWORD, "code": pyotp.TOTP(secret).at(iam.now), "new_password": NEW_PASSWORD}
    assert post(iam, "auth/password/change", payload, tokens).status_code == 401  # login counter replay
    payload = proof(iam, secret, new_password=NEW_PASSWORD)
    result = post(iam, "auth/password/change", payload, tokens)
    assert result.status_code == 200 and result.json() == {"status": "SIGNED_OUT"}
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens)).status_code == 401
    assert post(iam, "auth/refresh", {"refresh_token": tokens["refresh_token"], "device_id": str(iam.device)}).status_code == 401
    iam.advance()
    assert post(iam, "auth/mfa", {"challenge_token": challenge["challenge_token"], "code": pyotp.TOTP(secret).at(iam.now)}).status_code == 401
    assert post(iam, "auth/login", {"username": "operator", "password": PASSWORD, "device_id": str(iam.device)}).status_code == 401
    result = post(iam, "auth/login", {"username": "operator", "password": NEW_PASSWORD, "device_id": str(iam.device)})
    assert result.json()["status"] == "MFA_REQUIRED"
    with iam.engine.connect() as connection:
        assert connection.execute(text("SELECT auth_version FROM wms.app_user WHERE id=:id"), {"id": user}).scalar_one() == 1


def test_sensitive_failures_persist_and_are_shared_across_actions(iam):
    _, secret, tokens = setup_mfa(iam)
    for _ in range(5):
        response = post(iam, "auth/password/change", {"password": "incorrect", "new_password": NEW_PASSWORD}, tokens)
        assert response.status_code == 401
    response = post(iam, "auth/mfa/recovery-codes", proof(iam, secret), tokens)
    assert response.status_code == 429 and response.headers["Retry-After"] == "300"
    iam.advance(301)
    assert len(issue_codes(iam, secret, tokens)) == 8


def test_successful_sensitive_operations_also_throttle(iam):
    _, secret, tokens = setup_mfa(iam)
    for _ in range(5):
        assert len(issue_codes(iam, secret, tokens)) == 8
    assert post(iam, "auth/mfa/recovery-codes", proof(iam, secret), tokens).status_code == 429


def test_recovery_rotation_single_use_and_no_admin_mfa_bypass(iam, caplog):
    user, secret, tokens = setup_mfa(iam, admin=True)
    old_codes = issue_codes(iam, secret, tokens)
    codes = issue_codes(iam, secret, tokens)
    challenge = iam.login()
    body = {"challenge_token": challenge["challenge_token"], "recovery_code": old_codes[0]}
    assert post(iam, "auth/mfa/recover", body).status_code == 401
    body["recovery_code"] = codes[0]
    response = post(iam, "auth/mfa/recover", body)
    assert response.status_code == 200
    assert post(iam, "auth/mfa/recover", body).status_code == 401
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens)).status_code == 401
    plain = iam.login()
    assert plain["status"] == "AUTHENTICATED"
    assert iam.client.get("/api/v1/users", headers=iam.headers(plain)).json()["code"] == "MFA_REQUIRED"
    with iam.engine.connect() as connection:
        stored = json.dumps([dict(r) for r in connection.execute(text("SELECT * FROM wms.auth_recovery_code")).mappings()], default=str)
        audits = json.dumps([dict(r) for r in connection.execute(text("SELECT * FROM wms.audit_event")).mappings()], default=str)
        assert connection.execute(text("SELECT count(*) FROM wms.auth_recovery_code WHERE consumed_at IS NOT NULL")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM wms.auth_recovery_code WHERE revoked_at IS NULL")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM wms.mfa_factor WHERE user_id=:user AND revoked_at IS NULL"), {"user": user}).scalar_one() == 0
    assert all(value not in stored + audits + caplog.text for value in [*codes, *old_codes, secret, PASSWORD])
    # A new factor is enrolled through the existing password-confirmed workflow.
    enrollment = post(iam, "auth/mfa/enroll", {"password": PASSWORD}, plain).json()
    confirmation = post(iam, "auth/mfa/confirm", {"factor_id": enrollment["factor_id"], "code": pyotp.TOTP(enrollment["secret"]).at(iam.now)}, plain)
    assert confirmation.status_code == 200
    assert iam.client.get("/api/v1/users", headers=iam.headers(plain)).status_code == 200


def test_recovery_guessing_limit_survives_new_password_challenges(iam):
    _, secret, tokens = setup_mfa(iam)
    codes = issue_codes(iam, secret, tokens)
    for _ in range(5):
        challenge = iam.login()
        assert post(iam, "auth/mfa/recover", {"challenge_token": challenge["challenge_token"], "recovery_code": "x" * 43}).status_code == 401
    challenge = iam.login()
    payload = {"challenge_token": challenge["challenge_token"], "recovery_code": codes[0]}
    assert post(iam, "auth/mfa/recover", payload).status_code == 429
    iam.advance(301)
    assert post(iam, "auth/mfa/recover", payload).status_code == 401  # expired challenge
    payload["challenge_token"] = iam.login()["challenge_token"]
    assert post(iam, "auth/mfa/recover", payload).status_code == 200


def test_reset_mfa_reauth_and_old_factor_are_invalidated(iam):
    _, secret, tokens = setup_mfa(iam)
    codes = issue_codes(iam, secret, tokens)
    challenge = iam.login()
    assert post(iam, "auth/mfa/reset", proof(iam, secret), tokens).status_code == 200
    assert post(iam, "auth/mfa/recover", {"challenge_token": challenge["challenge_token"], "recovery_code": codes[0]}).status_code == 401
    assert iam.login()["status"] == "AUTHENTICATED"


def test_password_reset_admin_control_expiry_replay_and_target_mfa_retained(iam):
    _, admin_secret, admin = setup_mfa(iam, "administrator", admin=True)
    target, target_secret, old = setup_mfa(iam)
    path = f"users/{target}/password-reset"
    assert post(iam, path, proof(iam, target_secret, reason="Reset test"), old).status_code == 403
    assert post(iam, path, {"password": PASSWORD, "reason": "Reset test"}, admin).status_code == 401
    issued = post(iam, path, proof(iam, admin_secret, reason="Verified user request"), admin)
    assert issued.status_code == 200, issued.text
    reset = issued.json()["reset_token"]
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(old)).status_code == 401
    body = {"username": "operator", "reset_token": reset, "new_password": NEW_PASSWORD}
    assert post(iam, "auth/password/reset", {**body, "username": "administrator"}).status_code == 401
    assert post(iam, "auth/password/reset", body).status_code == 200
    assert post(iam, "auth/password/reset", body).status_code == 401
    result = post(iam, "auth/login", {"username": "operator", "password": NEW_PASSWORD, "device_id": str(iam.device)})
    assert result.json()["status"] == "MFA_REQUIRED"
    iam.advance()
    assert post(iam, "auth/mfa", {"challenge_token": result.json()["challenge_token"], "code": pyotp.TOTP(target_secret).at(iam.now)}).status_code == 200
    issued = post(iam, path, proof(iam, admin_secret, reason="Expiration test"), admin)
    assert issued.status_code == 200
    iam.advance(901)
    body["reset_token"] = issued.json()["reset_token"]
    assert post(iam, "auth/password/reset", body).status_code == 401


def test_new_reset_supersedes_old_and_revoked_admin_cannot_issue(iam):
    admin_id, secret, admin = setup_mfa(iam, "administrator", admin=True)
    target, _ = iam.user()
    path = f"users/{target}/password-reset"
    first = post(iam, path, proof(iam, secret, reason="First reset"), admin).json()["reset_token"]
    second = post(iam, path, proof(iam, secret, reason="Replacement reset"), admin).json()["reset_token"]
    payload = {"username": "operator", "reset_token": first, "new_password": NEW_PASSWORD}
    assert post(iam, "auth/password/reset", payload).status_code == 401
    with iam.engine.begin() as connection:
        connection.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:id"), {"id": admin_id, "now": iam.now})
    assert post(iam, path, proof(iam, secret, reason="Unauthorized reset"), admin).status_code == 403
    payload["reset_token"] = second
    assert post(iam, "auth/password/reset", payload).status_code == 200


@pytest.mark.parametrize("action", ["recovery", "password", "reset-token"])
def test_credential_races_use_two_postgres_sessions_and_one_commit(iam, action):
    user, secret, tokens = setup_mfa(iam)
    if action == "recovery":
        codes = issue_codes(iam, secret, tokens)
        challenge = iam.login()["challenge_token"]
        def operation():
            iam.service.recover_mfa(challenge, codes[0], uuid4())
    elif action == "password":
        payload = proof(iam, secret)
        def operation():
            iam.service.change_password(tokens["access_token"], PASSWORD, payload["code"], NEW_PASSWORD, uuid4())
    else:
        _, admin_secret, admin = setup_mfa(iam, "administrator", admin=True)
        reset = post(iam, f"users/{user}/password-reset", proof(iam, admin_secret, reason="Concurrent reset"), admin).json()["reset_token"]
        def operation():
            iam.service.complete_password_reset("operator", reset, NEW_PASSWORD, uuid4())
    gate = Barrier(2)
    def run():
        # Hold separate connections while both participants reach the barrier.
        with iam.engine.connect() as connection:
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            gate.wait(timeout=5)
            try:
                operation()
                return pid, "COMMITTED"
            except DomainError as error:
                return pid, error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len({pid for pid, _ in results}) == 2
    assert sum(status == "COMMITTED" for _, status in results) == 1
    with iam.engine.connect() as connection:
        events = {"recovery": "auth.mfa.recovered", "password": "auth.password.changed", "reset-token": "auth.password.reset"}
        assert connection.execute(text("SELECT count(*) FROM wms.audit_event WHERE action=:action"), {"action": events[action]}).scalar_one() == 1


def test_audit_failure_rolls_back_password_revocation_and_totp_counter(iam, monkeypatch):
    import apps.server.application.identity as identity
    user, secret, tokens = setup_mfa(iam)
    payload = proof(iam, secret)
    original = identity.audit
    def fail(*args, **kwargs):
        if args[2] == "auth.password.changed":
            raise RuntimeError("injected audit failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(identity, "audit", fail)
    with pytest.raises(RuntimeError):
        iam.service.change_password(tokens["access_token"], PASSWORD, payload["code"], NEW_PASSWORD, uuid4())
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens)).status_code == 200
    with iam.engine.connect() as connection:
        user_row = connection.execute(text("SELECT * FROM wms.app_user WHERE id=:id"), {"id": user}).mappings().one()
        assert user_row["auth_version"] == 0 and verify_password(user_row["password_hash"], PASSWORD)
    monkeypatch.setattr(identity, "audit", original)
    assert post(iam, "auth/password/change", {**payload, "new_password": NEW_PASSWORD}, tokens).status_code == 200


def test_audit_session_lookup_scope_allowlist_and_revocation(iam):
    admin_id, secret, admin = setup_mfa(iam, "administrator", admin=True)
    user, user_secret, ordinary = setup_mfa(iam)
    a, b = iam.warehouse("A"), iam.warehouse("B")
    iam.grant(user, "AUDITOR", a)
    headers = iam.headers(ordinary)
    for path in ["iam/events", "iam/sessions", "iam/lookup/users", "iam/lookup/warehouses"]:
        assert iam.client.get("/api/v1/" + path, headers=headers).status_code == 403
    h = iam.headers(admin)
    assert {r["id"] for r in iam.client.get("/api/v1/iam/lookup/warehouses", headers=h).json()} == {str(a), str(b)}
    assert iam.client.get("/api/v1/warehouses", headers=h).json() == []
    result = iam.client.get("/api/v1/iam/lookup/users?q=oper&limit=1", headers=h)
    assert result.json()[0]["id"] == str(user)
    sessions = iam.client.get(f"/api/v1/iam/sessions?user_id={user}", headers=h)
    assert sessions.status_code == 200 and len(sessions.json()) == 1
    assert sessions.json()[0]["is_active"]
    assert "token" not in sessions.text and "hash" not in sessions.text
    events = iam.client.get("/api/v1/iam/events?limit=1", headers=h)
    assert events.status_code == 200, events.text
    event = events.json()[0]
    assert set(event) == {"id", "actor_id", "actor_name", "action", "entity_id", "occurred_at", "request_id", "reason"}
    assert iam.client.get("/api/v1/iam/events?after=" + event["id"], headers=h).status_code == 200
    post(iam, f"users/{user}/revoke-sessions", {"reason": "Session list test"}, admin)
    assert not iam.client.get(f"/api/v1/iam/sessions?user_id={user}", headers=h).json()[0]["is_active"]
    with iam.engine.begin() as connection:
        connection.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:id"), {"id": admin_id, "now": iam.now})
    assert iam.client.get("/api/v1/iam/events", headers=h).status_code == 403
    assert secret and user_secret


@pytest.mark.parametrize("prefix_length", [10, 16, 17])
def test_upgrade_preserves_user_session_factor_and_new_secret_tables(empty_database, monkeypatch, prefix_length):
    import apps.server.infrastructure.migrations as migrations
    sources = migrations.migration_sources()
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "migration_sources", lambda: sources[:prefix_length])
        migrations.migrate(empty_database)
    user, session, factor = uuid4(), uuid4(), uuid4()
    with empty_database.begin() as connection:
        connection.execute(text("INSERT INTO wms.app_user VALUES (:id,'legacy-iam','Legacy','legacy-hash',true,7,now())"), {"id": user})
        connection.execute(text("INSERT INTO wms.auth_session VALUES (:id,:user,'legacy-refresh',:device,7,now()+interval '1 hour',NULL,now())"), {"id": session, "user": user, "device": uuid4()})
        connection.execute(text("INSERT INTO wms.mfa_factor(id,user_id,kind,credential_ciphertext,last_counter) VALUES (:id,:user,'TOTP','legacy-cipher',42)"), {"id": factor, "user": user})
    assert migrations.migrate(empty_database) == [name for name, _, _ in sources[prefix_length:]]
    assert migrations.is_ready(empty_database)
    with empty_database.connect() as connection:
        assert connection.execute(text("SELECT auth_version FROM wms.app_user WHERE id=:id"), {"id": user}).scalar_one() == 7
        assert connection.execute(text("SELECT refresh_hash FROM wms.auth_session WHERE id=:id"), {"id": session}).scalar_one() == "legacy-refresh"
        assert connection.execute(text("SELECT last_counter FROM wms.mfa_factor WHERE id=:id"), {"id": factor}).scalar_one() == 42
        assert connection.execute(text("SELECT count(*) FROM wms.auth_recovery_code")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM wms.auth_password_reset")).scalar_one() == 0


def test_password_reset_digest_and_validation_do_not_leak(iam, caplog):
    _, secret, admin = setup_mfa(iam, "administrator", admin=True)
    target, _ = iam.user()
    issued = post(iam, f"users/{target}/password-reset", proof(iam, secret, reason="Verified test"), admin)
    reset = issued.json()["reset_token"]
    invalid = post(iam, "auth/password/reset", {"username": "operator", "reset_token": reset, "new_password": "too-short"})
    assert invalid.status_code == 422 and reset not in invalid.text and "too-short" not in invalid.text
    with iam.engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM wms.auth_password_reset")).scalar_one()
        assert stored == token_hash(reset)
        audits = json.dumps([dict(r) for r in connection.execute(text("SELECT * FROM wms.audit_event")).mappings()], default=str)
    assert reset not in audits + caplog.text


def test_grant_history_keeps_request_approval_and_revocation_reasons(iam):
    _, first_secret, first = setup_mfa(iam, "adminone", admin=True)
    _, second_secret, second = setup_mfa(iam, "admintwo", admin=True)
    target, _ = iam.user()
    warehouse = iam.warehouse("HISTORY")
    requested = post(iam, "grant-requests", {"user_id": str(target), "role_code": "RECEIVER",
                     "scope_kind": "WAREHOUSE", "warehouse_id": str(warehouse), "reason": "Approved warehouse shift"}, first)
    assert requested.status_code == 201
    request_id = requested.json()["id"]
    assert post(iam, f"grant-requests/{request_id}/approve", {}, first).status_code == 409
    approved = post(iam, f"grant-requests/{request_id}/approve", {}, second)
    assert approved.status_code == 200
    grant_id = approved.json()["id"]
    assert post(iam, f"grants/{grant_id}/revoke", {"reason": "Shift ended"}, second).status_code == 200
    history = iam.client.get("/api/v1/iam/events", headers=iam.headers(second)).json()
    events = {item["action"]: item for item in history if item["entity_id"] in {request_id, grant_id}}
    assert events["iam.grant.requested"]["reason"] == "Approved warehouse shift"
    assert events["iam.grant.approved"]["reason"] == "Approved warehouse shift"
    assert events["iam.grant.revoked"]["reason"] == "Shift ended"
    assert events["iam.grant.approved"]["actor_name"] == "admintwo"
    assert first_secret and second_secret
