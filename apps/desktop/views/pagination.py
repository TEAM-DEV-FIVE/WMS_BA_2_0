"""Shared cursor history and table-footer navigation, committed only on success."""
from math import ceil
from tkinter import ttk


class CursorPages:
    def __init__(self, limit=50):
        self.limit = limit
        self.reset()

    def reset(self):
        self.cursors = [None]
        self.index = 0
        self.requested = None
        self.next_after = None
        self.total = None
        self.count = 0
        self.loaded = False

    def accept(self, result):
        after = self.requested
        if after is None:
            self.cursors = [None]
            self.index = 0
        elif after in self.cursors:
            self.index = self.cursors.index(after)
        else:
            self.cursors = self.cursors[:self.index + 1] + [after]
            self.index += 1
        self.count = len(result.get("items", []))
        self.next_after = result.get("next_after")
        self.total = result.get("total")
        if self.total is None and self.next_after is None:
            self.total = self.index * self.limit + self.count
        self.loaded = True

    @property
    def label(self):
        if not self.loaded:
            return "Chưa tải dữ liệu"
        if self.total == 0:
            return "0 kết quả"
        suffix = f" / {max(1, ceil(self.total / self.limit))}" if self.total is not None else ""
        return f"Trang {self.index + 1}{suffix}"


class PaginationBar(ttk.Frame):
    def __init__(self, parent, command, *, limit=50):
        super().__init__(parent, padding=(0, 8))
        self.command = command
        self.pages = CursorPages(limit)
        self.available = False
        self.columnconfigure(0, weight=1, uniform="edge")
        self.columnconfigure(2, weight=1, uniform="edge")
        self.summary = ttk.Label(self, style="Muted.TLabel")
        self.summary.grid(row=0, column=0, sticky="w")
        self.navigation = ttk.Frame(self)
        self.navigation.grid(row=0, column=1)
        self.previous_button = ttk.Button(self.navigation, text="‹ Trước", command=self.previous)
        self.previous_button.pack(side="left")
        self.position = ttk.Label(self.navigation, text="Chưa tải dữ liệu", anchor="center", width=16)
        self.position.pack(side="left", padx=8)
        self.next_button = ttk.Button(self.navigation, text="Sau ›", command=self.next, style="Primary.TButton")
        self.next_button.pack(side="left")
        self.refresh()

    def begin(self, after=None):
        self.pages.requested = after

    def loaded(self, result):
        self.pages.accept(result)
        self.refresh()

    def reset(self):
        self.pages.reset()
        self.refresh()

    def set_enabled(self, enabled):
        self.available = bool(enabled)
        self.refresh()

    def refresh(self):
        p = self.pages
        self.position.configure(text=p.label)
        self.summary.configure(text=(f"{p.total:,} bản ghi" if p.total is not None
                                     else f"{p.count} bản ghi trên trang" if p.loaded else ""))
        self.previous_button.state(["!disabled"] if self.available and p.index > 0 else ["disabled"])
        self.next_button.state(["!disabled"] if self.available and p.next_after else ["disabled"])

    def previous(self):
        if self.available and self.pages.index > 0:
            self.command(self.pages.cursors[self.pages.index - 1])

    def next(self):
        if self.available and self.pages.next_after:
            self.command(self.pages.next_after)


def below_table(table, command, *, limit=50):
    """Attach to the packed table container, including its existing scrollbars."""
    container = table
    while container.winfo_manager() != "pack":
        container = container.master
    bar = PaginationBar(container.master, command, limit=limit)
    bar.pack(fill="x", after=container)
    return bar


def install_pagination(view, command, *, limit=50, resource=None):
    for name in ("load_button", "create_button", "new_button"):
        button = getattr(view, name, None)
        if button is not None:
            button.configure(style="Primary.TButton" if name == "load_button" else "Success.TButton")
            if name in {"new_button", "create_button"} and button.winfo_manager() == "pack":
                button.pack_configure(side="right", padx=(8, 0))
    actions = getattr(view, "buttons", {})
    if "save" in actions:
        actions["save"].configure(style="Primary.TButton")
    for action in ("reject", "cancel"):
        if action in actions:
            actions[action].configure(style="Danger.TButton")
    for name in ("next_button", "previous_button", "prev_button"):
        old = getattr(view, name, None)
        if old is not None:
            old.pack_forget()
    if resource == "reversals":
        view.buttons["next"].pack_forget()
    view.pagination_resource = resource
    bar = view.pagination = below_table(view.table, command, limit=limit)
    view.next_button = bar.next_button
    if hasattr(view, "previous_button"):
        view.previous_button = bar.previous_button
    if hasattr(view, "prev_button"):
        view.prev_button = bar.previous_button
    if resource == "reversals":
        view.buttons["next"] = bar.next_button
    pages = getattr(view, "document_pages", None)
    if pages is not None:
        pages.groups["list"].append((bar, bar.pack_info()))
        if pages.current != "list":
            bar.pack_forget()
