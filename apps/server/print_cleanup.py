"""Expire private print PDFs; retain immutable job/attempt/audit history."""

import json

from apps.server.api.app import create_app


def main():
    from apps.server.application.print_retention import cleanup

    app = create_app()
    try:
        print(json.dumps(cleanup(app.state.printing)))
        return 0
    except Exception:
        print("Print cleanup failed; check private storage and worker leases.")
        return 1
    finally:
        app.state.database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
