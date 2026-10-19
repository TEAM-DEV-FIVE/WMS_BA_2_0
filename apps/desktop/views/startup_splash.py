"""Show the application logo while the main window is being constructed."""

import math
import time
import tkinter as tk
from importlib.resources import as_file, files

from PIL import Image, ImageOps, ImageTk

from apps.desktop.views.rounded_window import round_window, rounded_outline


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
        transparent_color = "#f0e1f0" if root.tk.call("tk", "windowingsystem") == "win32" else "#ffffff"
        self.window.configure(background=transparent_color)
        width, height, radius = 340, 280, 22
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        body = tk.Canvas(self.window, background=transparent_color, highlightthickness=0)
        body.pack(fill="both", expand=True)
        body.create_polygon(rounded_outline(width, height, radius, 2),
                            fill="#ffffff", outline="#6396bc", width=2)
        with as_file(files("apps.desktop.assets").joinpath("wms-logo-navy.png")) as path:
            with Image.open(path) as image:
                logo = image.convert("RGBA")
                bounds = logo.getchannel("A").point(lambda alpha: 255 if alpha > 8 else 0).getbbox()
                self.photo = ImageTk.PhotoImage(
                    ImageOps.contain(logo.crop(bounds), (114, 124), Image.Resampling.LANCZOS), master=root,
                )
        body.create_image(width//2, 24, image=self.photo, anchor="n")
        body.create_text(width//2, 169, text="Quản lý kho", fill="#103b63", font=("Segoe UI", 13, "bold"))
        self.status = tk.Label(body, text="Đang khởi động…", background="#ffffff", foreground="#62758a",
                               font=("Segoe UI", 10))
        body.create_window(width//2, 214, window=self.status)
        self.progress = tk.Canvas(body, width=220, height=4, background="#e8eef4", highlightthickness=0)
        body.create_window(width//2, 241, window=self.progress)
        self.bar = self.progress.create_rectangle(0, 0, 22, 4, fill="#0968a9", outline="")
        self.window.update_idletasks()
        round_window(self.window, width, height, radius, transparent_color)
        self.window.deiconify()
        # Paint before importing/building the heavy desktop views on this same Tk thread.
        self.window.update()

    def stage(self, message, progress):
        if self.closed:
            return
        self.status.configure(text=message)
        self.progress.coords(self.bar, 0, 0, round(220 * progress), 4)
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
