import json
import socket
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from apps.local_launcher import database, mysql_service, provision, runtime
from apps.local_launcher.database import SetupError
from apps.local_launcher.entry import self_test
from apps.local_launcher.product import API_PORT, PREFIX, PRODUCT


@pytest.mark.parametrize("version", ["8.0.23", "8.0.46", "8.4.11", "8.4.0"])
def test_supported_mysql(version):
    database.require_mysql_version(version)


@pytest.mark.parametrize("version", ["5.7.44", "8.0.22", "9.0.0", "8.4.0-MariaDB", "invalid"])
def test_incompatible_mysql_no_mutations(version):
    with pytest.raises(SetupError):
        database.require_mysql_version(version)


def test_resources_and_product_isolation():
    assert self_test()["product"] == PRODUCT
    assert API_PORT == (8766 if PRODUCT == "KWS" else 8765)
    assert ("import" in runtime.worker_kinds()) == (PRODUCT == "WMS")


def test_no_desktop_secret_environment(monkeypatch):
    for k in ("WMS_DATABASE_URL", "KWS_MFA_ENCRYPTION_KEY", "WMS_API_URL", "KWS_LOCAL_DATA_DIR"):
        monkeypatch.setenv(k, "PRIVATE")
    env = runtime.clean_environment()
    assert not any(k.startswith(("WMS_", "KWS_")) for k in env)


def test_mysql_handshake_distinguishes_other_listener(monkeypatch):
    stream = MagicMock()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: stream)
    stream.__enter__.return_value.recv.return_value = b"HTTP/"
    assert mysql_service.mysql_handshake(3306) is False
    stream.__enter__.return_value.recv.return_value = b"\x55\x00\x00\x00\x0a"
    assert mysql_service.mysql_handshake(3306) is True


def test_mysql_handshake_handles_packet_fragments(monkeypatch):
    stream = MagicMock()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: stream)
    stream.__enter__.return_value.recv.side_effect = [b"\x55\x00", b"\x00\x00", b"\x0a"]
    assert mysql_service.mysql_handshake(3306) is True


def test_closed_port_is_not_authentication_failure(monkeypatch):
    def unavailable(*a, **k):
        raise ConnectionRefusedError()

    monkeypatch.setattr(socket, "create_connection", unavailable)
    assert not mysql_service.mysql_handshake(3306)


@pytest.mark.parametrize("name", ["Spooler", "MySQL;Stop-Service Spooler", "MySQL & calc", "", "../MySQL"])
def test_only_discovered_mysql_services_can_start(name):
    with pytest.raises(SetupError):
        mysql_service.start_service(name, known_services=[mysql_service.Service("MySQL84", False)])


def test_running_service_is_not_restarted():
    mysql_service.start_service("MySQL84", known_services=[mysql_service.Service("MySQL84", True)])


def test_existing_database_stops_before_timezone_or_setup(tmp_path, monkeypatch):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        PRODUCT.lower() + "_mysql",
    )
    monkeypatch.setattr(provision, "root_connection", lambda *a: connection)
    tz = MagicMock()
    monkeypatch.setattr(provision, "add_missing_timezones", tz)
    with pytest.raises(SetupError, match="đã có"):
        provision.provision(
            tmp_path / "fresh",
            root_password="secret",
            mysql_port=3306,
            api_port=API_PORT,
            database=PRODUCT.lower() + "_mysql",
            username="admin",
            display_name="Admin",
            password="test-Admin-password-2026",
        )
    tz.assert_not_called()
    assert not (tmp_path / "fresh").exists()
    connection.close.assert_called_once()


def test_existing_home_stops_without_mysql_access(tmp_path, monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(database, "root_connection", connection)
    with pytest.raises(SetupError):
        database.setup(tmp_path, root_password="secret")
    connection.assert_not_called()


def test_timezone_existing_rows_are_preserved(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("8.4.11",), (1,), (12,), (13,)]
    monkeypatch.setattr(provision, "root_connection", lambda *a: connection)
    provision.add_missing_timezones("secret", 3306)
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert all(not q.startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE")) for q in sql)
    connection.commit.assert_called_once()


def test_timezone_missing_only_insert_no_replacement(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("8.4.11",), (1,), None, None]
    cursor.lastrowid = 10
    monkeypatch.setattr(provision, "root_connection", lambda *a: connection)
    provision.add_missing_timezones("secret", 3306)
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert sum(q.startswith("INSERT INTO mysql.time_zone_name") for q in sql) == 2
    assert all(not q.startswith(("UPDATE", "DELETE", "TRUNCATE")) for q in sql)


def test_errors_do_not_contain_password_or_url():
    message = database.failure_message(ValueError("mysql://root:secret@host/db"))
    assert "secret" not in message and "mysql://" not in message


def make_home(home):
    for folder in ("import", "export", "print", "logs"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    env = {
        PREFIX + "DATABASE_URL": "mysql+pymysql://runtime:secret@127.0.0.1:3306/"
        + PRODUCT.lower()
        + "_mysql",
        PREFIX + "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        PREFIX + "HOST": "127.0.0.1",
        PREFIX + "PORT": str(API_PORT),
        PREFIX + "BUSINESS_TIMEZONE": "Asia/Ho_Chi_Minh",
        **{
            PREFIX + kind.upper() + "_STORAGE_ROOT": str(home / kind)
            for kind in ("import", "export", "print")
        },
    }
    database.write_private(home / "runtime.json", {"version": 1, "environment": env})
    return env


def test_config_does_not_cross_product_or_loopback(tmp_path):
    make_home(tmp_path)
    env = database.load_environment(tmp_path)
    assert env[PREFIX + "HOST"] == "127.0.0.1"
    p = tmp_path / "runtime.json"
    data = json.loads(p.read_text())
    data["environment"][PREFIX + "DATABASE_URL"] = "mysql+pymysql://runtime:secret@remote/db"
    p.write_text(json.dumps(data))
    with pytest.raises(SetupError):
        database.load_environment(tmp_path)


def test_incomplete_setup_cannot_start(tmp_path):
    make_home(tmp_path)
    (tmp_path / "setup-incomplete.json").write_text("{}")
    with pytest.raises(SetupError):
        database.load_environment(tmp_path)


def test_server_shutdown_waits_and_does_not_terminate(tmp_path, monkeypatch):
    make_home(tmp_path)
    supervisor = runtime.Supervisor(tmp_path)
    process = MagicMock()
    supervisor.children = [("api", process)]

    def wait():
        assert supervisor.stop_path.exists()

    process.wait.side_effect = wait
    supervisor.stop()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    assert not supervisor.stop_path.exists()


def test_desktop_is_spawned_with_only_api_config(tmp_path, monkeypatch):
    make_home(tmp_path)
    bundle = tmp_path / "install" / "server"
    bundle.mkdir(parents=True)
    desktop = bundle.parent / "desktop" / (PRODUCT + ".exe")
    desktop.parent.mkdir()
    desktop.touch()
    monkeypatch.setattr(runtime.sys, "executable", str(bundle / (PRODUCT + "Local.exe")))
    monkeypatch.setenv(PREFIX + "DATABASE_URL", "SECRET")
    popen = MagicMock()
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    runtime.Supervisor(tmp_path).desktop()
    env = popen.call_args.kwargs["env"]
    assert PREFIX + "DATABASE_URL" not in env
    assert env[PREFIX + "API_URL"] == f"http://127.0.0.1:{API_PORT}/api/v1"
    assert env[PREFIX + "LOCAL_DATA_DIR"] == str(tmp_path / "desktop-data")
    assert not (tmp_path / "client.json").exists()


@pytest.mark.gui
def test_setup_ui_main_thread_and_uac_copy():
    import tkinter as tk

    from apps.local_launcher.ui import SetupWindow

    root = tk.Tk()
    window = SetupWindow(root, Path("unused-test-home"))
    try:
        root.update_idletasks()
        assert window.values["database"].get() == PRODUCT.lower() + "_mysql"
        assert window.root.winfo_width() >= 720
    finally:
        window.pool.shutdown(wait=True)
        root.destroy()


@pytest.mark.parametrize("exit_code", [0, 1056, 5, 1060, 1058])
def test_windows_service_start_elevates_only_access_denied(monkeypatch, exit_code):
    monkeypatch.setattr(mysql_service, "is_windows", lambda: True)
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    call = MagicMock(return_value=MagicMock(returncode=exit_code))
    elevation = MagicMock()
    monkeypatch.setattr(mysql_service.subprocess, "run", call)
    monkeypatch.setattr(mysql_service, "elevated_start", elevation)
    if exit_code not in (0, 1056, 5):
        with pytest.raises(SetupError):
            mysql_service.start_service("MySQL84", known_services=[mysql_service.Service("MySQL84", False)])
    else:
        mysql_service.start_service("MySQL84", known_services=[mysql_service.Service("MySQL84", False)])
    assert call.call_args.args[0][-2:] == ["start", "MySQL84"]
    assert "sc.exe" in call.call_args.args[0][0]
    assert elevation.call_count == (1 if exit_code == 5 else 0)


def test_cancelled_uac_does_not_retry_or_change_configuration(monkeypatch):
    monkeypatch.setattr(mysql_service, "is_windows", lambda: True)
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    call = MagicMock(return_value=MagicMock(returncode=5))
    monkeypatch.setattr(mysql_service.subprocess, "run", call)
    monkeypatch.setattr(mysql_service, "elevated_start", MagicMock(side_effect=SetupError("UAC đã hủy")))
    with pytest.raises(SetupError, match="UAC"):
        mysql_service.start_service("MySQL84", known_services=[mysql_service.Service("MySQL84", False)])
    assert call.call_count == 1
