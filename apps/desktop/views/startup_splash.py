"""Show the application logo while the main window is being constructed."""

import math
import time
import tkinter as tk
from importlib.resources import as_file, files

from PIL import Image, ImageOps, ImageTk


class StartupSplash:
    def __init__(self, root, *, minimum_ms=1000):
        self.root = root
        self.started = time.monotonic()
        self.minimum_ms = minimum_ms
        self.timer = None
        self.closed = False
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title("WMS — Đang khởi động")
        self.window.overrideredirect(True)
        self.window.configure(background="#d9e2ec")
        width, height = 420, 340
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        body = tk.Frame(self.window, background="#ffffff")
        body.pack(fill="both", expand=True, padx=1, pady=1)
        with as_file(files("apps.desktop.assets").joinpath("wms-logo-navy.png")) as path:
            with Image.open(path) as image:
                logo = image.convert("RGBA")
                bounds = logo.getchannel("A").point(lambda alpha: 255 if alpha > 8 else 0).getbbox()
                self.photo = ImageTk.PhotoImage(
                    ImageOps.contain(logo.crop(bounds), (148, 160), Image.Resampling.LANCZOS), master=root,
                )
        tk.Label(body, image=self.photo, background="#ffffff").pack(pady=(30, 12))
        tk.Label(body, text="Quản lý kho", background="#ffffff", foreground="#103b63",
                 font=("Segoe UI", 14, "bold")).pack()
        self.status = tk.Label(body, text="Đang khởi động…", background="#ffffff", foreground="#62758a",
                               font=("Segoe UI", 10))
        self.status.pack(pady=(18, 12))
        self.progress = tk.Canvas(body, width=260, height=4, background="#e8eef4", highlightthickness=0)
        self.progress.pack()
        self.bar = self.progress.create_rectangle(0, 0, 26, 4, fill="#0968a9", outline="")
        self.window.deiconify()
        # Paint before importing/building the heavy desktop views on this same Tk thread.
        self.window.update()

    def stage(self, message, progress):
        if self.closed:
            return
        self.status.configure(text=message)
        self.progress.coords(self.bar, 0, 0, round(260 * progress), 4)
        self.window.update_idletasks()

    def finish(self):
        self.stage("Sẵn sàng", 1)
        elapsed = (time.monotonic() - self.started) * 1000
        self.timer = self.root.after(max(0, math.ceil(self.minimum_ms - elapsed)), self.reveal)

    def reveal(self):
        self.timer = None
        if self.closed:
            return
        self.close()
        self.root.deiconify()
        self.root.lift()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.photo = None
        if self.window.winfo_exists():
            self.window.destroy()
