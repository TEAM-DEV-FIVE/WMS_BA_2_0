"""Local API/worker supervision; existing business modules are reused unchanged."""

import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread

import httpx

from apps.local_launcher.database import SetupError, load_environment
from apps.local_launcher.product import PREFIX, PRODUCT


def clean_environment():
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(("WMS_", "KWS_"))}


def worker_kinds():
    from apps.server.operations_worker import KINDS

    return ("outbox", *KINDS)


def executable(component, home, session):
    args = ["--component", component, "--home", str(home), "--session", session]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "apps.local_launcher.entry", *args]


def run_component(component, home, session):
    import re

    if not re.fullmatch(r"[0-9a-f]{32}", session):
        raise SetupError("Mã phiên máy chủ không hợp lệ.")
    environment = load_environment(home)
    # This process is server-only. Database credentials never go to the desktop.
    for key in list(os.environ):
        if key.upper().startswith(("WMS_", "KWS_")):
            del os.environ[key]
    os.environ.update({k: v for k, v in environment.items() if k.startswith(PREFIX)})
    stop_path = Path(home) / ("stop-" + session)
    finished = Event()
    lease_path = Path(home) / ("lease-" + session)

    def watch(callback):
        while not finished.wait(0.25):
            try:
                expired = time.time() - lease_path.stat().st_mtime > 30
            except FileNotFoundError:
                expired = True
            if stop_path.exists() or expired:
                callback()
                return

    try:
        if component == "api":
            import uvicorn

            from apps.server.api.app import create_app
            from apps.server.infrastructure.config import Settings

            settings = Settings()
            app = create_app(settings)

            @app.get("/_local/" + session, include_in_schema=False)
            def identity():
                return {"product": PRODUCT, "session": session}

            server = uvicorn.Server(
                uvicorn.Config(
                    app, host="127.0.0.1", port=settings.port, access_log=False, log_level="warning"
                )
            )
            Thread(target=watch, args=(lambda: setattr(server, "should_exit", True),), daemon=True).start()
            server.run()
            return 0
        from apps.server import operations_worker, worker

        original = worker.stop_signals

        @contextmanager
        def file_stop(stop):
            with original(stop):
                Thread(target=watch, args=(stop.set,), daemon=True).start()
                yield

        worker.stop_signals = file_stop
        operations_worker.stop_signals = file_stop
        if component == "outbox":
            return worker.main([])
        return operations_worker.main(["--kind", component])
    finally:
        finished.set()


class Supervisor:
    def __init__(self, home):
        self.home = Path(home).absolute()
        self.environment = load_environment(self.home)
        self.port = int(self.environment[PREFIX + "PORT"])
        self.session = secrets.token_hex(16)
        self.stop_path = self.home / ("stop-" + self.session)
        self.lease_path = self.home / ("lease-" + self.session)
        self.heartbeat_stop = Event()
        self.heartbeat_thread = None
        self.children = []
        self.streams = []

    def start(self):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.port))
            except OSError:
                raise SetupError(
                    f"Cổng API {self.port} đang được dùng. Hãy đóng phiên máy chủ cũ trước."
                ) from None
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.lease_path.touch()

        def heartbeat():
            while not self.heartbeat_stop.wait(1):
                self.lease_path.touch()

        self.heartbeat_thread = Thread(target=heartbeat, daemon=True)
        self.heartbeat_thread.start()
        try:
            for name in ("api", *worker_kinds()):
                log = (self.home / "logs" / (name + ".log")).open("ab")
                self.streams.append(log)
                proc = subprocess.Popen(
                    executable(name, self.home, self.session),
                    cwd=self.home,
                    env=clean_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    creationflags=flags,
                )
                self.children.append((name, proc))
            deadline = time.monotonic() + 120
            with httpx.Client(timeout=2, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if self.failed():
                        raise SetupError("Một thành phần máy chủ đã dừng. Kiểm tra thư mục logs.")
                    try:
                        base = f"http://127.0.0.1:{self.port}"
                        identity = client.get(base + "/_local/" + self.session)
                        ready = client.get(base + "/api/v1/ready")
                        if (
                            identity.status_code == 200
                            and identity.json() == {"product": PRODUCT, "session": self.session}
                            and ready.status_code == 200
                        ):
                            return
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.3)
            raise SetupError("Máy chủ chưa sẵn sàng sau 120 giây; xem logs. Dữ liệu được giữ nguyên.")
        except BaseException:
            self.stop()
            raise

    def failed(self):
        return any(proc.poll() is not None for _, proc in self.children)

    def stop(self):
        self.stop_path.touch()
        # Never force-kill a process while stock/audit/ACK may be committing.
        for _, proc in self.children:
            proc.wait()
        for stream in self.streams:
            stream.close()
        self.stop_path.unlink(missing_ok=True)
        self.heartbeat_stop.set()
        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join()
        self.lease_path.unlink(missing_ok=True)
        self.children.clear()
        self.streams.clear()

    def desktop(self):
        bundle = Path(sys.executable).resolve().parent
        desktop = bundle.parent / "desktop" / (PRODUCT + ".exe")
        if not desktop.is_file():
            raise SetupError("Không tìm thấy ứng dụng đi kèm. Hãy cài lại đúng bộ cài này.")
        env = clean_environment()
        env[PREFIX + "API_URL"] = f"http://127.0.0.1:{self.port}/api/v1"
        # Local edition has its own cache; existing LAN partitions/config stay intact.
        env[PREFIX + "LOCAL_DATA_DIR"] = str(self.home / "desktop-data")
        return subprocess.Popen([str(desktop)], cwd=desktop.parent, env=env)
