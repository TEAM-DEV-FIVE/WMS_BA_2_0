"""B04 worker isolation, unknown outcomes, and live GUI lifecycle."""
import threading

import httpx
import pyotp
import pytest
from sqlalchemy import text
from test_admin_desktop import live_admin, wait  # noqa: F401

from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.session import SessionPresenter
from packages.contracts.identity import SessionTokens

PASSWORD = "Test-only-password-2026!"


class SessionProbe:
    def __init__(self):
        self.main = threading.get_ident()
        self.errors, self.results = [], []

    def session_busy(self):
        assert threading.get_ident() == self.main

    def session_error(self, message, *, signed_out):
        assert threading.get_ident() == self.main
        self.errors.append((message, signed_out))

    def session_result(self, action, result):
        assert threading.get_ident() == self.main
        self.results.append((action, result))


@pytest.mark.parametrize("action", ["change_password", "reset_password", "reset_mfa", "recover_mfa", "recovery_codes"])
def test_sensitive_timeout_drops_tokens_no_replay_or_traceback_cache(action, tmp_path, caplog):
    calls = []
    secret = "private-test-payload-012345678901234567890"
    def respond(request):
        assert threading.get_ident() != view.main
        calls.append(request.url.path)
        assert "idempotency-key" not in request.headers
        raise httpx.ReadTimeout(secret)
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token=secret, refresh_token=secret, expires_in=900)
    api._challenge = secret
    view = SessionProbe()
    presenter = SessionPresenter(view, api)
    body = {"password": secret, "recovery_code": secret}
    try:
        presenter.submit(action, body)
        future = presenter.pending
        result = future.result(timeout=5)
        assert future.exception() is None and secret not in repr(result)
        presenter.drain()
        assert len(calls) == 1 and not body
        assert api._tokens is None and api._challenge is None
        assert view.errors[-1][1] and "đăng nhập lại" in view.errors[-1][0]
        assert not view.results and secret not in caplog.text
        assert not list(tmp_path.rglob("*.sqlite3"))
    finally:
        presenter.close()
        presenter.finish()


def test_sensitive_response_from_previous_session_is_discarded(tmp_path):
    value = "recovery-test-secret-012345678901234567890"
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"codes": [value] * 8})))
    api._tokens = SessionTokens(access_token="fixture", refresh_token="fixture", expires_in=900)
    view = SessionProbe()
    presenter = SessionPresenter(view, api)
    try:
        presenter.submit("recovery_codes", {"password": PASSWORD, "code": "123456"})
        presenter.pending.result(timeout=5)
        api.clear()  # a logout/login happened before Tk drains the old result
        presenter.drain()
        assert not view.results and view.errors[-1][1]
        assert value not in repr(view.errors)
    finally:
        presenter.close()
        presenter.finish()


@pytest.mark.integration
@pytest.mark.gui
def test_b04_gui_lookup_reset_history_and_password_change_real_http(live_admin, caplog, tmp_path):  # noqa: F811
    h = live_admin
    user, _ = h.iam.user("b04-target")
    h.login()
    h.load("Tra người nhận")
    h.view.search.set("b04-target")
    h.view.load()
    h.done()
    assert len(h.view.rows) == 1
    h.select(str(user))
    h.load("Tra kho")
    h.select(h.warehouse)
    h.load("Yêu cầu chờ duyệt")
    assert h.view.variables["user_id"].get() == str(user)
    assert h.view.variables["warehouse_id"].get() == h.warehouse
    assert "b04-target" in h.view.lookup_labels["user_id"].get()
    assert "ADMIN-UI" in h.view.lookup_labels["warehouse_id"].get()
    assert h.view.inputs["user_id"].instate(["readonly"])
    # Same real grant request/second-person workflow, with lookup-selected IDs.
    h.view.variables["scope_kind"].set("WAREHOUSE")
    h.view.variables["role_code"].set("RECEIVER")
    h.view.variables["reason"].set("B04 lookup grant")
    h.view.request_grant()
    h.done()
    assert h.view.last_result["status"] == "PENDING"
    old = h.iam.login("b04-target")
    h.load("Đặt lại mật khẩu")
    h.select(str(user))
    with h.iam.engine.connect() as connection:
        factor = connection.execute(text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:id"), {"id": h.one}).scalar_one()
    secret = h.iam.service.cipher().decrypt(factor.encode()).decode()
    h.iam.advance()
    h.view.variables["password"].set(PASSWORD)
    h.view.variables["code"].set(pyotp.TOTP(secret).at(h.iam.now))
    h.view.variables["reason"].set("B04 verified request")
    h.view.password_reset()
    assert not h.view.variables["password"].get() and not h.view.variables["code"].get()
    h.done()
    assert h.view.reset_dialog is not None and h.view.last_result is None
    entry = next(child for child in h.view.reset_dialog.winfo_children() if child.winfo_class() == "TEntry")
    reset = entry.get()
    assert len(reset) == 43
    assert h.iam.client.get("/api/v1/auth/me", headers=h.iam.headers(old)).status_code == 401
    h.load("Lịch sử phiên")
    assert any(row["user_id"] == str(user) and not row["is_active"] for row in h.view.rows.values())
    h.load("Lịch sử bảo mật")
    assert any(row["action"] == "iam.password_reset.issued" for row in h.view.rows.values())
    session = h.shell.session_view
    h.shell.notebook.select(session)
    session.presenter.submit("reset_password", {"username": "b04-target", "reset_token": reset,
                                                "new_password": "B04-new-password-2026!"})
    wait(h.root, lambda: session.presenter.pending is None)
    assert session.presenter.api._tokens is None and h.view.presenter.user is None
    session.username.set("b04-target")
    session.password.set("B04-new-password-2026!")
    session.login()
    wait(h.root, lambda: session.presenter.pending is None)
    assert "Chưa bật" in session.status.get()
    session.presenter.submit("change_password", {"password": "B04-new-password-2026!", "new_password": PASSWORD})
    wait(h.root, lambda: session.presenter.pending is None)
    assert session.presenter.api._tokens is None
    assert h.iam.login("b04-target")["status"] == "AUTHENTICATED"
    assert reset not in caplog.text
    for file in tmp_path.rglob("*.sqlite3"):
        raw = file.read_bytes()
        assert reset.encode() not in raw and PASSWORD.encode() not in raw


@pytest.mark.integration
@pytest.mark.gui
def test_b04_gui_recovery_codes_and_new_enrollment_real_http(live_admin):  # noqa: F811
    h = live_admin
    h.login()
    session = h.shell.session_view
    h.shell.notebook.select(session)
    with h.iam.engine.connect() as connection:
        ciphertext = connection.execute(text("SELECT credential_ciphertext FROM wms.mfa_factor WHERE user_id=:id"), {"id": h.one}).scalar_one()
    secret = h.iam.service.cipher().decrypt(ciphertext.encode()).decode()
    h.iam.advance()
    session.presenter.submit("recovery_codes", {"password": PASSWORD, "code": pyotp.TOTP(secret).at(h.iam.now)})
    wait(h.root, lambda: session.presenter.pending is None)
    assert session.secret_dialog is not None
    widget = next(child for child in session.secret_dialog.winfo_children() if child.winfo_class() == "Text")
    codes = widget.get("1.0", "end").split()
    assert len(codes) == 8
    session.logout()
    assert session.secret_dialog is None
    wait(h.root, lambda: session.presenter.pending is None)
    session.username.set("admin-one")
    session.password.set(PASSWORD)
    session.login()
    wait(h.root, lambda: session.presenter.pending is None)
    assert session.presenter.api._challenge
    session.presenter.submit("recover_mfa", {"recovery_code": codes[0]})
    wait(h.root, lambda: session.presenter.pending is None)
    assert session.presenter.api._tokens is None
    session.password.set(PASSWORD)
    session.login()
    wait(h.root, lambda: session.presenter.pending is None)
    assert not h.view.presenter.allowed("users")
    session.password.set(PASSWORD)
    session.enroll()
    wait(h.root, lambda: session.presenter.pending is None)
    new_secret = session.secret.get().split(": ", 1)[1]
    session.code.set(pyotp.TOTP(new_secret).at(h.iam.now))
    session.confirm()
    wait(h.root, lambda: session.presenter.pending is None)
    assert h.view.presenter.allowed("users")
    assert not session.secret.get()


@pytest.mark.gui
def test_security_dialog_widgets_clear_and_close_on_main_thread():
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell
    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        view = shell.session_view
        view.open_security()
        root.update()
        variables = list(view.lifecycle_variables.values())
        view.lifecycle_variables["password"].set("secret-test")
        view.clear_scope()
        assert view.lifecycle_dialog is None and not view.lifecycle_variables
        assert all(not variable.get() for variable in variables)
        view.show_codes(["secret-test"] * 8)
        assert view.secret_dialog
        view.clear_scope()
        assert view.secret_dialog is None
    finally:
        shell.close()
        shell.finish()


def test_admin_reset_timeout_invalidates_session_without_replay(tmp_path):
    from uuid import uuid4

    from test_admin_presenter import View

    from apps.desktop.presenters.admin import AdminPresenter
    from packages.contracts.identity import CurrentUser

    user = CurrentUser(id=uuid4(), username="administrator", display_name="Administrator", is_active=True,
                       mfa_verified=True, global_permissions=["iam.manage"])
    writes = []
    def respond(request):
        if request.url.path.endswith("auth/me"):
            return httpx.Response(200, json=user.model_dump(mode="json"))
        writes.append(request.url.path)
        raise httpx.ReadTimeout("private transport detail")
    api = IdentityClient(DesktopSettings(local_data_dir=tmp_path), transport=httpx.MockTransport(respond))
    api._tokens = SessionTokens(access_token="fixture", refresh_token="fixture", expires_in=900)
    view = View()
    presenter = AdminPresenter(view, api)
    presenter.reset(user)
    try:
        assert presenter.write("password_reset", {"password": PASSWORD, "code": "123456", "reason": "Test reset"}, str(uuid4()))
        result = presenter.pending.result(timeout=5)
        presenter.drain()
        assert result.uncertain and result.signed_out
        assert api._tokens is None and presenter.user is None
        assert len(writes) == 1 and PASSWORD not in repr(result)
        assert view.signed_out and not view.saved
        assert not list(tmp_path.rglob("*.sqlite3"))
    finally:
        presenter.close()
        presenter.finish()
        api.close()
