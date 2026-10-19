"""Read-only Windows service discovery and explicit, elevated service start."""

import ctypes
import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass

from apps.local_launcher.database import SetupError


@dataclass(frozen=True)
class Service:
    name: str
    running: bool
    port: int | None = None


def mysql_handshake(port, timeout=1):
    """A listening arbitrary TCP port is not proof that MySQL is present."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            data = b""
            while len(data) < 5:
                part = sock.recv(5 - len(data))
                if not part:
                    return False
                data += part
            return data[3] == 0 and data[4] == 10
    except OSError:
        return False


def is_windows():
    return os.name == "nt"


def discover_services():
    if not is_windows():
        return []
    # Static script only. No passwords, user strings or executable paths interpolated.
    script = (
        "@(Get-CimInstance Win32_Service | Where-Object { "
        "$_.PathName -match '(?i)(^|[\\\\\" ])mysqld(?:\\.exe)?([\\\" ]|$)' } | "
        "Select-Object Name,State,PathName) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=True,
    )
    data = json.loads(result.stdout or "[]")
    if isinstance(data, dict):
        data = [data]
    services = []
    for item in data:
        name = item.get("Name", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            continue
        match = re.search(r"--port(?:=|\s+)(\d+)\b", item.get("PathName", ""))
        services.append(Service(name, item.get("State") == "Running", int(match[1]) if match else None))
    return sorted(services, key=lambda s: s.name)


def installed_server():
    """Fallback for installations which have not registered a Windows service yet."""
    if not is_windows():
        return False
    from pathlib import Path

    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key)
        if base and any((Path(base) / "MySQL").glob("MySQL Server */bin/mysqld.exe")):
            return True
    return False


def start_service(service_name, *, known_services=None):
    """Start only a discovered mysqld service. UAC cancellation never alters config."""
    services = discover_services() if known_services is None else known_services
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", service_name):
        raise SetupError("Tên dịch vụ MySQL không hợp lệ.")
    found = next((s for s in services if s.name == service_name), None)
    if found is None:
        raise SetupError("Dịch vụ không còn là MySQL đã phát hiện. Hãy kiểm tra lại.")
    if found.running:
        return
    if not is_windows():
        raise SetupError("Khởi động dịch vụ chỉ hỗ trợ Windows.")
    # Try current privileges first; only access-denied requests UAC.
    system = os.path.join(os.environ["SystemRoot"], "System32")
    executable = os.path.join(system, "sc.exe")
    result = subprocess.run(
        [executable, "start", service_name],
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode in (0, 1056):
        return
    if result.returncode != 5:
        raise SetupError(
            f"Windows không khởi động được dịch vụ (mã {result.returncode}). "
            "Kiểm tra cấu hình dịch vụ MySQL; dữ liệu được giữ nguyên."
        )
    elevated_start(executable, service_name)


def elevated_start(executable, service_name):
    """Elevate only sc.exe start; never elevate the app or include credentials."""
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile = "runas", executable
    info.lpParameters = subprocess.list2cmdline(["start", service_name])
    info.nShow = 0
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise SetupError("Chưa được cấp quyền khởi động MySQL (UAC đã hủy hoặc bị từ chối).")
    try:
        if kernel.WaitForSingleObject(info.hProcess, 60000) != 0:
            raise SetupError("Windows vẫn đang xử lý yêu cầu; kiểm tra lại dịch vụ sau.")
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)) or code.value not in (0, 1056):
            raise SetupError("Windows chưa khởi động được MySQL. Kiểm tra trạng thái dịch vụ.")
    finally:
        kernel.CloseHandle(info.hProcess)
