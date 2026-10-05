"""Separate DB outbox worker: python -m apps.server.worker --help."""

import argparse
import importlib
import json
import logging
import re
import signal
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from threading import Event

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.server.application.outbox import ConsumerRegistry, OutboxProcessor, RetryPolicy
from apps.server.consumers.registry import fingerprint
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready
from apps.server.infrastructure.outbox import PostgresOutboxStore
from apps.server.infrastructure.worker_status import WorkerStatus

LOGGER = logging.getLogger("wms.outbox")


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WMS_OUTBOX_", extra="ignore", hide_input_in_errors=True)

    batch_size: int = Field(default=100, ge=1, le=1000)
    poll_seconds: float = Field(default=1.0, ge=0.05, le=60, allow_inf_nan=False)
    max_attempts: int = Field(default=5, ge=1, le=100)
    backoff_base_seconds: int = Field(default=5, ge=1, le=86400)
    backoff_max_seconds: int = Field(default=300, ge=1, le=86400)
    consumer_factory: str = "apps.server.consumers.registry:consumer_factory"

    @model_validator(mode="after")
    def valid_backoff(self):
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("Backoff base must not exceed maximum")
        return self


def load_registry(factory_path: str | None) -> ConsumerRegistry:
    """Load explicitly selected, trusted deployment code, never code from the DB."""
    if not factory_path or not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", factory_path):
        raise ValueError("Configure a trusted module:function consumer factory")
    module, name = factory_path.split(":")
    registry = getattr(importlib.import_module(module), name)()
    if not isinstance(registry, ConsumerRegistry) or not registry.event_types:
        raise ValueError("Factory must return a nonempty ConsumerRegistry")
    return registry


@contextmanager
def stop_signals(stop: Event) -> Iterator[None]:
    previous = {}

    def request_stop(signum, frame):
        stop.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_stop)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_worker(
    processor: OutboxProcessor, *, once: bool, poll_seconds: float, stop: Event, monitor=None
) -> int:
    while not stop.is_set():
        if monitor:
            monitor.update("BUSY")
        result = processor.run_batch(stop.is_set)
        LOGGER.info(json.dumps({"event": "outbox_batch", **asdict(result)}, sort_keys=True))
        if monitor:
            monitor.update(
                "IDLE", "DELIVERY_FAILED" if result.retry or result.exhausted else "OK", completed=True
            )
        if once:
            return 1 if result.retry or result.exhausted else 0
        # A signal interrupts waiting immediately; a full batch can continue immediately.
        if result.attempted < processor.batch_size:
            stop.wait(poll_seconds)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run at most one bounded batch, then exit")
    parser.add_argument("--consumer-factory", help="Trusted module:function returning ConsumerRegistry")
    parser.add_argument(
        "--check", action="store_true", help="Check database migrations and registry, then exit"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        worker_settings = WorkerSettings(
            **({"consumer_factory": args.consumer_factory} if args.consumer_factory is not None else {})
        )
        settings = Settings()
        registry = load_registry(worker_settings.consumer_factory)
    except Exception:
        LOGGER.error(
            "outbox_configuration_invalid: check WMS settings and a nonempty trusted consumer factory"
        )
        return 2
    engine = monitor = None
    try:
        engine = make_engine(settings)
        if not is_ready(engine):
            raise ValueError("Database migrations not ready")
        if args.check:
            print(
                json.dumps(
                    dict(ready=True, registry_hash=fingerprint(registry), event_types=registry.event_types)
                )
            )
            return 0
        monitor = WorkerStatus(engine, "outbox", fingerprint(registry))
        processor = OutboxProcessor(
            PostgresOutboxStore(engine),
            registry,
            batch_size=worker_settings.batch_size,
            retry=RetryPolicy(
                worker_settings.max_attempts,
                worker_settings.backoff_base_seconds,
                worker_settings.backoff_max_seconds,
            ),
        )
        stop = Event()
        with stop_signals(stop):
            result = run_worker(
                processor,
                once=args.once,
                poll_seconds=worker_settings.poll_seconds,
                stop=stop,
                monitor=monitor,
            )
            monitor.update("STOPPED")
            return result
    except Exception:
        LOGGER.error("outbox_worker_failed: database or worker unavailable; restart after investigation")
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
