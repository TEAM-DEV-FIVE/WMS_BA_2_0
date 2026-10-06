"""Session-fenced preview and explicit print actions. Never replay OS I/O."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from apps.desktop.api.imports import save_bytes, validated
from apps.desktop.printing.pdf import page_image
from apps.desktop.printing.spool import printers
from apps.desktop.printing.spool import submit as spool_submit
from packages.contracts.printing import PrintCreate, PrintJob


class PrintPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-print")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = self.job = self.user = self.warehouse = None
        self.commands = {}

    @property
    def scope(self):
        return self.user, self.warehouse

    def reset(self, user=None, warehouse=None):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.pending = self.job = None
        self.user = str(user) if user else None
        self.warehouse = str(warehouse) if warehouse else None
        self.view.print_clear()

    def submit(self, action, fn):
        if self.closed or self.pending or not self.user or not self.warehouse:
            return False
        self.sequence += 1
        seq, gen = self.sequence, self.api.session_generation
        self.view.print_busy()
        self.pending = self.executor.submit(self.api.in_session, gen, fn)
        self.pending.add_done_callback(lambda f: self.results.put((seq, gen, action, f)))
        return True

    def execute(self, command):
        path, body, key = command
        payload = json.loads(body)
        job = validated(PrintJob, self.api.command("POST", path, payload, key))
        if (
            path == "printing"
            and (
                job["source_id"] != payload["source_id"]
                or job["source_version"] != payload["expected_version"]
            )
        ) or (
            path != "printing"
            and (job["id"] != path.split("/")[1] or job["version"] != payload["expected_version"] + 1)
        ):
            raise ApiError("INVALID_RESPONSE", "ACK lệnh in không khớp.")
        return job

    def command(self, path, body):
        return path, json.dumps(body, sort_keys=True), str(uuid4())

    def search(self, template, q):
        path = "printing/sources?" + urlencode(dict(template=template, warehouse_id=self.warehouse, q=q))
        self.submit("sources", lambda: self.api.get(path))

    def create(self, template, source, paper, price, serial_code=""):
        if self.pending or self.commands.get(self.scope) or not source:
            return
        warehouse, scope = self.warehouse, self.scope
        self.job = None
        self.view.clear_preview()

        def run():
            body = dict(
                template=template,
                source_id=source["id"],
                expected_version=source["version"],
                warehouse_id=warehouse,
                paper=paper,
                include_price=price,
            )
            if serial_code:
                rows = self.api.get(
                    "serials/lookup?"
                    + urlencode(dict(warehouse_id=warehouse, code=serial_code, sku=source["number"]))
                )
                if len(rows) != 1:
                    raise ApiError("SCAN_NOT_FOUND", "Serial không duy nhất trong phạm vi kho.")
                body["serial_id"] = rows[0]["serial_id"]
            body = PrintCreate.model_validate(body).model_dump(mode="json")
            cmd = self.command("printing", body)
            self.commands[scope] = cmd
            return self.execute(cmd)

        self.submit("command", run)

    def refresh(self):
        if self.job:
            job_id = self.job["id"]
            self.submit("job", lambda: validated(PrintJob, self.api.get("printing/" + job_id)))

    def action(self, operation, reason):
        if not self.job or self.pending or self.commands.get(self.scope):
            return
        cmd = self.command(
            f"printing/{self.job['id']}/{operation}",
            dict(expected_version=self.job["version"], reason=reason),
        )
        self.commands[self.scope] = cmd
        self.view.clear_preview()
        self.submit("command", lambda: self.execute(cmd))

    def recover(self):
        cmd = self.commands.get(self.scope)
        if cmd:
            # A recovered spool claim is UNKNOWN. Recovery must NEVER submit to the device.
            self.submit("command", lambda: self.execute(cmd))

    def data(self, job, attempt=None):
        path = f"printing/{job['id']}/download" + ("?attempt_id=" + attempt if attempt else "")
        response = self.api.file_request("GET", path, binary=True)
        data = response.content
        if (
            len(data) != job["size_bytes"]
            or hashlib.sha256(data).hexdigest() != job["sha256"]
            or not data.startswith(b"%PDF-")
        ):
            raise ApiError("FILE_HASH_MISMATCH", "PDF không khớp bản in.")
        return data

    def preview(self, index=0):
        if self.job and self.job["status"] == "READY":
            job = dict(self.job)
            self.submit("preview", lambda: page_image(self.data(job), index))

    def download(self, path):
        if not self.job:
            return
        job = dict(self.job)
        seq, gen = self.sequence + 1, self.api.session_generation
        self.submit("saved", lambda: save_bytes(path, self.data(job), current=lambda: self.current(seq, gen)))

    def current(self, seq, gen):
        return not self.closed and self.sequence == seq and self.api.session_generation == gen

    def devices(self):
        self.submit("devices", printers)

    def spool(self, printer, driver, copies, reason):
        if (
            not self.job
            or self.pending
            or self.commands.get(self.scope)
            or self.job["attempt"]
            or self.job["status"] != "READY"
        ):
            return
        job, scope = dict(self.job), self.scope
        attempt = str(uuid4())
        cmd = self.command(
            f"printing/{job['id']}/spool",
            dict(
                expected_version=job["version"],
                reason=reason,
                attempt_id=attempt,
                printer=printer,
                driver=driver,
                copies=copies,
            ),
        )
        self.commands[scope] = cmd
        seq, gen = self.sequence + 1, self.api.session_generation

        def run():
            claimed = self.execute(cmd)
            data = self.data(claimed, attempt)
            if not self.current(seq, gen):
                raise ApiError("STALE_SESSION", "Phiên đã đổi; chưa gửi máy in.")
            # One call per explicit fresh claim; no spool call in recover().
            result = spool_submit(data, printer, job["paper"], copies)
            outcome = self.command(
                f"printing/{job['id']}/result",
                dict(
                    expected_version=claimed["version"],
                    attempt_id=attempt,
                    outcome=result.outcome,
                    spool_id=result.spool_id,
                    error_code=result.error_code,
                ),
            )
            self.commands[scope] = outcome
            return self.execute(outcome)

        self.submit("command", run)

    def drain(self):
        while True:
            try:
                seq, gen, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or seq != self.sequence:
                continue
            if gen != self.api.session_generation:
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
                    "PRINT_EXPIRED",
                }:
                    self.job = None
                    self.view.print_clear()
                if (
                    action == "command"
                    and isinstance(error, ApiError)
                    and error.code
                    not in {
                        "TIMEOUT",
                        "NETWORK_ERROR",
                        "INTERNAL_ERROR",
                        "INVALID_RESPONSE",
                        "UNAUTHENTICATED",
                        "FORBIDDEN",
                        "NOT_FOUND",
                        "SERVICE_UNAVAILABLE",
                        "DATABASE_BUSY",
                        "STALE_SESSION",
                    }
                ):
                    self.commands.pop(self.scope, None)
                self.view.print_error(str(error))
                continue
            if action in {"command", "job"}:
                if action == "command":
                    self.commands.pop(self.scope, None)
                self.job = result
                self.view.print_job(result)
            else:
                getattr(self.view, "print_" + action)(result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.view = self.pending = None
        self.commands.clear()
