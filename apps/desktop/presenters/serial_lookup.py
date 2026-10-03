from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from urllib.parse import urlencode

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

    def search(self, warehouse_id, code, sku=""):
        if self.closed:
            return
        self.sequence += 1
        sequence = self.sequence
        generation = self.api.session_generation
        params = {"warehouse_id": str(warehouse_id), "code": code.strip()}
        if sku.strip():
            params["sku"] = sku.strip()
        def run():
            return [SerialWarranty.model_validate(row) for row in self.api.get("serials/lookup?" + urlencode(params))]
        self.view.lookup_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, run)
        self.pending.add_done_callback(lambda future: self.results.put((sequence, future)))

    def reset(self):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.view.lookup_clear()

    def drain(self):
        while True:
            try:
                sequence, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            try:
                rows = future.result()
            except ApiError as error:
                self.view.lookup_clear()
                self.view.lookup_error(str(error))
            except Exception:
                self.view.lookup_clear()
                self.view.lookup_error("Không đọc được dữ liệu serial.")
            else:
                self.view.lookup_result(rows)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.view = None
        while not self.results.empty():
            self.results.get_nowait()
