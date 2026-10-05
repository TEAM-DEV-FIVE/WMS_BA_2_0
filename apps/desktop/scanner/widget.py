"""Main-thread scanner field; server validates exact item and quantity before selection."""

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from tkinter import ttk
from uuid import uuid4

from apps.desktop.scanner.hid import HID


class ScanBar(ttk.Frame):
    def __init__(self, parent, view, flow):
        super().__init__(parent)
        self.view, self.flow, self.api = view, flow, view.presenter.api
        self.scan_context = None
        self.hid = HID()
        self.pending = None
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-scan")
        self.results = Queue()
        self.code = tk.StringVar()
        self.quantity = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Quét để chọn dòng; xác nhận nghiệp vụ riêng.")
        ttk.Label(self, text="HID").pack(side="left")
        self.entry = ttk.Entry(self, textvariable=self.code, width=25)
        self.entry.pack(side="left", padx=3)
        self.entry.bind("<KeyPress>", self.key)
        self.entry.bind("<FocusOut>", lambda e: self.clear_buffer())
        ttk.Label(self, text="SL quét").pack(side="left")
        ttk.Entry(self, textvariable=self.quantity, width=7).pack(side="left", padx=3)
        ttk.Label(self, textvariable=self.status, wraplength=370).pack(side="left")
        self.poll_id = self.after(50, self.poll)
        self.bind("<Destroy>", self.destroyed, add=True)

    def clear_buffer(self):
        self.hid.reset()
        self.code.set("")

    def key(self, event):
        try:
            current = self.context()
            if current != self.scan_context:
                self.clear_buffer()
                self.scan_context = current
            value = self.hid.key(event.char, event.keysym, self.entry.focus_get() == self.entry)
            self.code.set(self.hid.buffer)
            if value:
                self.scan(value)
        except ValueError as error:
            self.status.set(str(error))
            self.code.set("")
        return "break"

    def context(self):
        doc = getattr(self.view, "doc", None)
        return (
            (
                self.api.session_generation,
                doc["id"],
                doc["version"],
                getattr(self.view.presenter, "sequence", None),
            )
            if doc
            else None
        )

    def scan(self, code):
        context = self.context()
        if (
            not context
            or self.pending
            or self.closed
            or getattr(self.view, "busy", False)
            or getattr(self.view.presenter, "uncertain", False)
        ):
            self.status.set("Mở phiếu và chờ thao tác hiện tại hoàn tất.")
            return
        body = dict(
            flow=self.flow,
            source_id=context[1],
            expected_version=context[2],
            code=code,
            quantity=self.quantity.get(),
        )

        api = self.api

        def run():
            # Read-only validation endpoint, deliberately no idempotency journal or stock command.
            return api.command("POST", "printing/scan", body, str(uuid4()))

        self.status.set("Đang xác thực mã…")
        self.pending = self.executor.submit(self.api.in_session, context[0], run)
        self.pending.add_done_callback(lambda future: self.results.put((context, code, future)))

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                context, code, future = self.results.get_nowait()
            except Empty:
                break
            self.pending = None
            if context != self.context():
                continue
            try:
                result = future.result()
                matches = result["matches"]
                if len(matches) != 1:
                    self.status.set("Mã khớp nhiều dòng/chủ/vị trí; chọn dòng cụ thể trước.")
                    continue
                self.apply(matches[0], code)
                self.status.set("Đã chọn đúng dòng; kiểm tra vị trí rồi xác nhận.")
            except Exception as error:
                self.status.set(str(error))
        self.poll_id = self.after(50, self.poll)

    def apply(self, match, code):
        view = self.view
        context = self.context()
        if self.flow == "COUNT":
            view.lines.selection_set(match["line_id"])
            view.lines.see(match["line_id"])
            field = "quantity"
        elif self.flow == "PICK":
            view.task_table.selection_set(match["task_id"])
            view.task_table.see(match["task_id"])
            field = "quantity"
        else:
            index = next(
                (
                    i
                    for i, line in enumerate(view.lines)
                    if str(line.get("id") or line.get("document_line_id")) == match["line_id"]
                ),
                None,
            )
            if index is None:
                raise ValueError("Dòng trên màn hình đã thay đổi; tải lại phiếu.")
            view.line_table.selection_set(str(index))
            view.line_table.see(str(index))
            field = "quantity" if self.flow == "TRANSFER" else "qty"

        # TreeviewSelect runs after selection_set and may populate its default quantity.
        # Apply the validated scan only after that handler, still on Tk's thread.
        def fill():
            if self.closed or context != self.context():
                return
            view.variables[field].set(match["quantity_base"])
            if self.flow == "PICK":
                view.scan("item_code", match["sku"])
                if match["serial_code"]:
                    view.scan("trace_code", match["serial_code"])

        self.after_idle(fill)

    def destroyed(self, event):
        if event.widget is self:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.after_cancel(self.poll_id)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.code = self.quantity = self.status = None
        # A running worker holds only API/context; do not capture Tk in worker closures.
