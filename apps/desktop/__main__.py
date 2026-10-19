import sqlite3
import tkinter as tk
from tkinter import messagebox

from pydantic import ValidationError

from apps.desktop.lifecycle import restart_application
from apps.desktop.startup import application_lock, configure_display, preflight_cache, settings_for_startup
from apps.desktop.views.startup_splash import StartupSplash


def create_shell(root, settings):
    # Import after painting the splash, so module loading is covered too.
    from apps.desktop.views.shell import DesktopShell

    return DesktopShell(root, settings)


def main() -> None:
    lock = root = shell = splash = None
    try:
        settings = settings_for_startup()
        lock = application_lock(settings.local_data_dir)
        configure_display()
        root = tk.Tk(className="WMSDesktop")
        root.withdraw()
        splash = StartupSplash(root)
        splash.stage("Kiểm tra dữ liệu trên máy…", .2)
        preflight_cache(settings.local_data_dir)
        splash.stage("Đang tải giao diện…", .55)
        shell = create_shell(root, settings)
        shell.session_view.presenter.api.enable_persistence()
        splash.finish()
        root.mainloop()
    except (ValidationError, ValueError, OSError, sqlite3.Error, tk.TclError):
        if splash is not None:
            splash.close()
        message = "Không mở được WMS. Kiểm tra cấu hình API/CA, phiên bản cache và cửa sổ đang mở. Giữ nguyên thư mục dữ liệu; không xóa nháp hoặc cài lùi."
        try:
            messagebox.showerror("WMS — Không khởi động được", message, parent=root)
        except tk.TclError:
            pass
        raise SystemExit(message) from None
    finally:
        try:
            if splash is not None:
                splash.close()
            if shell is not None:
                shell.finish()
            elif root is not None:
                root.destroy()
        finally:
            if lock is not None:
                lock.close()
    if shell is not None and shell.restart_requested:
        try:
            restart_application()
        except OSError:
            messagebox.showerror("Không tải lại được giao diện",
                                 "Ứng dụng đã đóng an toàn nhưng không tự mở lại được. Vui lòng mở WMS lại.")


if __name__ == "__main__":
    main()
