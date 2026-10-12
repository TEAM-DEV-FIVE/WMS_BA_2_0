"""ERP table presentation over native Treeview selection, scrolling and item APIs.

The native header and optional hierarchy column remain interactive. A clipped body
surface adds cell rules, wrapping and column colors that Tk 8.6 does not provide.
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

NUMERIC = {
    "qty", "quantity", "quantity_base", "base_quantity", "amount", "total", "price", "factor",
    "version", "line", "line_no", "row", "available", "reserved", "on_hand", "remaining",
    "inbound", "outbound", "opening", "closing", "net", "delta", "good", "bad", "base",
    "accepted", "rejected", "posted", "requested", "dispatched", "received_good", "received_damaged",
    "loss", "reported_missing", "snapshot_quantity", "approved_quantity", "reference_price",
    "reference_unit_price", "movement_count", "days_to_expiry", "movement_age_days",
}
CODES = {"code", "sku", "number", "document_number", "product_code", "barcode"}
CENTERED = {"status", "state", "kind", "tracking", "uom", "unit", "day", "date", "business_date"}


def column_alignment(column, original="w"):
    if column in NUMERIC or column.endswith(("_quantity", "_amount", "_value", "_price")):
        return "e"
    return "center" if column in CENTERED else original


def cell_lines(value, width, measure, limit=2):
    """Fit display text only; the original Treeview values remain untouched."""
    text = " ".join(str(value).split())
    if not text or width <= 0:
        return []
    lines = []
    while text and len(lines) < limit:
        if measure(text) <= width:
            lines.append(text)
            break
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if measure(text[:mid]) <= width:
                low = mid
            else:
                high = mid - 1
        if low == 0:
            break
        cut = low
        if len(lines) == limit - 1:
            if measure("…") > width:
                break
            while cut > 0 and measure(text[:cut] + "…") > width:
                cut -= 1
            lines.append(text[:cut].rstrip() + "…")
            break
        space = text.rfind(" ", 0, cut + 1)
        if space > cut // 2:
            cut = space
        lines.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return lines


class _TableSurface(tk.Canvas):
    pass


class DataTable(ttk.Treeview):
    def __init__(self, parent, **kwargs):
        self._closing = False
        self._paint_job = None
        self._surface = None
        self._body_x = self._body_y = 0
        self._scroll_callbacks = {axis: kwargs.pop(axis + "scrollcommand", None) for axis in ("x", "y")}
        super().__init__(parent, **kwargs)
        self._scroll_commands = {axis: self.register(lambda first, last, a=axis: self._scrolled(a, first, last))
                                 for axis in ("x", "y")}
        super().configure(**{axis + "scrollcommand": command for axis, command in self._scroll_commands.items()})
        self._style = ttk.Style(self)
        self._font = tkfont.Font(self, font=("Arial", 9))
        self._surface = _TableSurface(self, highlightthickness=0, borderwidth=0, takefocus=False)
        for sequence in ("<ButtonPress-1>", "<ButtonRelease-1>", "<B1-Motion>",
                         "<ButtonPress-3>", "<ButtonRelease-3>", "<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._surface.bind(sequence, lambda event, seq=sequence: self._forward(event, seq))
        for sequence in ("<Configure>", "<Map>", "<Expose>", "<<ThemeChanged>>", "<<TreeviewSelect>>",
                         "<<TreeviewOpen>>", "<<TreeviewClose>>", "<KeyRelease>", "<B1-Motion>",
                         "<ButtonRelease-1>", "<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, lambda event: self.redraw(), add="+")
        self.redraw()

    def _forward(self, event, sequence):
        self.focus_set()
        args = dict(x=event.x + self._body_x, y=event.y + self._body_y, state=event.state)
        if sequence == "<MouseWheel>":
            args["delta"] = event.delta
        elif "Motion" not in sequence:
            args["time"] = event.time
        self.event_generate(sequence, **args)
        self.redraw()
        return "break"

    def redraw(self):
        if not self._closing and self._surface is not None and self._paint_job is None:
            self._paint_job = self.after_idle(self._paint)

    def _paint(self):
        self._paint_job = None
        if self._closing or not self.winfo_ismapped():
            return
        surface = self._surface
        style = self.cget("style") or "Treeview"
        def color(key, fallback):
            return self._style.lookup(style, key) or fallback
        background = color("background", "#ffffff")
        foreground = color("foreground", "#172b4d")
        line = color("bordercolor", "#d7dfe9")
        stripe = self._style.lookup("Page.TFrame", "background") or "#f5f7fa"
        blue = self._style.lookup("Card.Number.TLabel", "foreground") or "#2448d8"
        selected = self._style.lookup(style, "background", ("selected",)) or "#e1e7fc"
        selected_text = self._style.lookup(style, "foreground", ("selected",)) or foreground
        rowheight = int(color("rowheight", "32"))
        width, height = self.winfo_width(), self.winfo_height()
        show = {str(value) for value in self.tk.splitlist(self.cget("show"))}
        header_end = 1
        if "headings" in show:
            for y in range(1, min(height, 100)):
                if self.identify_region(max(3, width // 2), y) in {"heading", "separator"}:
                    header_end = y + 1
        columns = list(self.tk.splitlist(self.cget("columns")))
        displayed = list(self.tk.splitlist(self.cget("displaycolumns")))
        if displayed != ["#all"]:
            columns = [columns[int(c)] if str(c).isdigit() else c for c in displayed]
        # Leave the native hierarchy/expanders usable on the locations screen.
        tree_width = int(super().column("#0", "width")) if "tree" in show else 0
        total_width = tree_width + sum(int(super(DataTable, self).column(c, "width")) for c in columns)
        offset = round(self.xview()[0] * total_width)
        body_x = max(1, tree_width - offset + 1) if tree_width else 1
        self._body_x, self._body_y = body_x, header_end
        surface.place(x=body_x, y=header_end, width=max(1, width-body_x-1), height=max(1, height-header_end-1))
        surface.configure(background=background)
        surface.delete("all")
        x = 1 + tree_width - offset - body_x
        geometry = []
        for column in columns:
            column_width = int(super().column(column, "width"))
            geometry.append((column, x, column_width))
            x += column_width
        chosen = set(self.selection())
        seen = set()
        for y in range(header_end + rowheight // 2, height + rowheight // 2, rowheight):
            item = self.identify_row(min(y, height - 2))
            if not item or item in seen:
                continue
            seen.add(item)
            bounds = self.bbox(item)
            if not bounds:
                continue
            _, row_y, _, row_height = bounds
            local_y = row_y - header_end
            fill = selected if item in chosen else stripe if self.index(item) % 2 else background
            surface.create_rectangle(0, local_y, width, local_y+row_height, fill=fill, outline="")
            for column, left, cell_width in geometry:
                if left + cell_width < 0 or left > width-body_x:
                    continue
                value = self.set(item, column)
                anchor = column_alignment(column, str(super().column(column, "anchor")))
                limit = 1 if anchor == "e" or column in CODES else max(1, min(2, row_height // self._font.metrics("linespace")))
                lines = cell_lines(value, cell_width-14, self._font.measure, limit)
                text_color = selected_text if item in chosen else blue if column in CODES else foreground
                if str(value) in {"✓", "✔"}:
                    text_color = "#258345" if background == "#ffffff" else "#72d59b"
                text_x = left + cell_width-7 if anchor == "e" else left+cell_width/2 if anchor == "center" else left+7
                line_height = self._font.metrics("linespace")
                first_y = local_y + (row_height-len(lines)*line_height)/2 + line_height/2
                for index, text in enumerate(lines):
                    surface.create_text(text_x, first_y + index*line_height, text=text,
                                        anchor=anchor, font=self._font, fill=text_color)
            surface.create_line(0, local_y+row_height-1, width, local_y+row_height-1, fill=line)
        for _, left, cell_width in geometry:
            surface.create_line(left+cell_width-1, 0, left+cell_width-1, height, fill=line)

    def _scrolled(self, axis, first, last):
        callback = self._scroll_callbacks[axis]
        if callable(callback):
            callback(first, last)
        elif callback:
            self.tk.call(*self.tk.splitlist(callback), first, last)
        self.redraw()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        for axis in ("x", "y"):
            name = axis + "scrollcommand"
            if name in kwargs:
                self._scroll_callbacks[axis] = kwargs[name]
                kwargs[name] = self._scroll_commands[axis]
        result = super().configure(cnf, **kwargs)
        if kwargs:
            self.redraw()
        return result

    config = configure

    def insert(self, parent, index, iid=None, **kwargs):
        result = super().insert(parent, index, iid=iid, **kwargs)
        self.redraw()
        return result

    def delete(self, *items):
        result = super().delete(*items)
        self.redraw()
        return result

    def item(self, item, option=None, **kwargs):
        result = super().item(item, option, **kwargs)
        if kwargs:
            self.redraw()
        return result

    def set(self, item, column=None, value=None):
        result = super().set(item, column, value)
        if value is not None:
            self.redraw()
        return result

    def column(self, column, option=None, **kwargs):
        result = super().column(column, option, **kwargs)
        if kwargs:
            self.redraw()
        return result

    def heading(self, column, option=None, **kwargs):
        result = super().heading(column, option, **kwargs)
        if kwargs:
            self.redraw()
        return result

    def xview(self, *args):
        result = super().xview(*args)
        if args:
            self.redraw()
        return result

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self.redraw()
        return result

    def xview_moveto(self, fraction):
        self.xview("moveto", fraction)

    def yview_moveto(self, fraction):
        self.yview("moveto", fraction)

    def xview_scroll(self, number, what):
        self.xview("scroll", number, what)

    def yview_scroll(self, number, what):
        self.yview("scroll", number, what)

    def set_children(self, item, *children):
        result = super().set_children(item, *children)
        self.redraw()
        return result

    def see(self, item):
        result = super().see(item)
        self.redraw()
        return result

    def move(self, item, parent, index):
        result = super().move(item, parent, index)
        self.redraw()
        return result

    def detach(self, *items):
        result = super().detach(*items)
        self.redraw()
        return result

    def destroy(self):
        self._closing = True
        if self._paint_job is not None:
            self.after_cancel(self._paint_job)
            self._paint_job = None
        super().destroy()
        self._surface = self._font = self._style = None
        self._scroll_callbacks.clear()
