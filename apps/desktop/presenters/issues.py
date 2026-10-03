from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from packages.contracts.issues import IssuePostResult, IssueView, ReservationPlan
from packages.contracts.orders import OrderResult


class IssuePresenter:
    """HTTP on one worker; UI delivery only through drain() on the Tk thread.

    Pending commands stay in memory per user until a valid ACK/definitive error.
    B19 owns durable recovery across process restarts; this presenter exposes the
    key/body and lookup contract without introducing another SQLite revision.
    """

    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-issues")
        self.results = Queue()
        self.sequence = 0
        self.user_id = None
        self.pending = None
        self.commands = {}
        self.closed = False

    @property
    def uncertain(self):
        return self.commands.get(self.user_id)

    def mark_unknown(self):
        if self.uncertain:
            self.uncertain.update(state="UNKNOWN", was_unknown=True)

    def reset(self, user_id=None):
        self.mark_unknown()
        self.sequence += 1
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.user_id = str(user_id) if user_id else None
        self.view.orders_clear()

    def submit(self, action, fn):
        if self.closed or not self.user_id:
            return
        self.sequence += 1
        sequence, user, generation = self.sequence, self.user_id, self.api.session_generation
        self.view.orders_busy()
        self.pending = self.executor.submit(self.api.in_session, generation, fn)
        self.pending.add_done_callback(lambda f: self.results.put((sequence, user, generation, action, f)))

    def load(self, warehouse, after=None):
        def run():
            permissions = self.api.permissions(warehouse)
            query = {"warehouse_id": str(warehouse), "limit": 25}
            if after:
                query["after"] = after
            page = self.api.get("issues?" + urlencode(query))
            sources, truncated = [], False
            if "issue.draft" in permissions:
                for status in ("APPROVED", "PARTIAL"):
                    result = self.api.get("sales-orders?" + urlencode({"warehouse_id": warehouse, "status": status, "limit": 100}))
                    sources += result["items"]
                    truncated = truncated or bool(result["next_after"])
            return page, sources, permissions, truncated
        self.submit("load", run)

    def read(self, doc_id):
        self.submit("read", lambda: IssueView.model_validate(self.api.get("issues/" + str(doc_id))).model_dump(mode="json"))

    def source(self, doc_id):
        self.submit("source", lambda: self.api.get("sales-orders/" + str(doc_id)))

    def plan(self, doc_id, line_id, qty):
        self.submit("plan", lambda: ReservationPlan.model_validate(self.api.get(
            f"issues/{doc_id}/reservation-plan?" + urlencode({"document_line_id": line_id, "quantity_base": qty})
        )).model_dump(mode="json"))

    def command(self, method, path, body):
        if self.uncertain:
            self.view.orders_error("UNKNOWN: tra ACK hoặc gửi lại đúng lệnh đang giữ trước khi tạo lệnh mới.")
            return
        if not self.user_id or self.closed:
            return
        self.commands[self.user_id] = dict(method=method, path=path, body=deepcopy(body), key=uuid4(), state="SENDING")
        self.retry()

    @staticmethod
    def valid_ack(result, record):
        model = IssuePostResult if record["path"].endswith("/post") else OrderResult
        ack = model.model_validate(result)
        if ack.kind != "ISSUE":
            raise ValueError("Wrong document kind in acknowledgement")
        parts = record["path"].split("/")
        if len(parts) > 1 and parts[0] in {"issues", "documents"} and str(ack.id) != parts[1]:
            raise ValueError("Acknowledgement belongs to another document")
        return ack.model_dump(mode="json")

    def retry(self):
        if self.uncertain:
            record = deepcopy(self.uncertain)
            self.uncertain["state"] = "SENDING"
            self.submit("command", lambda: self.valid_ack(self.api.command(
                record["method"], record["path"], record["body"], record["key"]), record))

    def lookup(self):
        if self.uncertain:
            record = deepcopy(self.uncertain)

            def run():
                response = self.api.get("issues/operations/" + str(record["key"]))
                if response.get("operation_status") != "COMMITTED":
                    raise ValueError("Unconfirmed operation")
                return self.valid_ack(response["result"], record)
            self.submit("lookup", run)

    def drain(self):
        while True:
            try:
                sequence, user, generation, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or user != self.user_id or sequence != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.mark_unknown()
                self.view.orders_clear()
                self.view.orders_error("Phiên đã đổi; đăng nhập và tải lại trước khi thao tác.")
                continue
            try:
                result = future.result()
            except ApiError as error:
                ambiguous = error.code in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE", "SESSION_CHANGED"}
                if self.uncertain and action in {"command", "lookup"}:
                    # A later denial/stale error cannot disprove an earlier COMMIT
                    # whose ACK was lost, since authorization precedes cached ACKs.
                    if action == "lookup" or ambiguous or self.uncertain.get("was_unknown"):
                        self.mark_unknown()
                    else:
                        self.commands.pop(user, None)
                if error.code in {"FORBIDDEN", "UNAUTHENTICATED", "REFRESH_REPLAY"}:
                    self.view.orders_clear()
                suffix = " UNKNOWN: chưa xác nhận; giữ cửa sổ và tra ACK/gửi lại cùng key." if self.uncertain else ""
                self.view.orders_error(str(error) + suffix)
            except Exception:
                self.mark_unknown()
                self.view.orders_error("Không xác minh được phản hồi. UNKNOWN nếu đang ghi; giữ cửa sổ và tra ACK/gửi lại đúng lệnh.")
            else:
                if action in {"command", "lookup"}:
                    self.commands.pop(user, None)
                    self.view.orders_saved(result)
                elif action == "load":
                    self.view.orders_loaded(*result)
                elif action == "read":
                    self.view.orders_read(result)
                elif action == "source":
                    self.view.source_loaded(result)
                else:
                    self.view.plan_loaded(result)

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
