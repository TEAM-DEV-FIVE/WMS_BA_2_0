import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from importlib.resources import files
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.local_store.device import device_identity
from apps.desktop.local_store.receipt_recovery import ReceiptPostJournal
from apps.desktop.local_store.store import LocalStore, canonical_payload
from apps.desktop.presenters.receipts import ReceiptPresenter


@pytest.fixture
def recovery(tmp_path):
    f = SimpleNamespace(user=uuid4(), device=uuid4(), key=uuid4(), doc=uuid4(), warehouse=uuid4())
    f.settings = DesktopSettings(local_data_dir=tmp_path)
    f.endpoint = f"receipts/{f.doc}/post"
    f.body = dict(
        expected_version=3,
        execution_key=str(uuid4()),
        reason="Nhận đợt một",
        lines=[dict(document_line_id=str(uuid4()), quantity_base="40")],
    )
    f.context = dict(document_number="RCV-TEST", warehouse_id=str(f.warehouse))
    f.response = dict(
        id=str(f.doc),
        number="RCV-TEST",
        kind="RECEIPT",
        warehouse_id=str(f.warehouse),
        status="PARTIAL",
        version=4,
        request_id=str(uuid4()),
        transaction_id=str(uuid4()),
        source_order_id=str(uuid4()),
        source_order_version=4,
        source_order_status="PARTIAL",
    )
    f.ack = {k: f.response[k] for k in ["id", "status", "version", "request_id", "transaction_id"]}
    f.ack["operation_status"] = "COMMITTED"

    class Api:
        session_generation = 0
        settings = f.settings
        device_id = str(f.device)

        def __init__(self):
            self.calls, self.committed = [], {}
            self.drop_response = False

        def in_session(self, generation, callback):
            if generation != self.session_generation:
                raise ApiError("UNAUTHENTICATED", "Session changed")
            return callback()

        def command(self, method, path, body, key):
            self.calls.append((method, path, json.loads(json.dumps(body)), str(key)))
            self.committed.setdefault(str(key), f.response.copy())
            if self.drop_response:
                self.drop_response = False
                raise ApiError("TIMEOUT", "Response lost after server commit")
            return self.committed[str(key)]

        def get(self, path):
            self.calls.append(("GET", path))
            if path.startswith("receipts/"):
                return {"id": str(f.doc)}
            if path.removeprefix("operations/") not in self.committed:
                raise ApiError("NOT_FOUND", "No result")
            return f.ack.copy()

    f.api = Api()

    def journal():
        value = ReceiptPostJournal(tmp_path, f.settings.api_url)
        value.open(f.user, f.device)
        return value

    f.journal = journal
    return f


def test_device_identity_is_stable_and_corruption_is_not_replaced(tmp_path):
    first = device_identity(tmp_path)
    assert device_identity(tmp_path) == first
    assert device_identity(tmp_path / "other") != first
    with sqlite3.connect(tmp_path / "device.sqlite3") as c:
        c.execute("UPDATE device SET value='damaged'")
    with pytest.raises(ValueError):
        device_identity(tmp_path)
    with sqlite3.connect(tmp_path / "device.sqlite3") as c:
        assert c.execute("SELECT value FROM device").fetchone()[0] == "damaged"


def test_partition_has_one_owner_and_lock_released_on_close(tmp_path):
    args = dict(server_id="server", user_id=uuid4(), device_id=uuid4())
    first = LocalStore(tmp_path, **args)
    try:
        with pytest.raises(OSError, match="cửa sổ"):
            LocalStore(tmp_path, **args)
    finally:
        first.close()
    second = LocalStore(tmp_path, **args)
    second.close()


def test_future_schema_is_preserved_and_migration_failure_rolls_back(tmp_path, monkeypatch):
    import apps.desktop.local_store.store as module

    args = dict(server_id="server", user_id=uuid4(), device_id=uuid4())
    initial = LocalStore(tmp_path, **args)
    path = initial.path
    initial.close()
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="version"):
        LocalStore(tmp_path, **args)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 99
        # This is a disposable test file: recreate only v1 to test an interrupted upgrade.
        c.executescript(
            "DROP INDEX ix_pending_state_time; ALTER TABLE pending_operation DROP COLUMN context; PRAGMA user_version=1;"
        )
    real = module.files

    class Resources:
        def joinpath(self, name):
            if name == "002_recovery.sql":
                return SimpleNamespace(
                    read_text=lambda **kw: (
                        "ALTER TABLE pending_operation ADD COLUMN context TEXT; SELECT missing_column;"
                    )
                )
            return real("apps.desktop.local_store").joinpath(name)

    with monkeypatch.context() as patch:
        patch.setattr(module, "files", lambda name: Resources())
        with pytest.raises(sqlite3.OperationalError):
            LocalStore(tmp_path, **args)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "context" not in {row[1] for row in c.execute("PRAGMA table_info(pending_operation)")}
    recovered = LocalStore(tmp_path, **args)
    recovered.close()


def test_v1_journal_upgrades_without_changing_command_or_keys(tmp_path):
    user, device, key, execution = uuid4(), uuid4(), uuid4(), uuid4()
    server = "https://wms.example/api/v1"
    path = tmp_path / (
        hashlib.sha256(json.dumps([server, str(user), str(device)]).encode()).hexdigest() + ".sqlite3"
    )
    body = {"expected_version": 3, "execution_key": str(execution)}
    endpoint = f"receipts/{uuid4()}/post"
    encoded = canonical_payload(body)
    digest = hashlib.sha256(json.dumps([endpoint, str(execution), encoded]).encode()).hexdigest()
    with sqlite3.connect(path) as c:
        c.executescript(
            files("apps.desktop.local_store").joinpath("001_local.sql").read_text()
            + "\nPRAGMA user_version=1;"
        )
        c.execute(
            "INSERT INTO pending_operation(key,execution_key,server_id,user_id,endpoint,payload,payload_hash,state,updated_at) VALUES (?,?,?,?,?,?,?,'SENDING','2026-10-03T00:00:00+00:00')",
            (str(key), str(execution), server, str(user), endpoint, encoded, digest),
        )
    store = LocalStore(tmp_path, server_id=server, user_id=user, device_id=device)
    try:
        record = store.operation(key)
        assert (
            record["key"],
            record["payload_hash"],
            record["payload"],
            record["execution_key"],
            record["state"],
            record["context"],
        ) == (str(key), digest, encoded, str(execution), "UNKNOWN", "{}")
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        store.close()


def test_process_death_after_sending_checkpoint_preserves_command_and_releases_lock(recovery):
    f = recovery
    script = """
import json, os, sys
from pathlib import Path
from uuid import UUID
from apps.desktop.local_store.store import LocalStore
d = json.loads(sys.argv[1])
s = LocalStore(Path(d['directory']), server_id=d['server'], user_id=UUID(d['user']), device_id=UUID(d['device']))
s.prepare(key=UUID(d['key']), execution_key=UUID(d['body']['execution_key']), endpoint=d['endpoint'], payload=d['body'])
s.transition(UUID(d['key']), 'SENDING')
os._exit(17)
"""
    directory = f.settings.local_data_dir / "receipts"
    args = dict(
        directory=str(directory),
        server=f.settings.api_url,
        user=str(f.user),
        device=str(f.device),
        key=str(f.key),
        body=f.body,
        endpoint=f.endpoint,
    )
    result = subprocess.run([sys.executable, "-c", script, json.dumps(args)], capture_output=True, text=True)
    assert result.returncode == 17, result.stderr
    journal = f.journal()
    try:
        record, body, _, _ = journal.checked(f.key)
        assert record["state"] == "UNKNOWN" and body == f.body
        assert record["execution_key"] == f.body["execution_key"]
        assert f.api.calls == []
    finally:
        journal.close()


def test_commit_response_lost_restart_lookup_does_not_repost(recovery):
    f = recovery
    journal = f.journal()
    f.api.drop_response = True
    try:
        with pytest.raises(ApiError, match="Response lost"):
            journal.send_new(f.api, key=f.key, endpoint=f.endpoint, body=f.body, context=f.context)
        assert journal.store.operation(f.key)["state"] == "UNKNOWN"
    finally:
        journal.close()
    recovered = f.journal()
    try:
        assert recovered.snapshot()[0]["context"] == f.context
        assert recovered.lookup(f.api, f.key) == f.ack
        assert recovered.store.operation(f.key)["state"] == "COMMITTED"
        assert [call[0] for call in f.api.calls] == ["POST", "GET"]
        assert (
            json.loads(recovered.store.operation(f.key)["response"])["request_id"] == f.response["request_id"]
        )
    finally:
        recovered.close()


def test_not_found_does_not_clear_pending_and_explicit_retry_preserves_request(recovery):
    f = recovery
    journal = f.journal()
    try:
        journal.store.prepare(
            key=f.key, execution_key=UUID(f.body["execution_key"]), endpoint=f.endpoint, payload=f.body
        )
        with pytest.raises(ApiError) as error:
            journal.lookup(f.api, f.key)
        assert error.value.code == "OPERATION_UNCONFIRMED"
        assert journal.store.operation(f.key)["state"] == "READY"
        with pytest.raises(ApiError, match="Còn lệnh"):
            journal.send_new(f.api, key=uuid4(), endpoint=f.endpoint, body=f.body, context={})
        assert all(call[0] == "GET" for call in f.api.calls)
        assert journal.retry(f.api, f.key) == f.ack
        assert f.api.calls[-2][0] == "GET"
        assert f.api.calls[-1] == ("POST", f.endpoint, f.body, str(f.key))
    finally:
        journal.close()


@pytest.mark.parametrize(
    "code",
    [
        "FORBIDDEN",
        "UNAUTHENTICATED",
        "NOT_FOUND",
        "IDEMPOTENCY_MISMATCH",
        "EXECUTION_MISMATCH",
        "DATABASE_BUSY",
    ],
)
def test_ambiguous_or_authorization_error_keeps_original_request(recovery, code):
    f = recovery
    journal = f.journal()

    def reject(*args):
        raise ApiError(code, "Blocked or uncertain")

    f.api.command = reject
    try:
        with pytest.raises(ApiError):
            journal.send_new(f.api, key=f.key, endpoint=f.endpoint, body=f.body, context={})
        record, body, _, _ = journal.checked(f.key)
        assert record["state"] == "UNKNOWN" and body == f.body
        if code in {"FORBIDDEN", "UNAUTHENTICATED"}:
            f.api.get = reject
            with pytest.raises(ApiError):
                journal.retry(f.api, f.key)
            assert journal.store.operation(f.key)["state"] == "UNKNOWN"
    finally:
        journal.close()


def test_stale_version_is_a_persisted_conflict_not_a_false_commit(recovery):
    f = recovery
    journal = f.journal()

    def stale(*args):
        raise ApiError("STALE_VERSION", "Tải lại phiếu", str(uuid4()))

    f.api.command = stale
    try:
        with pytest.raises(ApiError):
            journal.send_new(f.api, key=f.key, endpoint=f.endpoint, body=f.body, context={})
        assert journal.store.operation(f.key)["state"] == "CONFLICT"
        assert journal.store.operations(unresolved_only=True) == []
        with pytest.raises(ApiError, match="từ chối"):
            journal.retry(f.api, f.key)
    finally:
        journal.close()


@pytest.mark.parametrize("checkpoint", ["prepare", "sending", "ack"])
def test_storage_failure_prevents_send_or_preserves_unknown_ack(recovery, monkeypatch, checkpoint):
    f = recovery
    journal = f.journal()
    prepare, transition = journal.store.prepare, journal.store.transition

    def full(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    def guarded(key, state, **kwargs):
        if (checkpoint == "sending" and state == "SENDING") or (checkpoint == "ack" and state == "COMMITTED"):
            full()
        transition(key, state, **kwargs)

    monkeypatch.setattr(journal.store, "transition", guarded)
    if checkpoint == "prepare":
        monkeypatch.setattr(journal.store, "prepare", full)
    with pytest.raises(sqlite3.OperationalError):
        journal.send_new(f.api, key=f.key, endpoint=f.endpoint, body=f.body, context={})
    if checkpoint != "ack":
        assert f.api.calls == []
    monkeypatch.setattr(journal.store, "prepare", prepare)
    journal.close()
    recovered = f.journal()
    try:
        if checkpoint == "ack":
            assert recovered.store.operation(f.key)["state"] == "UNKNOWN"
            assert recovered.lookup(f.api, f.key) == f.ack
            assert [call[0] for call in f.api.calls] == ["POST", "GET"]
    finally:
        recovered.close()


@pytest.mark.parametrize("field", ["id", "version", "operation_status"])
def test_wrong_lookup_ack_never_marks_committed(recovery, field):
    f = recovery
    journal = f.journal()
    try:
        journal.store.prepare(
            key=f.key, execution_key=UUID(f.body["execution_key"]), endpoint=f.endpoint, payload=f.body
        )
        wrong = {**f.ack, field: {"id": str(uuid4()), "version": 99, "operation_status": "PENDING"}[field]}
        f.api.get = lambda path: wrong
        with pytest.raises(ApiError) as error:
            journal.lookup(f.api, f.key)
        assert error.value.code == "INVALID_RESPONSE"
        assert journal.store.operation(f.key)["state"] == "READY"
    finally:
        journal.close()


def test_corrupt_payload_or_unsupported_endpoint_cannot_be_replayed(recovery):
    f = recovery
    journal = f.journal()
    try:
        journal.store.prepare(
            key=f.key, execution_key=UUID(f.body["execution_key"]), endpoint=f.endpoint, payload=f.body
        )
        with journal.store.connection:
            journal.store.connection.execute("UPDATE pending_operation SET endpoint='auth/logout'")
        with pytest.raises(ValueError, match="hash"):
            journal.retry(f.api, f.key)
        payload = canonical_payload(f.body)
        digest = hashlib.sha256(
            json.dumps(["auth/logout", f.body["execution_key"], payload]).encode()
        ).hexdigest()
        with journal.store.connection:
            journal.store.connection.execute("UPDATE pending_operation SET payload_hash=?", (digest,))
        with pytest.raises(ValueError, match="endpoint"):
            journal.retry(f.api, f.key)
        assert f.api.calls == []
    finally:
        journal.close()


def test_corrupt_context_blocks_recovery_without_erasing_the_request(recovery):
    f = recovery
    journal = f.journal()
    try:
        journal.store.prepare(
            key=f.key, execution_key=UUID(f.body["execution_key"]), endpoint=f.endpoint, payload=f.body
        )
        with journal.store.connection:
            journal.store.connection.execute("UPDATE pending_operation SET context='[]'")
        with pytest.raises(ValueError, match="context"):
            journal.snapshot()
        assert journal.store.operation(f.key)["payload"] == canonical_payload(f.body)
        assert f.api.calls == []
    finally:
        journal.close()


class View:
    def __init__(self, f):
        self.main = threading.get_ident()
        self.doc = dict(id=str(f.doc), number="RCV-TEST", warehouse_id=str(f.warehouse))
        self.errors, self.reads, self.events = [], [], []

    def main_only(self):
        assert threading.get_ident() == self.main

    def recovery_changed(self):
        self.main_only()
        self.events.append("recovery")

    def orders_busy(self):
        self.main_only()

    def orders_clear(self):
        self.main_only()
        self.reads.clear()

    def orders_error(self, message):
        self.main_only()
        self.errors.append(message)

    def orders_read(self, doc):
        self.main_only()
        self.reads.append(doc)


def settle(presenter):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        presenter.drain()
        if not presenter.recovery_busy and presenter.pending is None:
            return
        time.sleep(0.01)
    pytest.fail("Presenter did not settle")


def test_presenter_restart_loads_journal_without_post_and_uses_current_user(recovery):
    f = recovery
    view = View(f)
    first = ReceiptPresenter(view, f.api)
    key = None
    try:
        first.reset(f.user)
        settle(first)
        assert first.recovery_ready and not first.uncertain
        f.api.drop_response = True
        first.command("POST", f.endpoint, f.body)
        settle(first)
        assert first.unresolved and len(f.api.committed) == 1
        key = first.recovery_records[0]["key"]
    finally:
        first.close()
        first.finish()
    second = ReceiptPresenter(view, f.api)
    try:
        second.reset(uuid4())
        settle(second)
        assert second.recovery_records == []
        second.reset(f.user)
        settle(second)
        assert second.recovery_records[0]["key"] == key
        assert len([call for call in f.api.calls if call[0] == "POST"]) == 1
        second.lookup(key)
        settle(second)
        assert not second.uncertain and second.recovery_records[0]["state"] == "COMMITTED"
        assert view.reads == [{"id": str(f.doc)}]
        assert len([call for call in f.api.calls if call[0] == "POST"]) == 1
    finally:
        second.close()
        second.finish()


def test_presenter_session_change_discards_old_result_but_keeps_durable_command(recovery):
    f = recovery
    view, started, release = View(f), threading.Event(), threading.Event()
    command = f.api.command

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return command(*args)

    f.api.command = delayed
    presenter = ReceiptPresenter(view, f.api)
    try:
        presenter.reset(f.user)
        settle(presenter)
        presenter.command("POST", f.endpoint, f.body)
        assert started.wait(5)
        presenter.reset(uuid4())
        release.set()
        settle(presenter)
        assert presenter.recovery_records == [] and view.reads == []
        presenter.reset(f.user)
        settle(presenter)
        assert presenter.recovery_records[0]["state"] == "COMMITTED"
    finally:
        release.set()
        presenter.close()
        presenter.finish()


def test_presenter_storage_unavailable_blocks_post(recovery):
    f = recovery
    (f.settings.local_data_dir / "receipts").write_text("not a directory")
    view = View(f)
    presenter = ReceiptPresenter(view, f.api)
    try:
        presenter.reset(f.user)
        settle(presenter)
        assert not presenter.recovery_ready and presenter.uncertain
        presenter.command("POST", f.endpoint, f.body)
        assert f.api.calls == [] and view.errors
    finally:
        presenter.close()
        presenter.finish()


def test_presenter_close_during_http_keeps_the_confirmed_result(recovery):
    f = recovery
    started, release = threading.Event(), threading.Event()
    command = f.api.command

    def delayed(*args):
        result = command(*args)
        started.set()
        assert release.wait(5)
        return result

    f.api.command = delayed
    presenter = ReceiptPresenter(View(f), f.api)
    try:
        presenter.reset(f.user)
        settle(presenter)
        presenter.command("POST", f.endpoint, f.body)
        assert started.wait(5)
        presenter.close()
        release.set()
        presenter.finish()
        journal = f.journal()
        try:
            assert journal.snapshot()[0]["state"] == "COMMITTED"
        finally:
            journal.close()
    finally:
        release.set()
        if not presenter.closed:
            presenter.close()
            presenter.finish()
