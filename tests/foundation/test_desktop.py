import threading
import time
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from apps.desktop.api.client import ApiClient, ApiError, DesktopSettings
from apps.desktop.local_store.store import LocalStore
from apps.desktop.presenters.connection import ConnectionPresenter
from packages.contracts import Health


@pytest.mark.parametrize("url", ["http://192.168.1.10/api/v1", "ftp://localhost/api/v1", "https://u:secret@host/api/v1", "https://host/api/v1?token=secret", "https://host/wrong"])
def test_insecure_or_invalid_lan_url_is_rejected(url):
    with pytest.raises(ValidationError):
        DesktopSettings(api_url=url)


def test_api_client_preserves_prefix_and_contract_error():
    paths = []
    request_id = str(uuid4())
    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith("health"):
            return httpx.Response(200, json=Health(status="ok").model_dump())
        return httpx.Response(503, json={"code": "DATABASE_NOT_READY", "message": "Not ready", "request_id": request_id})
    client = ApiClient(DesktopSettings(), transport=httpx.MockTransport(respond))
    try:
        assert client.health().status == "ok"
        with pytest.raises(ApiError) as error:
            client.health(readiness=True)
        assert error.value.code == "DATABASE_NOT_READY"
        assert error.value.request_id == request_id
        assert paths == ["/api/v1/health", "/api/v1/ready"]
    finally:
        client.close()


def test_api_client_handles_timeout_without_retry():
    calls = []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive internals")
    client = ApiClient(DesktopSettings(), transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(ApiError) as error:
            client.health()
        assert error.value.code == "TIMEOUT"
        assert "sensitive" not in str(error.value)
        assert len(calls) == 1
    finally:
        client.close()


def test_presenter_nonblocking_ignores_old_result_and_updates_on_main_thread():
    gate = threading.Event()
    started = threading.Event()
    main_thread = threading.get_ident()
    class Api:
        def health(self, *, readiness=False):
            assert threading.get_ident() != main_thread
            if not readiness:
                started.set()
                assert gate.wait(timeout=5)
            return Health(status="ready" if readiness else "ok")
        def close(self):
            pass
    class View:
        def __init__(self):
            self.values = []
        def show_loading(self):
            assert threading.get_ident() == main_thread
        def show_result(self, health):
            assert threading.get_ident() == main_thread
            self.values.append(health.status)
        def show_error(self, message):
            pytest.fail(message)
    view = View()
    presenter = ConnectionPresenter(view, Api())
    try:
        presenter.check()
        assert started.wait(timeout=5)  # UI thread is free while first HTTP is blocked.
        presenter.check(readiness=True)
        presenter.pending.result(timeout=5)
        gate.set()
        presenter.executor.shutdown(wait=True)
        assert view.values == []
        presenter.drain()
        assert view.values == ["ready"]
        presenter.close()
        presenter.drain()
        assert view.values == ["ready"]
    finally:
        gate.set()
        presenter.close()
        presenter.finish()


def test_local_crash_preserves_payload_key_and_isolates_user_server_device(tmp_path):
    user, device, key, execution = uuid4(), uuid4(), uuid4(), uuid4()
    identity = dict(server_id="https://wms.example/api/v1", user_id=user, device_id=device)
    store = LocalStore(tmp_path, **identity)
    draft = store.save_draft("RECEIPT", {"quantity": "80.000000"})
    payload = {"expected_version": 1, "execution_key": str(execution)}
    store.prepare(key=key, execution_key=execution, endpoint="/receipts/fixture/post", payload=payload, draft_id=draft)
    with pytest.raises(ValueError):
        store.transition(key, "COMMITTED", response={"status": "POSTED"})
    store.transition(key, "SENDING")
    original = store.operation(key)
    store.close()
    recovered = LocalStore(tmp_path, **identity)
    try:
        assert recovered.get_draft(draft)["state"] == "LOCAL_DRAFT"
        assert recovered.operation(key)["state"] == "UNKNOWN"
        for field in ["key", "payload", "payload_hash", "execution_key"]:
            assert recovered.operation(key)[field] == original[field]
        recovered.prepare(key=key, execution_key=execution, endpoint="/receipts/fixture/post", payload=payload, draft_id=draft)
        assert recovered.operation(key)["state"] == "UNKNOWN"
        with pytest.raises(ValueError):
            recovered.prepare(key=key, execution_key=execution, endpoint="/different", payload=payload, draft_id=draft)
        with pytest.raises(ValueError):
            recovered.transition(key, "COMMITTED")
        recovered.transition(key, "COMMITTED", response={"operation_status": "COMMITTED"})
        with pytest.raises(ValueError):
            recovered.transition(key, "SENDING")
        for override in [{"user_id": uuid4()}, {"device_id": uuid4()}, {"server_id": "https://other/api/v1"}]:
            other = LocalStore(tmp_path, **{**identity, **override})
            try:
                assert other.operation(key) is None
                assert other.get_draft(draft) is None
            finally:
                other.close()
    finally:
        recovered.close()


def test_local_store_rejects_credentials(tmp_path):
    store = LocalStore(tmp_path, server_id="server", user_id=uuid4(), device_id=uuid4())
    try:
        with pytest.raises(ValueError, match="Credentials"):
            store.save_draft("RECEIPT", {"nested": [{"refresh_token": "must-not-be-stored"}]})
    finally:
        store.close()


@pytest.mark.gui
def test_tk_shell_opens_calls_api_and_closes(monkeypatch):
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell
    monkeypatch.setattr(ApiClient, "health", lambda self, **kw: Health(status="ok"))
    root = tk.Tk()
    shell = DesktopShell(root, DesktopSettings())
    try:
        shell.presenter.check()
        deadline = time.monotonic() + 5
        while "Đã kết nối" not in shell.status.get() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert shell.status.get() == "Đã kết nối máy chủ."
    finally:
        shell.close()
        shell.finish()
