import threading
import time
from uuid import uuid4

import httpx
import pytest

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.presenters.master_data import MasterDataPresenter
from packages.contracts import FieldError
from packages.contracts.identity import SessionTokens


class View:
    def __init__(self):
        self.main = threading.get_ident()
        self.saved, self.loaded, self.errors = [], [], []
    def catalog_busy(self):
        assert threading.get_ident() == self.main
    def catalog_clear(self):
        self.saved.clear()
        self.loaded.clear()
    def catalog_saved(self, result):
        assert threading.get_ident() == self.main
        self.saved.append(result)
    def catalog_loaded(self, *result):
        assert threading.get_ident() == self.main
        self.loaded.append(result)
    def catalog_error(self, message, *, uncertain):
        assert threading.get_ident() == self.main
        self.errors.append((message, uncertain))


def test_master_presenter_preserves_unknown_write_and_key_until_explicit_retry():
    class Api:
        session_generation = 0
        def in_session(self, generation, action):
            return action()
        def command(self, method, path, body, key):
            self.calls.append((method, path, body.copy(), key))
            if len(self.calls) == 1:
                raise ApiError("TIMEOUT", "Quá hạn")
            return {"id": "saved"}
        calls = []
    api, view = Api(), View()
    presenter = MasterDataPresenter(view, api)
    try:
        body = {"code": "EA", "name": "Chiếc"}
        presenter.save("uoms", None, body)
        body["code"] = "MUTATED-OUTSIDE"
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert presenter.uncertain and view.errors[-1][1] is True
        presenter.save("uoms", None, {"code": "OTHER"})
        assert len(api.calls) == 1
        presenter.retry()
        presenter.pending.result(timeout=5)
        presenter.drain()
        assert api.calls[0] == api.calls[1]
        assert api.calls[0][2]["code"] == "EA"
        assert presenter.uncertain is None and view.saved == [{"id": "saved"}]
    finally:
        presenter.close()
        presenter.finish()


def test_master_presenter_keeps_form_on_field_error_and_drops_old_session_response():
    gate, started = threading.Event(), threading.Event()
    class Api:
        session_generation = 0
        def in_session(self, generation, action):
            return action()
        def command(self, *args):
            raise ApiError("DUPLICATE_CODE", "Mã trùng", field_errors=[FieldError(field="code", code="DUPLICATE_CODE", message="Mã đã tồn tại")])
        def get(self, path):
            started.set()
            assert gate.wait(timeout=5)
            return {"items": [{"name": "Previous user data"}], "next_after": None}
    view = View()
    presenter = MasterDataPresenter(view, Api())
    try:
        presenter.save("uoms", None, {"code": "EA"})
        with pytest.raises(ApiError):
            presenter.pending.result(timeout=5)
        presenter.drain()
        assert view.errors == [("Mã trùng · code: Mã đã tồn tại", False)]
        assert presenter.uncertain is None
        presenter.load("uoms")
        assert started.wait(timeout=5)
        presenter.reset()
        gate.set()
        presenter.pending.result(timeout=5)
        presenter.drain()
        assert view.loaded == []
    finally:
        gate.set()
        presenter.close()
        presenter.finish()


def test_identity_client_never_sends_old_catalog_command_as_new_user():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "saved"})
    api = IdentityClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    try:
        generation = api.session_generation
        api.clear()
        api._tokens = SessionTokens(access_token="new-user", refresh_token="refresh", expires_in=900)
        with pytest.raises(ApiError, match="Phiên đã thay đổi"):
            api.in_session(generation, lambda: api.command("POST", "master/uoms", {}, uuid4()))
        assert calls == []
        api.command("POST", "master/uoms", {"code": "EA"}, uuid4())
        assert len(calls) == 1 and calls[0].headers["Idempotency-Key"]
    finally:
        api.close()


@pytest.mark.integration
@pytest.mark.gui
def test_desktop_catalog_creates_edits_filters_and_clears_on_logout(iam):
    import socket
    import tkinter as tk

    import uvicorn

    from apps.desktop.views.shell import DesktopShell

    user, _ = iam.user("catalog-ui")
    iam.grant(user, "MASTER_DATA")
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
        shell = DesktopShell(root, DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        def wait(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert predicate()
        session = shell.session_view
        session.username.set("catalog-ui")
        session.password.set("Test-only-password-2026!")
        session.login()
        view = shell.master_view
        wait(lambda: "master.write" in view.permissions)
        view.load()
        wait(lambda: view.status.get().startswith("Đã tải"))
        view.variables["code"].set("EA")
        view.variables["name"].set("Chiếc")
        view.reason.set("Tạo đơn vị từ desktop")
        view.save()
        wait(lambda: view.status.get().startswith("Đã lưu"))
        assert view.current["code"] == "EA" and view.current["version"] == 1
        view.variables["name"].set("Cái")
        view.reason.set("Sửa tên đơn vị")
        view.save()
        wait(lambda: not view.busy)
        assert view.current["version"] == 2
        view.query.set("ea")
        view.load()
        wait(lambda: not view.busy)
        assert len(view.rows) == 1 and next(iter(view.rows.values()))["name"] == "Cái"
        view.new()
        view.variables["code"].set("EA")
        view.variables["name"].set("Giữ nội dung khi lỗi")
        view.reason.set("Thử mã trùng")
        view.save()
        wait(lambda: not view.busy)
        assert "Mã đã tồn tại" in view.status.get()
        assert view.variables["name"].get() == "Giữ nội dung khi lỗi"
        # Reloading the same identity preserves an uncertain write's key/body;
        # another identity cannot see or submit it.
        pending = ("uoms", None, {"code": "PENDING", "name": "Đang chờ", "decimal_places": 0,
                   "is_active": True, "reason": "Giữ yêu cầu"}, uuid4())
        view.presenter.uncertain = pending
        session.reload()
        wait(lambda: "master.write" in view.permissions)
        assert view.presenter.uncertain == pending
        assert view.variables["code"].get() == "PENDING"
        session.logout()
        assert view.rows == {} and view.current is None and not view.permissions
        wait(lambda: session.status.get() == "Đã đăng xuất.")
    finally:
        if shell:
            shell.close()
            shell.finish()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
