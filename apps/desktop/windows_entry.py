"""Frozen GUI/console entry. Helpers exit before creating a shell or opening user data."""

import argparse
import json
import os
import platform
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from apps.desktop.bundle import verify_manifest
from apps.desktop.startup import configure_display, preflight_cache
from packages.contracts.compatibility import CLIENT_VERSION

APP_MUTEX = "Local\\WMSDesktopRunning"


def verify_frozen_bundle():
    if sys.platform == "darwin":
        from apps.desktop.macos_bundle import verify_bundle

        return verify_bundle()
    return verify_manifest(Path(sys.executable).parent)


def installed_self_test():
    import tkinter as tk

    import certifi
    import pypdfium2 as pdfium
    from PIL import Image

    from apps.desktop.local_store.commands import CommandStore
    from apps.desktop.local_store.device import device_identity
    from apps.desktop.scanner.hid import HID

    manifest = verify_frozen_bundle() if getattr(sys, "frozen", False) else None
    assert Path(certifi.where()).is_file()
    import ssl

    assert ssl.create_default_context(cafile=certifi.where()).cert_store_stats()["x509_ca"] > 0
    assert files("apps.desktop.local_store").joinpath("003_commands.sql").is_file()
    if manifest:
        assert files("apps.desktop").joinpath("assets/DejaVuSans.ttf").is_file()
    # Load and execute PDFium native library, not just its Python wrapper.
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(100, 100)
    bitmap = page.render(scale=1)
    picture = bitmap.to_pil()
    assert isinstance(picture, Image.Image) and picture.size == (100, 100)
    picture.close()
    bitmap.close()
    page.close()
    pdf.close()
    configure_display()
    root = tk.Tk()
    try:
        root.title("WMS — Kiểm tra tiếng Việt")
        label = tk.Label(root, text="Kho tiếng Việt — Nhập / Xuất / Phục hồi")
        label.pack()
        root.update()
        assert label.winfo_width() > 0
        tk_version = str(root.tk.call("info", "patchlevel"))
    finally:
        root.destroy()
    with tempfile.TemporaryDirectory(prefix="WMS thử nghiệm ") as temporary:
        directory = Path(temporary)
        device = device_identity(directory)
        assert device_identity(directory) == device
        user = uuid4()
        with_store = CommandStore(
            directory / "commands", server_id="https://probe.invalid/api/v1", user_id=user, device_id=device
        )
        try:
            draft = with_store.save_draft("PROBE", {"quantity": "1"})
            assert with_store.get_draft(draft)
        finally:
            with_store.close()
        preflight_cache(directory)
    hid = HID()
    for char in "SKU-123":
        hid.key(char)
    assert hid.key(keysym="Return") == "SKU-123"
    return dict(
        status="PASS",
        version=CLIENT_VERSION,
        frozen=bool(manifest),
        tkinter=tk_version,
        resources=["SQLite003", "TLS CA", "PDFium", "Pillow", "Tk"],
        platform=sys.platform,
        python=sys.version.split()[0],
        architecture=platform.machine(),
        os_release=platform.platform(),
    )


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--spool":
        from apps.desktop.printing.spool import main as spool_main

        sys.argv = [sys.argv[0], *args[1:]]
        return spool_main()
    parser = argparse.ArgumentParser(description="WMS desktop / release verification")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-cache", type=Path)
    options = parser.parse_args(args)
    if options.check_cache is not None:
        preflight_cache(options.check_cache)
        return 0
    if options.self_test:
        result = installed_self_test()
        if options.report:
            options.report.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    if getattr(sys, "frozen", False):
        verify_frozen_bundle()
    # The installer refuses updates/uninstall while this named mutex exists.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        if not kernel.CreateMutexW(None, False, APP_MUTEX):
            raise ctypes.WinError(ctypes.get_last_error())
    from apps.desktop.__main__ import main as desktop_main

    desktop_main()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        message = "WMS không khởi động được. Kiểm tra bộ cài, cấu hình và phiên bản cache; giữ nguyên dữ liệu cá nhân."
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        else:
            from tkinter import messagebox

            messagebox.showerror("WMS", message)
        raise SystemExit(1) from None
