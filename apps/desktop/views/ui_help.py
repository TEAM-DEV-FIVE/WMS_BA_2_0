"""On-demand guidance and optional sections without changing form state."""
import tkinter as tk
from tkinter import ttk


class HelpButton(ttk.Button):
    def __init__(self, parent, text, *, title="Hướng dẫn", label="Hướng dẫn"):
        self.help_text, self.help_title = text, title
        super().__init__(parent, text=label, command=self.show)

    def show(self):
        window = tk.Toplevel(self)
        window.title(self.help_title)
        window.transient(self.winfo_toplevel())
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        options = ({"textvariable": self.help_text} if hasattr(self.help_text, "get")
                   else {"text": self.help_text or "Chưa có thông tin"})
        ttk.Label(body, **options, wraplength=520, justify="left").pack(fill="both", expand=True)
        ttk.Button(body, text="Đóng", command=window.destroy).pack(anchor="e", pady=(16, 0))
        window.bind("<Escape>", lambda event: window.destroy())

    def destroy(self):
        # A help panel can hold a live Tk variable owned by its view. Release
        # that reference on the UI thread before the closed view reaches GC.
        self.help_text = None
        super().destroy()


class Disclosure(ttk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title, self.open = title, False
        self.button = ttk.Button(self, text="› " + title, command=self.toggle)
        self.button.pack(anchor="w")
        self.body = ttk.Frame(self, padding=(0, 8))

    def toggle(self):
        self.open = not self.open
        self.button.configure(text=("⌄ " if self.open else "› ") + self.title)
        if self.open:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()


class StatusButton(HelpButton):
    """Keep full feedback available without a permanent paragraph on the page."""
    def __init__(self, parent, variable):
        super().__init__(parent, variable, title="Trạng thái thao tác", label="Xem trạng thái")
        self.sources = [("Nghiệp vụ", variable, variable.trace_add("write", self.refresh))]
        self.refresh()

    def add_source(self, title, variable):
        if len(self.sources) == 1:
            self.help_text = tk.StringVar(master=self)
        self.sources.append((title, variable, variable.trace_add("write", self.refresh)))
        self.refresh()

    def refresh(self, *args):
        values = [(title, variable.get()) for title, variable, _ in self.sources]
        value = "\n\n".join(f"{title}\n{text}" for title, text in values if text)
        if len(self.sources) > 1:
            self.help_text.set(value)
        warning = any(word in value.lower() for word in ("lỗi", "không thể", "không hợp lệ", "chưa rõ", "thất bại"))
        busy = any(text.startswith("Đang") for _, text in values)
        self.configure(text="Cần kiểm tra · Xem" if warning else "Đang xử lý…" if busy else "Xem trạng thái",
                       style="Danger.TButton" if warning else "TButton")

    def destroy(self):
        for _, variable, trace_id in self.sources:
            variable.trace_remove("write", trace_id)
        self.sources.clear()
        super().destroy()
