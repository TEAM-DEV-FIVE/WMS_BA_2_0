from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from typing import Protocol

from apps.desktop.api.client import ApiClient, ApiError
from packages.contracts import Health


class ConnectionView(Protocol):
    def show_loading(self) -> None: ...
    def show_result(self, health: Health) -> None: ...
    def show_error(self, message: str) -> None: ...


class ConnectionPresenter:
    """Only drain(), called by root.after on the main thread, touches the view."""

    def __init__(self, view: ConnectionView, api: ApiClient):
        self.view = view
        self.api = api
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wms-http")
        self.results: Queue[tuple[int, Future]] = Queue()
        self.sequence = 0
        self.closed = False
        self.pending: Future | None = None

    def check(self, *, readiness: bool = False) -> None:
        if self.closed:
            return
        self.sequence += 1
        sequence = self.sequence
        if self.pending is not None:
            self.pending.cancel()
        self.view.show_loading()
        future = self.executor.submit(self.api.health, readiness=readiness)
        future.add_done_callback(lambda result: self.results.put((sequence, result)))
        self.pending = future

    def invalidate(self) -> None:
        self.sequence += 1

    def drain(self) -> None:
        while True:
            try:
                sequence, future = self.results.get_nowait()
            except Empty:
                return
            if self.closed or sequence != self.sequence:
                continue
            try:
                result = future.result()
            except ApiError as exc:
                reference = f" (Mã tra cứu: {exc.request_id})" if exc.request_id else ""
                self.view.show_error(str(exc) + reference)
            except Exception:
                self.view.show_error("Không đọc được kết quả kết nối.")
            else:
                self.view.show_result(result)

    def close(self) -> None:
        self.closed = True
        self.invalidate()
        # Finalizer runs after active HTTP work, avoiding client.close() in mid-request.
        self.executor.shutdown(wait=False, cancel_futures=True)

    def finish(self) -> None:
        """Called after mainloop exits; bounded by the HTTP timeout."""
        self.executor.shutdown(wait=True)
        self.api.close()
        self.pending = None
        self.view = None
        while not self.results.empty():
            self.results.get_nowait()
