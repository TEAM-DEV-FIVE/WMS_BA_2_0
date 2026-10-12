import pytest

from apps.desktop.views.pagination import CursorPages


def test_cursor_history_commits_only_success_and_supports_back_then_forward():
    pages = CursorPages(2)
    pages.accept(dict(items=[1, 2], next_after="b", total=5))
    assert pages.label == "Trang 1 / 3"
    pages.requested = "b"
    # An HTTP failure never calls accept: page number and history stay intact.
    assert pages.index == 0 and pages.cursors == [None]
    pages.accept(dict(items=[3, 4], next_after="d", total=5))
    assert pages.label == "Trang 2 / 3"
    pages.requested = None
    pages.accept(dict(items=[1, 2], next_after="b", total=5))
    pages.requested = "b"
    pages.accept(dict(items=[3, 4], next_after="d", total=5))
    pages.requested = "d"
    pages.accept(dict(items=[5], next_after=None, total=5))
    assert pages.label == "Trang 3 / 3" and pages.next_after is None
    pages.requested = "b"
    pages.accept(dict(items=[3, 4], next_after="d", total=5))
    assert pages.index == 1 and len(pages.cursors) == 3
    pages.reset()
    pages.accept(dict(items=[], next_after=None, total=0))
    assert pages.label == "0 kết quả" and pages.index == 0


@pytest.mark.integration
def test_catalog_totals_follow_filter_cursor_and_permissions(iam):
    from test_master_data import create

    user, _ = iam.user("page-catalog")
    iam.grant(user, "MASTER_DATA")
    iam.catalog_headers = iam.headers(iam.login("page-catalog"))
    for index in range(5):
        create(iam, "uoms", code=f"PAGE{index}", name=f"Đơn vị {index}", decimal_places=0)
    path = "/api/v1/master/uoms"
    first = iam.client.get(path, params=dict(limit=2, q="PAGE"), headers=iam.catalog_headers).json()
    second = iam.client.get(path, params=dict(limit=2, q="PAGE", after=first["next_after"]), headers=iam.catalog_headers).json()
    assert first["total"] == second["total"] == 5
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    empty = iam.client.get(path, params=dict(q="no match"), headers=iam.catalog_headers).json()
    assert empty["total"] == 0 and not empty["items"]
    iam.user("page-no-grants")
    response = iam.client.get(path, headers=iam.headers(iam.login("page-no-grants")))
    assert response.status_code == 403 and "total" not in response.json()


@pytest.mark.integration
def test_identity_page_matches_legacy_and_checks_mfa_and_live_permissions(iam):
    user, secret = iam.user("page-admin", mfa=True)
    iam.grant(user, "SYSADMIN")
    headers = iam.headers(iam.login("page-admin", secret))
    for index in range(3):
        iam.user(f"page-person{index}")
    page = iam.client.get("/api/v1/iam/page/users?limit=2", headers=headers)
    assert page.status_code == 200, page.text
    page = page.json()
    legacy = iam.client.get("/api/v1/users?limit=200", headers=headers).json()
    assert page["total"] == len(legacy) and page["items"] == legacy[:2]
    last = iam.client.get("/api/v1/iam/page/users", params=dict(after=page["next_after"], limit=2), headers=headers).json()
    assert last["items"] == legacy[2:4] and last["total"] == len(legacy)
    found = iam.client.get("/api/v1/iam/page/lookup-users?q=person1", headers=headers).json()
    assert found["total"] == 1
    other, _ = iam.user("page-admin-without-mfa")
    iam.grant(other, "SYSADMIN")
    denied = iam.client.get("/api/v1/iam/page/users", headers=iam.headers(iam.login("page-admin-without-mfa")))
    assert denied.status_code == 403


@pytest.mark.gui
def test_pagination_footer_controls_and_preserves_current_page_on_error(tmp_path):
    import tkinter as tk

    from apps.desktop.api.client import DesktopSettings
    from apps.desktop.views.shell import DesktopShell

    root = tk.Tk()
    root.geometry("1280x850")
    shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path))
    try:
        shell.authenticated = True
        shell.show_authenticated_header(True)
        shell.resize_workspace()
        shell.open_key("master_container")
        view = shell.master_view
        view.show_details(False)
        bar = view.pagination
        calls = []
        bar.command = calls.append
        bar.loaded(dict(items=list(range(50)), next_after="next-id", total=111))
        bar.set_enabled(True)
        root.update()
        assert bar.winfo_rooty() >= view.table.winfo_rooty() + view.table.winfo_height()
        center = bar.navigation.winfo_rootx() + bar.navigation.winfo_width() / 2
        assert abs(center - (bar.winfo_rootx() + bar.winfo_width() / 2)) <= 1
        assert bar.previous_button.instate(["disabled"])
        assert bar.position.cget("text") == "Trang 1 / 3"
        bar.next_button.invoke()
        assert calls == ["next-id"]
        bar.begin("next-id")
        assert bar.position.cget("text") == "Trang 1 / 3"
        bar.loaded(dict(items=list(range(50)), next_after="last-id", total=111))
        bar.set_enabled(True)
        bar.previous_button.invoke()
        assert calls[-1] is None
        bar.reset()
        assert bar.next_button.instate(["disabled"])
    finally:
        shell.close()
        shell.finish()
