"""Bounded subprocess adapters. SUBMITTED means spooler ACK, never physical printing."""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PAPERS = {"A4": (210, 297), "A5": (148, 210), "100x50": (100, 50), "80x40": (80, 40)}


@dataclass(frozen=True)
class Result:
    outcome: str
    spool_id: str | None = None
    error_code: str | None = None


def printers():
    if os.name == "nt":
        from apps.desktop.printing.windows import printers as windows_printers

        return windows_printers()
    output = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=10, check=True)
    return [dict(name=n, driver="CUPS") for n in output.stdout.splitlines() if n and not n.startswith("-")]


def windows_command(printer, paper, copies):
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("WMSHelper.exe")), "--spool", printer, paper, str(copies)]
    return [sys.executable, "-m", "apps.desktop.printing.spool", printer, paper, str(copies)]


def submit(data, printer, paper, copies=1, timeout=60):
    if paper not in PAPERS or not 1 <= copies <= 20 or not printer or any(ord(c) < 32 for c in printer):
        return Result("FAILED", error_code="SPOOL_ERROR")
    try:
        if os.name == "nt":
            command = windows_command(printer, paper, copies)
        else:
            width, height = PAPERS[paper]
            command = [
                "lp",
                "-d",
                printer,
                "-n",
                str(copies),
                "-o",
                f"media=Custom.{width}x{height}mm",
                "-o",
                "print-scaling=none",
                "-t",
                "WMS document",
            ]
        result = subprocess.run(
            command, input=data, capture_output=True, timeout=timeout, env={**os.environ, "LC_ALL": "C"}
        )
        if result.returncode:
            # Spooler can fail after accepting some pages; never retry this automatically.
            return Result("UNKNOWN", error_code="SPOOL_ERROR")
        output = result.stdout.decode("utf-8", errors="replace")
        if os.name == "nt":
            value = json.loads(output)
            return Result("SUBMITTED", str(value["job_id"]))
        match = re.search(r"request id is ([A-Za-z0-9_.-]+)", output)
        return Result("SUBMITTED", match[1] if match else None)
    except FileNotFoundError:
        return Result("FAILED", error_code="SPOOL_UNAVAILABLE")
    except subprocess.TimeoutExpired:
        return Result("UNKNOWN", error_code="SPOOL_TIMEOUT")
    except Exception:
        return Result("UNKNOWN", error_code="SPOOL_ERROR")


def main():
    from apps.desktop.printing.windows import print_pdf

    printer, paper, copies = sys.argv[1:]
    data = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        return 1
    job = print_pdf(data, printer, PAPERS[paper], int(copies))
    print(json.dumps(dict(job_id=job)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
