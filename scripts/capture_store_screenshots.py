"""Capture production Tk views with explicit synthetic display data, never a live warehouse.

This is a listing illustration harness, not an API, authentication or acceptance test.
No production view is modified. Network requests are rejected during capture.
"""

import argparse
import ctypes
import hashlib
import json
import os
import platform
import tempfile
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import httpx
from PIL import ImageGrab

from apps.desktop.api.client import DesktopSettings
from apps.desktop.startup import configure_display
from apps.desktop.views.shell import DesktopShell


def windows_resolution():
    """Only used on a disposable CI desktop; set enough real pixels for a 1366x768 window."""
    if os.name != "nt":
        return
    from ctypes import wintypes as w

    class Mode(ctypes.Structure):
        _fields_ = [("device", w.WCHAR * 32), ("spec", w.WORD), ("driver", w.WORD),
                    ("size", w.WORD), ("extra", w.WORD), ("fields", w.DWORD),
                    ("x", w.LONG), ("y", w.LONG), ("orientation", w.DWORD), ("fixed", w.DWORD),
                    ("color", w.SHORT), ("duplex", w.SHORT), ("yres", w.SHORT),
                    ("tt", w.SHORT), ("collate", w.SHORT), ("form", w.WCHAR * 32),
                    ("logpixels", w.WORD), ("bits", w.DWORD), ("width", w.DWORD),
                    ("height", w.DWORD), ("flags", w.DWORD), ("frequency", w.DWORD),
                    ("icm", w.DWORD), ("intent", w.DWORD), ("media", w.DWORD),
                    ("dither", w.DWORD), ("reserved1", w.DWORD), ("reserved2", w.DWORD),
                    ("panningw", w.DWORD), ("panningh", w.DWORD)]

    mode = Mode()
    mode.size = ctypes.sizeof(Mode)
    user32 = ctypes.windll.user32
    if not user32.EnumDisplaySettingsW(None, -1, ctypes.byref(mode)):
        raise RuntimeError("Cannot inspect Windows display")
    if mode.width < 1366 or mode.height < 768:
        mode.width, mode.height = 1920, 1080
        mode.fields = 0x80000 | 0x100000
        if user32.ChangeDisplaySettingsW(ctypes.byref(mode), 0) != 0:
            raise RuntimeError("CI display cannot fit Store screenshots")


def capture(output):
    output.mkdir(parents=True, exist_ok=False)
    configure_display()
    windows_resolution()
    user = SimpleNamespace(id=UUID(int=1), global_permissions=["master.read", "master.write", "warehouse.configure"])
    warehouse = SimpleNamespace(id=UUID(int=2), code="KHO-MAU", name="Kho minh họa InternTechLead")
    names = ["Laptop văn phòng 14 inch", "Màn hình IPS 24 inch", "Bàn phím cơ USB", "Chuột không dây",
             "Ổ cứng SSD 1 TB", "RAM DDR4 16 GB", "Bộ phát Wi-Fi", "Switch mạng 8 cổng",
             "Cáp mạng CAT6 3 m", "Bộ chuyển USB-C", "Tai nghe có micro", "Webcam Full HD"]
    skus = ["LAP-014", "MON-024", "KEY-001", "MOU-002", "SSD-1TB", "RAM-016",
            "WIFI-01", "SW-008", "CAT6-03", "HUB-USB", "HEAD-01", "CAM-FHD"]
    files = []
    with tempfile.TemporaryDirectory(prefix="wms-store-illustration-") as temporary:
        settings = DesktopSettings(api_url="https://warehouse.example.invalid/api/v1", local_data_dir=Path(temporary))
        root = tk.Tk()
        root.overrideredirect(True)
        shell = DesktopShell(root, settings)
        root.geometry("1366x768+0+0")
        root.attributes("-topmost", True)

        def shot(view, filename, caption):
            shell.notebook.select(view)
            root.update()
            root.lift()
            root.focus_force()
            time.sleep(0.4)
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            assert (root.winfo_width(), root.winfo_height()) == (1366, 768)
            assert root.winfo_screenwidth() >= x + 1366 and root.winfo_screenheight() >= y + 768
            path = output / filename
            with ImageGrab.grab(bbox=(x, y, x + 1366, y + 768)) as screenshot:
                screenshot.save(path)
            files.append({"name": filename, "caption_vi": caption, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

        try:
            view = shell.master_view
            view.session_changed(user)
            view.entity.set("Sản phẩm")
            view.rebuild()
            products = [dict(id=str(UUID(int=100+n)), sku=sku, name=name, base_uom_id="uom",
                             category_id="category", tracking="SERIAL" if n < 2 else "NONE",
                             expiry_required=False, is_active=True, version=1)
                        for n, (sku, name) in enumerate(zip(skus, names))]
            view.catalog_loaded({"items": products, "next_after": None}, {
                "base_uom_id": {"items": [{"id": "uom", "code": "CAI", "name": "Cái"}], "next_after": None},
                "category_id": {"items": [{"id": "category", "code": "IT", "name": "Thiết bị công nghệ"}], "next_after": None}})
            view.table.selection_set(products[0]["id"])
            view.select()
            view.status.set("Dữ liệu mẫu minh họa · 12 sản phẩm · Quản lý mã hàng, đơn vị tính và theo dõi serial.")
            shell.master_container.select(view)
            shot(shell.master_container, "01-danh-muc-san-pham.png", "Danh mục sản phẩm — dữ liệu mẫu")

            view.entity.set("Vị trí")
            view.rebuild()
            wid = str(warehouse.id)
            rows = [dict(id="zone-a", warehouse_id=wid, code="A", name="Khu thiết bị điện tử", parent_id=None, kind="GROUP", is_active=True, version=1)]
            for rack in range(1, 4):
                rid = f"rack-{rack}"
                rows.append(dict(id=rid, warehouse_id=wid, code=f"A-{rack:02}", name=f"Dãy kệ {rack:02}", parent_id="zone-a", kind="GROUP", is_active=True, version=1))
                for bin_no in range(1, 4):
                    rows.append(dict(id=f"bin-{rack}-{bin_no}", warehouse_id=wid, code=f"A-{rack:02}-{bin_no:02}", name=f"Ô lưu trữ {bin_no:02}", parent_id=rid, kind="STORAGE", is_active=True, version=1))
            view.catalog_loaded({"items": rows, "next_after": None, "warehouses": {wid: {"id": wid, "code": warehouse.code, "name": warehouse.name}}}, {
                "warehouse_id": {"items": [{"id": wid, "code": warehouse.code, "name": warehouse.name}], "next_after": None},
                "parent_id": {"items": rows, "next_after": None}})
            view.table.selection_set("bin-1-1")
            view.select()
            view.status.set("Dữ liệu mẫu minh họa · Cấu trúc kho → khu vực → dãy kệ → ô lưu trữ.")
            shot(shell.master_container, "02-vi-tri-kho.png", "Cấu trúc vị trí kho — dữ liệu mẫu")

            view = shell.report_view
            view.session_changed(user, [warehouse])
            columns = ["sku", "location_code", "owner_code", "physical", "reserved", "available"]
            view.report_page({"snapshot": {"columns": columns, "report_code": "R01", "row_count": 12, "created_at": "2026-10-07 09:00"},
                "items": [dict(sku=sku, location_code=f"A-{1+n//4:02}-{1+n%3:02}", owner_code="COMPANY", physical=24+n*5, reserved=n%4, available=24+n*5-n%4) for n, sku in enumerate(skus)], "next_after": None})
            view.status.set("Dữ liệu mẫu minh họa · R01 · 12 dòng tồn theo vị trí, lượng đang giữ và lượng khả dụng.")
            shot(view, "03-bao-cao-ton-kho.png", "Báo cáo tồn theo vị trí — dữ liệu mẫu")

            view = shell.serial_view
            view.session_changed(user, [warehouse])
            view.code.set("000-LAP-DEMO-001")
            view.sku.set("LAP-014")
            serial = SimpleNamespace(serial_id=UUID(int=300), sku="LAP-014", serial_code="000-LAP-DEMO-001", status="VALID",
                as_of="2026-10-07", received_on="2026-10-01", warranty_start_on="2026-10-01", warranty_ends_on="2027-10-01",
                warranty_evidence_ref="Phiếu bảo hành mẫu BH-2026-001", receipt_number="PN-MAU-2026-001",
                supplier_name="Nhà cung cấp minh họa", receipt_move_id=UUID(int=301))
            view.lookup_result([serial], permissions=["warranty.write"])
            view.status.set("Dữ liệu mẫu minh họa · Tra cứu serial và chứng cứ bảo hành theo kho.")
            shot(view, "04-serial-bao-hanh.png", "Tra serial và bảo hành — dữ liệu mẫu")
        finally:
            shell.close()
            shell.finish()
    (output / "capture-info.json").write_text(json.dumps({"platform": platform.platform(), "size": [1366, 768],
        "capture": "unmodified production Tk views, native screen capture", "data": "synthetic presentation fixtures; no API or warehouse login",
        "acceptance_test": False, "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(files, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    with patch.object(httpx.Client, "send", side_effect=RuntimeError("Network disabled in screenshot harness")):
        capture(options.output)
