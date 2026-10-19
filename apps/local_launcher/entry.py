"""Dedicated Windows launcher; does not change the existing desktop entrypoint."""

import argparse
import json
import os
import sys
from pathlib import Path

from apps.local_launcher.database import SetupError, default_home, failure_message
from apps.local_launcher.product import PRODUCT


def verify_bundle():
    if not getattr(sys, "frozen", False):
        return
    import hashlib

    from apps.desktop.bundle import safe_relative

    root = Path(sys.executable).resolve().parent
    data = json.loads((root / "local-manifest.json").read_text(encoding="utf-8"))
    if data.get("product") != PRODUCT or data.get("kind") != "local-server" or not data.get("files"):
        raise SetupError("Bộ cài không đúng ứng dụng.")
    if PRODUCT + "Local.exe" not in data["files"]:
        raise SetupError("Thiếu chương trình khởi động trong bộ cài.")
    for name, digest in data["files"].items():
        path = root.joinpath(*safe_relative(name).parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SetupError("Đường dẫn bộ cài không hợp lệ.")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise SetupError("Bộ cài bị thiếu hoặc thay đổi. Hãy tải và cài lại.")


def self_test():
    from importlib.resources import files

    import argon2
    import pymysql
    import sqlglot

    from apps.local_launcher.runtime import worker_kinds
    from apps.server.infrastructure.mysql_migrations import assets

    assert len(assets()) == 6
    assert json.loads(files("apps.local_launcher").joinpath("timezones.json").read_text())["zones"]["UTC"]
    assert pymysql and sqlglot and argon2
    return {
        "product": PRODUCT,
        "status": "PASS",
        "scope": "frozen server resources; no database connection",
        "workers": list(worker_kinds()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--component")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        # Resource-only smoke has no database/password input: record a useful CI failure.
        try:
            verify_bundle()
            result = self_test()
        except Exception as exc:
            result = {
                "product": PRODUCT,
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "scope": "resource-only self-test; no database",
            }
        if args.report:
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if result["status"] == "PASS" else 1
    verify_bundle()
    if args.component:
        from apps.local_launcher.runtime import run_component, worker_kinds

        if args.component not in ("api", *worker_kinds()) or args.home is None or args.session is None:
            raise SetupError("Thành phần máy chủ không hợp lệ.")
        if sys.stderr is None:
            sys.stderr = sys.stdout = (args.home / "logs" / (args.component + ".log")).open(
                "a", encoding="utf-8"
            )
        return run_component(args.component, args.home, args.session)
    if os.name != "nt":
        raise SetupError("Bộ khởi động này dành cho Windows.")
    import tkinter as tk

    from apps.desktop.local_store.device import PartitionLock
    from apps.desktop.startup import configure_display
    from apps.local_launcher.ui import SetupWindow

    guard = Path(os.environ["LOCALAPPDATA"]) / (PRODUCT + "-Local-Launcher")
    guard.mkdir(mode=0o700, exist_ok=True)
    lock = PartitionLock(guard / "application.lock")
    mutex = None
    try:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        mutex = kernel.CreateMutexW(None, False, "Local\\" + PRODUCT + "LocalRunning")
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        configure_display()
        root = tk.Tk()
        window = SetupWindow(root, (args.home or default_home()).absolute())
        root.mainloop()
        window.pool.shutdown(wait=True)
    finally:
        if mutex:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(mutex)
        lock.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        message = str(exc) if isinstance(exc, SetupError) else failure_message(exc)
        if "--component" in sys.argv or "--self-test" in sys.argv:
            if sys.stderr:
                print(message, file=sys.stderr)
        else:
            from tkinter import messagebox

            messagebox.showerror(PRODUCT, message)
        raise SystemExit(1) from None
