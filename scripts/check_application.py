"""Run application tests using a disposable PostgreSQL cluster, never the runtime DB."""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def tests(environment, gui):
    report = ROOT / ".reports/application.xml"
    report.parent.mkdir(exist_ok=True)
    args = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", f"--junitxml={report}"]
    if not gui:
        args += ["-m", "not gui"]
    return subprocess.run(args, cwd=ROOT, env=environment).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="Also run Tk smoke (requires a display / xvfb-run)")
    args = parser.parse_args()
    environment = os.environ.copy()
    if environment.get("WMS_TEST_DATABASE_URL"):
        return tests(environment, args.gui)
    if not shutil.which("pg_config"):
        parser.error("Install PostgreSQL server tools or set WMS_TEST_DATABASE_URL to a disposable wms_test_* DB")
    binaries = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with tempfile.TemporaryDirectory(prefix="wms-app-") as temporary:
        directory = Path(temporary)
        data, log = directory / "data", directory / "postgres.log"
        run(binaries / "initdb", "-D", data, "--auth=trust", "--no-locale", "--encoding=UTF8", stdout=subprocess.DEVNULL)
        try:
            run(binaries / "pg_ctl", "-D", data, "-l", log, "-o", f"-k {temporary} -c listen_addresses=''", "-w", "start", stdout=subprocess.DEVNULL)
            run(binaries / "createdb", "-h", temporary, "wms_test_application")
            environment["WMS_TEST_DATABASE_URL"] = f"postgresql+psycopg://{getpass.getuser()}@/wms_test_application?host={temporary}"
            return tests(environment, args.gui)
        except subprocess.CalledProcessError:
            print("Temporary PostgreSQL/test command failed.", file=sys.stderr)
            if log.exists():
                print(log.read_text()[-5000:], file=sys.stderr)
            return 1
        finally:
            if (data / "postmaster.pid").exists():
                run(binaries / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop", stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
