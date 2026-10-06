"""Main-thread recovery UI; workers return only data and sanitized messages."""

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Empty, Queue
from tkinter import messagebox, ttk

from apps.desktop.api.client import ApiError


def recovery_work(api, generation, action, key, warehouse, body=None):
    def run():
        result = (api.recovery_detail(key) if action == "detail"
                  else api.edit_draft(key, body) if action == "edit"
                  else api.discard_draft(key) if action == "discard"
                  else api.recover(key, retry=action == "retry") if key else None)
        return api.recovery_records(warehouse), result
    try:
        rows, result = api.in_session(generation, run)
        return rows, result, ""
    except ApiError as error:
        return [], None, str(error)
    except Exception:
        return [], None, "Không đọc được phục hồi. Giữ dữ liệu cục bộ để đối chiếu."


class RecoveryView(ttk.Frame):
    def __init__(self, parent, api):
        super().__init__(parent, padding=12)
        self.api = api
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wms-recovery-http")
        self.results = Queue()
        self.sequence = 0
        self.user = self.pending = None
        self.closed = False
        self.rows = {}
        self.detail = None
        self.fields = {}
        self.scopes = [None, "GLOBAL"]
        self.status = tk.StringVar(value="Đăng nhập để mở nhật ký của bạn trên thiết bị này.")
        ttk.Label(self, text="Nháp và phục hồi lệnh", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="Không tự gửi khi mở ứng dụng. Tra ACK trước; gửi lại giữ đúng key, nội dung và version.\n"
                  "Xung đột: tải lại chứng từ ở màn nghiệp vụ và đối chiếu thủ công. In phục hồi chỉ là ACK, không gửi máy in.",
                  wraplength=800).pack(anchor="w", pady=8)
        self.selector = ttk.Combobox(self, state="readonly", values=["Tất cả kho", "Danh mục / chưa xác định kho"])
        self.selector.current(0)
        self.selector.pack(anchor="w")
        self.selector.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.tree = ttk.Treeview(self, columns=("state", "path", "warehouse", "time"), show="headings", height=7)
        for name, title, width in [("state", "Trạng thái", 100), ("path", "Thao tác", 360),
                                   ("warehouse", "Kho", 120), ("time", "Cập nhật", 180)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width)
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.clear_detail())
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.buttons = []
        for text, callback in [("Tải nhật ký", self.refresh), ("Tra ACK", lambda: self.selected("lookup")),
                               ("Xem nội dung", lambda: self.selected("detail")),
                               ("Gửi nháp / gửi lại cùng key", lambda: self.selected("retry")),
                               ("Bỏ nháp chưa gửi", lambda: self.selected("discard"))]:
            button = ttk.Button(controls, text=text, command=callback)
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        self.detail_tree = ttk.Treeview(self, columns=("field", "value"), show="headings", height=5)
        self.detail_tree.heading("field", text="Trường / dòng")
        self.detail_tree.heading("value", text="Nội dung đã lưu (cần quyền hiện tại để xem)")
        self.detail_tree.pack(fill="both", pady=4)
        self.detail_tree.bind("<<TreeviewSelect>>", self.choose_field)
        edit = ttk.Frame(self)
        edit.pack(fill="x")
        self.edit_value = tk.StringVar()
        self.edit_entry = ttk.Entry(edit, textvariable=self.edit_value, width=65)
        self.edit_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(edit, text="Sửa trường nháp", command=self.edit_field).pack(side="left")
        ttk.Button(edit, text="Lưu sửa nháp", command=self.save_edits).pack(side="left")
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(anchor="w", pady=8)

    def clear_detail(self):
        if self.closed:
            return
        self.detail = None
        self.fields.clear()
        self.detail_tree.delete(*self.detail_tree.get_children())
        self.edit_value.set("")

    def show_detail(self, detail):
        self.clear_detail()
        self.detail = detail
        def visit(value, path=()):
            if isinstance(value, dict):
                for field, child in value.items():
                    visit(child, path + (field,))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, path + (index,))
            else:
                item = str(len(self.fields))
                self.fields[item] = (path, value)
                label = " / ".join(f"Dòng {p + 1}" if isinstance(p, int) else p.replace("_", " ") for p in path)
                self.detail_tree.insert("", "end", iid=item, values=(label, "" if value is None else str(value)))
        visit(detail["body"])

    def choose_field(self, event=None):
        selected = self.detail_tree.selection()
        if selected:
            self.edit_value.set(str(self.fields[selected[0]][1]))

    def edit_field(self):
        selected = self.detail_tree.selection()
        if not selected or not self.detail or not self.detail["editable"]:
            return
        path, old = self.fields[selected[0]]
        if isinstance(path[-1], str) and (path[-1].endswith(("_id", "_version", "_key")) or path[-1] == "id"):
            self.status.set("Đổi tham chiếu hoặc phiên bản: tải lại màn nghiệp vụ để lập nháp mới.")
            return
        value = self.edit_value.get()
        try:
            if isinstance(old, bool):
                if value not in {"True", "False"}:
                    raise ValueError
                value = value == "True"
            elif isinstance(old, int):
                value = int(value)
            elif old is None:
                value = value or None
        except ValueError:
            self.status.set("Giữ đúng kiểu dữ liệu của trường đang sửa.")
            return
        target = self.detail["body"]
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value
        self.fields[selected[0]] = path, value
        self.detail_tree.set(selected[0], "value", str(value))
        self.status.set("Đã sửa trên màn hình; chọn Lưu sửa nháp để giữ xuống máy. Chưa gửi máy chủ.")

    def save_edits(self):
        if self.detail and self.detail["editable"]:
            self.submit("edit", self.detail["key"], deepcopy(self.detail["body"]))

    def session_changed(self, user=None, warehouses=None):
        self.sequence += 1
        self.user = str(user.id) if user else None
        self.rows.clear()
        self.clear_detail()
        self.tree.delete(*self.tree.get_children())
        self.pending = None
        self.scopes = [None, "GLOBAL"] + [str(w.id) for w in warehouses or []]
        self.selector.configure(values=["Tất cả kho", "Danh mục / chưa xác định kho"] + [w.name for w in warehouses or []])
        self.selector.current(0)
        self.status.set("Nhật ký riêng theo máy chủ, tài khoản và thiết bị." if user else "Đăng nhập để mở nhật ký.")
        if user:
            self.refresh()

    def refresh(self):
        self.submit("list")

    def selected(self, action):
        selected = self.tree.selection()
        if not selected or self.pending:
            return
        key = selected[0]
        row = self.rows[key]
        if action == "discard" and (row["state"] != "DRAFT" or not messagebox.askyesno(
                "Bỏ nháp chưa gửi", "Xóa nháp này? Lệnh đã gửi luôn được giữ lại.", parent=self)):
            return
        if action == "retry" and not messagebox.askyesno(
                "Gửi đúng lệnh đã lưu", f"{row['method']} {row['path']}\nKey: {key}\n"
                "Tra ACK rồi gửi đúng nội dung/version cũ nếu chưa có kết quả?\n"
                "Nếu đã sửa chứng từ, hãy hủy và tải lại để đối chiếu trước.", parent=self):
            return
        self.submit(action, key)

    def submit(self, action, key=None, body=None):
        if self.closed or not self.user or self.pending:
            return
        self.sequence += 1
        seq, generation = self.sequence, self.api.session_generation
        self.status.set("Đang tra cứu…")
        self.pending = self.executor.submit(recovery_work, self.api, generation, action, key,
                                            self.scopes[self.selector.current()], body)
        queue = self.results
        self.pending.add_done_callback(lambda future: queue.put((seq, generation, future)))

    def drain(self):
        while True:
            try:
                seq, generation, future = self.results.get_nowait()
            except Empty:
                break
            if self.closed or seq != self.sequence:
                continue
            self.pending = None
            if generation != self.api.session_generation:
                self.session_changed()
                continue
            rows, result, error = future.result()
            self.clear_detail()
            self.rows = {r["key"]: r for r in rows}
            self.tree.delete(*self.tree.get_children())
            for row in rows:
                self.tree.insert("", "end", iid=row["key"], values=(row["state"], row["method"] + " " + row["path"],
                                                                         row["warehouse"], row["updated_at"]))
            self.status.set(error or ("Máy chủ đã xác nhận. Tải lại màn nghiệp vụ để xem kết quả hiện tại."
                                      if result else f"{len(rows)} lệnh. Nháp chưa gửi không phải dữ liệu đã ghi sổ."))
            if result and "editable" in result:
                # Tree selection events from the list reset occur on the next Tk tick.
                self.after_idle(lambda data=result, seq=seq, generation=generation: self.show_detail(data)
                                if not self.closed and self.sequence == seq and self.api.session_generation == generation else None)
                self.status.set("Nháp chưa gửi có thể sửa trường; version và tham chiếu giữ nguyên."
                                if result["editable"] else "Lệnh đã gửi: nội dung chỉ đọc.")

    def close(self):
        self.closed = True
        self.sequence += 1
        self.executor.shutdown(wait=False, cancel_futures=True)

    def release_variables(self):
        self.status = None
        self.edit_value = None
        self.detail = None

    def finish(self):
        self.executor.shutdown(wait=True)
        self.pending = None
        self.rows.clear()
        while not self.results.empty():
            self.results.get_nowait()
