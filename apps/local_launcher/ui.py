"""First-run and local server controls; all Tk calls remain on the main thread."""

import os
import time
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox, ttk

from sqlalchemy.engine import make_url

from apps.local_launcher.database import SetupError, failure_message, load_environment
from apps.local_launcher.mysql_service import (
    discover_services,
    installed_server,
    mysql_handshake,
    start_service,
)
from apps.local_launcher.product import API_PORT, MYSQL_DOWNLOAD, PREFIX, PRODUCT
from apps.local_launcher.provision import bootstrap_admin, needs_admin, provision
from apps.local_launcher.runtime import Supervisor


def desktop_running():
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenMutexW(0x00100000, False, "Local\\" + PRODUCT + "DesktopRunning")
    if handle:
        kernel.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5  # Access denied also means another user's instance exists.


class SetupWindow:
    def __init__(self, root, home):
        self.root, self.home = root, Path(home)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-setup")
        self.supervisor = None
        self.future = None
        self.download_opened = False
        self.services = []
        self.root.title(PRODUCT + " — MySQL trên máy này")
        self.root.geometry("780x690")
        self.root.minsize(720, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=PRODUCT + " • Thiết lập trên máy này", font=("Segoe UI", 19, "bold")).pack(
            anchor="w"
        )
        ttk.Label(frame, text="MySQL có sẵn → máy chủ tại máy → ứng dụng quản lý kho", wraplength=700).pack(
            anchor="w", pady=(8, 16)
        )
        self.status = tk.StringVar(value="Đang kiểm tra MySQL…")
        ttk.Label(frame, textvariable=self.status, wraplength=700).pack(anchor="w", pady=8)
        form = ttk.Frame(frame)
        form.pack(fill="x")
        self.values = {}
        fields = [
            ("port", "Cổng MySQL", "3306"),
            ("database", "Database riêng", PRODUCT.lower() + "_mysql"),
            ("root", "Mật khẩu MySQL root", ""),
            ("username", "Tài khoản quản trị app", "admin"),
            ("display", "Tên hiển thị", "Quản trị viên"),
            ("password", "Mật khẩu app (12–128 ký tự)", ""),
            ("confirm", "Nhập lại mật khẩu app", ""),
        ]
        for row, (key, label, value) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=5)
            var = tk.StringVar(value=value)
            self.values[key] = var
            entry = ttk.Entry(
                form, textvariable=var, show="•" if key in ("root", "password", "confirm") else ""
            )
            if key == "database":
                entry.configure(state="readonly")
            entry.grid(row=row, column=1, sticky="ew", pady=5, padx=(20, 0))
        form.columnconfigure(1, weight=1)
        self.service = tk.StringVar()
        ttk.Label(form, text="Dịch vụ MySQL").grid(row=7, column=0, sticky="w", pady=5)
        self.service_combo = ttk.Combobox(form, textvariable=self.service, state="readonly")
        self.service_combo.grid(row=7, column=1, sticky="ew", padx=(20, 0))
        self.timezone = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text="Bổ sung múi giờ UTC / Việt Nam nếu MySQL còn thiếu", variable=self.timezone
        ).pack(anchor="w", pady=(14, 4))
        ttk.Label(
            frame,
            text="Database mới chỉ có cấu trúc và tài khoản quản trị; chưa có hàng hay phiếu.\nMật khẩu root chỉ dùng lúc thiết lập, không được lưu. Dữ liệu cũ được giữ nguyên.",
            wraplength=700,
        ).pack(anchor="w", pady=8)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=12)
        self.buttons = []
        for text, command in [
            ("Kiểm tra / bật MySQL", self.detect),
            ("Thiết lập và mở", self.create),
            ("Mở ứng dụng", self.open_app),
            ("Tải MySQL", self.download),
        ]:
            button = ttk.Button(bar, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        ttk.Button(frame, text="Mở bản dùng máy chủ đã cấu hình trước", command=self.existing_client).pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="Cửa sổ này quản lý máy chủ tại máy. Đóng ứng dụng kho trước khi đóng cửa sổ này.\nNếu Windows hỏi UAC khi bật MySQL, chọn Yes để cấp quyền khởi động dịch vụ.",
            wraplength=700,
        ).pack(anchor="w", pady=12)
        root.after(100, self.detect)

    def work(self, function, done):
        if self.future is not None:
            return
        for button in self.buttons:
            button.configure(state="disabled")
        self.future = self.pool.submit(function)
        self.done = done
        self.root.after(100, self.poll)

    def poll(self):
        if not self.future.done():
            self.root.after(100, self.poll)
            return
        future, self.future = self.future, None
        for button in self.buttons:
            button.configure(state="normal")
        try:
            result = future.result()
        except Exception as exc:
            message = str(exc) if isinstance(exc, SetupError) else failure_message(exc)
            self.status.set(message)
            messagebox.showerror(PRODUCT + " — Cần kiểm tra", message, parent=self.root)
            return
        self.done(result)

    def detect(self):
        if self.future is not None or self.supervisor is not None:
            return
        try:
            port = int(self.values["port"].get())
            if (self.home / "runtime.json").exists():
                env = load_environment(self.home)
                port = make_url(env[PREFIX + "DATABASE_URL"]).port or 3306
                self.values["port"].set(str(port))
            if not 1 <= port <= 65535:
                raise ValueError()
        except Exception:
            self.status.set("Cấu hình hoặc cổng chưa hợp lệ. Kiểm tra lại; không xóa dữ liệu cũ.")
            return
        selected = self.service.get()
        self.status.set("Đang kiểm tra / khởi động dịch vụ MySQL…")

        def detect_and_start():
            if mysql_handshake(port):
                return "ready", []
            services = discover_services()
            candidate = next((s for s in services if s.name == selected), None)
            if candidate is None and len(services) == 1:
                candidate = services[0]
            if candidate is not None and not candidate.running:
                start_service(candidate.name)  # Re-discover before privileged action.
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if mysql_handshake(port):
                        return "ready", services
                    time.sleep(0.5)
            if services:
                return "select" if len(services) > 1 and candidate is None else "stopped", services
            return ("installed" if installed_server() else "missing"), services

        def finish(result):
            state, self.services = result
            self.service_combo.configure(values=[s.name for s in self.services])
            if len(self.services) == 1:
                self.service.set(self.services[0].name)
            if state == "ready":
                self.status.set(
                    "MySQL đang chạy. Nhập mật khẩu để thiết lập lần đầu, hoặc mở ứng dụng đã cấu hình."
                )
                if (self.home / "runtime.json").exists():
                    self.open_app()
            elif state == "missing":
                self.status.set(
                    "Chưa phát hiện MySQL Server tại cổng này. Trang tải chính thức đã được mở; cài Server, rồi bấm Kiểm tra / bật MySQL. Nếu cài ở cổng khác, nhập đúng cổng."
                )
                if not self.download_opened:
                    self.download()
            elif state == "select":
                self.status.set(
                    "Có nhiều dịch vụ MySQL. Chọn đúng dịch vụ và cổng rồi bấm Kiểm tra / bật MySQL."
                )
            elif state == "installed":
                self.status.set(
                    "Đã có MySQL Server nhưng chưa có dịch vụ. Hoàn tất MySQL Configurator, bật dịch vụ và kiểm tra lại."
                )
            else:
                self.status.set(
                    "Đã phát hiện dịch vụ nhưng chưa kết nối được. Kiểm tra cổng hoặc cấu hình dịch vụ; không cần cài lại."
                )

        self.work(detect_and_start, finish)

    def download(self):
        self.download_opened = True
        webbrowser.open(MYSQL_DOWNLOAD, new=2)

    def create(self):
        if self.supervisor is not None or self.future is not None:
            return
        values = {k: v.get() for k, v in self.values.items()}
        if values["password"] != values["confirm"]:
            self.status.set("Hai mật khẩu app không khớp.")
            return
        timezone = self.timezone.get()
        for key in ("root", "password", "confirm"):
            self.values[key].set("")
        self.status.set("Đang tạo database mới và tài khoản quản trị. Vui lòng chờ, không đóng cửa sổ…")

        def create_database():
            try:
                if (self.home / "runtime.json").exists():
                    if not needs_admin(self.home):
                        raise SetupError("Đã có tài khoản. Hãy bấm Mở ứng dụng.")
                    bootstrap_admin(self.home, values["username"], values["display"], values["password"])
                else:
                    provision(
                        self.home,
                        root_password=values["root"],
                        mysql_port=int(values["port"]),
                        api_port=API_PORT,
                        database=values["database"],
                        username=values["username"],
                        display_name=values["display"],
                        password=values["password"],
                        timezone=timezone,
                    )
            finally:
                values.clear()

        self.work(create_database, lambda _: self.open_app())

    def open_app(self):
        if self.future is not None:
            return
        if self.supervisor is not None:
            if self.supervisor.failed():
                self.status.set("Máy chủ đã gặp lỗi. Đóng app rồi đóng cửa sổ này để dừng an toàn; xem logs.")
            else:
                self.supervisor.desktop()
            return
        if not (self.home / "runtime.json").exists():
            self.status.set("Chưa có cấu hình máy chủ tại máy. Hãy hoàn thành Thiết lập và mở.")
            return
        self.status.set("Đang kiểm tra cấu hình và khởi động máy chủ…")

        def start():
            if needs_admin(self.home):
                raise SetupError(
                    "Database đã tạo, còn thiếu tài khoản. Nhập tài khoản/mật khẩu app và bấm Thiết lập và mở; không cần mật khẩu root."
                )
            supervisor = Supervisor(self.home)
            supervisor.start()
            return supervisor

        def opened(supervisor):
            self.supervisor = supervisor
            try:
                supervisor.desktop()
                self.status.set(
                    "Máy chủ đã sẵn sàng. Đăng nhập bằng tài khoản vừa tạo, bật MFA và cấp quyền theo quy trình trong app."
                )
                self.root.iconify()
            except SetupError as exc:
                self.status.set(str(exc))

        self.work(start, opened)

    def existing_client(self):
        import subprocess
        import sys

        if self.future is not None:
            return
        path = Path(sys.executable).resolve().parent.parent / "desktop" / (PRODUCT + ".exe")
        if not path.is_file():
            self.status.set("Không tìm thấy bộ giao diện đi kèm.")
            return
        # No overrides: retain the pre-existing client.json/API/cache configuration.
        from apps.local_launcher.runtime import clean_environment

        env = clean_environment()
        for key, value in os.environ.items():
            if key.upper() in {PREFIX + "API_URL", PREFIX + "LOCAL_DATA_DIR"}:
                env[key] = value
        subprocess.Popen([str(path)], cwd=path.parent, env=env)

    def close(self):
        if self.future is not None:
            self.status.set("Đang xử lý. Vui lòng đợi hoàn tất trước khi đóng.")
            return
        if desktop_running():
            messagebox.showinfo(
                PRODUCT,
                "Đóng ứng dụng kho trước để các thao tác hoàn tất, rồi đóng cửa sổ này.",
                parent=self.root,
            )
            return
        if self.supervisor is not None:
            supervisor, self.supervisor = self.supervisor, None
            self.status.set("Đang dừng máy chủ, chờ các giao dịch hoàn tất…")
            self.work(supervisor.stop, lambda _: self.finish_close())
        else:
            self.finish_close()

    def finish_close(self):
        self.pool.shutdown(wait=True)
        self.root.destroy()
