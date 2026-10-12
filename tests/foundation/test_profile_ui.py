import socket
import threading
import time
import tkinter as tk
from pathlib import Path

import pyotp
import pytest
import uvicorn
from PIL import ImageGrab

from apps.desktop.api.client import DesktopSettings
from apps.desktop.views.shell import DesktopShell


@pytest.mark.integration
@pytest.mark.gui
def test_profile_menu_save_permissions_and_logout(iam, tmp_path, monkeypatch):
    _, secret = iam.user("kien", mfa=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    root = shell = None
    try:
        root = tk.Tk()
        root.geometry("1280x850+0+0")
        def wait(predicate):
            until = time.monotonic() + 12
            while not predicate() and time.monotonic() < until:
                root.update()
                time.sleep(.01)
            assert predicate()
        wait(lambda: server.started)
        shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path, api_url=f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1"))
        session = shell.session_view
        wait(lambda: session.presenter.pending is None)
        session.username.set("kien")
        session.password.set("Test-only-password-2026!")
        session.login()
        wait(lambda: session.screen == "mfa")
        session.code.set(pyotp.TOTP(secret).at(iam.now))
        session.mfa()
        wait(lambda: shell.authenticated)
        assert "kien" in shell.account_button.text
        assert shell.account_button.avatar
        assert [shell.account_menu.entrycget(i, "label") for i in range(2)] == ["Chỉnh sửa hồ sơ", "Đăng xuất"]
        shell.account_menu.invoke(0)
        root.update()
        assert session.profile_dialog.winfo_exists()
        from tests.foundation.test_avatar import photo
        avatar_path = tmp_path / "photo.png"
        avatar_path.write_bytes(photo())
        monkeypatch.setattr("apps.desktop.views.image_picker.ImagePicker.start", lambda picker: picker.finish(str(avatar_path)))
        session.choose_avatar()
        wait(lambda: session.presenter.pending is None)
        assert session.profile_avatar
        assert shell.account_button.image is None  # Preview only until saved
        session.profile_name.set("Trần Trung Kiên")
        session.save_profile()
        wait(lambda: session.presenter.pending is None)
        assert not session.profile_dialog
        assert shell.current_user.display_name == "Trần Trung Kiên"
        assert shell.current_user.avatar_base64
        assert shell.account_button.image is not None
        assert "Trần Trung Kiên" in shell.account_button.text
        assert not hasattr(shell, "home_view")
        assert session.presenter.api.me().display_name == "Trần Trung Kiên"
        session.session_result("warehouse", ["stock.read", "document.read"])
        assert session.permissions.get() == "Được cấp 2 quyền tại kho"
        assert "stock.read" not in session.permissions.get()
        shell.account_menu.invoke(0)
        root.update()
        assert session.profile_name.get() == "Trần Trung Kiên"
        report = Path(".reports/admin-ui/profile.png")
        report.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab().save(report)
        session.remove_avatar()
        assert session.profile_avatar is None
        session.close_profile()  # Cancel retains the saved avatar
        assert shell.current_user.avatar_base64
        assert session.presenter.api.me().avatar_base64
        for dark in (True, False):
            shell.toggle_theme(dark)
            root.update()
            assert shell.account_button.winfo_ismapped()
        root.geometry("900x690")
        root.update()
        assert shell.account_button.winfo_rootx() >= 0
        assert shell.theme_button.winfo_rootx() + shell.theme_button.winfo_width() <= root.winfo_width()
        shell.account_menu.invoke(1)
        wait(lambda: session.presenter.pending is None)
        assert not shell.authenticated
        assert session.current_user is None
        assert shell.current_user is None
        assert shell.account_button.image is None
        assert not session.permission_codes
        assert not shell.account_button.winfo_ismapped()
    finally:
        if shell:
            shell.close()
            shell.finish()
        elif root:
            root.destroy()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
