from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from packages.contracts.traceability import SerialWarranty


class SerialLookupPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-serial")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = None
        self.uncertain = None

    def submit(self, action, function):
        if self.closed:
            return
        self.sequence += 1
        sequence, generation = self.sequence, self.api.session_generation
        self.view.lookup_busy(writing=action == "save")
        self.pending = self.executor.submit(self.api.in_session, generation, function)
        self.pending.add_done_callback(lambda future: self.results.put((sequence, generation, action, future)))

    def search(self, warehouse_id, code, sku=""):
        if self.closed or self.uncertain:
            return
        params = {"warehouse_id": str(warehouse_id), "code": code.strip()}
        if sku.strip():
            params["sku"] = sku.strip()
        def run():
            permissions = self.api.permissions(warehouse_id)
            rows = [SerialWarranty.model_validate(row) for row in self.api.get("serials/lookup?" + urlencode(params))]
            return rows, permissions
        self.submit("search", run)

    def save(self, serial_id, warehouse_id, body):
        if self.uncertain:
            return
        self.uncertain = (str(serial_id), str(warehouse_id), deepcopy(body), uuid4())
        self.retry()

    def retry(self):
        if not self.uncertain:
            return
        serial, _, body, key = self.uncertain
        self.submit("save", lambda: self.api.command("POST", f"serials/{serial}/warranty-records", body, key))

    def reset(self):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.uncertain = None
        self.view.lookup_clear()

    def drain(self):
        while True:
            try:
                sequence, generation, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.view.lookup_clear()
                self.view.lookup_error("Phiên đã thay đổi. Đăng nhập hoặc tải lại phiên trước khi tiếp tục.",
                                       uncertain=bool(self.uncertain))
                continue
            try:
                rows = future.result()
            except ApiError as error:
                uncertain = action == "save" and error.code in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE"}
                if action == "save" and not uncertain:
                    self.uncertain = None
                if action == "search" or error.code in {"FORBIDDEN", "UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.view.lookup_clear()
                detail = " · ".join(f"{field.field}: {field.message}" for field in error.field_errors)
                self.view.lookup_error(str(error) + (" · " + detail if detail else ""), uncertain=uncertain)
            except Exception:
                if action == "search":
                    self.view.lookup_clear()
                self.view.lookup_error("Không đọc được dữ liệu serial.", uncertain=action == "save")
            else:
                if action == "save":
                    self.uncertain = None
                    self.view.lookup_saved(rows)
                else:
                    self.view.lookup_result(*rows)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.uncertain = self.view = None
        while not self.results.empty():
            self.results.get_nowait()
