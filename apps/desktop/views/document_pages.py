"""List/detail navigation without recreating forms or changing document state."""
from tkinter import ttk

from apps.desktop.views.ui_help import HelpButton


class DocumentPages:
    def __init__(self, table, *, footer=None, detail_title="Chi tiết phiếu"):
        # A table can be packed directly or gridded inside its scrollbar frame.
        listing = table
        while listing.winfo_manager() != "pack":
            listing = listing.master
        listing.pack_configure(fill="both", expand=True)
        if table.master is listing and table.winfo_manager() == "grid":
            listing.rowconfigure(int(table.grid_info()["row"]), weight=1)
        parent = listing.master
        siblings = parent.pack_slaves()
        details = siblings[siblings.index(listing) + 1:]
        if footer is not None and footer not in details:
            details.insert(0, footer)
        self.groups = {"list": [(listing, listing.pack_info())],
                       "detail": [(widget, widget.pack_info()) for widget in details]}
        self.table = table
        self.current = None
        self.bar = ttk.Frame(parent)
        self.bar.pack(fill="x", pady=(4, 8), before=listing)
        self.list_button = ttk.Button(self.bar, text="Danh sách", command=self.show_list)
        self.list_button.pack(side="left")
        self.detail_button = ttk.Button(self.bar, text=detail_title, command=self.show_detail)
        self.detail_button.pack(side="left", padx=6)
        self.hint = HelpButton(self.bar, "Chọn phiếu rồi mở chi tiết hoặc nhấn Enter. Quay lại Danh sách để chọn phiếu khác.")
        self.hint.pack(side="right")
        # A modest minimum lets the footer stay visible on laptops; expansion
        # supplies the remaining height on larger windows.
        table.configure(height=4)
        table.bind("<Return>", self.open_selected, add="+")
        table.bind("<Double-1>", self.open_selected, add="+")
        self.show_list()

    def open_selected(self, event=None):
        if event is not None and event.type.name == "ButtonPress":
            if not self.table.identify_row(event.y):
                return
        if self.table.selection():
            self.show_detail()
        return "break"

    def show_list(self):
        self.show("list")

    def show_detail(self):
        self.show("detail")

    def show(self, page):
        if self.current == page:
            return
        # Hide only geometry: unsaved inputs, selection, pending commands and
        # permission-controlled button states remain owned by their presenters.
        for group in self.groups.values():
            for widget, _ in group:
                widget.pack_forget()
        for widget, options in self.groups[page]:
            widget.pack(**options)
        self.current = page
        for name, button in (("list", self.list_button), ("detail", self.detail_button)):
            button.configure(style="Primary.TButton" if name == page else "TButton")
        (self.list_button if page == "list" else self.detail_button).focus_set()
        # Scrollable forms may have been at the bottom on the previous page.
        ancestor = self.bar.master
        while ancestor is not None:
            if ancestor.winfo_class() == "Canvas":
                ancestor.yview_moveto(0)
                break
            ancestor = getattr(ancestor, "master", None)


def show_document(view):
    pages = getattr(view, "document_pages", None)
    if pages is not None:
        pages.show_detail()


def reset_document_page(view):
    pages = getattr(view, "document_pages", None)
    if pages is not None:
        pages.show_list()
