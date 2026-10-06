import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy import text

from apps.server.api.app import create_app
from apps.server.domain.errors import DomainError

pytestmark = pytest.mark.integration
PASSWORD = "Test-only-password-2026!"



def test_login_logout_expiry_and_no_secret_leaks(iam, caplog):
    user, _ = iam.user()
    caplog.set_level(logging.INFO, logger="wms.api")
    tokens = iam.login()
    assert tokens["token_type"] == "bearer"
    response = iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens))
    assert response.status_code == 200
    assert response.json()["id"] == str(user)
    assert response.headers["Cache-Control"] == "no-store"
    assert "password" not in response.text
    iam.advance(901)
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens)).status_code == 401
    tokens = iam.login()
    assert iam.client.post("/api/v1/auth/logout", headers=iam.headers(tokens)).status_code == 200
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(tokens)).status_code == 401
    logs = "\n".join(r.message for r in caplog.records if r.name == "wms.api")
    with iam.engine.connect() as connection:
        events = json.dumps([dict(r) for r in connection.execute(text("SELECT action,before_data,after_data,reason FROM wms.audit_event")).mappings()], default=str)
        stored = connection.execute(text("SELECT password_hash FROM wms.app_user WHERE id=:id"), {"id": user}).scalar_one()
        assert stored.startswith("$argon2id$")
    for secret in [PASSWORD, tokens["access_token"], tokens["refresh_token"]]:
        assert secret not in logs + events


def test_login_rate_limit_persists_and_unknown_user_is_generic(iam):
    iam.user()
    for _ in range(5):
        r = iam.client.post("/api/v1/auth/login", json={"username": "operator", "password": "bad", "device_id": str(iam.device)})
        assert r.status_code == 401
    r = iam.client.post("/api/v1/auth/login", json={"username": "operator", "password": PASSWORD, "device_id": str(iam.device)})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "300"
    missing = iam.client.post("/api/v1/auth/login", json={"username": "missing", "password": "bad", "device_id": str(iam.device)})
    assert missing.status_code == 401
    iam.advance(301)
    assert iam.login()["status"] == "AUTHENTICATED"


def test_refresh_rotation_replay_revokes_family_and_device_is_checked(iam):
    iam.user()
    initial = iam.login()
    wrong_device = iam.client.post("/api/v1/auth/refresh", json={"refresh_token": initial["refresh_token"], "device_id": str(uuid4())})
    assert wrong_device.status_code == 401
    payload = {"refresh_token": initial["refresh_token"], "device_id": str(iam.device)}
    rotated = iam.client.post("/api/v1/auth/refresh", json=payload)
    assert rotated.status_code == 200
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(initial)).status_code == 401
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(rotated.json())).status_code == 200
    replay = iam.client.post("/api/v1/auth/refresh", json=payload)
    assert replay.status_code == 401 and replay.json()["code"] == "REFRESH_REPLAY"
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(rotated.json())).status_code == 401


def test_concurrent_refresh_cannot_leave_replayed_session_valid(iam):
    iam.user()
    tokens = iam.login()
    gate = Barrier(2)
    def rotate():
        gate.wait(timeout=5)
        try:
            return iam.service.refresh(tokens["refresh_token"], iam.device, uuid4())
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: rotate(), range(2)))
    assert sum(r == "REFRESH_REPLAY" for r in results) == 1
    success = next(r for r in results if not isinstance(r, str))
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(success.model_dump())).status_code == 401


def test_mfa_enrollment_login_replay_and_secret_encryption(iam):
    user, _ = iam.user()
    old = iam.login()
    current = iam.login()
    enrollment = iam.client.post("/api/v1/auth/mfa/enroll", headers=iam.headers(current), json={"password": PASSWORD})
    assert enrollment.status_code == 200, enrollment.text
    data = enrollment.json()
    code = pyotp.TOTP(data["secret"]).at(iam.now)
    confirmed = iam.client.post("/api/v1/auth/mfa/confirm", headers=iam.headers(current), json={"factor_id": data["factor_id"], "code": code})
    assert confirmed.status_code == 200, confirmed.text
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(old)).status_code == 401
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(current)).json()["mfa_verified"] is True
    challenge = iam.login()
    assert challenge["status"] == "MFA_REQUIRED" and "access_token" not in challenge
    payload = {"challenge_token": challenge["challenge_token"], "code": code}
    assert iam.client.post("/api/v1/auth/mfa", json=payload).status_code == 401
    iam.advance()
    payload["code"] = pyotp.TOTP(data["secret"]).at(iam.now)
    response = iam.client.post("/api/v1/auth/mfa", json=payload)
    assert response.status_code == 200, response.text
    assert iam.client.post("/api/v1/auth/mfa", json=payload).status_code == 401
    with iam.engine.connect() as connection:
        ciphertext = connection.execute(text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:user AND verified_at IS NOT NULL"), {"user": user}).scalar_one()
        assert data["secret"] not in ciphertext
        assert iam.service.cipher().decrypt(ciphertext.encode()).decode() == data["secret"]


def test_mfa_challenges_expire_and_rate_limit_survives_new_challenge(iam):
    iam.user(mfa=True)
    challenge = iam.login()
    iam.advance(301)
    assert iam.client.post("/api/v1/auth/mfa", json={"challenge_token": challenge["challenge_token"], "code": "xxxxxx"}).status_code == 401
    for _ in range(5):
        challenge = iam.login()
        assert iam.client.post("/api/v1/auth/mfa", json={"challenge_token": challenge["challenge_token"], "code": "xxxxxx"}).status_code == 401
    challenge = iam.login()
    assert iam.client.post("/api/v1/auth/mfa", json={"challenge_token": challenge["challenge_token"], "code": "xxxxxx"}).status_code == 429


def test_lock_or_revoke_has_immediate_effect_on_open_session(iam):
    admin, secret = iam.user("adminone", mfa=True)
    iam.grant(admin, "SYSADMIN")
    target, _ = iam.user()
    current = iam.login()
    admin_tokens = iam.login("adminone", secret)
    route = f"/api/v1/users/{target}/active"
    assert iam.client.patch(route, headers=iam.headers(current), json={"is_active": False, "reason": "Test lock"}).status_code == 403
    r = iam.client.patch(route, headers=iam.headers(admin_tokens), json={"is_active": False, "reason": "Test lock"})
    assert r.status_code == 200
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(current)).status_code == 401
    assert iam.client.patch(route, headers=iam.headers(admin_tokens), json={"is_active": True, "reason": "Test unlock"}).status_code == 200
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(current)).status_code == 401
    fresh = iam.login()
    r = iam.client.post(f"/api/v1/users/{target}/revoke-sessions", headers=iam.headers(admin_tokens), json={"reason": "Test revoke"})
    assert r.status_code == 200
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(fresh)).status_code == 401


def test_scope_is_not_cross_product_and_price_is_hidden_at_api(iam):
    user, _ = iam.user()
    a, b, c = (iam.warehouse(name) for name in ["A", "B", "C"])
    iam.grant(user, "CONTROLLER", a)
    grant_b = iam.grant(user, "RECEIVER", b)
    tokens = iam.login()
    headers = iam.headers(tokens)
    assert {x["id"] for x in iam.client.get("/api/v1/warehouses", headers=headers).json()} == {str(a), str(b)}
    assert "document.approve" in iam.client.get(f"/api/v1/warehouses/{a}/permissions", headers=headers).json()
    assert "document.approve" not in iam.client.get(f"/api/v1/warehouses/{b}/permissions", headers=headers).json()
    assert iam.client.get(f"/api/v1/warehouses/{c}/permissions", headers=headers).status_code == 404
    docs = [iam.document(wh, user) for wh in [a, b, c]]
    assert iam.client.get(f"/api/v1/documents/{docs[0]}", headers=headers).json()["lines"][0]["reference_unit_price"] == "99.0000"
    body = iam.client.get(f"/api/v1/documents/{docs[1]}", headers=headers).json()
    assert "reference_unit_price" not in body["lines"][0]
    assert iam.client.get(f"/api/v1/documents/{docs[2]}", headers=headers).status_code == 404
    with iam.engine.begin() as conn:
        conn.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE id=:id"), {"now": iam.now, "id": grant_b})
    assert iam.client.get(f"/api/v1/documents/{docs[1]}", headers=headers).status_code == 404


def test_restricted_document_visibility_and_global_scope(iam):
    user, _ = iam.user()
    other, _ = iam.user("another")
    warehouse = iam.warehouse("A")
    iam.grant(user, "RECEIVER", warehouse)
    iam.grant(user, "CONTROLLER")  # GLOBAL must not yield warehouse permissions.
    doc = iam.document(warehouse, other)
    headers = iam.headers(iam.login())
    assert iam.client.get(f"/api/v1/documents/{doc}", headers=headers).status_code == 404
    with iam.engine.begin() as conn:
        conn.execute(text("INSERT INTO wms.document_assignment VALUES (:id,:doc,:user,:assigner)"),
                     {"id": uuid4(), "doc": doc, "user": user, "assigner": other})
    assert iam.client.get(f"/api/v1/documents/{doc}", headers=headers).status_code == 200
    assert "price.read" not in iam.client.get(f"/api/v1/warehouses/{warehouse}/permissions", headers=headers).json()


def test_expired_future_and_all_warehouse_grants(iam):
    user, _ = iam.user()
    a, b = iam.warehouse("A"), iam.warehouse("B")
    expired = iam.grant(user, "RECEIVER", a, until=iam.now-timedelta(seconds=1))
    future = iam.grant(user, "RECEIVER", b)
    with iam.engine.begin() as conn:
        conn.execute(text("UPDATE wms.user_role_grant SET valid_from=:future WHERE id=:id"), {"future": iam.now+timedelta(days=1), "id": future})
    headers = iam.headers(iam.login())
    assert iam.client.get("/api/v1/warehouses", headers=headers).json() == []
    iam.grant(user, "AUDITOR", scope="ALL_WAREHOUSES")
    assert len(iam.client.get("/api/v1/warehouses", headers=headers).json()) == 2
    assert "audit.security.read" not in iam.client.get("/api/v1/auth/me", headers=headers).json()["global_permissions"]
    assert expired


def test_sysadmin_requires_mfa_and_never_implicitly_gets_stock(iam):
    admin, _ = iam.user()
    iam.grant(admin, "SYSADMIN")
    iam.warehouse("A")
    headers = iam.headers(iam.login())
    response = iam.client.get("/api/v1/users", headers=headers)
    assert response.status_code == 403 and response.json()["code"] == "MFA_REQUIRED"
    assert iam.client.get("/api/v1/warehouses", headers=headers).json() == []


def test_two_person_grant_approval_and_revoke(iam):
    first, secret1 = iam.user("adminone", mfa=True)
    second, secret2 = iam.user("admintwo", mfa=True)
    target, _ = iam.user()
    for user in [first, second]:
        iam.grant(user, "SYSADMIN")
    warehouse = iam.warehouse("A")
    h1 = iam.headers(iam.login("adminone", secret1))
    h2 = iam.headers(iam.login("admintwo", secret2))
    target_headers = iam.headers(iam.login())
    payload = {"user_id": str(target), "role_code": "RECEIVER", "scope_kind": "WAREHOUSE", "warehouse_id": str(warehouse), "reason": "Test access"}
    assert iam.client.post("/api/v1/grant-requests", headers=h1, json={**payload, "user_id": str(first)}).status_code == 409
    pending = iam.client.post("/api/v1/grant-requests", headers=h1, json=payload)
    assert pending.status_code == 201, pending.text
    route = f"/api/v1/grant-requests/{pending.json()['id']}/approve"
    assert iam.client.get("/api/v1/warehouses", headers=target_headers).json() == []
    assert iam.client.post(route, headers=h1).status_code == 409
    approved = iam.client.post(route, headers=h2)
    assert approved.status_code == 200, approved.text
    assert iam.client.post(route, headers=h2).json() == approved.json()
    assert len(iam.client.get("/api/v1/warehouses", headers=target_headers).json()) == 1
    revoked = iam.client.post(f"/api/v1/grants/{approved.json()['id']}/revoke", headers=h2, json={"reason": "Test revoke"})
    assert revoked.status_code == 200
    assert iam.client.get("/api/v1/warehouses", headers=target_headers).json() == []


def test_bootstrap_limited_to_initial_two_admins(iam):
    first = iam.service.bootstrap("adminone", "First", PASSWORD)
    second = iam.service.bootstrap("admintwo", "Second", PASSWORD)
    assert first != second
    with pytest.raises(DomainError, match="Bootstrap"):
        iam.service.bootstrap("third", "Third", PASSWORD)


def test_approval_substitution_still_rejects_self_approval(iam):
    user, _ = iam.user()
    creator, _ = iam.user("creator")
    warehouse = iam.warehouse("A")
    iam.grant(user, "CONTROLLER", warehouse)
    tokens = iam.login()
    doc = iam.document(warehouse, creator)
    with iam.engine.begin() as connection:
        auth = iam.service.authorization(connection, tokens["access_token"])
        document = auth.document(doc)
        auth.require_approval(document)
        with pytest.raises(DomainError, match="Người"):
            auth.require_approval(document, requester_id=user)
        with pytest.raises(DomainError, match="Người"):
            auth.require_approval(document, previous_approvers=(user,))


def test_unknown_permission_denied_and_inactive_role_removes_access(iam):
    user, _ = iam.user()
    warehouse = iam.warehouse("A")
    iam.grant(user, "RECEIVER", warehouse)
    tokens = iam.login()
    with iam.engine.begin() as connection:
        auth = iam.service.authorization(connection, tokens["access_token"])
        assert not auth.allows("consignment.transfer", warehouse)
        connection.execute(text("UPDATE wms.role SET is_active=false WHERE code='RECEIVER'"))
    assert iam.client.get("/api/v1/warehouses", headers=iam.headers(tokens)).json() == []


def test_concurrent_mfa_challenge_can_only_be_used_once(iam):
    _, secret = iam.user(mfa=True)
    challenge = iam.login()
    gate = Barrier(2)
    def complete():
        gate.wait(timeout=5)
        try:
            return iam.service.complete_mfa(challenge["challenge_token"], pyotp.TOTP(secret).at(iam.now), uuid4())
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: complete(), range(2)))
    assert sum(isinstance(value, str) for value in results) == 1
    with iam.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM wms.auth_session")).scalar_one() == 1


@pytest.mark.gui
def test_desktop_login_mfa_and_revocation_over_real_http(iam):
    import socket
    import threading
    import time
    import tkinter as tk

    import uvicorn

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    user, secret = iam.user(mfa=True)
    warehouse = iam.warehouse("A")
    iam.grant(user, "RECEIVER", warehouse)
    app = create_app(iam.service.settings, engine=iam.engine)
    app.state.identity.clock = lambda: iam.now
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        view = shell.session_view
        def wait_for(text):
            deadline = time.monotonic()+5
            while text not in view.status.get() and time.monotonic()<deadline:
                root.update()
                time.sleep(0.01)
            assert text in view.status.get(), view.status.get()
        view.username.set("operator")
        view.password.set(PASSWORD)
        view.login()
        assert view.password.get() == ""
        wait_for("Nhập mã")
        view.code.set(pyotp.TOTP(secret).at(iam.now))
        view.mfa()
        assert view.code.get() == ""
        wait_for("MFA đã xác thực")
        assert len(view.warehouses) == 1
        view.selector.current(0)
        view.select_warehouse()
        wait_for("Đã chọn kho")
        assert "receipt.post" in view.permissions.get()
        with iam.engine.begin() as connection:
            connection.execute(text("UPDATE wms.app_user SET is_active=false WHERE id=:id"), {"id": user})
        view.reload()
        wait_for("thu hồi")
        assert view.warehouses == []
        assert view.permissions.get() == ""
        assert view.presenter.api._tokens is None
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
