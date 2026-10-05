"""Run separately from the DB-only outbox worker; bounded PDF file work."""

import argparse
import json
import logging
from threading import Event

from apps.server.api.app import create_app
from apps.server.application.print_jobs import PrintExecutor
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
        executor = PrintExecutor(create_app(settings, engine=engine).state.printing)
        with stop_signals(stop):
            while not stop.is_set():
                result = executor.run_one()
                if result:
                    print(json.dumps({"print_execution": result}), flush=True)
                if args.once:
                    return 1 if result in {"FAILED", "RETRY", "LOST_LEASE"} else 0
                if not result:
                    stop.wait(1)
    except Exception:
        logging.getLogger("wms.prints").error(
            "print_worker_unavailable: check configuration, database and storage"
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
