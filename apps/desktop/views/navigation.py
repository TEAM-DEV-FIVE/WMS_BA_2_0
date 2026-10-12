"""A menu with explicit selection and a small reversible pointer animation."""

import tkinter as tk


class HoverItem(tk.Canvas):
    def __init__(self, parent, label, command):
        super().__init__(parent, height=44, width=110, background='#515154', highlightthickness=0,
                         borderwidth=0, cursor='hand2', takefocus=True)
        self.label, self.command = label, command
        self.selected, self.hovered = False, False
        self.level, self.timer = 0.0, None
        self.bind('<Configure>', lambda event: self.draw())
        self.bind('<Enter>', lambda event: self.hover(True))
        self.bind('<Leave>', lambda event: self.hover(False))
        self.bind('<FocusIn>', lambda event: self.hover(True))
        self.bind('<FocusOut>', lambda event: self.hover(False))
        self.bind('<Button-1>', lambda event: self.activate())
        self.bind('<Return>', lambda event: self.activate())
        self.bind('<space>', lambda event: self.activate())

    def activate(self):
        self.command()

    def hover(self, value):
        self.hovered = value
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.animate()

    def animate(self):
        target = 1.0 if self.hovered else 0.0
        delta = target - self.level
        self.level = target if abs(delta) < .08 else self.level + delta * .45
        self.draw()
        self.timer = self.after(16, self.animate) if self.level != target else None

    def draw(self):
        self.delete('all')
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if self.selected:
            base = (102,102,105)
            color = '#' + ''.join(f'{round(c + self.level*20):02x}' for c in base)
            x, y, right, bottom, radius = 5, 4, width-5, height-4, 8
            self.create_polygon(x+radius,y, right-radius,y, right,y, right,y+radius,
                right,bottom-radius, right,bottom, right-radius,bottom, x+radius,bottom,
                x,bottom, x,bottom-radius, x,y+radius, x,y, smooth=True, splinesteps=24, fill=color, outline='')
        size = 11 if self.level < .4 else 12
        self.create_text(width/2,height/2,text=self.label,fill='#ffffff' if self.selected or self.level>.2 else '#d2d2d7',
                         font=('Segoe UI',size))

    def destroy(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.command = None
        super().destroy()


class NavigationStrip(tk.Frame):
    def __init__(self, parent, items, on_select=lambda index: None):
        super().__init__(parent, background='#515154', height=44)
        self.items = []
        self.on_select = on_select
        for index, (label, command) in enumerate(items):
            self.columnconfigure(index, weight=1, uniform='items')
            def choose(i=index, action=command):
                if action() is not False:
                    self.select(i)
                    self.on_select(i)
            item = HoverItem(self,label,choose)
            item.grid(row=0,column=index,sticky='ew')
            self.items.append(item)

    def select(self, index):
        for i, item in enumerate(self.items):
            item.selected = i == index
            item.draw()

    def destroy(self):
        self.on_select = None
        super().destroy()
