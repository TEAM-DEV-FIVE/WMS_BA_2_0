"""Product descriptions from authorized metadata, with packaged illustrative photos."""

import json
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import as_file, files
from queue import Empty, Queue
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from apps.desktop.api.client import ApiError
from apps.desktop.catalog_display import display_sku


def read_photo(key):
    assets = files("apps.desktop.assets").joinpath("catalog")
    sources = json.loads(assets.joinpath("sources.json").read_text())
    source = sources.get(key)
    if source is None:
        return None, None
    # Only manifest entries can select a local asset; metadata is never a URL/path.
    with as_file(assets.joinpath(source["file"])) as path, Image.open(path) as photo:
        image = ImageOps.contain(photo.convert("RGB"), (330, 280), Image.Resampling.LANCZOS)
    return image, source


class ProductProfile:
    def __init__(self, parent, api, product):
        self.api, self.generation = api, api.session_generation
        self.closed, self.photo = False, None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-product-profile")
        self.results = Queue()
        self.window = tk.Toplevel(parent)
        self.window.title("Thông tin sản phẩm  " + display_sku(product["sku"]))
        self.window.geometry("920x620")
        self.window.minsize(680, 480)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=product["name"], font=("Segoe UI", 16, "bold"), wraplength=820).pack(anchor="w")
        ttk.Label(body, text="SKU: " + display_sku(product["sku"])).pack(anchor="w", pady=(4, 16))
        self.message = ttk.Label(body, text="Đang tải hồ sơ sản phẩm…", wraplength=820)
        self.message.pack(side="bottom", fill="x", pady=(12, 0))
        content = ttk.Frame(body)
        content.pack(fill="both", expand=True)
        left = ttk.Frame(content)
        left.pack(side="left", fill="y", padx=(0, 20))
        self.image_label = ttk.Label(left, text="Đang tải ảnh…", anchor="center")
        self.image_label.pack(pady=10)
        self.credit = ttk.Label(left, wraplength=310, justify="left")
        self.credit.pack(fill="x", pady=10)
        self.source_button = ttk.Button(left, text="Nguồn ảnh và giấy phép")
        right = ttk.Frame(content)
        right.pack(side="left", fill="both", expand=True)
        self.text = tk.Text(
            right,
            wrap="word",
            width=42,
            relief="flat",
            padx=12,
            pady=12,
            font=("Segoe UI", 11),
            state="disabled",
        )
        self.text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(right, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        # The worker captures data only; Tk/image objects stay on the UI thread.
        results, generation, product_id = self.results, self.generation, product["id"]

        def fetch():
            def read():
                profile = api.get("custom-fields/products/" + product_id)
                image, source = read_photo(profile["values"].get("image_key", ""))
                return profile, image, source

            return api.in_session(generation, read)

        future = self.executor.submit(fetch)
        future.add_done_callback(results.put)
        self.timer = self.window.after(60, self.drain)

    def drain(self):
        if self.closed:
            return
        if self.api.session_generation != self.generation:
            self.close()
            return
        try:
            future = self.results.get_nowait()
        except Empty:
            self.timer = self.window.after(60, self.drain)
            return
        try:
            profile, image, source = future.result()
        except ApiError as exc:
            self.message.configure(text=str(exc))
            self.image_label.configure(text="Không tải được hồ sơ")
        except Exception:
            self.message.configure(text="Không đọc được hồ sơ; Đóng và mở lại để thử lại")
        else:
            if image is not None:
                self.photo = ImageTk.PhotoImage(image, master=self.window)
                self.image_label.configure(image=self.photo, text="")
                self.credit.configure(
                    text=source["note"] + "\n\n" + source["author"] + "  " + source["license"]
                )
                self.source_button.configure(command=lambda: webbrowser.open(source["source"], new=2))
                self.source_button.pack(anchor="w")
            else:
                self.image_label.configure(text="Chưa có ảnh sản phẩm")
            self.text.configure(state="normal")
            for field in profile["schema"]["fields"]:
                value = profile["values"].get(field["code"])
                if value is not None and field["code"] != "image_key":
                    self.text.insert("end", field["label"] + "\n" + str(value) + "\n\n")
            self.text.configure(state="disabled")
            self.message.configure(text="Mô tả lưu trên máy chủ  Chỉnh sửa tại Trường mở rộng → Sản phẩm")
        self.timer = self.window.after(150, self.check_session)

    def check_session(self):
        if self.closed:
            return
        if self.api.session_generation != self.generation:
            self.close()
        else:
            self.timer = self.window.after(150, self.check_session)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.window.after_cancel(self.timer)
        self.image_label.configure(image="")
        self.photo = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.window.destroy()
