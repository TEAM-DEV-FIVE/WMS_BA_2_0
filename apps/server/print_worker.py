"""Supervised print executor (separate from the database-only outbox worker)."""

import sys

from apps.server.operations_worker import main as operations_main


def main(argv=None):
    return operations_main(['--kind', 'print', *(sys.argv[1:] if argv is None else argv)])


if __name__ == '__main__':
    raise SystemExit(main())
