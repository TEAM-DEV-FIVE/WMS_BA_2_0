"""Import orchestration. B19 can journal ImportCommand before execute/retry.

Commands and file bytes are retained in RAM per server client/user/kind/warehouse;
no automatic writes, no new key after an uncertain result, no Tk access in workers.
"""

import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from queue import Empty, Queue
from uuid import uuid4

from apps.desktop.api.client import ApiError
from apps.desktop.api.imports import (
    ImportApi,
    SourceFile,
    check_source,
    checked_ack,
    save_bytes,
    source_file,
    upload_path,
)
from packages.contracts.imports import ImportAction, ImportCommit, ImportCreate

UNKNOWN = {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE", "UNAUTHENTICATED",
           "REFRESH_REPLAY", "FORBIDDEN", "NOT_FOUND", "DATABASE_NOT_READY", "SERVICE_UNAVAILABLE"}


@dataclass(frozen=True)
class ImportCommand:
    operation: str
    path: str
    body_json: str = field(repr=False)
    key: str
    user_id: str
    kind: str
    warehouse: str | None
    file_id: str | None = None
    job_id: str | None = None
    source: SourceFile | None = field(default=None, repr=False)
    schema_version: int = 1


class ImportPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.imports = ImportApi(api)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-imports")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = None
        self.user_id, self.kind, self.warehouse = None, "01_uom", None
        self.commands = {}
        self.checked_key = None
        self.job = self.source = self.file = None
        self.next_poll = 0

    @property
    def scope(self):
        return self.user_id, self.kind, self.warehouse

    @property
    def uncertain(self):
        return self.commands.get(self.scope)

    def reset(self, user_id=None, kind="01_uom", warehouse=None):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.user_id = str(user_id) if user_id else None
        self.kind, self.warehouse = kind, str(warehouse) if warehouse else None
        self.job = self.source = self.file = None
        self.checked_key = None
        self.view.import_clear()

    def submit(self, action, fn, context=None):
        if self.closed or self.pending is not None or not self.user_id:
            return False
        self.sequence += 1
        sequence, generation = self.sequence, self.api.session_generation
        self.view.import_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, fn)
        self.pending.add_done_callback(lambda future: self.results.put(
            (sequence, generation, action, context, future)))
        return True

    def load(self):
        warehouse = self.warehouse

        def run():
            capabilities = self.imports.capabilities()
            user = self.api.me()
            permissions = list(user.global_permissions)
            if warehouse:
                permissions.extend(self.api.permissions(warehouse))
            return capabilities, permissions

        self.submit("load", run)

    def prepare(self, path, limit, row_limit):
        if self.uncertain:
            return
        kind = self.kind
        self.source = self.file = self.job = None
        self.view.import_clear_data()
        self.submit("source", lambda: source_file(path, kind, limit, row_limit))

    def template(self, path, columns):
        def run():
            output = io.StringIO(newline="")
            csv.writer(output).writerow(columns)
            return save_bytes(path, output.getvalue().encode("utf-8-sig"))
        self.submit("download", run)

    def upload(self):
        if self.source:
            self.command("upload", upload_path(self.kind, self.warehouse), {}, source=self.source)

    def create(self, reason, reference):
        if self.file:
            body = ImportCreate(file_id=self.file["id"], reason=reason,
                                signed_count_reference=reference or None).model_dump(mode="json")
            if self.kind == "11_opening" and not reference:
                raise ValueError("Tồn đầu kỳ cần biên bản kiểm đếm đã ký.")
            self.command("create", "imports", body, file_id=self.file["id"])

    def action(self, action, reason):
        if not self.job or action not in {"commit", "cancel", "validate"}:
            return
        body = dict(expected_version=self.job["version"], reason=reason)
        if action == "commit":
            body.update(commit_token=self.job["commit_token"], file_hash=self.job["file_hash"])
        body = (ImportCommit if action == "commit" else ImportAction).model_validate(body).model_dump(mode="json")
        self.command(action, f"imports/{self.job['id']}/{action}", body,
                     file_id=self.job["file_id"], job_id=self.job["id"],
                     source=self.source if action == "commit" else None)

    def command(self, operation, path, body, **context):
        if self.closed or self.pending is not None or self.uncertain or not self.user_id:
            return
        command = ImportCommand(operation, path, json.dumps(body, sort_keys=True), str(uuid4()),
                                self.user_id, self.kind, self.warehouse, **context)
        self.commands[self.scope] = command
        self.checked_key = None

        def run():
            if command.source:
                check_source(command.source)
            return self.imports.execute(command)

        self.submit("command", run, command)

    def read(self, job_id, after=0):
        kind, warehouse = self.kind, self.warehouse
        previous = self.job

        def run():
            job = self.imports.read(job_id, kind, warehouse)
            file = self.imports.metadata(job["file_id"])
            if (file["id"] != job["file_id"] or file["sha256"] != job["file_hash"]
                    or file["warehouse_id"] != warehouse or file["kind"] != kind):
                raise ApiError("INVALID_RESPONSE", "Metadata tệp không khớp job.")
            cursor = after
            if previous and (previous["id"], previous["version"], previous["generation"]) != (job["id"], job["version"], job["generation"]):
                cursor = 0
            page = self.imports.rows(job_id, cursor)
            current = self.imports.read(job_id, kind, warehouse)
            if (current["version"], current["generation"]) != (job["version"], job["generation"]):
                raise ApiError("STALE_DATA", "Job vừa đổi; đọc lại trang dữ liệu.")
            return job, file, page, cursor

        self.submit("read", run)

    def lookup(self):
        command = self.uncertain
        if not command:
            return
        self.checked_key = None

        def run():
            if command.job_id:
                job = self.imports.read(command.job_id, command.kind, command.warehouse)
                body = json.loads(command.body_json)
                if (command.operation == "commit" and job["status"] == "COMMITTED"
                        and job["commit_token"] == body["commit_token"]
                        and job["file_hash"] == body["file_hash"]
                        and job["version"] == body["expected_version"] + 1):
                    ack = checked_ack(command, job["result"])
                    if ack["id"] != command.job_id or ack["status"] != "COMMITTED" or ack["version"] != job["version"]:
                        raise ApiError("INVALID_RESPONSE", "ACK lưu không khớp job.")
                    return ack
            elif command.file_id:
                self.imports.metadata(command.file_id)
            else:
                self.api.me()
            # No lookup-by-key route for upload/create. Only explicit exact replay
            # can recover their IDs; a successful read here is not a negative ACK.
            return None

        self.submit("lookup", run, command)

    def retry(self):
        command = self.uncertain
        if command and self.checked_key == command.key:
            self.checked_key = None
            self.submit("command", lambda: self.imports.execute(command), command)

    def download(self, path, errors=False):
        if not self.job:
            return
        job = dict(self.job)
        sequence, generation = self.sequence + 1, self.api.session_generation

        def current():
            return not self.closed and self.sequence == sequence and self.api.session_generation == generation

        def run():
            data = self.imports.download(job, errors)
            return save_bytes(path, data, current)

        self.submit("download", run)

    def drain(self):
        while True:
            try:
                sequence, generation, action, context, future = self.results.get_nowait()
            except Empty:
                break
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.view.import_clear()
                self.view.import_error("Phiên đã đổi; đăng nhập và tra lại yêu cầu.")
                continue
            try:
                result = future.result()
            except ApiError as error:
                if action == "command" and error.code not in UNKNOWN:
                    self.commands.pop(self.scope, None)
                if action == "lookup" and error.code == "NOT_FOUND":
                    self.checked_key = context.key
                if action == "read" or error.code in {"FORBIDDEN", "NOT_FOUND", "UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.job = self.file = None
                    self.view.import_clear_data()
                self.next_poll = time.monotonic() + 5
                self.view.import_error(f"{error.code}: {error}")
            except Exception:
                if action == "read":
                    self.job = self.file = None
                    self.view.import_clear_data()
                self.next_poll = time.monotonic() + 5
                self.view.import_error("Không đọc được kết quả; tra trạng thái trước khi gửi lại.")
            else:
                if action == "load":
                    self.view.import_loaded(*result)
                elif action == "source":
                    self.source = result
                    self.view.import_source(result)
                elif action == "read":
                    self.job, self.file = result[:2]
                    self.next_poll = time.monotonic() + 2
                    self.view.import_read(*result)
                elif action == "lookup" and result is None:
                    self.checked_key = context.key
                    self.view.import_checked()
                elif action in {"lookup", "command"}:
                    self.commands.pop(self.scope, None)
                    self.checked_key = None
                    if context.operation == "upload":
                        self.source, self.file = context.source, result
                    self.view.import_saved(result, context.operation)
                elif action == "download":
                    self.view.import_downloaded(result)
        if (not self.closed and self.pending is None and not self.uncertain and self.job
                and self.job["status"] in {"QUEUED", "VALIDATING"} and time.monotonic() >= self.next_poll):
            self.read(self.job["id"])

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.view = self.pending = self.job = self.source = self.file = None
        self.commands.clear()
        while not self.results.empty():
            self.results.get_nowait()
