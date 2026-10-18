"""Full-color operating-system icon, independent of the header's theme logos."""

from importlib.resources import as_file, files

from PIL import Image, ImageTk


def install_application_icon(root):
    with as_file(files("apps.desktop.assets").joinpath("wms-app-icon.png")) as path:
        with Image.open(path) as source:
            images = tuple(
                ImageTk.PhotoImage(source.resize((size, size), Image.Resampling.LANCZOS), master=root)
                for size in (32, 48, 256)
            )
    root.iconphoto(True, *images)
    # Tk does not retain Python PhotoImage references; keep them for the window's lifetime.
    root._wms_application_icons = images
    return images
