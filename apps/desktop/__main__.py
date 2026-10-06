import sqlite3
import tkinter as tk
from tkinter import messagebox

from pydantic import ValidationError

from apps.desktop.startup import application_lock, configure_display, preflight_cache, settings_for_startup
from apps.desktop.views.shell import DesktopShell


def main() -> None:
    lock = root = shell = None
    try:
        settings = settings_for_startup()
        lock = application_lock(settings.local_data_dir)
        preflight_cache(settings.local_data_dir)
        configure_display()
        root = tk.Tk(className="WMSDesktop")
        shell = DesktopShell(root, settings)
        root.mainloop()
    except (ValidationError, ValueError, OSError, sqlite3.Error, tk.TclError):
        message = "Không mở được WMS. Kiểm tra cấu hình API/CA, phiên bản cache và cửa sổ đang mở. Giữ nguyên thư mục dữ liệu; không xóa nháp hoặc cài lùi."
        try:
            messagebox.showerror("WMS — Không khởi động được", message, parent=root)
        except tk.TclError:
            pass
        raise SystemExit(message) from None
    finally:
        try:
            if shell is not None:
                shell.finish()
            elif root is not None:
                root.destroy()
        finally:
            if lock is not None:
                lock.close()


if __name__ == "__main__":
    main()
