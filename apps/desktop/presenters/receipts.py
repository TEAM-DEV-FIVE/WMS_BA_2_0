from copy import deepcopy
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from apps.desktop.local_store.receipt_recovery import ReceiptPostJournal, receipt_endpoint
from apps.desktop.presenters.orders import OrderPresenter


class ReceiptPresenter(OrderPresenter):
    def __init__(self, view, api):
        super().__init__(view, api)
        self.journal = ReceiptPostJournal(api.settings.local_data_dir, api.settings.api_url)
        self.recovery_view = None
        self.recovery_records = []
        self.recovery_ready = False
        self.recovery_busy = False
        self.recovery_epoch = 0
        self.recovery_results = Queue()
        self.recovery_futures = set()

    @property
    def memory_uncertain(self):
        return super().uncertain

    @property
    def unresolved(self):
        return any(r["state"] in {"READY", "SENDING", "UNKNOWN"} for r in self.recovery_records)

    @property
    def uncertain(self):
        return self.memory_uncertain or (
            True if not self.recovery_ready or self.recovery_busy or self.unresolved else None
        )

    def reset(self, user_id=None):
        self.recovery_epoch += 1
        self.recovery_records = []
        self.recovery_ready = self.recovery_busy = False
        super().reset(user_id)
        if self.recovery_view:
            self.recovery_view.clear()
        if not self.closed:
            # The same worker owns SQLite for its entire lifetime, including close.
            self.executor.submit(self.journal.close)
            if self.user_id:
                self.scan_recovery()

    def scan_recovery(self):
        if self.user_id and not self.closed:
            self.journal_task("scan", lambda: None)

    def journal_task(self, action, callback):
        if self.closed or not self.user_id or self.recovery_busy:
            return
        epoch, user, generation = self.recovery_epoch, self.user_id, self.api.session_generation
        device = self.api.device_id
        self.recovery_busy = True
        self.view.recovery_changed()
        if self.recovery_view:
            self.recovery_view.loading()

        def run():
            result, error, records = None, None, None

            def work():
                self.journal.open(user, device)
                return callback()

            try:
                result = self.api.in_session(generation, work)
                records = self.journal.snapshot()
            except ApiError as exc:
                error = exc
                try:
                    if self.journal.store:
                        records = self.journal.snapshot()
                except Exception:
                    error = ApiError(
                        "LOCAL_STORAGE_ERROR",
                        "Không đọc được dữ liệu phục hồi. Giữ file và kiểm tra ổ đĩa/quyền truy cập.",
                    )
            except Exception:
                error = ApiError(
                    "LOCAL_STORAGE_ERROR",
                    "Không mở/lưu được lệnh nhận hàng. Giữ thư mục dữ liệu; kiểm tra ổ đĩa hoặc cửa sổ WMS khác.",
                )
            return result, error, records

        future = self.executor.submit(run)
        self.recovery_futures.add(future)
        future.add_done_callback(lambda f: self.recovery_results.put((epoch, user, generation, action, f)))

    def command(self, method, path, body):
        if method == "POST" and path.startswith("receipts/") and path.endswith("/post"):
            if self.uncertain:
                self.view.orders_error(
                    "Cần hoàn tất kiểm tra/phục hồi lệnh trước trong tab Phục hồi nhận hàng."
                )
                return
            try:
                doc_id, endpoint = receipt_endpoint(path)
            except ValueError:
                self.view.orders_error("Đường dẫn ghi sổ không hợp lệ.")
                return
            doc = self.view.doc or {}
            context = {
                "document_number": doc.get("number", str(doc_id)),
                "warehouse_id": doc.get("warehouse_id"),
            }
            saved_body, key = deepcopy(body), uuid4()
            self.journal_task(
                "post",
                lambda: self.journal.send_new(
                    self.api, key=key, endpoint=endpoint, body=saved_body, context=context
                ),
            )
        else:
            super().command(method, path, body)

    def retry(self, key=None):
        if key is None:
            if self.memory_uncertain:
                super().retry()
            return
        self.journal_task("retry", lambda: self.journal.retry(self.api, key))

    def lookup(self, key):
        self.journal_task("lookup", lambda: self.journal.lookup(self.api, key))

    def drain(self):
        super().drain()
        while True:
            try:
                epoch, user, generation, action, future = self.recovery_results.get_nowait()
            except Empty:
                return
            self.recovery_futures.discard(future)
            if self.closed or epoch != self.recovery_epoch or user != self.user_id:
                continue
            self.recovery_busy = False
            if generation != self.api.session_generation:
                self.recovery_ready = False
                self.recovery_records = []
                self.view.orders_clear()
                if self.recovery_view:
                    self.recovery_view.clear()
                self.view.orders_error("Phiên đã đổi; đăng nhập lại để mở dữ liệu phục hồi đúng tài khoản.")
                self.view.recovery_changed()
                continue
            result, error, records = future.result()
            self.recovery_ready = records is not None
            if records is not None:
                self.recovery_records = records
            self.view.recovery_changed()
            if self.recovery_view:
                self.recovery_view.loaded(records or [], error, result)
            if error:
                if error.code in {"FORBIDDEN", "UNAUTHENTICATED", "NOT_FOUND", "REFRESH_REPLAY"}:
                    self.view.orders_clear()
                self.view.orders_error(str(error))
            elif result and result.get("operation_status") == "COMMITTED":
                self.read("receipts", result["id"])

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.sequence += 1
        self.recovery_epoch += 1
        if self.pending:
            self.pending.cancel()
        for future in self.recovery_futures:
            future.cancel()
        self.executor.submit(self.journal.close)
        self.executor.shutdown(wait=False, cancel_futures=False)

    def finish(self):
        super().finish()
        self.recovery_view = None
        self.recovery_records.clear()
        self.recovery_futures.clear()
        while not self.recovery_results.empty():
            self.recovery_results.get_nowait()

    def load(self, path, warehouse, status="", after=None):
        def run():
            permissions = self.api.permissions(warehouse)
            params = {"warehouse_id": str(warehouse), "limit": 25}
            if after:
                params["after"] = after
            if status:
                params["status"] = status
            page = self.api.get("receipts?" + urlencode(params))
            refs = {"locations": [], "sources": []}
            if any(p in permissions for p in ["receipt.draft", "receipt.post", "document.approve"]):
                refs["locations"] = self.api.get(
                    "receipts/locations?" + urlencode({"warehouse_id": warehouse})
                )
            if "receipt.draft" in permissions:
                for state in ["APPROVED", "PARTIAL"]:
                    source = self.api.get(
                        "purchase-orders?"
                        + urlencode({"warehouse_id": warehouse, "status": state, "limit": 100})
                    )
                    refs["sources"] += source["items"]
                    refs["source_truncated"] = refs.get("source_truncated", False) or bool(
                        source["next_after"]
                    )
            return page, refs, permissions

        self.submit("load", run)

    def source(self, doc_id):
        self.submit("conversions", lambda: self.api.get("purchase-orders/" + doc_id))
