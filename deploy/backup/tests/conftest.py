import getpass
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from apps.server.infrastructure.migrations import migrate
from scripts.wms_backup import Postgres, Repository

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/foundation"))
spec = importlib.util.spec_from_file_location("b22_shared_fixtures", ROOT / "tests/conftest.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
iam = shared.iam
isolated_desktop_data = shared.isolated_desktop_data
pytest_plugins = ["scripts.pytest_checks"]


@pytest.fixture
def cluster(tmp_path):
    assert tmp_path.resolve().is_relative_to(Path("/tmp")), "DR fixture must remain in /tmp"
    if shutil.disk_usage(tmp_path).free < 2 * 1024**3:
        pytest.fail("Disposable B22 drill requires 2 GiB free; no fallback to another disk")
    binary = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    data, sock, repository = [tmp_path / n for n in ("primary", "socket", "repository")]
    sock.mkdir(mode=0o700)
    repository.mkdir(mode=0o700)
    identity = uuid4().hex
    (repository / ".repository-id").write_text(identity)
    repo = Repository(repository, identity, require_mount=False, max_bytes=1024**3)
    pg = Postgres(binary, sock, 55439, "wms_test_dr", getpass.getuser())
    subprocess.run([str(binary / "initdb"), "-D", str(data), "--auth=trust", "--data-checksums",
                    "--no-locale", "--encoding=UTF8"], check=True, stdout=subprocess.DEVNULL)
    command = shlex.join([sys.executable, str(ROOT / "scripts/wms_backup.py"), "archive", "--repository",
                         str(repository), "--repository-id", identity, "--source", "%p", "--name", "%f", "--local", "--max-bytes", str(1024**3)])
    with (data / "postgresql.conf").open("a") as f:
        f.write("\nlisten_addresses=''\nshared_buffers='16MB'\nmax_wal_size='64MB'\nmin_wal_size='32MB'\n"
                "archive_mode=on\nwal_level=replica\narchive_timeout=60\nlog_min_error_statement=panic\n"
                "archive_command='" + command.replace("'", "''") + "'\n")
    args = shlex.join(["-k", str(sock), "-p", pg.port])
    pg.run("pg_ctl", "-D", data, "-l", tmp_path / "primary.log", "-o", args, "-w", "start")
    pg.run("createdb", "-h", sock, "-p", pg.port, pg.database)
    class Fixture:
        pass
    fixture = Fixture()
    fixture.pg, fixture.repo, fixture.path, fixture.data, fixture.binary = pg, repo, tmp_path, data, binary
    try:
        yield fixture
    finally:
        if (data / "postmaster.pid").exists():
            pg.run("pg_ctl", "-D", data, "-m", "immediate", "-w", "stop")
        # The tests leave evidence in pytest's /tmp tree; no block devices or user data.


@pytest.fixture
def database(cluster):
    pg = cluster.pg
    from sqlalchemy import URL
    engine = create_engine(URL.create("postgresql+psycopg", username=pg.user, database=pg.database,
                                     query={"host": pg.socket, "port": pg.port}))
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def preserve_umask():
    value = os.umask(0o077)
    yield
    os.umask(value)
