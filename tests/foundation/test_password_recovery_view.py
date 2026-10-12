import time

import pytest

from apps.desktop.api.client import ApiError, DesktopSettings
from apps.desktop.api.identity import IdentityClient


@pytest.fixture
def recovery_view(monkeypatch, tmp_path):
    import tkinter as tk

    from apps.desktop.views.session import SessionView

    monkeypatch.setattr(IdentityClient, "auth_options", lambda self: dict(email=True, sms=False, google=False))
    root = tk.Tk()
    root.geometry("1200x800")
    view = SessionView(root, DesktopSettings(local_data_dir=tmp_path))
    view.pack(fill="both", expand=True)

    def settle():
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            root.update()
            view.presenter.drain()
            if view.presenter.pending is None:
                root.update()
                return
            time.sleep(.01)
        pytest.fail("Session worker did not settle")

    settle()
    try:
        yield root, view, settle
    finally:
        view.presenter.close()
        view.release_variables()
        root.destroy()
        view.presenter.finish()


@pytest.mark.gui
def test_recovery_is_a_page_with_theme_back_navigation_and_secret_cleanup(recovery_view):
    import tkinter as tk

    root, view, settle = recovery_view
    original_hero, footer = view.hero_source, view.footer
    view.password.set("not-to-retain")
    view.forgot_button.invoke()
    settle()
    assert view.screen == "recovery" and view.lifecycle_dialog is None
    assert not any(isinstance(child, tk.Toplevel) for child in root.winfo_children())
    assert view.hero_source is not original_hero and view.footer is footer
    assert not view.credentials.winfo_ismapped() and view.recovery_ui.request_panel.winfo_ismapped()
    assert view.password.get() == ""
    view.set_dark(True)
    assert view.recovery_ui.contact_entry.inner.cget("background") == "#222938"
    view.recovery_ui.open_reset()
    settle()
    assert view.screen == "recovery_reset"
    view.recovery_ui.values["reset_token"].set("private-reset-code")
    view.recovery_ui.values["new_password"].set("not-to-retain")
    view.back_button.invoke()
    settle()
    assert view.screen == "login" and view.hero_source is original_hero
    assert all(value.get() == "" for value in view.recovery_ui.values.values())


@pytest.mark.gui
def test_recovery_validates_sends_once_and_keeps_reset_errors_inline(recovery_view, monkeypatch):
    root, view, settle = recovery_view
    calls = []
    fail_reset = True

    def action(api, name, body):
        calls.append((name, dict(body)))
        body.clear()
        if name == "self_reset":
            if fail_reset:
                raise ApiError("UNAUTHENTICATED", "Mã khôi phục không hợp lệ hoặc đã hết hạn.")
            return "SIGNED_OUT"
        return {"message": "Nếu liên hệ đã được xác minh, hướng dẫn sẽ được gửi."}

    monkeypatch.setattr(IdentityClient, "auth_action", action)
    view.open_recovery()
    form = view.recovery_ui
    form.request()
    assert not calls and "email hợp lệ" in view.status.get()
    form.values["contact"].set("warehouse@example.com")
    view.capabilities["email"] = False
    form.request()
    assert not calls and "chưa bật" in view.status.get()
    view.capabilities["email"] = True
    form.request()
    form.request()  # Busy guard prevents duplicate sends and navigation.
    view.return_from_recovery()
    assert view.screen == "recovery"
    settle()
    assert calls == [("forgot", dict(kind="email", value="warehouse@example.com", purpose="password"))]
    assert "Nếu liên hệ" in view.status.get()
    form.open_reset()
    for key, value in dict(username="kien", reset_token="fixture-reset-code", new_password="New-password-2026!", confirm_password="different").items():
        form.values[key].set(value)
    form.reset()
    assert len(calls) == 1 and "chưa trùng" in view.status.get()
    form.values["confirm_password"].set("New-password-2026!")
    form.reset()
    assert all(form.values[key].get() == "" for key in ("reset_token", "new_password", "confirm_password"))
    settle()
    assert view.screen == "recovery_reset" and "hết hạn" in view.status.get()
    assert view.lifecycle_dialog is None
    fail_reset = False
    for key, value in dict(username="kien", reset_token="fresh-reset-code", new_password="New-password-2026!", confirm_password="New-password-2026!").items():
        form.values[key].set(value)
    form.reset()
    settle()
    assert view.screen == "login" and "xác thực MFA" in view.status.get()
    assert all(value.get() == "" for value in form.values.values())


@pytest.mark.gui
@pytest.mark.parametrize("dark", [False, True])
def test_mfa_qr_is_scannable_and_cleared_on_expiry_or_logout(recovery_view, dark):
    from uuid import uuid4

    import pyotp
    import zxingcpp
    from PIL import ImageTk

    from packages.contracts.identity import Enrollment

    root, view, settle = recovery_view
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name="fixture-user", issuer_name="WMS")
    result = Enrollment(factor_id=uuid4(), secret=secret, provisioning_uri=uri, expires_in=1)
    view.set_dark(dark)
    view.session_result("enroll", result)
    root.update()
    assert view.screen == "enroll" and view.enrollment_qr_label.winfo_ismapped()
    qr_image = ImageTk.getimage(view.enrollment_qr_image).convert("RGB")
    decoded = zxingcpp.read_barcode(qr_image)
    assert decoded is not None and decoded.text == uri
    assert qr_image.getpixel((0, 0)) == (255, 255, 255)
    assert view.factor_id == result.factor_id
    assert "Nhập khóa" in view.secret.get()
    view.code.set("123456")
    deadline = time.monotonic() + 1.3
    while time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert view.enrollment_qr_image is None and not view.enrollment_qr_label.winfo_ismapped()
    assert not view.secret.get() and not view.code.get() and view.factor_id is None
    assert "hết hạn" in view.status.get()
    view.session_result("enroll", result)
    root.update()
    image_name = str(view.enrollment_qr_image)
    view.clear_scope()
    root.update()
    assert view.enrollment_qr_image is None and view.enrollment_timer is None
    assert image_name not in root.tk.call("image", "names")
    assert view.screen == "login" and not view.secret.get()
