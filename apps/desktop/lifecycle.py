"""Wait for background work without blocking Tk; restart only after cleanup."""

import os
import sys
from threading import Event, Thread


def await_workers(executors):
    """Executors must already be stopped on the UI thread by their owners.

    The helper only joins workers: no widgets, API teardown or Tcl references
    are passed into this thread. In particular, queued journal close work must
    finish rather than being cancelled here.
    """
    done = Event()

    def join_workers():
        for executor in executors:
            executor.shutdown(wait=True)
        done.set()

    Thread(target=join_workers, name="wms-shutdown", daemon=True).start()
    return done


def restart_application():
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.extend(["-m", "apps.desktop"])
    os.execv(sys.executable, args)
