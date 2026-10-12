"""Install the reviewed avatar update on this user's existing local WMS server.

Run outside the Codex restricted session using cap_nhat_avatar.sh.
Tests finish before maintenance; no runtime credentials are printed.
"""
import getpass
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, **kwargs)


def main():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from apps.server.infrastructure.migrations import migrate
    from scripts.lan_runtime import read_config

    os.umask(0o077)
    config = read_config(Path.home() / ".config/wms-local-server/runtime.env", secret=True)
    runtime_url = make_url(config["WMS_DATABASE_URL"])
    socket = Path.home() / ".local/share/wms-local-server/socket"
    if runtime_url.host or runtime_url.query.get("host") != str(socket) or runtime_url.username != "wms_app":
        raise RuntimeError("Chỉ hỗ trợ cấu hình WMS local hiện có")
    run("systemctl", "--user", "is-active", "wms-local.target", stdout=subprocess.DEVNULL)
    print("Kiểm tra API, xử lý ảnh và giao diện trên database tạm", flush=True)
    run("xvfb-run", "-a", "-s", "-screen 0 1440x960x24", sys.executable,
        "scripts/check_application.py", "--gui",
        "--test-path", "tests/foundation/test_avatar.py", "--test-path", "tests/foundation/test_profile.py",
        "--test-path", "tests/foundation/test_profile_ui.py", "--report", ".reports/avatar-full.xml")
    output = ROOT / "build/avatar-update"
    output.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", output,
        stdout=subprocess.DEVNULL)
    wheel = output / "wms_lan-0.1.0-py3-none-any.whl"
    backup = ROOT / "build/avatar-update-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700)
    owner_url = runtime_url.set(username=getpass.getuser(), password=None)
    engine = create_engine(owner_url, hide_parameters=True, connect_args={"options": "-c role=wms_owner"})
    stopped = migrated = installed = False
    try:
        print("Tạm dừng WMS để sao lưu và cập nhật", flush=True)
        run("systemctl", "--user", "stop", "wms-local.target")
        stopped = True
        run("systemctl", "--user", "start", "wms-local-postgres")
        binaries = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
        run(binaries / "pg_dump", "-h", socket, "-p", runtime_url.query.get("port", "54329"),
            "-U", getpass.getuser(), "-d", runtime_url.database, "-Fc", "-f", backup / "before-avatar.dump")
        run(binaries / "pg_restore", "--list", backup / "before-avatar.dump", stdout=subprocess.DEVNULL)
        revisions = migrate(engine)
        migrated = True
        with engine.begin() as connection:
            connection.execute(text("GRANT SELECT, INSERT, UPDATE ON wms.user_avatar TO wms_app"))
        run(sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", wheel)
        installed = True
        run("systemctl", "--user", "start", "wms-local.target")
        stopped = False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            try:
                with opener.open("http://127.0.0.1:8000/api/v1/ready", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Máy chủ chưa sẵn sàng sau cập nhật")
        print("Đã cập nhật " + (", ".join(revisions) or "phiên bản hiện có"))
        print("Sao lưu: " + str(backup))
        print("Mở lại WMS → tên tài khoản → Chỉnh sửa hồ sơ → Chọn ảnh → Lưu thay đổi")
    except Exception:
        # A failed atomic migration leaves the old server usable. After a migration,
        # never start the old wheel against the new schema without a matching install.
        if stopped and (not migrated or installed):
            subprocess.run(["systemctl", "--user", "start", "wms-local.target"], check=False)
        if migrated and not installed:
            print("Database đã cập nhật nhưng chưa cài xong ứng dụng; máy chủ được giữ dừng")
            print("Chạy lại lệnh cài wheel tại " + str(wheel) + " rồi khởi động wms-local.target")
        print("Bản sao lưu nằm tại " + str(backup))
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Chưa hoàn tất cập nhật (" + type(exc).__name__ + "); giữ lại thông báo phía trên để kiểm tra", file=sys.stderr)
        raise SystemExit(1) from None
