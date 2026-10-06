from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from queue import Empty, Queue

from apps.desktop.api.client import ApiError


@dataclass
class SessionResult:
    data: object = field(default=None, repr=False)
    message: str = ""
    signed_out: bool = False
    generation: int = 0


class SessionPresenter:
    def __init__(self, view, api):
        self.view = view
        self.api = api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-session")
        self.results = Queue()
        self.closed = False
        self.sequence = 0
        self.pending = None

    def submit(self, action, *args):
        if self.closed or self.pending:
            return
        self.sequence += 1
        sequence = self.sequence
        self.view.session_busy()
        self.pending = self.executor.submit(self.guarded_run, self.api.session_generation, action, args)
        queue = self.results
        self.pending.add_done_callback(lambda future: queue.put((sequence, action, future)))

    def guarded_run(self, generation, action, args):
        # Catch inside the worker so Future never stores exception frames with
        # passwords, TOTP codes, recovery payloads or HTTP headers.
        result = SessionResult()
        def execute():
            try:
                result.data = self.run(action, args)
            except ApiError as exc:
                result.message = str(exc)
                result.signed_out = exc.code in {"UNAUTHENTICATED", "REFRESH_REPLAY"} or action == "logout"
                if action in {"change_password", "reset_password", "reset_mfa", "recover_mfa", "recovery_codes", "enroll", "confirm"}:
                    self.api.clear()
                    result.signed_out = True
                    if exc.code in {"TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR", "INVALID_RESPONSE"}:
                        result.message = "Chưa rõ kết quả. Hãy đăng nhập lại; không tự gửi lại thao tác bảo mật."
            except Exception:
                self.api.clear()
                result.message = "Không đọc được phản hồi. Hãy đăng nhập lại; không tự gửi lại thao tác."
                result.signed_out = True
            result.generation = self.api.session_generation
        try:
            self.api.in_session(generation, execute)
        except ApiError:
            result.message = "Phiên đã thay đổi. Hãy đăng nhập lại."
            result.signed_out = True
            result.generation = self.api.session_generation
        return result

    def run(self, action, args):
        if action in {"change_password", "reset_password", "reset_mfa", "recover_mfa", "recovery_codes"}:
            return self.api.lifecycle(action, args[0])
        if action == "login":
            status = self.api.login(*args)
            return self.snapshot() if status == "AUTHENTICATED" else status
        if action == "mfa":
            self.api.mfa(*args)
            return self.snapshot()
        if action == "reload":
            return self.snapshot()
        if action == "logout":
            self.api.logout()
            return "SIGNED_OUT"
        if action == "enroll":
            return self.api.enroll(*args)
        if action == "confirm":
            self.api.confirm_enrollment(*args)
            return self.snapshot()
        if action == "warehouse":
            return self.api.permissions(*args)
        raise ValueError("Unknown session action")

    def snapshot(self):
        return {"user": self.api.me(), "warehouses": self.api.warehouses()}

    def drain(self):
        while True:
            try:
                sequence, action, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            self.pending = None
            try:
                result = future.result()
                if isinstance(result, SessionResult):
                    if result.generation != self.api.session_generation:
                        self.view.session_error("Phiên đã thay đổi. Tải lại phiên.", signed_out=True)
                        continue
                    if result.message:
                        self.view.session_error(result.message, signed_out=result.signed_out)
                        continue
                    result = result.data
            except ApiError as exc:
                self.view.session_error(str(exc), signed_out=exc.code in {"UNAUTHENTICATED", "REFRESH_REPLAY"} or action == "logout")
            except Exception:
                self.view.session_error("Không đọc được phản hồi phiên làm việc.", signed_out=False)
            else:
                self.view.session_result(action, result)

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self):
        self.executor.shutdown(wait=True)
        self.api.close()
        self.pending = None
        self.view = None
        while not self.results.empty():
            self.results.get_nowait()
