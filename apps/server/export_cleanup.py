"""Explicit B17 expiry cleanup; uses server credentials and private storage."""

import json

from apps.server.application.export_retention import cleanup
from apps.server.application.exports import ExportService
from apps.server.application.identity import IdentityService
from apps.server.application.reports import ReportService
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine


def main():
    settings = Settings()
    engine = make_engine(settings)
    try:
        print(json.dumps(cleanup(ExportService(ReportService(IdentityService(engine, settings))))))
        return 0
    except Exception:
        print("Export cleanup failed; check database, worker leases and private storage permissions.")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
