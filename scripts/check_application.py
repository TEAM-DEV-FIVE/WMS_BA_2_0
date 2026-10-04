"""Run application tests using a disposable PostgreSQL cluster, never the runtime DB."""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from ci_support import evidence, logged_run

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def tests(environment, options, pg_version=None):
    report = options.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    environment["WMS_TEST_COLLECTION_REPORT"] = str(report.with_suffix(".collection.json"))
    environment["WMS_TEST_SUITE"] = options.suite
    args = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "--strict-markers",
            f"--junitxml={report}"]
    marker = {"unit": "not integration and not gui", "gui": "gui and not integration"}.get(options.suite)
    if marker or not options.gui:
        args += ["-m", marker or "not gui"]
    status = logged_run(args, report.with_suffix(".log"), cwd=ROOT, env=environment)
    counts = {}
    if report.exists():
        suites = ElementTree.parse(report).getroot().iter("testsuite")
        counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for key in counts:
                counts[key] += int(suite.get(key, 0))
        if counts["skipped"] or not counts["tests"]:
            print("FAIL: selected tests were skipped or no tests ran")
            status = status or 1
    else:
        status = status or 1
    evidence(report.with_suffix(".environment.json"), suite=options.suite, gui=options.gui or options.suite == "gui",
             postgres=pg_version, result=status, junit=counts)
    return status


def database_version(environment, expected):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(environment["WMS_TEST_DATABASE_URL"])
    if url.drivername != "postgresql+psycopg" or not (url.database or "").startswith("wms_test_"):
        raise ValueError("WMS_TEST_DATABASE_URL must use PostgreSQL and a disposable wms_test_* database")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SHOW server_version")).scalar_one()
            major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10000
        if major < 15 or (expected and major != expected):
            raise ValueError(f"Unexpected PostgreSQL major: {major}; requested: {expected or '15+'}")
        return version
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="Also run Tk smoke (requires a display / xvfb-run)")
    parser.add_argument("--suite", choices=("all", "unit", "gui"), default="all",
                        help="gui selects every non-DB GUI test; all includes DB tests")
    parser.add_argument("--report", type=Path, default=ROOT / ".reports/application.xml")
    parser.add_argument("--pg-bindir", type=Path, help="Select local PG binaries, e.g. /usr/lib/postgresql/15/bin")
    parser.add_argument("--expected-pg-major", type=int, choices=(15, 16))
    args = parser.parse_args()
    environment = os.environ.copy()
    environment.pop("WMS_DATABASE_URL", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = str(ROOT)
    # Existing reports must not be mistaken for evidence of this invocation.
    for suffix in (".xml", ".log", ".collection.json", ".environment.json"):
        args.report.with_suffix(suffix).unlink(missing_ok=True)
    if args.suite != "all":
        environment.pop("WMS_TEST_DATABASE_URL", None)
        return tests(environment, args)
    if environment.get("WMS_TEST_DATABASE_URL"):
        return tests(environment, args, database_version(environment, args.expected_pg_major))
    if not args.pg_bindir and not shutil.which("pg_config"):
        parser.error("Install PostgreSQL server tools or set WMS_TEST_DATABASE_URL to a disposable wms_test_* DB")
    binaries = args.pg_bindir or Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    with tempfile.TemporaryDirectory(prefix="wms-app-") as temporary:
        directory = Path(temporary)
        data, log = directory / "data", directory / "postgres.log"
        run(binaries / "initdb", "-D", data, "--auth=trust", "--no-locale", "--encoding=UTF8", stdout=subprocess.DEVNULL)
        try:
            run(binaries / "pg_ctl", "-D", data, "-l", log, "-o", f"-k '{temporary}' -c listen_addresses=''", "-w", "start", stdout=subprocess.DEVNULL)
            run(binaries / "createdb", "-h", temporary, "wms_test_application")
            environment["WMS_TEST_DATABASE_URL"] = (
                f"postgresql+psycopg://{quote(getpass.getuser(), safe='')}@/wms_test_application?host={quote(temporary)}"
            )
            return tests(environment, args, database_version(environment, args.expected_pg_major))
        except subprocess.CalledProcessError:
            print("Temporary PostgreSQL/test command failed.", file=sys.stderr)
            if log.exists():
                print(log.read_text()[-5000:], file=sys.stderr)
            return 1
        finally:
            if (data / "postmaster.pid").exists():
                run(binaries / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop", stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
