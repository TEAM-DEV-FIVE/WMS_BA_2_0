import json
import threading
from uuid import uuid4

import httpx
import pytest

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.admin import AdminPresenter
from packages.contracts.identity import CurrentUser, SessionTokens


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.loaded, self.saved, self.errors, self.signed_out = [], [], [], []
        self.clears = 0

    def check_thread(self):
        assert threading.get_ident() == self.main

    def admin_busy(self):
        self.check_thread()

    def admin_clear(self):
        self.check_thread()
        self.clears += 1
        self.loaded.clear()
        self.saved.clear()

    def admin_loaded(self, *args):
        self.check_thread()
        self.loaded.append(args)

    def admin_saved(self, *args):
        self.check_thread()
        self.saved.append(args)

    def admin_error(self, message):
        self.check_thread()
        self.errors.append(message)

    def admin_signed_out(self, message):
        self.check_thread()
        self.signed_out.append(message)


def current_user(*permissions, mfa=True):
    return CurrentUser(id=uuid4(), username="admin", display_name="Administrator", is_active=True,
                       mfa_verified=mfa, global_permissions=list(permissions))


@pytest.fixture
def setup_admin():
    active = []

    def create(handler, user=None):
        user = user or current_user("iam.manage", "role.manage")
        main = threading.get_ident()
        calls = []

        def respond(request):
            assert threading.get_ident() != main
            calls.append((request.method, request.url.path, dict(request.url.params)))
            if request.url.path.endswith("/auth/me"):
                return httpx.Response(200, json=user.model_dump(mode="json"))
            return handler(request)

        api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
        api._tokens = SessionTokens(access_token="test-access", refresh_token="test-refresh", expires_in=900)
        view = View()
        presenter = AdminPresenter(view, api)
        presenter.reset(user.model_copy(deep=True))
        active.append((presenter, api))
        return presenter, api, view, calls

    yield create
    for presenter, api in active:
        presenter.close()
        presenter.finish()
        api.close()


def complete(presenter):
    future = presenter.pending
    result = future.result(timeout=5)
    presenter.drain()
    return result


@pytest.mark.parametrize("permissions,mfa,resource,allowed", [
    ([], True, "users", False), (["role.manage"], True, "users", False),
    (["iam.manage"], True, "roles", False), (["iam.manage", "role.manage"], False, "users", False),
    (["iam.manage", "role.manage"], False, "grant-requests", False),
    (["iam.manage"], True, "users", True), (["role.manage"], True, "roles", True),
])
def test_permissions_and_mfa_gate_each_resource(setup_admin, permissions, mfa, resource, allowed):
    presenter, _, view, calls = setup_admin(lambda _: httpx.Response(200, json=[]), current_user(*permissions, mfa=mfa))
    assert presenter.load(resource) is allowed
    if allowed:
        complete(presenter)
        assert view.loaded
    else:
        assert not calls and view.errors


@pytest.mark.parametrize("resource,cursor", [("users", "user-099"), ("grants", str(uuid4())), ("grant-requests", str(uuid4()))])
def test_paging_uses_username_or_uuid_and_checks_the_page_after_exact_limit(setup_admin, resource, cursor):
    if resource == "users":
        rows = [{"id": str(uuid4()), "username": f"user-{i:03d}", "display_name": "Fixture", "is_active": True}
                for i in range(100)]
    else:
        rows = [{"id": str(uuid4()), "user_id": str(uuid4()), "role_code": "RECEIVER", "scope_kind": "GLOBAL",
                 "warehouse_id": None, "valid_from": "2026-10-01T00:00:00Z", "valid_until": None,
                 "revoked_at": None, "reason": "Test fixture", "requested_by": str(uuid4()),
                 "requested_at": "2026-10-01T00:00:00Z"} for _ in range(100)]
    rows[-1]["username" if resource == "users" else "id"] = cursor

    def respond(request):
        return httpx.Response(200, json=[] if request.url.params.get("after") else rows)

    presenter, _, view, calls = setup_admin(respond)
    presenter.load(resource)
    complete(presenter)
    assert view.loaded[-1][2] == cursor
    presenter.load(resource, cursor)
    complete(presenter)
    assert view.loaded[-1][1:3] == ([], None)
    assert calls[-1][2] == {"limit": "100", "after": cursor}


def test_timeout_does_not_replay_or_keep_secret_and_requires_explicit_reconciliation(setup_admin, caplog, tmp_path):
    writes = []
    password = "Only-for-test-password-9087!"

    def respond(request):
        if request.method == "POST":
            writes.append(json.loads(request.content)["username"])
            assert "idempotency-key" not in request.headers
            raise httpx.ReadTimeout("transport detail " + password)
        return httpx.Response(200, json=[])

    presenter, _, view, _ = setup_admin(respond)
    body = {"username": "new-user", "display_name": "New user", "password": password}
    presenter.write("create_user", body)
    result = complete(presenter)
    assert result.uncertain and password not in repr(result)
    assert writes == ["new-user"] and presenter.uncertain_resource == "users"
    assert not presenter.write("create_user", body)
    presenter.acknowledge()
    assert presenter.uncertain_resource == "users"
    presenter.load("grants")
    complete(presenter)
    presenter.acknowledge()
    assert presenter.uncertain_resource == "users"
    presenter.load("users")
    complete(presenter)
    assert presenter.reloaded
    presenter.acknowledge()
    assert presenter.uncertain_resource is None and writes == ["new-user"]
    assert password not in caplog.text + repr(view.errors)
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_busy_guard_and_ui_thread_only_drop_response_after_reset(setup_admin):
    started, release = threading.Event(), threading.Event()

    def respond(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json=[{"id": str(uuid4()), "username": "old-user", "display_name": "Old", "is_active": True}])

    presenter, _, view, calls = setup_admin(respond)
    try:
        presenter.load("users")
        assert started.wait(5)
        future = presenter.pending
        assert not presenter.load("roles")
        assert not presenter.write("revoke_sessions", {"reason": "Test duplicate"}, str(uuid4()))
        presenter.reset()
        release.set()
        future.result(timeout=5)
        presenter.drain()
        assert not view.loaded and not view.saved and len(calls) == 2
    finally:
        release.set()


def test_cancel_between_permission_check_and_write_sends_no_command(setup_admin):
    presenter, api, view, calls = setup_admin(lambda _: pytest.fail("Cancelled write reached HTTP"))
    started, release = threading.Event(), threading.Event()
    original = api.me

    def wait_me():
        user = original()
        started.set()
        assert release.wait(5)
        return user

    api.me = wait_me
    try:
        presenter.write("revoke_sessions", {"reason": "Test cancellation"}, str(uuid4()))
        assert started.wait(5)
        future = presenter.pending
        presenter.reset()
        release.set()
        future.result(timeout=5)
        presenter.drain()
        assert len(calls) == 1 and not view.saved
    finally:
        release.set()


def test_expired_permission_is_checked_before_command_and_clears_data(setup_admin):
    user = current_user("iam.manage", "role.manage")
    presenter, _, view, calls = setup_admin(lambda _: httpx.Response(200, json=[]), user)
    presenter.load("users")
    complete(presenter)
    user.global_permissions.remove("iam.manage")
    presenter.write("create_user", {"username": "new-user", "display_name": "User", "password": "Test-password-only!"})
    complete(presenter)
    assert not view.loaded and not presenter.allowed("users")
    assert all(method == "GET" for method, _, _ in calls)
    assert "không có quyền" in view.errors[-1]


@pytest.mark.parametrize("code", ["SELF_APPROVAL", "INVALID_SCOPE", "NOT_FOUND"])
def test_server_business_errors_are_preserved_without_replay(setup_admin, code):
    request_id = str(uuid4())
    presenter, _, view, calls = setup_admin(lambda _: httpx.Response(403, json={
        "code": code, "message": "Server refused current role/warehouse/SOD", "request_id": request_id}))
    presenter.write("approve_grant", record_id=str(uuid4()))
    complete(presenter)
    assert request_id in view.errors[-1] and "Server refused" in view.errors[-1]
    assert presenter.uncertain_resource is None
    assert len([method for method, _, _ in calls if method == "POST"]) == 1


def test_self_revoke_and_external_invalidation_clear_data(setup_admin):
    presenter, api, view, _ = setup_admin(lambda _: httpx.Response(200, json={"status": "REVOKED"}))
    presenter.write("revoke_sessions", {"reason": "End current session"}, str(presenter.user.id))
    complete(presenter)
    assert api._tokens is None and presenter.user is None and view.signed_out
    presenter.reset(current_user("iam.manage"))
    api.clear()
    presenter.drain()
    assert presenter.user is None and len(view.signed_out) == 2


def test_new_login_before_result_drain_drops_old_data(setup_admin):
    presenter, api, view, _ = setup_admin(lambda _: httpx.Response(200, json=[
        {"id": str(uuid4()), "username": "old-user", "display_name": "Old", "is_active": True}]))
    presenter.load("users")
    presenter.pending.result(timeout=5)
    api.clear()
    api._tokens = SessionTokens(access_token="new-user", refresh_token="new-refresh", expires_in=900)
    presenter.drain()
    assert not view.loaded and presenter.user is None and view.signed_out


@pytest.mark.parametrize("body", [
    {"user_id": "bad", "scope_kind": "GLOBAL"},
    {"user_id": str(uuid4()), "scope_kind": "WAREHOUSE", "warehouse_id": None},
    {"user_id": str(uuid4()), "scope_kind": "GLOBAL", "warehouse_id": str(uuid4())},
    {"user_id": str(uuid4()), "scope_kind": "GLOBAL", "valid_until": "2027-01-01T00:00:00"},
])
def test_uuid_scope_and_timezone_validation_prevents_http(setup_admin, body):
    presenter, _, view, calls = setup_admin(lambda _: pytest.fail("Invalid input reached HTTP"))
    assert not presenter.write("request_grant", {"role_code": "RECEIVER", "reason": "Test scope", **body})
    assert not calls and view.errors


def test_invalid_password_validation_never_exposes_secret(setup_admin, caplog):
    presenter, _, view, calls = setup_admin(lambda _: pytest.fail("Invalid input reached HTTP"))
    assert not presenter.write("create_user", {"username": "new-user", "display_name": "New", "password": "secret-1"})
    assert not calls and "secret-1" not in repr(view.errors) + caplog.text


@pytest.mark.parametrize("scope", ["GLOBAL", "WAREHOUSE", "ALL_WAREHOUSES"])
def test_role_only_admin_can_request_each_scope_without_warehouse_or_user_lookup(setup_admin, scope):
    user_id, warehouse_id = str(uuid4()), str(uuid4()) if scope == "WAREHOUSE" else None

    def respond(request):
        assert request.url.path.endswith("/grant-requests") and request.method == "POST"
        body = json.loads(request.content)
        assert body == {"user_id": user_id, "role_code": "RECEIVER", "scope_kind": scope,
                        "warehouse_id": warehouse_id, "valid_until": "2027-01-01T00:00:00+07:00", "reason": "Test scope"}
        return httpx.Response(201, json={"id": str(uuid4()), "status": "PENDING"})

    presenter, _, view, calls = setup_admin(respond, current_user("role.manage"))
    presenter.write("request_grant", {"user_id": user_id, "role_code": "RECEIVER", "scope_kind": scope,
                                      "warehouse_id": warehouse_id, "valid_until": "2027-01-01T00:00:00+07:00", "reason": "Test scope"})
    complete(presenter)
    assert view.saved and not view.errors and len(calls) == 2


@pytest.mark.parametrize("action", ["load", "create_user"])
def test_invalid_success_response_is_safe_and_write_result_is_uncertain(setup_admin, action):
    presenter, _, view, _ = setup_admin(lambda _: httpx.Response(200, json=[{"password": "must-not-display"}]))
    if action == "load":
        presenter.load("users")
    else:
        presenter.write(action, {"username": "new-user", "display_name": "New", "password": "Test-password-only!"})
    result = complete(presenter)
    assert result.code == "INVALID_RESPONSE" and result.uncertain == (action != "load")
    assert "must-not-display" not in repr(result)
    assert not view.loaded and not view.saved and "must-not-display" not in repr(view.errors)


def test_close_while_worker_running_keeps_future_free_of_tk_and_does_not_render(setup_admin):
    started, release = threading.Event(), threading.Event()

    def respond(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json=[])

    presenter, _, view, _ = setup_admin(respond)
    try:
        presenter.load("users")
        assert started.wait(5)
        presenter.close()
        release.set()
        presenter.finish()
        presenter.drain()
        assert not view.loaded
    finally:
        release.set()
