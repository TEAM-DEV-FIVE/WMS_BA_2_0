"""Run separately from the DB-only outbox worker; bounded CSV/XLSX file work."""

import argparse
import json
import logging
from threading import Event

from apps.server.application.export_jobs import ExportExecutor
from apps.server.application.exports import ExportService
from apps.server.application.identity import IdentityService
from apps.server.application.reports import ReportService
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.worker import stop_signals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    stop, engine = Event(), None
    try:
        settings = Settings()
        engine = make_engine(settings)
        executor = ExportExecutor(ExportService(ReportService(IdentityService(engine, settings))))
        with stop_signals(stop):
            while not stop.is_set():
                result = executor.run_one()
                if result:
                    print(json.dumps({"export_execution": result}), flush=True)
                if args.once:
                    return 1 if result in {"FAILED", "RETRY", "LOST_LEASE"} else 0
                if not result:
                    stop.wait(1)
    except Exception:
        logging.getLogger("wms.exports").error(
            "export_worker_unavailable: check configuration, database and storage"
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
