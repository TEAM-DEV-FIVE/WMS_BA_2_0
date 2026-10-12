"""Native vertical action list, shared by printing and reports."""
import tkinter as tk
from tkinter import ttk


class ActionMenu(ttk.Menubutton):
    def __init__(self, parent, actions, *, title="Thao tác"):
        super().__init__(parent, text=title + " ▾", style="Action.TMenubutton")
        self.menu = tk.Menu(self, tearoff=False)
        for label, command in actions:
            self.menu.add_command(label=label, command=command)
        self.configure(menu=self.menu)
