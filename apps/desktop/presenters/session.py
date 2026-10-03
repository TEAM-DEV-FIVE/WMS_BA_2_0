from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

from apps.desktop.api.client import ApiError


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
        if self.closed:
            return
        self.sequence += 1
        sequence = self.sequence
        self.view.session_busy()
        self.pending = self.executor.submit(self.run, action, args)
        self.pending.add_done_callback(lambda future: self.results.put((sequence, action, future)))

    def run(self, action, args):
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
