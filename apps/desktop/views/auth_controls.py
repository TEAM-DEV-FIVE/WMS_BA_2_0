"""Rounded auth controls drawn with Tk, retaining ttk editing and keyboard behavior."""

import base64
import time
import tkinter as tk
from importlib.resources import as_file, files
from io import BytesIO
from math import ceil
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageOps, ImageTk


def circle_surface(master, diameter, *, fill=None, outline="#55555d", stroke=1.5):
    """Supersample UI borders; brand icons remain their original image assets."""
    size = max(1, ceil(diameter))
    scale = 4
    layer = Image.new("RGBA", (size*scale, size*scale))
    painter = ImageDraw.Draw(layer)
    inset = min(max(stroke/2, .5), diameter/4)*scale
    painter.ellipse((inset, inset, diameter*scale-inset, diameter*scale-inset),
                    fill=fill, outline=outline, width=max(1, round(stroke*scale)))
    return ImageTk.PhotoImage(layer.resize((size, size), Image.Resampling.LANCZOS), master=master)


def rounded(canvas, width, height, *, fill, outline="", radius=8):
    r, x, y, right, bottom = radius, 1, 1, width-1, height-1
    return canvas.create_polygon(x+r,y, right-r,y, right,y, right,y+r,
        right,bottom-r, right,bottom, right-r,bottom, x+r,bottom,
        x,bottom, x,bottom-r, x,y+r, x,y, smooth=True, splinesteps=24,
        fill=fill, outline=outline, width=1)


def ui_icon(master, name, tone="slate", size=22):
    aliases = {"help":"headset", "account":"user-round", "eye-hidden":"eye-off"}
    name = aliases.get(name,name)
    with as_file(files("apps.desktop.assets").joinpath(f"ui-{name}-{tone}.png")) as path:
        with Image.open(path) as source:
            return ImageTk.PhotoImage(ImageOps.contain(source,(size,size),Image.Resampling.LANCZOS),master=master)


def avatar_photo(master, encoded, size):
    """Render the saved square PNG within a smooth circular UI viewport."""
    with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as source:
        picture = source.convert("RGBA").resize((size * 3, size * 3), Image.Resampling.LANCZOS)
    mask = Image.new("L", picture.size)
    ImageDraw.Draw(mask).ellipse((0, 0, picture.width - 1, picture.height - 1), fill=255)
    clipped = Image.new("RGBA", picture.size)
    clipped.paste(picture, (0, 0), mask)
    return ImageTk.PhotoImage(clipped.resize((size, size), Image.Resampling.LANCZOS), master=master)


class ThemeSwitch(tk.Canvas):
    """Two official icons with one animated selection, usable by mouse and keyboard."""

    def __init__(self, parent, command):
        super().__init__(parent, width=96, height=40, background="#515154",
                         borderwidth=0, highlightthickness=0, takefocus=True, cursor="hand2")
        self.command = command
        self.dark_mode = False
        self.position = 0.0
        self.light_surface = False
        self.timer = None
        self.focused = False
        self.icons = [ui_icon(self, "sun", "white"), ui_icon(self, "moon", "white")]
        self.bind("<Configure>", lambda event: self.draw())
        self.bind("<Button-1>", self.click)
        self.bind("<Left>", lambda event: self.choose(False))
        self.bind("<Right>", lambda event: self.choose(True))
        self.bind("<space>", lambda event: self.choose(not self.dark_mode))
        self.bind("<Return>", lambda event: self.choose(not self.dark_mode))
        self.bind("<FocusIn>", lambda event: self.focus(True))
        self.bind("<FocusOut>", lambda event: self.focus(False))

    def focus(self, focused):
        self.focused = focused
        self.draw()

    def click(self, event):
        self.focus_set()
        self.choose(event.x >= self.winfo_width()/2)

    def choose(self, dark):
        if dark != self.dark_mode:
            self.set_dark(dark)
            self.command(dark)
        return "break"

    def set_dark(self, dark):
        if dark == self.dark_mode:
            return
        self.dark_mode = dark
        if self.timer is not None:
            self.after_cancel(self.timer)
        start, target, started = self.position, float(dark), time.monotonic()

        def tick():
            self.timer = None
            elapsed = min(1.0, (time.monotonic()-started)/.2)
            eased = 1-(1-elapsed)**3
            self.position = start+(target-start)*eased
            self.draw()
            if elapsed < 1:
                self.timer = self.after(16, tick)
        tick()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        rounded(self, width, height, fill="#e8edf2" if self.light_surface else "#3b3b40", outline="#a5ceff" if self.focused else "#ccd4dd" if self.light_surface else "#69696f", radius=12)
        half = (width-8)/2
        selected = rounded(self, half, height-8, fill="#777780", radius=9)
        self.move(selected, 4+self.position*half, 4)
        for index, icon in enumerate(self.icons):
            self.create_image(4+(index+.5)*half, height/2, image=icon)

    def destroy(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.icons.clear()
        self.command = None
        super().destroy()


class RoundedField(tk.Canvas):
    def __init__(self, parent, *, combo=False, leading=None, **options):
        try:
            background = parent.cget("background")
        except tk.TclError:
            background = "#ffffff"
        super().__init__(parent, height=46, width=300, background=background,
                         highlightthickness=0, borderwidth=0)
        self.leading = leading
        self.dark_mode = False
        self.leading_image = ui_icon(self,leading) if leading else None
        self.focused = False
        self.values = list(options.pop("values", ()))
        self.inner = tk.Entry(self, relief="flat", borderwidth=0, highlightthickness=0,
                              background="#ffffff", disabledbackground="#ffffff", readonlybackground="#ffffff",
                              foreground="#102a43", insertbackground="#102a43", font=("Segoe UI", 11), **options)
        self.trailing = None
        self.dropdown = None
        if combo:
            self.dropdown = tk.Menu(self, tearoff=False)
            self.trailing = RoundedButton(self, "", self.show_choices, link=True, glyph="chevron-down")
        self.inner.bind("<FocusIn>", lambda event: self.focus(True))
        self.inner.bind("<FocusOut>", lambda event: self.focus(False))
        super().bind("<Configure>", lambda event: self.draw())

    def focus(self, value):
        self.focused = value
        self.draw()

    def set_dark(self, enabled):
        self.dark_mode = enabled
        background = "#171b24" if enabled else "#ffffff"
        field = "#222938" if enabled else "#ffffff"
        foreground = "#edf2f7" if enabled else "#102a43"
        super().configure(background=background)
        self.inner.configure(background=field, disabledbackground=field, readonlybackground=field,
                             foreground=foreground, insertbackground=foreground)
        if self.trailing:
            self.trailing.set_dark(enabled, background=field)
        self.draw()

    def draw(self):
        super().delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        rounded(self,width,height,fill="#222938" if self.dark_mode else "#ffffff",
                outline=("#78baff" if self.dark_mode else "#0066cc") if self.focused else ("#465167" if self.dark_mode else "#e2e4e8"))
        left = 40 if self.leading else 14
        right = 45 if self.trailing else 14
        if self.leading:
            self.create_image(22,height/2,image=self.leading_image)
        self.inner.place(x=left,y=12,width=max(1,width-left-right),height=max(1,height-24))
        if self.trailing:
            self.trailing.place(x=width-40,y=6,width=32,height=height-12)

    def configure(self, cnf=None, **kwargs):
        if cnf or not hasattr(self,"inner"):
            return super().configure(cnf, **kwargs)
        if "values" in kwargs:
            self.values = list(kwargs.pop("values"))
        inner = {k:kwargs.pop(k) for k in list(kwargs) if k in {"textvariable","show","font","state","justify"}}
        if inner:
            self.inner.configure(**inner)
        if kwargs:
            return super().configure(**kwargs)

    config = configure

    def cget(self, key):
        if key == "values":
            return tuple(self.values)
        if hasattr(self,"inner") and key in {"textvariable","show","font","state","justify"}:
            return self.inner.cget(key)
        return super().cget(key)

    def bind(self, sequence=None, func=None, add=None):
        if sequence and sequence in {"<Return>","<<ComboboxSelected>>","<FocusIn>"}:
            return self.inner.bind(sequence,func,add or "+")
        return super().bind(sequence,func,add)

    def focus_set(self):
        self.inner.focus_set()

    def state(self, statespec=None):
        if statespec:
            if "disabled" in statespec:
                self.inner.configure(state="disabled")
            elif "readonly" in statespec:
                self.inner.configure(state="readonly")
            elif "!disabled" in statespec or "!readonly" in statespec:
                self.inner.configure(state="normal")
        current = self.inner.cget("state")
        return () if current == "normal" else (current,)

    def instate(self, statespec, callback=None):
        current = self.state()
        match = all((item[1:] not in current) if item.startswith("!") else (item in current) for item in statespec)
        return callback() if match and callback else match

    def get(self):
        return self.inner.get()

    def set(self, value):
        self.inner.delete(0,"end")
        self.inner.insert(0,value)

    def current(self, index=None):
        if index is not None:
            self.set(self.values[index])
        return self.values.index(self.get()) if self.get() in self.values else -1

    def show_choices(self):
        if self.dropdown is None or self.instate(["disabled"]):
            return
        self.dropdown.delete(0,"end")
        for value in self.values:
            def choose(item=value):
                self.set(item)
                self.inner.event_generate("<<ComboboxSelected>>")
            self.dropdown.add_command(label=value,command=choose)
        self.dropdown.tk_popup(self.winfo_rootx(),self.winfo_rooty()+self.winfo_height())

    def insert(self, index, value):
        self.inner.insert(index,value)

    def delete(self, first, last=None):
        # Canvas redraw explicitly uses the parent implementation.
        self.inner.delete(first,last)

    def destroy(self):
        self.leading_image = None
        super().destroy()


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, *, primary=False, link=False, glyph=None, header=False, circular=False):
        self.avatar = False
        self.avatar_surface = None
        self.text, self.command = text, command
        self.circular = circular
        self.circle_image = None
        self.circle_key = None
        self.primary, self.link, self.glyph, self.header = primary, link, glyph, header
        self.header_surface, self.header_tone = "#515154", "white"
        self.image, self.disabled, self.hovered = None, False, False
        self.dark_mode = False
        self.surface = "#ffffff"
        self.glyph_images = {}
        bg = "#515154" if header else "#ffffff"
        super().__init__(parent, width=max(76,len(text)*8+32), height=48 if primary else 40,
                         background=bg, borderwidth=0, highlightthickness=0, cursor="hand2",takefocus=True)
        self.bind("<Configure>",lambda event:self.draw())
        self.bind("<Enter>",lambda event:self.hover(True))
        self.bind("<Leave>",lambda event:self.hover(False))
        self.bind("<Button-1>",lambda event:self.invoke())
        self.bind("<Return>",lambda event:self.invoke())
        self.bind("<space>",lambda event:self.invoke())

    def set_dark(self, enabled, *, background=None):
        self.dark_mode = enabled
        self.surface = background or ("#171b24" if enabled else "#ffffff")
        super().configure(background=self.header_surface if self.header else self.surface)
        self.draw()

    def glyph_image(self):
        tone = self.header_tone if self.header else "white" if self.dark_mode else "slate"
        key = self.glyph,tone
        if key not in self.glyph_images:
            self.glyph_images[key] = ui_icon(self,self.glyph,tone)
        return self.glyph_images[key]

    def hover(self, value):
        self.hovered = value
        self.draw()

    def draw(self):
        super().delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        fill = "#0066cc" if self.primary else self.header_surface if self.header else self.surface
        if self.disabled:
            fill = "#91b5db" if self.primary else fill
        elif self.hovered:
            fill = "#005bb5" if self.primary else ("#edf4fd" if self.header_tone != "white" else "#626265") if self.header else "#2d3748" if self.dark_mode else "#f4f7fa"
        outline = "" if self.primary or self.link or self.header else "#465167" if self.dark_mode else "#e2e4e8"
        if self.circular:
            diameter = max(1, min(width, height)-2)
            border = "#8b8b94" if self.hovered else "#55555d"
            key = diameter, fill, border
            if key != self.circle_key:
                self.circle_image = circle_surface(self, diameter, fill=fill, outline=border)
                self.circle_key = key
            self.create_image(width/2, height/2, image=self.circle_image)
        else:
            rounded(self,width,height,fill=fill,outline=outline)
        color = "#ffffff" if self.primary or self.header else ("#78baff" if self.dark_mode else "#0066cc") if self.link else "#edf2f7" if self.dark_mode else "#263449"
        if self.header and self.header_tone != "white":
            color = "#315c80"
        if self.disabled and not self.primary:
            color = "#7b8794"
        if self.glyph and not self.text:
            self.create_image(width/2,height/2,image=self.glyph_image())
            return
        if self.image and not self.text:
            self.create_image(width/2,height/2,image=self.image)
            return
        font = ("Segoe UI",11,"bold") if self.primary else ("Segoe UI",10)
        text_width = tkfont.Font(self,font=font).measure(self.text)
        has_icon = bool(self.image or self.glyph)
        icon_width, gap = (32 if self.avatar and self.image else 22), 12
        start = (width-text_width-(icon_width+gap if has_icon else 0))/2
        self.create_text(start+(icon_width+gap if has_icon else 0),height/2,text=self.text,fill=color,font=font,anchor="w")
        if self.image:
            # Keep brand images sharp and colored even when credentials are unavailable.
            self.create_image(start+icon_width/2,height/2,image=self.image)
        elif self.glyph:
            if self.avatar:
                self.avatar_surface = circle_surface(self, 32, fill="#e8f2ff" if self.header_tone != "white" else "#354961", outline=None)
                self.create_image(start+icon_width/2, height/2, image=self.avatar_surface)
            self.create_image(start+icon_width/2,height/2,image=self.glyph_image())

    def configure(self, cnf=None, **kwargs):
        if not hasattr(self,"text"):
            return super().configure(cnf,**kwargs)
        for name in ("text","image"):
            if name in kwargs:
                setattr(self,name,kwargs.pop(name))
        kwargs.pop("compound",None)
        result = super().configure(cnf,**kwargs) if cnf or kwargs else None
        self.draw()
        return result

    config = configure

    def state(self, statespec=None):
        if statespec:
            if "disabled" in statespec:
                self.disabled = True
            if "!disabled" in statespec:
                self.disabled = False
            self.draw()
        return ("disabled",) if self.disabled else ()

    def instate(self, statespec, callback=None):
        match = all(self.disabled if s=="disabled" else not self.disabled for s in statespec)
        if match and callback:
            return callback()
        return match

    def invoke(self):
        if not self.disabled and self.command:
            return self.command()

    def destroy(self):
        self.command = None
        self.image = None
        self.circle_image = None
        self.avatar_surface = None
        self.glyph_images.clear()
        super().destroy()
