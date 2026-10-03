import socket
import threading
import time
from concurrent.futures import Future
from datetime import timedelta
from uuid import uuid4

import httpx
import pyotp
import pytest
import uvicorn
from sqlalchemy import text

from apps.desktop.api.client import DesktopSettings
from apps.desktop.views.shell import DesktopShell
from packages.contracts.identity import CurrentUser, SessionTokens

PASSWORD = "Test-only-password-2026!"


def wait(root, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert predicate()


@pytest.fixture
def live_admin(iam, tmp_path):
    import tkinter as tk

    one, secret_one = iam.user("admin-one", mfa=True)
    two, secret_two = iam.user("admin-two", mfa=True)
    iam.grant(one, "SYSADMIN")
    iam.grant(two, "SYSADMIN")
    warehouse = iam.warehouse("ADMIN-UI")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    shell = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        root = tk.Tk()
        shell = DesktopShell(root, DesktopSettings(
            api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1", local_data_dir=tmp_path / "local"))

        class Harness:
            def __init__(self):
                self.shell, self.root, self.iam = shell, root, iam
                self.view = shell.admin_view
                self.one, self.two, self.warehouse = str(one), str(two), str(warehouse)

            def login(self, username="admin-one", secret=secret_one):
                iam.advance()
                session = shell.session_view
                session.username.set(username)
                session.password.set(PASSWORD)
                session.login()
                assert session.password.get() == ""
                wait(root, lambda: session.presenter.pending is None)
                if secret:
                    assert "Nhập mã" in session.status.get()
                    session.code.set(pyotp.TOTP(secret).at(iam.now))
                    session.mfa()
                    assert session.code.get() == ""
                    wait(root, lambda: session.presenter.pending is None)
                assert self.view.presenter.user is not None, session.status.get()
                shell.notebook.select(self.view)
                root.update()

            def second(self):
                self.login("admin-two", secret_two)

            def load(self, entity):
                self.view.entity.set(entity)
                self.view.switch()
                self.view.load()
                self.done()
                assert self.view.status.get().startswith("Trang"), self.view.status.get()

            def done(self):
                wait(root, lambda: self.view.presenter.pending is None and not self.view.busy)

            def select(self, record_id):
                self.view.table.selection_set(record_id)
                self.view.select()
                root.update()

            def request(self, recipient, *, role="RECEIVER", scope="WAREHOUSE", warehouse_id=None):
                self.load("Yêu cầu chờ duyệt")
                values = {"user_id": recipient, "role_code": role, "scope_kind": scope,
                          "warehouse_id": (warehouse_id or self.warehouse) if scope == "WAREHOUSE" else "",
                          "valid_until": (iam.now + timedelta(days=1)).isoformat(), "reason": "Cấp quyền phục vụ ca nhận hàng"}
                for key, value in values.items():
                    self.view.variables[key].set(value)
                self.view.request_grant()
                self.done()
                assert self.view.status.get().startswith("Đã xử lý"), self.view.status.get()
                return self.view.last_result["id"]

        yield Harness()
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.integration
@pytest.mark.gui
def test_admin_tk_http_users_grants_sod_and_revocation(live_admin, caplog, tmp_path):
    h = live_admin
    h.login()
    view, iam = h.view, h.iam
    assert h.shell.session_view.warehouses == []
    assert set(view.presenter.user.global_permissions) >= {"iam.manage", "role.manage"}
    h.load("Tài khoản")
    for field, value in {"username": "created-by-ui", "display_name": "Nhân viên mới", "password": PASSWORD}.items():
        view.variables[field].set(value)
    view.action_buttons["create_user"].invoke()
    assert view.variables["password"].get() == ""
    h.done()
    assert view.status.get().startswith("Đã xử lý"), view.status.get()
    target = view.last_result["id"]
    old_tokens = iam.login("created-by-ui")
    h.load("Tài khoản")
    h.select(target)
    view.variables["reason"].set("Khóa tài khoản kiểm thử")
    view.action_buttons["lock"].invoke()
    h.done()
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(old_tokens)).status_code == 401
    h.load("Tài khoản")
    h.select(target)
    assert view.current["is_active"] is False
    view.variables["reason"].set("Mở tài khoản kiểm thử")
    view.action_buttons["unlock"].invoke()
    h.done()
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(old_tokens)).status_code == 401
    target_tokens = iam.login("created-by-ui")
    h.load("Tài khoản")
    h.select(target)
    view.variables["reason"].set("Thu hồi phiên kiểm thử")
    view.action_buttons["revoke_sessions"].invoke()
    h.done()
    assert iam.client.get("/api/v1/auth/me", headers=iam.headers(target_tokens)).status_code == 401

    h.load("Role")
    h.select("RECEIVER")
    assert view.variables["role_code"].get() == "RECEIVER"
    request_id = h.request(target)
    self_recipient_request = h.request(h.two)
    view.variables["user_id"].set(h.one)
    view.request_grant()
    h.done()
    assert "Không được tự yêu cầu" in view.status.get()
    h.load("Yêu cầu chờ duyệt")
    h.select(request_id)
    assert view.current["warehouse_id"] == h.warehouse
    assert "Cấp quyền" in view.details.get("1.0", "end")
    assert view.action_buttons["approve_grant"].instate(["disabled"])
    # Even a direct handler call is rejected by the real server's SOD guard.
    view.approve_grant()
    h.done()
    assert "quản trị viên thứ hai" in view.status.get()

    h.second()
    assert not view.rows and view.current is None
    h.load("Yêu cầu chờ duyệt")
    h.select(self_recipient_request)
    assert view.action_buttons["approve_grant"].instate(["disabled"])
    view.approve_grant()
    h.done()
    assert "không phải người nhận quyền" in view.status.get()
    h.select(request_id)
    view.action_buttons["approve_grant"].invoke()
    h.done()
    grant_id = view.last_result["id"]
    target_tokens = iam.login("created-by-ui")
    available = iam.client.get("/api/v1/warehouses", headers=iam.headers(target_tokens))
    assert [row["id"] for row in available.json()] == [h.warehouse]
    h.load("Grant đã cấp")
    h.select(grant_id)
    assert view.current["scope_kind"] == "WAREHOUSE" and view.current["valid_until"]
    view.variables["reason"].set("Kết thúc ca làm việc")
    view.action_buttons["revoke_grant"].invoke()
    h.done()
    assert iam.client.get("/api/v1/warehouses", headers=iam.headers(target_tokens)).json() == []
    h.load("Grant đã cấp")
    h.select(grant_id)
    assert view.current["revoked_at"] and view.action_buttons["revoke_grant"].instate(["disabled"])

    # Revoking our own session clears every tab immediately, including credentials.
    h.load("Tài khoản")
    h.select(h.two)
    assert view.action_buttons["lock"].instate(["disabled"])
    h.shell.session_view.password.set(PASSWORD)
    h.shell.session_view.code.set("123456")
    view.variables["reason"].set("Kết thúc phiên quản trị")
    view.revoke_sessions()
    h.done()
    assert view.presenter.user is None and not view.rows and view.last_result is None
    assert h.shell.session_view.presenter.api._tokens is None
    assert not h.shell.session_view.password.get() and not h.shell.session_view.code.get()
    assert h.shell.session_view.warehouses == []
    assert all(not v.get() for key, v in view.variables.items() if key != "scope_kind")
    assert PASSWORD not in caplog.text
    for path in tmp_path.rglob("*.sqlite3"):
        data = path.read_bytes()
        assert PASSWORD.encode() not in data and target_tokens["access_token"].encode() not in data


@pytest.mark.integration
@pytest.mark.gui
@pytest.mark.parametrize("change", ["warehouse", "role", "requester"])
def test_admin_approval_shows_live_server_changes(live_admin, change):
    h = live_admin
    target, _ = h.iam.user("recipient")
    h.login()
    request_id = h.request(str(target))
    h.second()
    h.load("Yêu cầu chờ duyệt")
    h.select(request_id)
    with h.iam.engine.begin() as connection:
        if change == "warehouse":
            connection.execute(text("UPDATE wms.warehouse SET is_active=false WHERE id=:id"), {"id": h.warehouse})
        elif change == "role":
            connection.execute(text("UPDATE wms.role SET is_active=false WHERE code='RECEIVER'"))
        else:
            connection.execute(text("UPDATE wms.user_role_grant SET revoked_at=:now WHERE user_id=:id"),
                               {"now": h.iam.now, "id": h.one})
    h.view.approve_grant()
    h.done()
    assert "không còn hợp lệ" in h.view.status.get()
    assert h.view.presenter.uncertain_resource is None


@pytest.mark.integration
@pytest.mark.gui
def test_admin_external_revocation_clears_session_and_permission_loss_disables_ui(live_admin):
    h = live_admin
    revoker, secret = h.iam.user("external-revoker", mfa=True)
    h.iam.grant(revoker, "SYSADMIN")
    external = h.iam.headers(h.iam.login("external-revoker", secret))
    h.login()
    h.load("Tài khoản")
    h.view.variables["password"].set(PASSWORD)
    response = h.iam.client.post(f"/api/v1/users/{h.one}/revoke-sessions", headers=external,
                                 json={"reason": "External session revocation"})
    assert response.status_code == 200
    h.view.load()
    h.done()
    assert not h.view.rows and not h.view.variables["password"].get()
    assert h.view.presenter.user is None and h.shell.session_view.presenter.api._tokens is None
    assert h.view.load_button.instate(["disabled"])
    h.login()
    h.load("Tài khoản")
    grants = h.iam.client.get("/api/v1/grants", headers=external).json()
    admin_grant = next(item["id"] for item in grants if item["user_id"] == h.one)
    assert h.iam.client.post(f"/api/v1/grants/{admin_grant}/revoke", headers=external,
                             json={"reason": "External role revocation"}).status_code == 200
    h.view.load()
    h.done()
    assert "không có quyền" in h.view.status.get()
    assert not h.view.rows and h.view.load_button.instate(["disabled"])


@pytest.mark.integration
@pytest.mark.gui
def test_admin_real_pagination_more_than_two_hundred_rows_and_logout(live_admin):
    h = live_admin
    # These are inert fixture users, not desktop writes or production passwords.
    with h.iam.engine.begin() as connection:
        connection.execute(text("""INSERT INTO wms.app_user(id,username,display_name,password_hash,is_active,auth_version,created_at)
            VALUES (:id,:username,'Pagination fixture','not-a-login-hash',true,0,:now)"""),
                           [{"id": uuid4(), "username": f"page-{i:03d}", "now": h.iam.now} for i in range(205)])
        connection.execute(text("""INSERT INTO wms.grant_request
            (id,user_id,role_id,scope_kind,warehouse_id,reason,requested_by,requested_at)
            SELECT :id,:user,id,'WAREHOUSE',:warehouse,'Pagination fixture',:requester,:now
            FROM wms.role WHERE code='RECEIVER'"""),
                           [{"id": uuid4(), "user": h.two, "warehouse": h.warehouse, "requester": h.one,
                             "now": h.iam.now} for _ in range(205)])
        connection.execute(text("""INSERT INTO wms.user_role_grant
            (id,user_id,role_id,scope_kind,warehouse_id,valid_from,granted_by)
            SELECT :id,:user,id,'WAREHOUSE',:warehouse,:now,:actor FROM wms.role WHERE code='RECEIVER'"""),
                           [{"id": uuid4(), "user": h.two, "warehouse": h.warehouse, "actor": h.one,
                             "now": h.iam.now} for _ in range(205)])
    h.login()
    for entity, count in [("Tài khoản", 207), ("Yêu cầu chờ duyệt", 205), ("Grant đã cấp", 207)]:
        h.load(entity)
        seen = set(h.view.rows)
        while h.view.next_after:
            h.view.next_button.invoke()
            h.done()
            assert not seen.intersection(h.view.rows)
            seen.update(h.view.rows)
        assert len(seen) == count and h.view.page == 3
        assert h.view.next_button.instate(["disabled"])
    h.view.variables["reason"].set("Private draft")
    h.shell.session_view.logout()
    assert not h.view.rows and not h.view.variables["reason"].get()
    wait(h.root, lambda: h.shell.session_view.presenter.pending is None)


@pytest.mark.gui
@pytest.mark.parametrize("permissions,mfa", [([], True), (["iam.manage"], True),
                                            (["role.manage"], True), (["iam.manage", "role.manage"], False)])
def test_admin_widgets_require_each_permission_and_mfa(permissions, mfa):
    import tkinter as tk

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        view = shell.admin_view
        user = CurrentUser(id=uuid4(), username="restricted", display_name="Restricted", is_active=True,
                           mfa_verified=mfa, global_permissions=permissions)
        view.session_changed(user)
        for entity, resource, permission in [("Tài khoản", "users", "iam.manage"),
                                             ("Yêu cầu chờ duyệt", "grant-requests", "role.manage"),
                                             ("Grant đã cấp", "grants", "role.manage")]:
            view.entity.set(entity)
            view.switch()
            allowed = mfa and permission in permissions
            assert view.load_button.instate(["!disabled"] if allowed else ["disabled"])
            if resource == "users":
                assert view.action_buttons["create_user"].instate(["!disabled"] if allowed else ["disabled"])
            if resource == "grant-requests":
                assert view.action_buttons["request_grant"].instate(["!disabled"] if allowed else ["disabled"])
                assert view.inputs["warehouse_id"].instate(["disabled"])
                view.variables["scope_kind"].set("WAREHOUSE")
                view.scope_changed()
                assert view.inputs["warehouse_id"].instate(["!disabled"] if allowed else ["disabled"])
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_admin_invalidation_discards_pending_session_snapshot():
    import tkinter as tk

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        user = CurrentUser(id=uuid4(), username="admin", display_name="Administrator", is_active=True,
                           mfa_verified=True, global_permissions=["iam.manage", "role.manage"])
        shell.session_changed(user, [])
        session = shell.session_view.presenter
        stale = Future()
        stale.set_result({"user": user, "warehouses": []})
        session.pending = stale
        session.results.put((session.sequence, "reload", stale))
        session.api.clear()
        shell.admin_view.presenter.drain()
        session.drain()
        assert shell.admin_view.presenter.user is None
        assert not shell.admin_view.presenter.allowed("users")
        assert "không còn hiệu lực" in shell.session_view.status.get()
    finally:
        shell.close()
        shell.finish()


@pytest.mark.gui
def test_admin_900_by_690_navigation_layout_timeout_secret_and_cleanup(caplog, tmp_path):
    import tkinter as tk

    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    view = shell.admin_view
    user = CurrentUser(id=uuid4(), username="admin", display_name="Administrator", is_active=True,
                       mfa_verified=True, global_permissions=["iam.manage", "role.manage"])
    calls = []
    started, release = threading.Event(), threading.Event()

    def respond(request):
        if request.url.path.endswith("auth/me"):
            return httpx.Response(200, json=user.model_dump(mode="json"))
        if request.method == "POST":
            calls.append(request.url.path)
            started.set()
            assert release.wait(5)
            raise httpx.ReadTimeout("test timeout")
        return httpx.Response(200, json=[])

    api = shell.session_view.presenter.api
    api.client.close()
    api.client = httpx.Client(base_url="http://localhost/api/v1/", transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="fixture-token", refresh_token="fixture-refresh", expires_in=900)
    view.session_changed(user)
    closed = False
    try:
        root.update()
        assert root.winfo_width() == 900 and root.winfo_height() == 690
        assert len(shell.navigation["values"]) == 15
        assert {"Khách trả hàng", "Trả nhà cung cấp"} <= set(shell.navigation["values"])
        assert "Giữ hàng / xuất kho" in shell.navigation["values"]
        for index, tab in enumerate(shell.notebook.tabs()):
            shell.navigation.current(index)
            shell.navigation.event_generate("<<ComboboxSelected>>")
            root.update()
            assert shell.notebook.select() == tab
        shell.notebook.select(view)
        for entity in ("Tài khoản", "Role", "Grant đã cấp", "Yêu cầu chờ duyệt"):
            view.entity.set(entity)
            view.switch()
            root.update()
            for widget in [view.selector, view.load_button, view.next_button, view.ack_button, view.hint,
                           *view.inputs.values(), *view.action_buttons.values()]:
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() >= root.winfo_rootx()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + 900
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + 690
        view.entity.set("Tài khoản")
        view.switch()
        view.variables["username"].set("new-user")
        view.variables["display_name"].set("New user")
        view.variables["password"].set(PASSWORD)
        view.create_user()
        assert not view.variables["password"].get()
        assert started.wait(5)
        view.create_user()  # Programmatic duplicate is also blocked.
        assert view.action_buttons["create_user"].instate(["disabled"])
        release.set()
        wait(root, lambda: not view.busy)
        assert len(calls) == 1 and "Chưa rõ kết quả" in view.notice.get()
        assert view.action_buttons["create_user"].instate(["disabled"])
        view.load()
        wait(root, lambda: not view.busy)
        view.ack_button.invoke()
        assert len(calls) == 1 and view.action_buttons["create_user"].instate(["!disabled"])
        assert PASSWORD not in caplog.text
        assert not list(tmp_path.rglob("*.sqlite3"))
        # Tear down Tk while a worker still owns a request, then join on the UI thread.
        started.clear()
        release.clear()
        view.variables["password"].set(PASSWORD)
        view.create_user()
        assert started.wait(5)
        shell.close()
        closed = True
        release.set()
        shell.finish()
        assert view.entity is None and view.variables == {} and view.presenter.view is None
    finally:
        release.set()
        if not closed:
            shell.close()
            shell.finish()
