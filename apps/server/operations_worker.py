"""Supervised I/O/retention workers, one kind per process, bounded cycles."""

import argparse
import json
import logging
from threading import Event

from apps.server.application.export_jobs import ExportExecutor
from apps.server.application.export_retention import cleanup as export_cleanup
from apps.server.application.import_jobs import ImportExecutor
from apps.server.application.print_jobs import PrintExecutor
from apps.server.application.print_retention import cleanup as print_cleanup
from apps.server.consumers.registry import fingerprint
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready
from apps.server.infrastructure.worker_status import WorkerStatus
from apps.server.worker import WorkerSettings, load_registry, stop_signals

LOGGER = logging.getLogger("wms.workers")
KINDS = ("import", "export", "print", "export-cleanup", "print-cleanup")


def compose(app, kind):
    """Reuse production services; never spool physical print from a server worker."""
    if kind == "import":
        return ImportExecutor(app.state.imports).run_one
    if kind == "export":
        return ExportExecutor(app.state.exports).run_one
    if kind == "print":
        return PrintExecutor(app.state.printing).run_one
    if kind == "export-cleanup":
        return lambda: export_cleanup(app.state.exports, batch_size=100)
    if kind == "print-cleanup":
        return lambda: print_cleanup(app.state.printing, batch_size=100)
    raise ValueError("Unsupported worker kind")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = monitor = None
    stop = Event()
    try:
        from apps.server.api.app import create_app

        settings = Settings()
        engine = make_engine(settings)
        if not is_ready(engine):
            raise ValueError("Database migrations not ready")
        registry = load_registry(WorkerSettings().consumer_factory)
        app = create_app(settings, engine=engine)
        roots = [s.storage.root.resolve() for s in (app.state.imports, app.state.exports, app.state.printing)]
        if len(set(roots)) != 3 or any(a in b.parents for a in roots for b in roots if a != b):
            raise ValueError("Storage roots must be separate")
        run_one = compose(app, args.kind)
        if args.check:
            print(json.dumps(dict(ready=True, kind=args.kind, registry_hash=fingerprint(registry))))
            return 0
        monitor = WorkerStatus(engine, args.kind, fingerprint(registry))
        with stop_signals(stop):
            while not stop.is_set():
                monitor.update("BUSY")
                outcome = run_one()
                result = "CLEANED" if isinstance(outcome, dict) else outcome or "EMPTY"
                monitor.update("IDLE", result, completed=True)
                if isinstance(outcome, dict):
                    LOGGER.info(json.dumps(dict(event="cleanup_batch", kind=args.kind, counts=outcome)))
                if args.once:
                    monitor.update("STOPPED", result)
                    return int(result in ("FAILED", "RETRY", "LOST_LEASE"))
                # Cleanup every 15 min, with heartbeats while waiting and interruptible shutdown.
                delay = 900 if args.kind.endswith("cleanup") else 1 if outcome is None else 0
                while delay > 0 and not stop.is_set():
                    step = min(30, delay)
                    stop.wait(step)
                    delay -= step
                    if not stop.is_set():
                        monitor.update("IDLE", result)
        monitor.update("STOPPED")
        return 0
    except Exception:
        LOGGER.error(json.dumps(dict(event="worker_failed", kind=args.kind, code="WORKER_FAILED")))
        if monitor:
            try:
                monitor.update("FAILED", "WORKER_FAILED")
            except Exception:
                pass
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
