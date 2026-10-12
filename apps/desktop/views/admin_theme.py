"""Shared business UI theme; leaves presenters and native keyboard behavior intact."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from apps.desktop.views.auth_controls import ui_icon

LIGHT = dict(
    page="#f5f7fa",
    surface="#ffffff",
    text="#172b4d",
    muted="#65717c",
    line="#d7dfe9",
    hover="#edf4fd",
    selected="#e1e7fc",
    blue="#2448d8",
)
DARK = dict(
    page="#141a24",
    surface="#1d2635",
    text="#eef3fa",
    muted="#a3b1c5",
    line="#39475d",
    hover="#293a52",
    selected="#28466c",
    blue="#78baff",
)
ACTION_COLORS = {"Teal": "#087f8c", "Purple": "#7041a6", "Amber": "#956000",
                 "Slate": "#4e6078", "Danger": "#b42338", "Indigo": "#4248a2"}
# Keep solid action colors even when import controls are unavailable.
IMPORT_COLORS = {
    "Primary": "#005b9e",
    "Teal": ACTION_COLORS["Teal"],
    "Success": "#087f5b",
    "Danger": ACTION_COLORS["Danger"],
    "Purple": ACTION_COLORS["Purple"],
    "Amber": ACTION_COLORS["Amber"],
}


class AdminTheme:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.images = []
        self.icon_images = {}
        self.dark = False
        self.registered = set()

    def border(self, fill, outline):
        # UI control geometry, not a brand icon. Supersampling keeps corners crisp.
        image = Image.new("RGBA", (72, 72))
        ImageDraw.Draw(image).rounded_rectangle((2, 2, 69, 69), radius=15, fill=fill, outline=outline, width=3)
        photo = ImageTk.PhotoImage(image.resize((24, 24), Image.Resampling.LANCZOS), master=self.root)
        self.images.append(photo)
        return photo

    def work_tab(self, fill, outline):
        """Angled tab control geometry; not an icon or brand asset."""
        image = Image.new("RGBA", (216, 90))
        ImageDraw.Draw(image).polygon([(1, 88), (39, 2), (176, 2), (214, 88)], fill=fill, outline=outline, width=3)
        photo = ImageTk.PhotoImage(image.resize((72, 30), Image.Resampling.LANCZOS), master=self.root)
        self.images.append(photo)
        return photo

    def apply(self, dark=False):
        self.dark = dark
        p, s = DARK if dark else LIGHT, self.style
        suffix = "Dark" if dark else "Light"
        if suffix not in self.registered:
            normal = self.border(p["surface"], p["line"])
            hover = self.border(p["hover"], p["blue"])
            disabled = self.border(p["page"], p["line"])
            arrow = ui_icon(self.root, "chevron-down", "white" if dark else "slate", size=16)
            self.images.append(arrow)
            s.element_create(suffix + ".Combo.downarrow", "image", arrow, sticky="")
            primary = self.border("#005b9e", "#005b9e")
            pressed = self.border("#0056ad", "#0056ad")
            s.element_create(
                suffix + ".Admin.border",
                "image",
                normal,
                ("disabled", disabled),
                ("focus", hover),
                ("active", hover),
                border=6,
                padding=0,
                sticky="nsew",
            )
            s.element_create(
                suffix + ".Primary.border",
                "image",
                primary,
                ("disabled", disabled),
                ("pressed", pressed),
                ("active", pressed),
                border=6,
                padding=0,
                sticky="nsew",
            )
            success = self.border("#087f5b", "#087f5b")
            success_active = self.border("#06664a", "#06664a")
            s.element_create(suffix + ".Success.border", "image", success,
                             ("disabled", disabled), ("pressed", success_active),
                             ("active", success_active), border=6, padding=0, sticky="nsew")
            for name, color in ACTION_COLORS.items():
                surface = self.border(color, color)
                s.element_create(suffix + "." + name + ".border", "image", surface,
                                 ("disabled", disabled), border=6, padding=0, sticky="nsew")
            for name, color in IMPORT_COLORS.items():
                surface = self.border(color, color)
                s.element_create(suffix + ".Import." + name + ".border", "image", surface,
                                 border=6, padding=0, sticky="nsew")
            tab = self.work_tab(p["surface"], p["line"])
            selected_tab = self.work_tab("#005b9e", "#005b9e")
            hover_tab = self.work_tab(p["hover"], p["blue"])
            s.element_create(suffix + ".WorkTab.border", "image", tab,
                             ("selected", selected_tab), ("active", hover_tab),
                             border=(15, 2, 15, 2), sticky="nsew")
            self.registered.add(suffix)
        s.configure(
            ".",
            font=("Arial", 10),
            background=p["surface"],
            foreground=p["text"],
            troughcolor=p["page"],
            bordercolor=p["line"],
            lightcolor=p["line"],
            darkcolor=p["line"],
        )
        s.configure("TFrame", background=p["surface"])
        s.configure("Page.TFrame", background=p["page"])
        s.configure("TLabel", background=p["surface"], foreground=p["text"])
        s.configure("Muted.TLabel", foreground=p["muted"])
        s.configure("Page.TLabel", background=p["page"], foreground=p["muted"])
        s.configure("Title.TLabel", font=("Arial", 12, "bold"), background=p["page"], foreground=p["text"])
        s.configure(
            "Card.Title.TLabel", font=("Arial", 10, "bold"), foreground=p["text"], background=p["surface"]
        )
        s.configure("Card.Number.TLabel", font=("Arial", 18, "bold"), foreground=p["blue"])
        s.configure("TLabelframe", borderwidth=1, relief="solid", background=p["surface"])
        s.configure("TLabelframe.Label", font=("Arial", 9, "bold"), foreground=p["text"])
        s.layout(
            "TButton",
            [
                (
                    suffix + ".Admin.border",
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Button.padding",
                                {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]},
                            )
                        ],
                    },
                )
            ],
        )
        s.layout(
            "Primary.TButton",
            [
                (
                    suffix + ".Primary.border",
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Button.padding",
                                {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]},
                            )
                        ],
                    },
                )
            ],
        )
        s.layout("Success.TButton", [(suffix + ".Success.border", {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})
        ]})])
        s.configure("TButton", padding=(12, 7), borderwidth=0, anchor="center", font=("Arial", 10))
        s.map("TButton", foreground=[("disabled", p["muted"]), ("active", p["blue"])])
        s.configure("Primary.TButton", foreground="#ffffff", font=("Arial", 10, "bold"))
        s.layout("Action.TMenubutton", s.layout("Primary.TButton"))
        s.configure("Action.TMenubutton", padding=(12, 7), foreground="#ffffff", font=("Arial", 10, "bold"))
        s.map("Primary.TButton", foreground=[("disabled", p["muted"]), ("!disabled", "#ffffff")])
        s.configure("Success.TButton", foreground="#ffffff", font=("Arial", 10, "bold"))
        s.map("Success.TButton", foreground=[("disabled", p["muted"]), ("!disabled", "#ffffff")])
        s.configure("Danger.TButton", foreground="#fca5a5" if dark else "#b42318")
        s.map("Danger.TButton", foreground=[("disabled", p["muted"]),
                                            ("!disabled", "#fca5a5" if dark else "#b42318")])
        for name in ACTION_COLORS:
            s.layout(name + ".TButton", [(suffix + "." + name + ".border", {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})
            ]})])
            s.configure(name + ".TButton", foreground="#ffffff")
            s.map(name + ".TButton", foreground=[("disabled", p["muted"]), ("!disabled", "#ffffff")])
        for name in IMPORT_COLORS:
            style = "Import." + name + ".TButton"
            s.layout(style, [(suffix + ".Import." + name + ".border", {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})
            ]})])
            s.map(style, foreground=[("disabled", "#ffffff"), ("!disabled", "#ffffff")])
        s.layout(
            "TEntry",
            [
                (
                    suffix + ".Admin.border",
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Entry.padding",
                                {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]},
                            )
                        ],
                    },
                )
            ],
        )
        s.layout("TCombobox", [(suffix + ".Admin.border", {"sticky": "nsew", "children": [
            (suffix + ".Combo.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]})
        ]})])
        s.configure("TCombobox", arrowsize=16, borderwidth=0, relief="flat")
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            s.configure(
                name,
                padding=(4, 2),
                fieldbackground=p["surface"],
                foreground=p["text"],
                insertcolor=p["text"],
                arrowcolor=p["muted"],
                selectbackground=p["selected"],
                selectforeground=p["text"],
            )
            s.map(
                name,
                fieldbackground=[("disabled", p["page"]), ("readonly", p["surface"])],
                foreground=[("disabled", p["muted"]), ("readonly", p["text"])],
                bordercolor=[("focus", p["blue"])],
            )
        for name in ("TCheckbutton", "TRadiobutton"):
            s.configure(name, background=p["surface"], foreground=p["text"], padding=2)
            s.map(name, background=[("active", p["hover"])], foreground=[("disabled", p["muted"])])
        s.configure("TNotebook", background=p["surface"], borderwidth=0, tabmargins=(2, 4, 2, 0))
        s.configure("TNotebook.Tab", padding=(12, 7), background=p["page"], foreground=p["muted"],
                    font=("Arial", 10), expand=(0, 0, 0, 0))
        s.map(
            "TNotebook.Tab",
            background=[("selected", "#005b9e"), ("active", p["hover"])],
            foreground=[("selected", "#ffffff"), ("active", p["text"])],
            padding=[("selected", (12, 7)), ("!selected", (12, 7))],
            expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))],
        )
        s.layout("WMS.TNotebook.Tab", [])
        s.configure(
            "Treeview",
            background=p["surface"],
            fieldbackground=p["surface"],
            foreground=p["text"],
            rowheight=32,
            font=("Arial", 9),
            borderwidth=1,
            relief="solid",
            bordercolor=p["line"],
        )
        s.configure(
            "Treeview.Heading",
            font=("Arial", 9, "bold"),
            padding=(7, 6),
            background="#005b9e",
            foreground="#ffffff",
            bordercolor="#337cb1",
            lightcolor="#337cb1",
            darkcolor="#337cb1",
            relief="solid",
            borderwidth=1,
        )
        s.map("Treeview", background=[("selected", p["selected"])], foreground=[("selected", p["text"])])
        s.map("Treeview.Heading", background=[("pressed", "#004579"), ("active", "#086db7")],
              foreground=[("!disabled", "#ffffff")])
        s.configure("Nav.Treeview", rowheight=28, font=("Arial", 10), background=p["surface"], borderwidth=0, relief="flat")
        s.configure("Vertical.TScrollbar", width=11, arrowsize=11, background=p["line"], borderwidth=0)
        s.configure("Horizontal.TScrollbar", width=11, arrowsize=11, background=p["line"], borderwidth=0)
        s.configure("TSeparator", background=p["line"])
        s.layout(
            "ERP.Nav.TButton",
            [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})],
        )
        s.configure(
            "ERP.Nav.TButton",
            background="#005b9e",
            foreground="#ffffff",
            padding=(16, 14),
            font=("Arial", 10, "bold"),
        )
        s.map(
            "ERP.Nav.TButton",
            background=[("selected", "#003f73"), ("active", "#2179b7")],
            foreground=[("!disabled", "#ffffff")],
        )
        s.configure("ERP.WorkTab.TButton", padding=(18, 5), background=p["page"])
        s.layout("ERP.WorkTab.TButton", [(suffix + ".WorkTab.border", {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})
        ]})])
        s.map(
            "ERP.WorkTab.TButton",
            background=[("!disabled", p["page"])],
            foreground=[("selected", "#ffffff"), ("!selected", p["muted"])],
        )
        self.root.option_add("*TCombobox*Listbox.background", p["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["selected"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["text"])

    def native(self, widget):
        """Called on UI thread for business Text widgets, including new dialogs."""
        p = DARK if self.dark else LIGHT
        if isinstance(widget, ttk.Button):
            self.action_button(widget)
        elif isinstance(widget, ttk.Treeview):
            widget.tag_configure("stripe", background=p["page"])
            widget.tag_configure("plain", background=p["surface"])
            if hasattr(widget, "redraw"):
                widget.redraw()
        elif isinstance(widget, tk.Text):
            widget.configure(
                background=p["surface"],
                foreground=p["text"],
                insertbackground=p["text"],
                selectbackground=p["selected"],
                selectforeground=p["text"],
                relief="flat",
                highlightthickness=1,
                highlightbackground=p["line"],
                highlightcolor=p["blue"],
                padx=6,
                pady=4,
            )
        elif isinstance(widget, tk.Canvas) and widget.winfo_class() == "Canvas":
            # Custom auth/header controls manage their own palette.
            if type(widget) is tk.Canvas:
                widget.configure(background=p["page"])

    def action_button(self, widget):
        """Official Lucide assets for common actions; preserve keyboard and commands."""
        style = str(widget.cget("style"))
        if style.startswith(("ERP.", "Auth.")):
            return
        label = str(widget.cget("text"))
        icon = getattr(widget, "_action_icon_name", None)
        if icon:
            pass
        elif label.startswith(("Tạo mới", "Tạo từ", "Phiếu mới", "Phiên mới", "Thêm mới", "Thêm dòng")):
            style, icon = style if style not in {"", "TButton", "Primary.TButton"} else "Success.TButton", "plus"
        elif label.startswith(("Chọn tệp", "Mở chứng từ")):
            icon = "folder-open"
        elif label.startswith(("Upload", "Tải lên")):
            icon = "upload"
        elif label.startswith(("Tải tệp", "Tải CSV", "Xuất CSV", "Xuất XLSX")):
            icon = "download"
        elif label.startswith(("Xác nhận", "Duyệt")):
            icon = "circle-check"
        elif label.startswith(("Hủy", "Từ chối")):
            icon = "circle-x"
        elif label.startswith(("Gửi lại", "Chạy lại")):
            icon = "rotate-ccw"
        elif label.startswith(("Kiểm tra", "Kiểm định")):
            icon = "file-check"
        elif label.startswith(("Gửi máy in", "In lại", "Tìm máy in")):
            icon = "printer"
        elif label.startswith(("Xem thông tin", "Quy định", "Yêu cầu tệp")):
            icon = "info"
        elif label.startswith(("Tải", "Đọc lại")):
            icon = "refresh-cw"
        elif label.startswith(("Tìm", "Tra cứu")):
            icon = "search"
        elif label.startswith("Lưu"):
            style, icon = style if style not in {"", "TButton"} else "Primary.TButton", "save"
        elif label == "Hướng dẫn":
            icon = "circle-question-mark"
        if icon is None or (widget.cget("image") and not getattr(widget, "_action_icon", False)):
            return
        filled = {"Primary.TButton", "Success.TButton", *(name + ".TButton" for name in ACTION_COLORS)}
        tone = "white" if style.removeprefix("Import.") in filled or self.dark else "blue"
        disabled_tone = "white" if style.startswith("Import.") else "slate"
        for variant in (tone, disabled_tone):
            key = (icon, variant)
            if key not in self.icon_images:
                self.icon_images[key] = ui_icon(self.root, "action-" + icon, variant, size=18)
        widget.configure(style=style, image=(self.icon_images[icon, tone], "disabled", self.icon_images[icon, disabled_tone]),
                         compound="left")
        widget._action_icon = True

    def close(self):
        self.images.clear()
        self.icon_images.clear()
        # Style owns a Tcl interpreter reference too; release it on the UI thread.
        self.style = None
        self.root = None
