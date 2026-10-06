import tkinter as tk

import pytest

from apps.desktop.views.job_history import JobHistoryPanel

pytestmark = pytest.mark.gui


def test_changed_filters_restart_paging_and_expired_jobs_cannot_open():
    root = tk.Tk()
    requests, opened = [], []
    panel = JobHistoryPanel(root, lambda query: requests.append(query) or True, opened.append, ["READY"])
    try:
        assert panel.load()
        panel.next_after = "old-cursor"
        panel.page(1)
        assert requests[-1]["after"] == "old-cursor"
        panel.next_after = "next-cursor"
        panel.state.set("READY")
        panel.page(1)
        assert "after" not in requests[-1] and panel.cursors == [None]
        panel.until.set("2026-10-06")
        panel.load()
        assert requests[-1]["until"] == "2026-10-07T00:00:00+00:00"
        count = len(requests)
        panel.since.set("not-a-date")
        assert not panel.load() and len(requests) == count
        panel.show(dict(items=[dict(id="expired", created_at="2026-10-06", kind="R01 / csv",
                                   status="CANCELLED", error_code="REPORT_EXPIRED", expired=True)], next_after=None))
        panel.tree.selection_set("expired")
        panel.open_selected()
        assert not opened
        panel.clear()
        assert not panel.rows and not panel.tree.get_children()
    finally:
        panel.release_variables()
        root.destroy()
