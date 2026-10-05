"""Windows 10/11 GDI printer adapter; uses installed USB/LAN drivers, no PDF shell verbs.

Called in a disposable child process. Driver hangs have a timeout in spool.submit.
"""

import ctypes as ct
from ctypes import wintypes as wt


def api():
    spool = ct.WinDLL("winspool.drv", use_last_error=True)
    gdi = ct.WinDLL("gdi32", use_last_error=True)
    declarations = [
        (spool, "OpenPrinterW", [wt.LPWSTR, ct.POINTER(wt.HANDLE), ct.c_void_p], wt.BOOL),
        (spool, "ClosePrinter", [wt.HANDLE], wt.BOOL),
        (
            spool,
            "EnumPrintersW",
            [
                wt.DWORD,
                wt.LPWSTR,
                wt.DWORD,
                ct.c_void_p,
                wt.DWORD,
                ct.POINTER(wt.DWORD),
                ct.POINTER(wt.DWORD),
            ],
            wt.BOOL,
        ),
        (
            spool,
            "DocumentPropertiesW",
            [wt.HWND, wt.HANDLE, wt.LPWSTR, ct.c_void_p, ct.c_void_p, wt.DWORD],
            wt.LONG,
        ),
        (gdi, "CreateDCW", [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ct.c_void_p], wt.HDC),
        (gdi, "GetDeviceCaps", [wt.HDC, ct.c_int], ct.c_int),
        (gdi, "StartDocW", [wt.HDC, ct.c_void_p], ct.c_int),
    ]
    for name in ["StartPage", "EndPage", "EndDoc", "AbortDoc", "DeleteDC"]:
        declarations.append((gdi, name, [wt.HDC], ct.c_int))
    for lib, name, args, result in declarations:
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = result
    return spool, gdi


def printers():
    spool, _ = api()
    needed, count = wt.DWORD(), wt.DWORD()
    spool.EnumPrintersW(6, None, 4, None, 0, ct.byref(needed), ct.byref(count))
    if not needed.value:
        return []
    buffer = ct.create_string_buffer(needed.value)
    if not spool.EnumPrintersW(6, None, 4, buffer, len(buffer), ct.byref(needed), ct.byref(count)):
        raise ct.WinError(ct.get_last_error())

    class Printer(ct.Structure):
        _fields_ = [("name", wt.LPWSTR), ("server", wt.LPWSTR), ("attributes", wt.DWORD)]

    rows = ct.cast(buffer, ct.POINTER(Printer))
    return [dict(name=rows[i].name, driver="WINDOWS_GDI") for i in range(count.value)]


def print_pdf(data, printer, paper, copies):
    import pypdfium2 as pdfium
    from PIL import ImageWin

    from apps.desktop.printing.pdf import LOCK

    spool, gdi = api()
    handle = wt.HANDLE()
    if not spool.OpenPrinterW(printer, ct.byref(handle), None):
        raise ct.WinError(ct.get_last_error())
    dc = None
    started = False
    try:
        size = spool.DocumentPropertiesW(None, handle, printer, None, None, 0)
        if size < 220:
            raise OSError("Invalid printer DEVMODE")
        devmode = ct.create_string_buffer(size)
        if spool.DocumentPropertiesW(None, handle, printer, devmode, None, 2) != 1:
            raise OSError("Cannot read printer settings")
        # DEVMODEW: 32 WCHAR device name, 4 WORDs, DWORD fields then printer union.
        fields = ct.c_uint32.from_buffer(devmode, 72)
        fields.value |= 1 | 2 | 4 | 8 | 0x100
        for offset, value in [
            (76, 1),
            (78, 256),
            (80, round(paper[1] * 10)),
            (82, round(paper[0] * 10)),
            (86, 1),
        ]:
            ct.c_int16.from_buffer(devmode, offset).value = value
        if spool.DocumentPropertiesW(None, handle, printer, devmode, devmode, 10) != 1:
            raise OSError("Driver rejected paper")
        dc = gdi.CreateDCW("WINSPOOL", printer, None, devmode)
        if not dc:
            raise OSError("Cannot open printer DC")
        dpi_x, dpi_y = gdi.GetDeviceCaps(dc, 88), gdi.GetDeviceCaps(dc, 90)
        physical_x, physical_y = gdi.GetDeviceCaps(dc, 110), gdi.GetDeviceCaps(dc, 111)
        if (
            min(dpi_x, dpi_y) <= 0
            or abs(physical_x / dpi_x * 25.4 - paper[0]) > 2
            or abs(physical_y / dpi_y * 25.4 - paper[1]) > 2
        ):
            raise OSError("Driver paper size differs from PDF")

        class DocInfo(ct.Structure):
            _fields_ = [
                ("size", ct.c_int),
                ("name", wt.LPCWSTR),
                ("output", wt.LPCWSTR),
                ("datatype", wt.LPCWSTR),
                ("type", wt.DWORD),
            ]

        info = DocInfo(ct.sizeof(DocInfo), "WMS document", None, None, 0)
        with LOCK, pdfium.PdfDocument(data) as document:
            if not 0 < len(document) <= 200:
                raise ValueError("Page limit")
            for i in range(len(document)):
                w, h = document.get_page_size(i)
                if abs(w / 72 * 25.4 - paper[0]) > 1 or abs(h / 72 * 25.4 - paper[1]) > 1:
                    raise ValueError("PDF paper mismatch")
            job = gdi.StartDocW(dc, ct.byref(info))
            if job <= 0:
                raise OSError("StartDoc failed")
            started = True
            for _ in range(copies):
                for i in range(len(document)):
                    page = document[i]
                    bitmap = page.render(scale=300 / 72)
                    try:
                        image = bitmap.to_pil().convert("RGB")
                        if gdi.StartPage(dc) <= 0:
                            raise OSError("StartPage failed")
                        x, y = -gdi.GetDeviceCaps(dc, 112), -gdi.GetDeviceCaps(dc, 113)
                        ImageWin.Dib(image).draw(dc, (x, y, x + physical_x, y + physical_y))
                        if gdi.EndPage(dc) <= 0:
                            raise OSError("EndPage failed")
                    finally:
                        bitmap.close()
                        page.close()
            if gdi.EndDoc(dc) <= 0:
                raise OSError("EndDoc failed")
            started = False
            return job
    finally:
        if dc:
            if started:
                gdi.AbortDoc(dc)
            gdi.DeleteDC(dc)
        spool.ClosePrinter(handle)
