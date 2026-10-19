"""Clip a borderless Tk window to its rounded canvas outline."""

import ctypes
import ctypes.util
import math
import tkinter as tk


def rounded_outline(width, height, radius, inset=1):
    points = []
    for cx, cy, start in (
        (width-radius-inset, radius+inset, -90),
        (width-radius-inset, height-radius-inset, 0),
        (radius+inset, height-radius-inset, 90),
        (radius+inset, radius+inset, 180),
    ):
        for step in range(13):
            angle = math.radians(start + step * 7.5)
            points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def round_window(window, width, height, radius, transparent_color):
    system = window.tk.call("tk", "windowingsystem")
    if system == "win32":
        window.wm_attributes("-transparentcolor", transparent_color)
        return True
    if system != "x11":
        return False
    try:
        x11_name, extension_name = ctypes.util.find_library("X11"), ctypes.util.find_library("Xext")
        if not x11_name or not extension_name:
            return False
        x11, extension = ctypes.CDLL(x11_name), ctypes.CDLL(extension_name)
    except OSError:
        return False

    class Rectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    extension.XShapeQueryExtension.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    extension.XShapeQueryExtension.restype = ctypes.c_int
    extension.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(Rectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    extension.XShapeCombineRectangles.restype = None
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        event, error = ctypes.c_int(), ctypes.c_int()
        if not extension.XShapeQueryExtension(display, ctypes.byref(event), ctypes.byref(error)):
            return False
        rows = []
        for y in range(height):
            distance = max(radius - (y + .5), (y + .5) - (height - radius), 0)
            inset = math.ceil(radius - math.sqrt(max(0, radius**2-distance**2))) if distance else 0
            rows.append(Rectangle(inset, y, width-2*inset, 1))
        rectangles = (Rectangle * len(rows))(*rows)
        # Tk has a client and a wrapper window on X11. Clip both, including input.
        for identifier in {window.winfo_id(), int(window.wm_frame(), 0)}:
            extension.XShapeCombineRectangles(display, identifier, 0, 0, 0, rectangles, len(rows), 0, 0)
        x11.XSync(display, 0)
        return True
    except tk.TclError:
        return False
    finally:
        x11.XCloseDisplay(display)
