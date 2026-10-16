"""Run tests against a private disposable MySQL instance, never the local WMS DB."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pymysql
from sqlalchemy.engine import URL


def main():
    binary = shutil.which("mysqld")
    if not binary:
        raise SystemExit("MySQL server binary is required")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="wms-mysql-test-") as temporary:
        directory = Path(temporary)
        data, socket, log = directory / "data", directory / "mysql.sock", directory / "mysql.log"
        subprocess.run([binary, "--no-defaults", "--initialize-insecure", f"--datadir={data}", f"--log-error={log}"], check=True)
        process = subprocess.Popen([binary, "--no-defaults", f"--datadir={data}", f"--socket={socket}",
                                    f"--pid-file={directory / 'mysql.pid'}", f"--log-error={log}",
                                    "--skip-networking", "--skip-log-bin", "--innodb-buffer-pool-size=134217728",
                                    "--innodb-redo-log-capacity=67108864"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(300):
                if process.poll() is not None:
                    raise RuntimeError("Disposable MySQL exited; inspect its startup configuration")
                try:
                    connection = pymysql.connect(user="root", unix_socket=str(socket))
                    break
                except pymysql.OperationalError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Disposable MySQL did not start")
            with connection.cursor() as cursor:
                cursor.execute("CREATE DATABASE wms_test_application")
                cursor.execute("SELECT VERSION()")
                print("Disposable MySQL", cursor.fetchone()[0], flush=True)
            connection.close()
            timezone_sql = subprocess.run(["mysql_tzinfo_to_sql", "/usr/share/zoneinfo"], check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
            subprocess.run(["mysql", "--no-defaults", f"--socket={socket}", "--user=root", "mysql"], input=timezone_sql, check=True, stdout=subprocess.DEVNULL)
            environment = dict(os.environ)
            environment.pop("WMS_DATABASE_URL", None)
            environment.pop("KWS_DATABASE_URL", None)
            url = URL.create("mysql+pymysql", username="root", database="wms_test_application", query={"unix_socket": str(socket)})
            environment["WMS_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
            environment["KWS_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
            environment["PYTHONPATH"] = str(root)
            arguments = sys.argv[1:] or ["tests/foundation/test_identity.py", "-q"]
            return subprocess.run([sys.executable, "-m", "pytest", *arguments], cwd=root, env=environment).returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
