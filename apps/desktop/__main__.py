import tkinter as tk

from pydantic import ValidationError

from apps.desktop.api.client import DesktopSettings
from apps.desktop.views.shell import DesktopShell


def main() -> None:
    try:
        settings = DesktopSettings()
        root = tk.Tk()
        shell = DesktopShell(root, settings)
    except (ValidationError, OSError, tk.TclError):
        raise SystemExit("Không mở được WMS. Kiểm tra Tk/display, WMS_API_URL và WMS_CA_FILE.") from None
    try:
        root.mainloop()
    finally:
        shell.finish()


if __name__ == "__main__":
    main()
