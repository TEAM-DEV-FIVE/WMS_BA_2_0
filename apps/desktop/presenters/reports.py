"""HTTP/file workers with session fencing and exact-key recovery in RAM."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from apps.desktop.api.imports import save_bytes, validated
from packages.contracts.reports import ExportView, ReportCriteria, ReportPage, ReportSnapshot


class ReportPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-reports")
        self.results = Queue()
        self.sequence, self.closed = 0, False
        self.pending = self.user_id = self.warehouse = self.snapshot = self.job = None
        self.commands = {}
        self.next_after = None

    @property
    def scope(self):
        return self.user_id, self.warehouse

    @property
    def uncertain(self):
        return self.commands.get(self.scope)

    def reset(self, user_id=None, warehouse=None):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.pending = self.snapshot = self.job = self.next_after = None
        self.user_id, self.warehouse = (
            str(user_id) if user_id else None,
            str(warehouse) if warehouse else None,
        )
        self.view.report_clear()

    def submit(self, action, fn):
        if self.closed or self.pending is not None or not self.user_id or not self.warehouse:
            return False
        self.sequence += 1
        sequence, generation = self.sequence, self.api.session_generation
        self.view.report_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, fn)
        self.pending.add_done_callback(
            lambda future: self.results.put((sequence, generation, action, future))
        )
        return True

    def execute(self, command):
        path, body, key, kind = command
        payload = json.loads(body)
        result = validated(
            ReportSnapshot if kind == "snapshot" else ExportView, self.api.command("POST", path, payload, key)
        )
        if kind == "snapshot":
            matches = result["criteria"] == payload and result["report_code"] == path.split("/")[1]
        elif path == "exports":
            matches = (
                result["snapshot_id"] == payload["snapshot_id"] and result["format"] == payload["format"]
            )
        else:
            matches = (
                result["id"] == path.split("/")[1] and result["version"] == payload["expected_version"] + 1
            )
        if not matches:
            raise ApiError("INVALID_RESPONSE", "ACK không khớp yêu cầu; tra/gửi lại cùng key.")
        return result

    def create(self, code, filters, product_code="", owner_code="", locations=""):
        if (
            self.uncertain
            or self.pending is not None
            or self.closed
            or not self.user_id
            or not self.warehouse
        ):
            return
        self.snapshot = self.job = self.next_after = None
        self.view.report_clear()
        warehouse, scope = self.warehouse, self.scope

        def run():
            body = dict(filters, warehouse_id=warehouse)

            def resolve(kind, code):
                result = self.api.get(
                    "reports/lookups/"
                    + kind
                    + "?"
                    + urlencode(dict(warehouse_id=warehouse, code=code.strip()))
                )
                if len(result) != 1:
                    raise ApiError("INVALID_FILTER", "Không tìm thấy mã " + kind + ": " + code)
                return result[0]["id"]

            if product_code.strip():
                body["product_id"] = resolve("product", product_code)
            if owner_code.strip():
                body["owner_id"] = resolve("owner", owner_code)
            if locations.strip():
                body["location_ids"] = [resolve("location", c) for c in locations.split(",") if c.strip()]
            body = ReportCriteria.model_validate(body).model_dump(mode="json")
            command = (
                f"reports/{code}/snapshots",
                json.dumps(body, sort_keys=True),
                str(uuid4()),
                "snapshot",
            )
            self.commands[scope] = command
            return self.execute(command)

        self.submit("snapshot", run)

    def export(self, format):
        if not self.snapshot or self.uncertain or self.pending is not None or self.closed:
            return
        command = (
            "exports",
            json.dumps(dict(snapshot_id=self.snapshot["id"], format=format)),
            str(uuid4()),
            "job",
        )
        self.commands[self.scope] = command
        self.submit("job", lambda: self.execute(command))

    def action(self, operation):
        if not self.job or self.uncertain or self.pending is not None or self.closed:
            return
        command = (
            f"exports/{self.job['id']}/{operation}",
            json.dumps(dict(expected_version=self.job["version"])),
            str(uuid4()),
            "job",
        )
        self.commands[self.scope] = command
        self.submit("job", lambda: self.execute(command))

    def recover(self):
        command = self.uncertain
        if not command:
            return

        def run():
            self.api.me()  # Establish current identity before explicitly replaying the retained exact key/body.
            return self.execute(command)

        self.submit(command[3], run)

    def read(self, after=0):
        if not self.snapshot:
            return
        snapshot_id = self.snapshot["id"]

        def run():
            result = validated(
                ReportPage, self.api.get(f"reports/snapshots/{snapshot_id}?after={after}&limit=50")
            )
            if result["snapshot"]["id"] != snapshot_id:
                raise ApiError("INVALID_RESPONSE", "Snapshot không khớp yêu cầu.")
            return result

        self.submit("page", run)

    def refresh(self):
        if self.job:
            job_id = self.job["id"]

            def run():
                result = validated(ExportView, self.api.get("exports/" + job_id))
                if result["id"] != job_id:
                    raise ApiError("INVALID_RESPONSE", "Job không khớp yêu cầu.")
                return result

            self.submit("status", run)

    def download(self, path):
        if not self.job:
            return
        job, sequence, generation = dict(self.job), self.sequence + 1, self.api.session_generation

        def run():
            response = self.api.file_request("GET", f"exports/{job['id']}/download", binary=True)
            if (
                hashlib.sha256(response.content).hexdigest() != job["sha256"]
                or len(response.content) != job["size_bytes"]
            ):
                raise ApiError("FILE_HASH_MISMATCH", "Tệp tải về không khớp metadata.")
            return save_bytes(
                path,
                response.content,
                current=lambda: (
                    not self.closed
                    and self.sequence == sequence
                    and self.api.session_generation == generation
                ),
            )

        self.submit("download", run)

    def drain(self):
        while True:
            try:
                sequence, generation, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            if generation != self.api.session_generation:
                self.reset()
                continue
            self.pending = None
            try:
                result = future.result()
            except Exception as error:
                if isinstance(error, ApiError) and error.code in {
                    "FORBIDDEN",
                    "UNAUTHENTICATED",
                    "NOT_FOUND",
                    "REPORT_EXPIRED",
                }:
                    self.snapshot = self.job = self.next_after = None
                    self.view.report_clear()
                if action in {"snapshot", "job"} and isinstance(error, ApiError) and error.code not in {
                    "TIMEOUT",
                    "NETWORK_ERROR",
                    "INTERNAL_ERROR",
                    "INVALID_RESPONSE",
                    "UNAUTHENTICATED",
                    "FORBIDDEN",
                    "NOT_FOUND",
                    "SERVICE_UNAVAILABLE",
                    "DATABASE_BUSY",
                }:
                    self.commands.pop(self.scope, None)
                self.view.report_error(str(error))
                continue
            if action == "snapshot":
                self.commands.pop(self.scope, None)
                self.snapshot, self.job = result, None
                self.read()
            elif action == "page":
                self.snapshot, self.next_after = result["snapshot"], result["next_after"]
                self.view.report_page(result)
            elif action in {"job", "status"}:
                if action == "job":
                    self.commands.pop(self.scope, None)
                self.job = result
                self.view.report_job(result)
            else:
                self.view.report_saved(result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.view = self.pending = None
        self.commands.clear()
