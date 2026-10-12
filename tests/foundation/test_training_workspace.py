import socket
import threading
import time
import tkinter as tk
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
import uvicorn

from apps.desktop.api.client import DesktopSettings
from apps.desktop.views.shell import DesktopShell
from scripts.prepare_training_quality import seed_quality
from scripts.prepare_training_workflows import seed_workflows
from scripts.seed_demo_catalog import seed


@pytest.mark.integration
@pytest.mark.gui
@pytest.mark.parametrize("dataset", ["training", "published"])
def test_every_training_workspace_opens_with_server_data(iam, tmp_path, dataset):
    user_id, secret = iam.user('kien', mfa=True)
    iam.grant(user_id, 'SYSADMIN')
    if dataset == "training":
        seed(iam.engine, iam.service.settings)
        seed_quality(iam.engine, iam.service.settings)
        seed_workflows(iam.engine, iam.service.settings)
    else:
        from scripts.import_warehouse_source import import_orders, prepare
        from tests.foundation.test_warehouse_source import fixture_source
        iam.grant(user_id, "MASTER_DATA")
        fixture_source(tmp_path)
        manifest = prepare(iam.engine, iam.service.settings, tmp_path)
        import_orders(iam.engine, iam.service.settings, tmp_path, manifest)
    # Maintenance uses the real clock; read its time-bounded grants at that clock.
    iam.now = datetime.now(UTC) + timedelta(seconds=2)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(iam.client.app, access_log=False, log_level='warning'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
    thread.start()
    root = shell = None
    try:
        until = time.monotonic()+5
        while not server.started and time.monotonic()<until:
            time.sleep(.01)
        assert server.started
        root = tk.Tk()
        root.geometry('1440x940')
        shell = DesktopShell(root, DesktopSettings(local_data_dir=tmp_path, api_url=f'http://127.0.0.1:{sock.getsockname()[1]}/api/v1'))
        def wait(predicate):
            until = time.monotonic()+12
            while not predicate() and time.monotonic()<until:
                root.update()
                time.sleep(.01)
            assert predicate()
        root.update()
        wait(lambda: shell.session_view.presenter.pending is None)
        session = shell.session_view
        session.username.set('kien')
        session.password.set('Test-only-password-2026!')
        session.login()
        wait(lambda: session.screen=='mfa')
        session.code.set(pyotp.TOTP(secret).at(iam.now))
        session.mfa()
        wait(lambda: shell.authenticated)
        for key, table_name in [
            ('master_container','table'), ('serial_view','table'), ('custom_fields_view','field_table'),
            ('order_view','table'), ('approval_view','table'), ('receipt_view','table'),
            ('opening_view','table'), ('consignment_view','table'), ('issue_view','table'),
            ('fulfillment_view','table'), ('quality_view','table'), ('move_view','table'),
            ('transfer_view','table'), ('customer_return_view','table'), ('supplier_return_view','table'),
            ('report_view','tree'), ('count_view','table'), ('period_view','table'), ('reversal_view','table'),
        ]:
            view = shell.master_view if key=='master_container' else getattr(shell,key)
            shell.open_key(key)
            root.update()
            wait(lambda: view.presenter.pending is None and not getattr(view,'busy',False) and view not in shell.workspace_loading.pending)
            status = getattr(view, "status", getattr(view, "variables", {}).get("status"))
            assert getattr(view,table_name).get_children(), (key, status.get() if status else "")
        for width in (1440,900):
            root.geometry(f'{width}x940')
            root.update()
            buttons=list(shell.group_buttons.values())
            assert buttons[-1].winfo_x()+buttons[-1].winfo_width() >= shell.erp_bar.winfo_width()-2
            assert all(b.winfo_width()>85 for b in buttons)
    finally:
        if shell:
            shell.close()
            shell.finish()
        elif root:
            root.destroy()
        server.should_exit = True
        thread.join(5)
        sock.close()
