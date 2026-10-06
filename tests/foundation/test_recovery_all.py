import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from importlib.resources import files
from uuid import uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from test_orders import orders  # noqa: F401
from test_printing import printing, ready  # noqa: F401
from test_receipts import receiving, totals  # noqa: F401

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient
from apps.desktop.local_store.commands import CommandStore
from apps.server.api.app import create_app
from apps.server.infrastructure.config import Settings
from packages.contracts.recovery import route_policy
from packages.contracts.recovery_routes import ROUTES

BODY = {"code": "RECOVERY", "name": "Chiếc", "decimal_places": 0, "reason": "Kiểm thử phục hồi"}


def test_every_write_has_explicit_recovery_policy():
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    try:
        writes = {(m.upper(), p.removeprefix("/api/v1/")) for p, v in app.openapi()["paths"].items()
                  for m in v if m in {"post", "put", "patch", "delete"}}
        assert writes == {(m, p) for m, p, _ in ROUTES}
        assert len(writes) == 120
        assert app.openapi()["paths"]["/api/v1/master/uoms"]["post"]["x-wms-recovery"]["mode"] == "COMMAND"
        for method, path, mode in ROUTES:
            assert route_policy(method, path) == (mode, path)
        for path in ["https://attacker.test/auth", "../users", "/master/uoms", "master/%75oms", "master/uoms?token=secret"]:
            with pytest.raises(ValueError):
                route_policy("POST", path)
    finally:
        app.state.database.dispose()


@pytest.mark.parametrize("field", ["password", "new_password", "oldPassword", "TOTP", "mfa_secret",
                                      "recovery_code", "recoveryCodes", "reset_token", "challenge_token",
                                      "access-token", "Authorization", "credentials"])
def test_secrets_rejected_before_any_journal_write(tmp_path, field):
    store = CommandStore(tmp_path, server_id="server", user_id=uuid4(), device_id=uuid4())
    try:
        with pytest.raises(ValueError):
            store.prepare_command("POST", "master/uoms", {"nested": [{field: "never-on-disk"}]}, uuid4())
        assert not store.command_list()
    finally:
        store.close()
    assert all(b"never-on-disk" not in p.read_bytes() for p in tmp_path.iterdir() if p.is_file())


def test_upgrade_v2_backs_up_and_preserves_drafts_scans_pending(tmp_path):
    user, device, draft, key, execution = [uuid4() for _ in range(5)]
    server = "server"
    path = tmp_path / (hashlib.sha256(json.dumps([server, str(user), str(device)]).encode()).hexdigest() + ".sqlite3")
    with sqlite3.connect(path) as c:
        for name in ["001_local.sql", "002_recovery.sql"]:
            c.executescript(files("apps.desktop.local_store").joinpath(name).read_text())
        c.execute("PRAGMA user_version=2")
        c.execute("INSERT INTO local_draft(id,server_id,user_id,device_id,kind,payload,state,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (str(draft), server, str(user), str(device), "RECEIPT", '{"amount":"1.000000"}', "LOCAL_DRAFT", "2026"))
        c.execute("INSERT INTO scan_event(id,draft_id,barcode,quantity,occurred_at) VALUES (?,?,?,?,?)",
                  (str(uuid4()), str(draft), "000123", "1", "2026"))
        c.execute("INSERT INTO pending_operation(key,execution_key,server_id,user_id,endpoint,payload,payload_hash,state,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (str(key), str(execution), server, str(user), "receipts/old/post", "{}", "legacy", "SENDING", "2026"))
    store = CommandStore(tmp_path, server_id=server, user_id=user, device_id=device)
    try:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert store.get_draft(draft)["payload"] == '{"amount":"1.000000"}'
        assert store.connection.execute("SELECT barcode FROM scan_event").fetchone()[0] == "000123"
        assert store.operation(key)["state"] == "UNKNOWN"
        backups = list(tmp_path.glob("*.backup.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as c:
            assert c.execute("PRAGMA user_version").fetchone()[0] == 2
            assert c.execute("SELECT state FROM pending_operation").fetchone()[0] == "SENDING"
    finally:
        store.close()


def test_envelope_hash_partition_state_cleanup_and_lock(tmp_path):
    args = dict(server_id="server", user_id=uuid4(), device_id=uuid4())
    store = CommandStore(tmp_path, **args)
    key, draft, warehouse = uuid4(), uuid4(), str(uuid4())
    try:
        store.prepare_command("POST", "master/uoms", BODY, key, warehouse)
        store.prepare_command("POST", "master/categories", {"name": "nháp"}, draft, warehouse, draft=True)
        with pytest.raises(ValueError):
            store.prepare_command("POST", "master/uoms", {**BODY, "name": "khác"}, key, warehouse)
        with pytest.raises(ValueError):
            store.prepare_command("POST", "master/uoms", BODY, uuid4(), warehouse)
        with pytest.raises(OSError):
            CommandStore(tmp_path, **args)
        store.command_transition(key, "SENDING")
    finally:
        store.close()
    store = CommandStore(tmp_path, **args)
    try:
        assert store.checked(key)["state"] == "UNKNOWN"
        assert store.cleanup("9999") == 0
        assert len(store.command_list(warehouse)) == 2
        assert store.command_list(str(uuid4())) == []
        store.command_transition(key, "COMMITTED", {"id": str(uuid4())})
        assert store.cleanup("9999") == 1
        assert store.checked(draft)["state"] == "DRAFT"
        with store.connection:
            store.connection.execute("UPDATE recovery_command SET warehouse_id='GLOBAL' WHERE key=?", (str(draft),))
        with pytest.raises(ValueError, match="mismatch"):
            store.checked(draft)
    finally:
        store.close()
    for changed in [dict(user_id=uuid4()), dict(server_id="other"), dict(device_id=uuid4())]:
        other = CommandStore(tmp_path, **{**args, **changed})
        assert other.command_list() == []
        other.close()


def test_only_unsent_draft_can_be_edited_or_discarded(tmp_path):
    store = CommandStore(tmp_path, server_id="server", user_id=uuid4(), device_id=uuid4())
    try:
        first = store.prepare_command("POST", "master/uoms", BODY, uuid4(), draft=True)
        updated = store.prepare_command("POST", "master/uoms", {**BODY, "name": "Cái"}, uuid4(), draft=True)
        assert first["key"] == updated["key"] and updated["envelope"]["body"]["name"] == "Cái"
        assert len(store.command_list()) == 1
        store.discard_draft(first["key"])
        assert store.command_list() == []
        key = uuid4()
        store.prepare_command("POST", "master/uoms", BODY, key)
        with pytest.raises(ValueError):
            store.discard_draft(key)
    finally:
        store.close()


@pytest.fixture
def live_recovery(iam, tmp_path):
    user, _ = iam.user("recovery")
    iam.recovery_grant = iam.grant(user, "MASTER_DATA")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        iam.desktop_settings = DesktopSettings(api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1", local_data_dir=tmp_path / "recovery")
        yield iam
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()


def desktop(f):
    api = IdentityClient(f.desktop_settings)
    api.enable_recovery()
    api.login("recovery", "Test-only-password-2026!")
    api.me()
    return api


@pytest.mark.integration
def test_lookup_is_read_only_bound_to_payload_and_current_grants(live_recovery):
    f = live_recovery
    api, key = desktop(f), uuid4()
    try:
        with pytest.raises(ApiError, match="Chưa có ACK"):
            api._recovery_request("POST", "master/uoms", BODY, key, lookup=True)
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.uom")).scalar_one() == 0
        result = api.command("POST", "master/uoms", BODY, key)
        assert api.recover(key) == result
        assert api.command("POST", "master/uoms", BODY, key) == result
        with pytest.raises(ApiError) as error:
            api._recovery_request("POST", "master/uoms", {**BODY, "name": "changed"}, key, lookup=True)
        assert error.value.code == "IDEMPOTENCY_MISMATCH"
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": f.recovery_grant})
        with pytest.raises(ApiError) as error:
            api.recover(key, retry=True)
        assert error.value.code == "FORBIDDEN"
        assert api._journal_call("checked", key)["state"] == "COMMITTED"
        assert "response" not in api.recovery_records()[0]
    finally:
        api.close()


@pytest.mark.integration
def test_draft_network_flapping_and_stale_conflict(live_recovery):
    f, key = live_recovery, uuid4()
    api = desktop(f)
    try:
        api.draft_only = True
        with pytest.raises(ApiError) as error:
            api.command("POST", "master/uoms", BODY, key)
        assert error.value.code == "DRAFT_SAVED"
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.uom")).scalar_one() == 0
        api.draft_only = False
        detail = api.recovery_detail(key)
        assert detail["editable"] and detail["body"] == BODY
        api.edit_draft(key, {**BODY, "name": "Cái"})
        assert api.recovery_detail(key)["body"]["name"] == "Cái"
        with pytest.raises(ApiError):
            api.edit_draft(key, {**BODY, "decimal_places": "bad"})
        original = api._recovery_request
        def dropped(*args, **kwargs):
            value = original(*args, **kwargs)
            if not kwargs.get("lookup"):
                raise ApiError("TIMEOUT", "Injected lost ACK after real commit")
            return value
        api._recovery_request = dropped
        with pytest.raises(ApiError):
            api.recover(key, retry=True)
        assert api._journal_call("checked", key)["state"] == "UNKNOWN"
        api._recovery_request = original
        api.draft_only = True
        with pytest.raises(ApiError) as error:
            api.command("POST", "master/uoms", {**BODY, "name": "Cái"}, key)
        assert error.value.code == "RECOVERY_REQUIRED"
        assert api._journal_call("checked", key)["state"] == "UNKNOWN"
        api.draft_only = False
        result = api.recover(key, retry=True)
        assert result["code"] == "RECOVERY"
        update = {**BODY, "expected_version": 1, "name": "Cái"}
        api.command("PUT", "master/uoms/" + result["id"], update, uuid4())
        stale = uuid4()
        with pytest.raises(ApiError) as error:
            api.command("PUT", "master/uoms/" + result["id"], update, stale)
        assert error.value.code == "STALE_VERSION"
        assert api._journal_call("checked", stale)["state"] == "CONFLICT"
        with pytest.raises(ApiError):
            api.recover(stale, retry=True)
    finally:
        api.close()


CHILD = r'''
import json, os, sys
from apps.desktop.api.client import DesktopSettings
from apps.desktop.api.identity import IdentityClient
d = json.load(sys.stdin)
api = IdentityClient(DesktopSettings(api_url=d['url'], local_data_dir=d['directory']))
api.enable_recovery()
api.login(d.get('username', 'recovery'), 'Test-only-password-2026!')
api.me()
phase = d['phase']
call = api._journal_call
def checkpoint(action, *args, **kw):
    if phase == 'before_ack' and action == 'command_transition' and args[1] == 'COMMITTED': os._exit(17)
    result = call(action, *args, **kw)
    if phase == 'prepared' and action == 'prepare_command': os._exit(17)
    if phase == 'before_send' and action == 'command_transition' and args[1] == 'SENDING': os._exit(17)
    if phase == 'after_ack' and action == 'command_transition' and args[1] == 'COMMITTED': os._exit(17)
    return result
api._journal_call = checkpoint
request = api._request
def http(*args, **kw):
    result = request(*args, **kw)
    if phase == 'after_commit' and kw.get('recovery_hash'): os._exit(17)
    return result
api._request = http
if phase == 'restart':
    rows = api.recovery_records()
    assert len(rows) == 1
    result = api.recover(d['key'], retry=True)
    print(json.dumps({'state':api.recovery_records()[0]['state'], 'id':result['id']}))
else:
    api.command('POST', d.get('path', 'master/uoms'), d['body'], d['key'])
api.close()
'''


@pytest.mark.integration
@pytest.mark.parametrize("phase", ["prepared", "before_send", "after_commit", "before_ack", "after_ack"])
def test_process_death_then_other_process_recovers_exactly_once(live_recovery, phase):
    f, key = live_recovery, uuid4()
    payload = dict(url=f.desktop_settings.api_url, directory=str(f.desktop_settings.local_data_dir), key=str(key), body=BODY, phase=phase)
    child = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert child.returncode == 17, child.stderr
    with f.engine.connect() as c:
        count = c.execute(text("SELECT count(*) FROM wms.uom")).scalar_one()
        assert count == (0 if phase in {"prepared", "before_send"} else 1)
    payload["phase"] = "restart"
    restarted = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout)["state"] == "COMMITTED"
    with f.engine.connect() as c:
        for table in ["uom", "outbox_event", "idempotency_record"]:
            assert c.execute(text(f"SELECT count(*) FROM wms.{table}")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM wms.audit_event WHERE action LIKE 'master.%'")).scalar_one() == 1
    for path in f.desktop_settings.local_data_dir.rglob("*.sqlite3"):
        data = path.read_bytes()
        assert b"Test-only-password" not in data and b"access_token" not in data and b"refresh_token" not in data


@pytest.mark.integration
def test_invalid_ack_retains_unknown_and_other_user_cannot_recover(live_recovery):
    f, key = live_recovery, uuid4()
    api = desktop(f)
    try:
        def lose_proof(response):
            response.headers.pop("X-WMS-ACK", None)
        api.client.event_hooks["response"].append(lose_proof)
        with pytest.raises(ApiError) as error:
            api.command("POST", "master/uoms", BODY, key)
        assert error.value.code == "INVALID_RESPONSE"
        assert api._journal_call("checked", key)["state"] == "UNKNOWN"
        api.client.event_hooks["response"].clear()
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.user_role_grant SET revoked_at=now() WHERE id=:id"), {"id": f.recovery_grant})
        with pytest.raises(ApiError) as error:
            api.recover(key, retry=True)
        assert error.value.code == "FORBIDDEN"
        assert api._journal_call("checked", key)["state"] == "UNKNOWN"
        with f.engine.begin() as c:
            c.execute(text("UPDATE wms.user_role_grant SET revoked_at=NULL WHERE id=:id"), {"id": f.recovery_grant})
        old_generation = api.session_generation
        api.logout()
        user, _ = f.user("other-recovery")
        f.grant(user, "MASTER_DATA")
        api.login("other-recovery", "Test-only-password-2026!")
        api.me()
        assert api.recovery_records() == []
        with pytest.raises(ApiError):
            api.recover(key, retry=True)
        with pytest.raises(ApiError):
            api.in_session(old_generation, lambda: api.command("POST", "master/uoms", BODY, uuid4()))
        api.logout()
        api.login("recovery", "Test-only-password-2026!")
        api.me()
        assert api.recover(key)["code"] == "RECOVERY"
    finally:
        api.close()


@pytest.mark.integration
def test_offline_drafts_checkpoint_before_presenter_permission_reads(live_recovery):
    from apps.desktop.presenters import (
        counting,
        custom_fields,
        fulfillment,
        moves,
        returns,
        reversals,
        transfers,
    )

    f = live_recovery
    api = desktop(f)
    calls = []
    def disconnected(request):
        calls.append(request.method)
        raise httpx.ConnectError("LAN disconnected", request=request)
    api.client.event_hooks["request"].append(disconnected)
    api.draft_only = True
    warehouse = str(uuid4())
    try:
        for module, path in [(moves, "moves"), (returns, "returns"), (transfers, "transfers"),
                             (counting, "counts"), (fulfillment, f"fulfillment/{uuid4()}/picks"),
                             (custom_fields, f"custom-fields/products/{uuid4()}"), (reversals, "reversals")]:
            worker = transfers.run_transfer_request if module is transfers else module.run_request
            method = "PUT" if module is custom_fields else "POST"
            _, _, error, generation = worker(api, api.session_generation, threading.Event(), method, path,
                                              {"reason": "Nháp đang nhập khi đứt LAN"}, uuid4(), warehouse)
            assert error[0] == "DRAFT_SAVED" and generation == api.session_generation
        assert calls == []
        rows = api.recovery_records(warehouse)
        assert len(rows) == 7 and all(row["state"] == "DRAFT" for row in rows)
    finally:
        api.close()


def crash_and_recover_business(f, tmp_path, path, body, phase):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(f.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        key = str(uuid4())
        payload = dict(url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1", directory=str(tmp_path),
                       key=key, body=body, phase=phase, username="buyer", path=path)
        child = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        assert child.returncode == 17, child.stderr
        payload["phase"] = "restart"
        result = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["state"] == "COMMITTED"
        return key
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.integration
@pytest.mark.parametrize("phase", ["before_send", "after_commit"])
def test_receipt_post_process_death_preserves_ledger_and_execution_key(receiving, tmp_path, phase):  # noqa: F811
    f = receiving
    doc = f.receipt_approve()
    body = f.post_body(doc)
    key = crash_and_recover_business(f, tmp_path, f"receipts/{doc['id']}/post", body, phase)
    assert totals(f) == (1, 1, 40, 0)
    with f.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM wms.idempotency_record WHERE key=:key"), {"key": key}).scalar_one() == 1
        assert str(c.execute(text("SELECT execution_key FROM wms.inventory_transaction")).scalar_one()) == body["execution_key"]


@pytest.mark.integration
def test_print_spool_claim_process_recovery_does_not_replay_os_io(printing, tmp_path):  # noqa: F811
    f = printing
    job = ready(f)
    body = dict(expected_version=job["version"], reason="Đối chiếu lượt in", attempt_id=str(uuid4()),
                printer="B19-no-device", driver="CUPS", copies=1)
    crash_and_recover_business(f, tmp_path / "desktop", f"printing/{job['id']}/spool", body, "after_commit")
    with f.engine.connect() as c:
        attempts = c.execute(text("SELECT status,spool_id FROM wms.print_attempt")).all()
        assert attempts == [("UNKNOWN", None)]
    assert totals(f) == (0, 0, 0, 0)


@pytest.mark.integration
@pytest.mark.gui
def test_real_tk_draft_recovery_logout_and_no_automatic_send(live_recovery):
    import tkinter as tk

    from apps.desktop.views.shell import DesktopShell

    f = live_recovery
    root = tk.Tk()
    shell = DesktopShell(root, f.desktop_settings)
    try:
        def wait(predicate):
            deadline = time.monotonic() + 12
            while not predicate() and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert predicate()
        session, view, recovery = shell.session_view, shell.master_view, shell.recovery_view
        session.username.set("recovery")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: "master.write" in view.permissions)
        shell.draft_only.set(True)
        shell.set_draft_mode()
        view.variables["code"].set("RECOVERY")
        view.variables["name"].set("Chiếc")
        view.reason.set("Nháp trước khi gửi")
        view.save()
        wait(lambda: not view.busy)
        assert "nháp" in view.status.get()
        recovery.refresh()
        wait(lambda: len(recovery.rows) == 1)
        key = next(iter(recovery.rows))
        assert recovery.rows[key]["state"] == "DRAFT"
        recovery.submit("detail", key)
        wait(lambda: recovery.detail is not None)
        field = next(item for item, (path, _) in recovery.fields.items() if path == ("name",))
        recovery.detail_tree.selection_set(field)
        root.update()
        recovery.edit_value.set("Cái từ nháp")
        recovery.edit_field()
        recovery.save_edits()
        wait(lambda: recovery.pending is None)
        with f.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM wms.uom")).scalar_one() == 0
        # Explicit operator retry uses the actual HTTP worker; no mock API/DB.
        recovery.submit("retry", key)
        wait(lambda: recovery.rows.get(key, {}).get("state") == "COMMITTED")
        assert "xác nhận" in recovery.status.get()
        with f.engine.connect() as c:
            assert c.execute(text("SELECT name FROM wms.uom")).scalar_one() == "Cái từ nháp"
        session.logout()
        wait(lambda: session.status.get() == "Đã đăng xuất.")
        assert recovery.rows == {} and recovery.tree.get_children() == ()
    finally:
        shell.close()
        shell.finish()
