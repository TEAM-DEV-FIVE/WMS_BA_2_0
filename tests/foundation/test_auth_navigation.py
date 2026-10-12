import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest

from apps.desktop.api.client import ApiError
from apps.desktop.api.google_login import browser_flow


def test_zalo_footer_link_opens_correct_contact(monkeypatch):
    from apps.desktop.views.session import ZALO_URL, SessionView

    calls = []
    monkeypatch.setattr("apps.desktop.views.session.webbrowser.open", lambda url, new: calls.append((url, new)) or True)
    SessionView.open_zalo(None)
    assert calls == [(ZALO_URL, 2)]
    assert ZALO_URL == "https://zalo.me/0869233973"


@pytest.mark.gui
def test_theme_switch_click_keyboard_animation_and_close():
    import tkinter as tk

    from apps.desktop.views.auth_controls import ThemeSwitch

    root = tk.Tk()
    changes = []
    switch = ThemeSwitch(root, changes.append)
    switch.pack()

    def settle():
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            root.update()
            time.sleep(.01)

    try:
        root.update()
        assert not switch.dark_mode and switch.position == 0
        switch.event_generate("<Button-1>", x=72, y=20)
        assert changes == [True] and switch.timer is not None
        assert switch.position < 1  # Selection moves instead of jumping.
        settle()
        assert switch.position == 1 and switch.timer is None
        switch.focus_force()
        root.update()
        switch.event_generate("<Left>")
        assert changes == [True, False]
        switch.event_generate("<Right>")  # Reverse an in-flight animation.
        settle()
        assert changes == [True, False, True] and switch.position == 1
        switch.event_generate("<Button-1>", x=72, y=20)
        assert changes == [True, False, True]
        switch.choose(False)
        assert switch.timer is not None
        switch.destroy()
        assert switch.timer is None
        root.update()
    finally:
        root.destroy()


@pytest.mark.gui
def test_menu_flat_until_selected_hover_reverts_and_rejected_navigation_keeps_selection():
    import tkinter as tk

    from apps.desktop.views.navigation import NavigationStrip

    root = tk.Tk()
    menu = NavigationStrip(root, [("Chức năng", lambda: True), ("Quản trị", lambda: False)])
    menu.pack(fill="x")
    root.geometry("800x100")
    def settle():
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
    try:
        root.update()
        first, second = menu.items
        assert not any(item.selected for item in menu.items)
        assert [first.type(i) for i in first.find_all()] == ["text"]
        first.event_generate("<Enter>")
        settle()
        text = first.find_all()[-1]
        assert first.level == 1 and first.itemcget(text, "fill") == "#ffffff"
        assert first.itemcget(text, "font").endswith("12")
        assert [first.type(i) for i in first.find_all()] == ["text"]
        first.event_generate("<Leave>")
        settle()
        assert first.level == 0
        assert first.itemcget(first.find_all()[-1], "font").endswith("11")
        first.event_generate("<Button-1>")
        root.update()
        assert first.selected and first.type(first.find_all()[0]) == "polygon"
        second.event_generate("<Button-1>")
        root.update()
        assert first.selected and not second.selected
        first.hover(True)
        menu.destroy()  # Pending animation must be cancelled before Tk shutdown.
        root.update()
    finally:
        root.destroy()


def test_google_loopback_rejects_wrong_state_then_exchanges_once_and_clears_secrets(monkeypatch):
    calls, statuses, threads = [], [], []
    class Api:
        device_id = str(uuid4())
        def _request(self, method, path, *, body, authenticated):
            calls.append((path, dict(body), authenticated))
            if path.endswith("start"):
                self.port = body["port"]
                return dict(state="correct-state", url=f"https://accounts.google.com/?port={self.port}")
            return dict(message="linked")
    api = Api()
    def open_browser(url):
        port = int(parse_qs(urlsplit(url).query)["port"][0])
        def callback():
            with httpx.Client(trust_env=False) as client:
                for state in ("wrong-state", "correct-state"):
                    response = client.get(f"http://127.0.0.1:{port}/wms-google", params=dict(state=state, code="one-use-code"))
                    statuses.append(response.status_code)
                    assert response.headers["cache-control"] == "no-store"
        thread = threading.Thread(target=callback)
        thread.start()
        threads.append(thread)
        return True
    monkeypatch.setattr("apps.desktop.api.google_login.webbrowser.open", open_browser)
    credentials = dict(password="fixture-secret", code="123456")
    assert browser_flow(api, link=True, credentials=credentials) == {"message": "linked"}
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert credentials == {}
    assert statuses == [400, 200]
    assert len(calls) == 2 and calls[1] == ("auth/google/complete", dict(state="correct-state", code="one-use-code"), True)
    with httpx.Client(trust_env=False) as client, pytest.raises(httpx.ConnectError):
        client.get(f"http://127.0.0.1:{api.port}/wms-google")


def test_google_cancel_is_prompt_and_does_not_exchange(monkeypatch):
    calls = []
    class Api:
        device_id = str(uuid4())
        def _request(self, method, path, *, body, authenticated):
            calls.append(path)
            return dict(state="fixture", url="https://accounts.google.com/")
    monkeypatch.setattr("apps.desktop.api.google_login.webbrowser.open", lambda url: True)
    started = time.monotonic()
    with pytest.raises(ApiError, match="hủy"):
        browser_flow(Api(), cancelled=lambda: True)
    assert time.monotonic() - started < 2
    assert calls == ["auth/google/start"]
