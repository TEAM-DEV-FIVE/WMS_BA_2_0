"""Expiry cleanup with an advisory file-publication fence, no I/O transaction.

Only B18's private storage is touched. Print job tombstones retain the generation
so old outbox deliveries cannot resurrect a deleted file.
"""

import re
import time
from contextlib import contextmanager

from sqlalchemy import text

from apps.server.domain.errors import DomainError

STORAGE_LOCK = 871624920018


@contextmanager
def storage_fence(engine, *, shared):
    suffix = "_shared" if shared else ""
    with engine.connect() as c:
        acquired = c.execute(
            text(f"SELECT pg_try_advisory_lock{suffix}(:key)"), {"key": STORAGE_LOCK}
        ).scalar_one()
        c.commit()  # Keep only a session advisory lock, never an open transaction during I/O.
        if not acquired:
            raise DomainError("DATABASE_BUSY", "Storage đang được dọn/tạo file; thử lại.", retryable=True)
        try:
            yield
        finally:
            c.execute(text(f"SELECT pg_advisory_unlock{suffix}(:key)"), {"key": STORAGE_LOCK})
            c.commit()


def cleanup(service):
    engine, storage, now = service.identity.engine, service.storage, service.identity.clock()
    with storage_fence(engine, shared=False):
        with engine.begin() as c:
            jobs = (
                c.execute(
                    text(
                        "SELECT id,file_id FROM wms.print_job WHERE expires_at<=:now AND error_code IS DISTINCT FROM 'PRINT_EXPIRED'"
                    ),
                    dict(now=now),
                )
                .mappings()
                .all()
            )
            ids = [j["id"] for j in jobs]
            files = (
                c.execute(
                    text("SELECT id,storage_key FROM wms.stored_file WHERE id=ANY(CAST(:ids AS uuid[]))"),
                    dict(ids=[j["file_id"] for j in jobs if j["file_id"]]),
                )
                .mappings()
                .all()
            )
        for file in files:
            storage.path(file["storage_key"]).unlink(missing_ok=True)
        with engine.begin() as c:
            c.execute(
                text("""UPDATE wms.print_task SET status='DONE',lease_token=NULL,lease_until=NULL
                              WHERE job_id=ANY(CAST(:ids AS uuid[]))"""),
                dict(ids=ids),
            )
            c.execute(
                text("""UPDATE wms.print_job SET file_id=NULL,status='CANCELLED',version=version+1,
                         generation=generation+1,error_code='PRINT_EXPIRED' WHERE id=ANY(CAST(:ids AS uuid[]))"""),
                dict(ids=ids),
            )
            c.execute(
                text("DELETE FROM wms.stored_file WHERE id=ANY(CAST(:ids AS uuid[]))"),
                dict(ids=[f["id"] for f in files]),
            )
            referenced = set(c.execute(text("SELECT storage_key FROM wms.stored_file")).scalars())
        orphans = 0
        if storage.root.exists():
            storage.path("0" * 64)
            for path in storage.root.iterdir():
                if (
                    re.fullmatch(r"(?:[0-9a-f]{64}|[0-9a-f]{32}\.part)", path.name)
                    and path.name not in referenced
                    and not path.is_symlink()
                    and path.stat().st_mtime < time.time() - 86400
                ):
                    path.unlink()
                    orphans += 1
        return dict(jobs=len(jobs), files=len(files), orphans=orphans)
