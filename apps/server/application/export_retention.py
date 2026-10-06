"""Expiry cleanup with an advisory file-publication fence, no I/O transaction.

Only B17's private storage is touched. Export job tombstones retain the generation
so old outbox deliveries cannot resurrect a deleted snapshot or file.
"""

import os
import re
import time
from contextlib import contextmanager

from sqlalchemy import text

from apps.server.domain.errors import DomainError

STORAGE_LOCK = 871624920017


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


def cleanup(service, *, batch_size=100):
    if not 1 <= batch_size <= 1000:
        raise ValueError("Cleanup batch must be between 1 and 1000")
    engine, storage, now = service.identity.engine, service.storage, service.identity.clock()
    with storage_fence(engine, shared=False):
        with engine.begin() as c:
            expired = (
                c.execute(
                    text("""SELECT s.id FROM wms.report_snapshot s WHERE expires_at<=:now
                    AND NOT EXISTS (SELECT 1 FROM wms.export_job j
                      WHERE j.snapshot_id=s.id AND (j.status IN ('QUEUED','RUNNING') OR EXISTS
                        (SELECT 1 FROM wms.export_task t WHERE t.job_id=j.id AND t.status IN ('READY','RUNNING'))))
                    ORDER BY expires_at,id LIMIT :limit"""),
                    {"now": now, "limit": batch_size},
                )
                .scalars()
                .all()
            )
            files = (
                c.execute(
                    text("""SELECT f.id,f.storage_key FROM wms.stored_file f
                JOIN wms.export_job j ON j.file_id=f.id WHERE j.snapshot_id=ANY(CAST(:expired AS uuid[]))"""),
                    {"expired": expired},
                )
                .mappings()
                .all()
            )
        # Failed unlink keeps DB references/quota for an explicit retry.
        for file in files:
            storage.path(file["storage_key"]).unlink(missing_ok=True)
        with engine.begin() as c:
            c.execute(
                text("""UPDATE wms.export_task SET status='DONE',lease_token=NULL,lease_until=NULL
                WHERE job_id IN (SELECT id FROM wms.export_job WHERE snapshot_id=ANY(CAST(:expired AS uuid[])))"""),
                {"expired": expired},
            )
            # Preserve only authorization metadata for history, never rows, prices or original filters.
            c.execute(text("""UPDATE wms.export_job j SET filters=jsonb_build_object('history_scope',
                jsonb_build_object('warehouse_id',s.criteria->>'warehouse_id',
                  'include_price',s.criteria->'include_price','required_warehouses',to_jsonb(s.required_warehouses),
                  'count_sessions',COALESCE((SELECT jsonb_agg(DISTINCT r.payload->>'session_id')
                     FROM wms.report_snapshot_row r WHERE r.snapshot_id=s.id AND s.report_code='R07'), '[]'::jsonb)))
                FROM wms.report_snapshot s WHERE j.snapshot_id=s.id AND s.id=ANY(CAST(:expired AS uuid[]))"""),
                {"expired": expired})
            c.execute(
                text("""UPDATE wms.export_job SET status='CANCELLED',generation=generation+1,version=version+1,
                file_id=NULL,snapshot_id=NULL,error_code='REPORT_EXPIRED'
                WHERE snapshot_id=ANY(CAST(:expired AS uuid[]))"""),
                {"expired": expired},
            )
            c.execute(
                text("DELETE FROM wms.stored_file WHERE id=ANY(CAST(:ids AS uuid[]))"),
                {"ids": [f["id"] for f in files]},
            )
            c.execute(
                text("DELETE FROM wms.report_snapshot WHERE id=ANY(CAST(:expired AS uuid[]))"),
                {"expired": expired},
            )
            referenced = set(c.execute(text("SELECT storage_key FROM wms.stored_file")).scalars())
        # Crash leftovers are immutable objects; avoid recent files conservatively.
        orphan_count = 0
        if storage.root.exists():
            storage.path("0" * 64)  # Reject symlink storage root just like read/put.
            for entry in os.scandir(storage.root):
                path = storage.root / entry.name
                if (
                    re.fullmatch(r"(?:[0-9a-f]{64}|[0-9a-f]{32}\.part)", path.name)
                    and path.name not in referenced
                    and not path.is_symlink()
                ):
                    if path.stat().st_mtime < time.time() - 86400:
                        path.unlink()
                        orphan_count += 1
                        if orphan_count >= batch_size:
                            break
        return dict(snapshots=len(expired), files=len(files), orphans=orphan_count)
