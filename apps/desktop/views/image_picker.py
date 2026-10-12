"""Use the OS file chooser, without blocking Tk while the Linux chooser runs."""
import shutil
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog


def image_directory():
    home = Path.home()
    return next((path for path in (home / "Pictures", home / "Ảnh", home / "Downloads") if path.is_dir()), home)


class ImagePicker:
    def __init__(self, parent, on_selected):
        self.parent = parent
        self.on_selected = on_selected
        self.process = None
        self.timer = None
        self.closed = False

    def start(self):
        executable = shutil.which("zenity") if sys.platform.startswith("linux") else None
        if not executable:
            self.fallback()
            return
        try:
            self.process = subprocess.Popen([
                executable, "--file-selection", "--title=Chọn ảnh đại diện", "--modal",
                "--width=900", "--height=600", "--filename=" + str(image_directory()) + "/",
                "--file-filter=Ảnh | *.jpg *.jpeg *.png *.webp *.JPG *.JPEG *.PNG *.WEBP",
                "--file-filter=Tất cả tệp | *",
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        except OSError:
            self.fallback()
            return
        # The native chooser owns input while open; restore the profile's grab on return.
        self.parent.grab_release()
        self.poll()

    def poll(self):
        self.timer = None
        if self.closed:
            return
        if self.process.poll() is None:
            self.timer = self.parent.after(80, self.poll)
            return
        output, _ = self.process.communicate()
        code = self.process.returncode
        self.process = None
        if code not in (0, 1):
            self.fallback()
        else:
            self.finish(output.removesuffix("\n") if code == 0 else "")

    def fallback(self):
        if not self.closed:
            self.finish(filedialog.askopenfilename(parent=self.parent, title="Chọn ảnh đại diện",
                initialdir=str(image_directory()), filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp"), ("Tất cả tệp", "*")]))

    def finish(self, path):
        if self.closed:
            return
        self.closed = True
        if self.parent.winfo_exists():
            self.parent.lift()
            self.parent.grab_set()
            self.on_selected(path)
        self.on_selected = None

    def cancel(self):
        self.closed = True
        self.on_selected = None
        if self.timer is not None:
            self.parent.after_cancel(self.timer)
            self.timer = None
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.communicate(timeout=.2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
            self.process = None
