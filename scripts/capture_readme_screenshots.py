"""Capture current WMS screens after a real interactive login; no synthetic data.

Run on the user's desktop with WMS closed. Uses normal API permissions/loaders.
Does not create/approve/post stock documents or modify account grants.
"""

import hashlib
import json
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

from PIL import ImageGrab

from apps.desktop.startup import application_lock, configure_display, preflight_cache, settings_for_startup
from apps.desktop.views.admin_workspace import SECTIONS
from apps.desktop.views.shell import DesktopShell

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets/readme'


def capture():
    settings = settings_for_startup()
    lock = application_lock(settings.local_data_dir)
    shell = root = None
    records = []
    try:
        preflight_cache(settings.local_data_dir)
        configure_display()
        root = tk.Tk(className='WMSReportCapture')
        width, height = min(1440, root.winfo_screenwidth()), min(920, root.winfo_screenheight() - 60)
        root.geometry(f'{width}x{height}+0+0')
        shell = DesktopShell(root, settings)
        # Authentication remains interactive; no passwords/tokens in CLI or screenshots.
        DEST.mkdir(parents=True, exist_ok=True)

        def shot(key, title):
            root.update_idletasks()
            root.lift()
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            file = DEST / (key + '.png')
            ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(file)
            records.append({'feature': key, 'title': title, 'file': file.relative_to(ROOT).as_posix(),
                            'captured_at': datetime.now(timezone.utc).isoformat(),
                            'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                            'source': 'actual Tk application and current authorized API responses'})
            (DEST / 'screenshots.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')

        def wait_screen(index, started):
            if shell.closed or shell.closing:
                return
            busy = any(getattr(owner, 'pending', None) for owner in shell.worker_owners())
            if busy:
                if time.monotonic() - started > 60:
                    messagebox.showerror('Chưa chụp được ảnh', 'Tác vụ tải dữ liệu chưa kết thúc. '
                                         'Hãy kiểm tra kết nối rồi chạy lại công cụ.', parent=root)
                    return
                root.after(200, lambda: wait_screen(index, started))
                return
            _, key, title, _ = SECTIONS[index]
            root.after(400, lambda: save_screen(index, key, title))

        def save_screen(index, key, title):
            if shell.closed or shell.closing:
                return
            shot(key, title)
            next_screen(index + 1)

        def next_screen(index):
            if index == len(SECTIONS):
                messagebox.showinfo('Đã chụp xong', f'Đã lưu {len(records)} ảnh giao diện thực vào assets/readme. '
                                    'Bạn có thể đóng cửa sổ này.', parent=root)
                return
            if shell.closed or shell.closing or not shell.authenticated:
                return
            shell.open_key(SECTIONS[index][1])
            root.after(300, lambda: wait_screen(index, time.monotonic()))

        def await_login():
            if shell.closed or shell.closing:
                return
            if not shell.authenticated:
                root.after(500, await_login)
                return
            if messagebox.askokcancel('Chụp ảnh cho README',
                    'Sẽ mở lần lượt các màn hình và chụp dữ liệu tài khoản này được phép xem. '
                    'Không lập, duyệt hoặc ghi sổ chứng từ. Trong lúc chụp, vui lòng không thao tác cửa sổ.',
                    parent=root, default=messagebox.CANCEL):
                shell.toggle_theme(False)
                next_screen(0)

        root.update()
        shot('login', 'Đăng nhập')
        messagebox.showinfo('Ảnh giao diện thực', 'Đăng nhập bằng tài khoản của bạn và hoàn tất MFA. '
                            'Công cụ sẽ hỏi trước khi chụp các tính năng.', parent=root)
        root.after(500, await_login)
        root.mainloop()
    finally:
        if shell is not None:
            shell.close()
            shell.finish()
        elif root is not None:
            root.destroy()
        lock.close()


if __name__ == '__main__':
    capture()
