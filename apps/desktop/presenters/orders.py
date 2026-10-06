from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError


class OrderPresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-orders")
        self.results = Queue()
        self.sequence = 0
        self.closed = False
        self.pending = None
        self.user_id = None
        self.commands = {}
        self.needs_reload = False

    @property
    def uncertain(self):
        return self.commands.get(self.user_id)

    def reset(self, user_id=None):
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.user_id = str(user_id) if user_id else None
        self.needs_reload = False
        self.view.orders_clear()

    def submit(self, action, fn):
        if self.closed:
            return
        self.sequence += 1
        sequence = self.sequence
        generation = self.api.session_generation
        self.view.orders_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, fn)
        self.pending.add_done_callback(lambda future: self.results.put((sequence, generation, action, future)))

    def load(self, path, warehouse, status="", after=None, query=""):
        def run():
            permissions = self.api.permissions(warehouse)
            params = {"warehouse_id": str(warehouse), "limit": 25}
            if status:
                params["status"] = status
            if after:
                params["after"] = after
            if query:
                params["q"] = query
            page = self.api.get(path + "?" + urlencode(params))
            refs = {}
            if ("po.draft" if path == "purchase-orders" else "so.draft") in permissions:
                try:
                    refs = {
                        r: self.api.get("master/" + r + "?active=true&limit=200")
                        for r in ["products", "partners", "uoms"]
                    }
                except ApiError as error:
                    if error.code != "FORBIDDEN":
                        raise
                    # Catalogue grants are GLOBAL; missing them must not hide authorized order reads.
                    refs = {}
            return page, refs, permissions

        self.submit("load", run)

    def read(self, path, doc_id):
        self.submit("read", lambda: self.api.get(path + "/" + doc_id))

    def review(self, doc_id):
        self.submit("review", lambda: self.api.get(f"documents/{doc_id}/approval-snapshots"))

    def candidates(self, doc_id, query="", after=None):
        params = {"q": query, "limit": 25}
        if after:
            params["after"] = after
        self.submit("candidates", lambda: self.api.get(
            f"documents/{doc_id}/assignment-candidates?" + urlencode(params)))

    def conversions(self, product_id):
        self.submit(
            "conversions",
            lambda: self.api.get(
                "master/product-uoms?" + urlencode({"product_id": product_id, "active": "true", "limit": 200})
            ),
        )

    def command(self, method, path, body):
        if self.closed or not self.user_id:
            return
        if self.needs_reload and "expected_version" in body:
            self.view.orders_error("Phiếu hoặc quyền đã đổi. Tải lại chi tiết trước khi thao tác tiếp.")
            return
        if self.uncertain:
            self.view.orders_error("Yêu cầu trước chưa rõ kết quả. Gửi lại đúng yêu cầu đang giữ.")
            return
        self.commands[self.user_id] = (method, path, deepcopy(body), uuid4())
        self.retry()

    def retry(self):
        if self.uncertain and not (self.pending and not self.pending.done()):
            method, path, body, key = self.uncertain
            self.submit("command", lambda: self.api.command(method, path, body, key))

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
                self.view.orders_clear()
                self.view.orders_error("Phiên đã thay đổi. Đăng nhập lại để tải dữ liệu đúng tài khoản.")
                continue
            try:
                result = future.result()
            except ApiError as error:
                uncertain = error.code in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE"}
                if action == "command" and not uncertain:
                    self.commands.pop(self.user_id, None)
                if action == "command" and error.code in {
                    "STALE_VERSION", "STALE_APPROVAL", "INVALID_STATE", "SELF_APPROVAL",
                    "FORBIDDEN", "NOT_FOUND", "UNAUTHENTICATED", "REFRESH_REPLAY",
                }:
                    self.needs_reload = True
                if error.code in {"FORBIDDEN", "UNAUTHENTICATED", "NOT_FOUND", "REFRESH_REPLAY"}:
                    self.view.orders_clear()
                detail = " · ".join(f"{f.field}: {f.message}" for f in error.field_errors)
                self.view.orders_error(str(error) + (" · " + detail if detail else ""))
            except Exception:
                self.view.orders_error("Không đọc được phản hồi. Giữ nguyên nội dung và kiểm tra kết nối.")
            else:
                if action == "command":
                    self.commands.pop(self.user_id, None)
                    self.view.orders_saved(result)
                elif action == "load":
                    self.view.orders_loaded(*result)
                elif action == "read":
                    self.needs_reload = False
                    self.view.orders_read(result)
                elif action == "review":
                    self.view.orders_review(result)
                elif action == "candidates":
                    self.view.orders_candidates(result)
                else:
                    self.view.orders_conversions(result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.view = None
        self.commands.clear()
        while not self.results.empty():
            self.results.get_nowait()
