from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from threading import Event
from urllib.parse import urlencode
from uuid import uuid4

from apps.desktop.api.client import ApiError
from packages.contracts.moves import MovePostResult
from packages.contracts.orders import OrderResult
from packages.contracts.quality import QualityResult
from packages.contracts.receipts import OperationView


def run_request(api, generation, cancelled, method, path, body, key, warehouse):
    # Only plain API/state goes to the worker, never widgets or bound view methods.
    def execute():
        if cancelled.is_set():
            return None, []
        permissions = api.permissions(warehouse)
        if cancelled.is_set():
            return None, permissions
        data = api.get(path) if method == "GET" else api.command(method, path, body, key)
        parts = path.split("/")
        if method != "GET":
            model = QualityResult if parts[0] == "quality" else MovePostResult if parts[-1] == "post" else OrderResult
            data = model.model_validate(data).model_dump(mode="json")
            if data["warehouse_id"] != warehouse or data["version"] < 1:
                raise ValueError("ACK scope/version mismatch")
            if parts[0] in {"moves", "documents"} and len(parts) > 1 and data["id"] != parts[1]:
                raise ValueError("ACK document mismatch")
            if parts[0] == "quality" and data["receipt_move_id"] != parts[2]:
                raise ValueError("ACK source mismatch")
        elif parts[:2] == ["moves", "operations"]:
            data = OperationView.model_validate(data).model_dump(mode="json")
            if data["id"] != body["document_id"] or data["status"] != "COMPLETED" or not data["transaction_id"]:
                raise ValueError("ACK operation mismatch")
        return data, permissions
    try:
        data, permissions = api.in_session(generation, execute)
        return data, permissions, None, api.session_generation
    except ApiError as exc:
        return None, [], (exc.code, str(exc)), api.session_generation
    except Exception:
        return None, [], ("INVALID_RESPONSE", "Không đọc được phản hồi; giữ đúng key/nội dung để đối chiếu."), api.session_generation


class MovePresenter:
    def __init__(self, view, api):
        self.view, self.api = view, api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-move-quality")
        self.results = Queue()
        self.pending = None
        self.closed = False
        self.sequence = 0
        self.cancelled = Event()
        self.user_id = self.warehouse_id = None
        self.generation = api.session_generation
        self.commands = {}

    @property
    def scope(self):
        return self.user_id, self.warehouse_id

    @property
    def uncertain(self):
        return self.commands.get(self.scope)

    def reset(self, user_id=None, warehouse_id=None):
        self.sequence += 1
        self.cancelled.set()
        self.cancelled = Event()
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.user_id = str(user_id) if user_id else None
        self.warehouse_id = str(warehouse_id) if warehouse_id else None
        self.generation = self.api.session_generation
        self.view.workflow_clear()

    def submit(self, action, method, path, body=None, key=None):
        if self.closed or self.pending or not all(self.scope):
            return False
        self.view.workflow_busy()
        future = self.executor.submit(run_request, self.api, self.generation, self.cancelled,
                                      method, path, body, key, self.warehouse_id)
        self.pending = future
        queue, sequence, scope = self.results, self.sequence, self.scope
        future.add_done_callback(lambda done: queue.put((sequence, scope, action, done)))
        return True

    def load(self, resource="moves", after=None):
        params = {"warehouse_id": self.warehouse_id, "limit": 50}
        if after:
            params["after"] = after
        return self.submit(resource, "GET", resource + "?" + urlencode(params))

    def read(self, doc_id):
        return self.submit("read", "GET", "moves/" + str(doc_id))

    def command(self, method, path, body):
        if self.closed or self.pending or not all(self.scope):
            return False
        if self.uncertain:
            self.view.workflow_error("Yêu cầu trước chưa rõ kết quả. Chỉ gửi lại đúng key/nội dung đang giữ.")
            return False
        self.commands[self.scope] = (method, path, deepcopy(body), uuid4())
        return self.retry()

    def retry(self):
        if not self.pending and self.uncertain:
            return self.submit("command", *self.uncertain)
        return False

    def operation(self):
        if self.uncertain and self.uncertain[1].endswith("/post"):
            return self.submit("operation", "GET", "moves/operations/" + str(self.uncertain[3]),
                               {"document_id": self.uncertain[1].split("/")[1]})
        return False

    def drain(self):
        if self.closed:
            return
        while True:
            try:
                sequence, scope, action, future = self.results.get_nowait()
            except Empty:
                break
            if sequence != self.sequence or scope != self.scope:
                continue
            self.pending = None
            data, permissions, error, generation = future.result()
            if generation != self.generation or generation != self.api.session_generation or (error and error[0] in {"UNAUTHENTICATED", "REFRESH_REPLAY"}):
                self.reset()
                self.view.workflow_signed_out("Phiên không còn hiệu lực. Đăng nhập lại và đối chiếu lệnh chưa rõ kết quả.")
                continue
            if error:
                code, message = error
                # Current authorization can fail even after an earlier attempt committed.
                # Keep the original command until its ACK can be reconciled.
                if action == "command" and code not in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE",
                                                       "DATABASE_BUSY", "FORBIDDEN", "NOT_FOUND",
                                                       "IDEMPOTENCY_MISMATCH", "EXECUTION_MISMATCH"}:
                    self.commands.pop(scope, None)
                if code == "FORBIDDEN":
                    self.view.workflow_clear()
                self.view.workflow_error(message)
            elif action in {"command", "operation"}:
                self.commands.pop(scope, None)
                self.view.workflow_saved(data)
            else:
                self.view.workflow_loaded(action, data, permissions)
        if self.user_id and self.generation != self.api.session_generation:
            self.reset()
            self.view.workflow_signed_out("Phiên đã thay đổi. Tải lại phiên trước khi tiếp tục.")

    def close(self):
        self.closed = True
        self.sequence += 1
        self.cancelled.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = self.view = None
        self.commands.clear()
        while not self.results.empty():
            self.results.get_nowait()
